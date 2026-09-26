#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pure_push.py —— 参考 git.bat/git_logic.py 的 push 语义，用 dulwich 1.2.15 + Python 标准库(socket/ssl/http)实现全功能 push。
# 功能：自动暂存(已跟踪+未跟踪, 正确处理 .gitignore/.gitattributes/嵌套/全局排除)、LFS 指针化(阈值或 filter=lfs, 不调外部 lfs 进程)、
#       CRLF 规范化/renormalize/ident、分提交(按 Blob 大小)、非快进检测、原子/推送选项能力协商、重试(408/429/5xx+指数退避+Retry-After)、
#       低速看门狗(默认 <10B/s 持续 60s 断开)、实时速度+连接详情(TLS/套件/HTTP状态/已传/剩余)。
# 用法: python pure_push.py -v 3 -u push https://user:token@github.com/owner/repo[.git][/tree/分支]
#       python pure_push.py --self-test
from __future__ import annotations
import argparse,base64,contextlib,hashlib,http.client,io,json,logging,os,re,socket,ssl,stat,sys,tempfile,threading,time,unittest
from contextlib import contextmanager,suppress
from datetime import datetime,timedelta
from email.utils import parsedate_to_datetime
from importlib.metadata import version as pkg_version
from pathlib import Path
from urllib.parse import unquote,urljoin,urlsplit,urlunsplit
from dulwich.attrs import Pattern as AttrPattern
from dulwich.errors import MissingReference,NotGitRepository
from dulwich.ignore import IgnoreFilter,IgnoreFilterManager,default_user_ignore_filter_path
from dulwich.index import IndexEntry,index_entry_from_stat,validate_path,get_path_element_validator,write_index_dict
from dulwich.object_store import iter_tree_contents
from dulwich.objects import Blob,Commit,Tree
from dulwich.repo import Repo
LOG=logging.getLogger("PurePush")
POINTER_PREFIX=b"version https://git-lfs.github.com/spec/v1\n"  # LFS 指针文件魔数
LFS_JSON="application/vnd.git-lfs+json"
EMPTY_TREE=b"4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # SHA-1 空树
RETRY_HTTP={408,425,429,500,502,503,504}  # 可重试 HTTP 状态；401/403/404/409/413 等一律致命
SECRETS=set()  # 日志脱敏用的令牌集合
class StopPush(RuntimeError):pass  # 致命错误：直接终止（认证/权限/本地状态/协议错误）
class NetworkFailure(RuntimeError):
    def __init__(s,msg,retry_after=0):super().__init__(msg);s.retry_after=retry_after  # 可重试网络错误
class HTTPFailure(NetworkFailure):
    def __init__(s,code,url,detail="",retry_after=0):
        super().__init__(f"HTTP {code} {safe_url(url)} {detail}",retry_after);s.code=int(code)
def remember(secret):
    if secret and len(str(secret))>3:SECRETS.add(str(secret))  # 令牌入集合，日志统一替换为 ***
def safe_url(value):
    # 所有日志去除 URL 用户信息与查询串，签名上传地址不会泄露令牌
    try:
        p=urlsplit(str(value));host=p.hostname or ""
        host=f"[{host}]" if ":" in host else host
        return urlunsplit((p.scheme,host+(f":{p.port}" if p.port else ""),p.path,"",""))
    except ValueError:return "[URL 已隐藏]"
def redact(value):
    text=str(value)
    for secret in sorted(SECRETS,key=len,reverse=True):text=text.replace(secret,"***")
    text=re.sub(r"https?://[^\s\"' ]+",lambda m:safe_url(m.group()),text)
    return text.replace("\x1b","\\x1b")
class SafeFormatter(logging.Formatter):
    def format(self,record):return redact(super().format(record))  # 连异常消息也统一脱敏，不用 http.client debuglevel
def setup_logging(v):
    h=logging.StreamHandler(sys.stdout)
    h.setFormatter(SafeFormatter("%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s","%Y-%m-%d %H:%M:%S"))
    LOG.handlers[:]=[h];LOG.propagate=False
    LOG.setLevel({0:logging.ERROR,1:logging.WARNING,2:logging.INFO}.get(v,logging.DEBUG))
def trace(a,message,*values):
    if getattr(a,"verbose",0)>=3:LOG.debug(message,*values)  # -v3 输出逐文件暂存明细
def text(value):return value.decode("utf-8","surrogateescape") if isinstance(value,bytes) else str(value)
def human(n):
    n=float(n)
    for u in ("B","KiB","MiB","GiB","TiB"):
        if abs(n)<1024 or u=="TiB":return (f"{n:.1f}{u}" if u!="B" else f"{int(n)}B")
        n/=1024
def parse_size(v,default=100*1024**2):
    s=str(v).strip().lower()
    m=re.fullmatch(r"(\d+(?:\.\d+)?)\s*([kmgtp]?i?b?)",s)
    if not m:return default
    mult={"":1,"b":1,"k":1024,"kb":1024,"kib":1024,"m":1024**2,"mb":1024**2,"mib":1024**2,"g":1024**3,"gb":1024**3,"gib":1024**3,"t":1024**4,"tb":1024**4,"tib":1024**4,"p":1024**5,"pb":1024**5,"pib":1024**5}[m.group(2)]
    return int(float(m.group(1))*mult)
def stime():return time.strftime("%Y-%m-%d %H:%M:%S")
# ============================ 安全的本地文件读取 ============================
def sig2(st):return st.st_size,st.st_mtime_ns
# 【教训/修复】L988 把 st_dev/st_ino/st_mode/st_ctime 也参与签名：Windows 上对同一未修改文件，
# os.stat(path) 与 os.fstat(fd) 这些字段可能不相等，导致“读取前文件已经变化”误报。
# (size, mtime_ns) 是 git 索引真正使用的字段，跨 stat/fstat 稳定，只有真实写入才会改变它们。
@contextmanager
def regular_reader(path):
    path=Path(path)
    before=path.lstat()
    if not stat.S_ISREG(before.st_mode):raise StopPush(f"不是普通文件，拒绝跟随链接: {path}")
    fd=os.open(path,os.O_RDONLY|getattr(os,"O_BINARY",0)|getattr(os,"O_NOFOLLOW",0))
    with os.fdopen(fd,"rb") as f:
        if sig2(os.fstat(f.fileno()))!=sig2(before):raise StopPush(f"读取前文件已经变化: {path}")
        yield f,before
        if sig2(os.fstat(f.fileno()))!=sig2(before) or sig2(path.lstat())!=sig2(before):
            raise StopPush(f"读取时文件发生变化，请重试本地操作: {path}")
def read_regular(path,limit=None):
    with regular_reader(Path(path)) as (f,st):
        if limit is not None and st.st_size>limit:raise StopPush(f"配置文件过大: {path}")
        return f.read()
def config_bytes(path):
    path=Path(path)
    if path.is_symlink():return b""  # 配置/忽略/属性文件绝不跟随符号链接
    try:return read_regular(path,8*1024*1024)
    except (FileNotFoundError,NotADirectoryError):return b""
def cfg(config,section,key,default=b""):
    try:return config.get(section,key)
    except (KeyError,AttributeError,TypeError):return default
def yes(config,section,key,default=False):
    try:return config.get_boolean(section,key,default)
    except (KeyError,AttributeError,TypeError):return default
# ============================ gitignore ============================
class SafeIgnore(IgnoreFilterManager):
    # 1.2.15 的 is_ignored 返回 True=忽略 / False=!规则重新包含 / None=无匹配
    def _load_path(self,path):
        if (Path(self._top_path)/path/".gitignore").is_symlink():return None  # 符号链接的 .gitignore 不加载
        return super()._load_path(path)
    def _is_dir(self,path):
        p=Path(self._top_path)/path
        return path.endswith("/") or (p.is_dir() and not p.is_symlink())
def ignore_manager(repo,config):
    # 优先级从低到高：用户全局排除 → $GIT_DIR/info/exclude → 各级 .gitignore（越深越优先）
    ignorecase=yes(config,(b"core",),b"ignorecase",False)
    filters=[]
    for path in (Path(default_user_ignore_filter_path(config)).expanduser(),Path(repo.controldir())/"info"/"exclude"):
        try:filters.append(IgnoreFilter.from_path(path,ignorecase))
        except FileNotFoundError:pass
    return SafeIgnore(str(repo.path),filters,ignorecase)
def is_ignored_strict(manager,rel):
    # 【git 语义修复】父目录被忽略时，其下文件不能用 ! 重新包含（blocked/ + !blocked/no.txt 仍忽略）；
    # dulwich 的 manager 只按路径自身匹配，未实现父目录规则，必须逐级向上检查。
    parts=rel.split("/")
    for i in range(1,len(parts)):
        if manager.is_ignored("/".join(parts[:i])) is True:return True
    return manager.is_ignored(rel) is True
# ============================ gitattributes ============================
def attr_words(line):
    # Dulwich 的简单 split 不识别 C 引号路径，先解码首字段再交给其 wildmatch
    line=line.strip()
    if not line or line.startswith(b"#"):return None,[]
    if not line.startswith(b'"'):
        words=line.split();return words[0],words[1:]
    out=bytearray();i=1
    esc={ord("a"):7,ord("b"):8,ord("t"):9,ord("n"):10,ord("v"):11,ord("f"):12,ord("r"):13,34:34,92:92}
    while i<len(line):
        b=line[i];i+=1
        if b==34:break
        if b==92:
            if i>=len(line):break
            b=line[i];i+=1
            if 48<=b<=55:
                v=b-48
                if i<len(line) and 48<=line[i]<=55:v=v*8+(line[i]-48);i+=1
                if i<len(line) and 48<=line[i]<=55:v=v*8+(line[i]-48);i+=1
                if v>255:raise StopPush("属性路径的八进制转义超出字节范围")
                out.append(v);continue
            if b in esc:out.append(esc[b])
            else:raise StopPush(".gitattributes 中存在不支持的 C 转义")
        else:out.append(b)
    rest=line[i:].split()
    return bytes(out),rest
def parse_attribute(token):
    # 三种状态：设置(True) / 取消(-x → False) / 未指定(!x → None)；filter=lfs 这种键值对
    if token[:1]==b"!":return token[1:],None
    if token[:1]==b"-":return token[1:],False
    if b"=" in token:return tuple(token.split(b"=",1))
    return token,True
class Attributes:
    # 按 全局 → 各级目录 .gitattributes(根→文件所在目录) → info/attributes 合并；
    # 支持 [attr]宏（仅顶层可定义）、binary 内建宏、C 引号路径、!/- 状态
    def __init__(self,repo,config,index):
        self.repo=repo;self.root=Path(repo.path);self.index=index;self.cache={}
        self.global_path=Path(text(cfg(config,b"core",b"attributesfile",os.fsencode(Path(os.environ.get("XDG_CONFIG_HOME",str(Path.home()/".config")))/"git"/"attributes")))).expanduser()
        self.info=Path(repo.controldir())/"info"/"attributes"
    def load(self,path,relative=None,macro_allowed=True):
        key=str(path)
        if key in self.cache:return self.cache[key]
        data=config_bytes(path)
        if not Path(path).exists() and relative is not None and relative in self.index:
            entry=self.index[relative]  # 工作区文件已删除时退回索引里的 Blob
            if entry.mode in (0o100644,0o100755):
                try:data=self.repo.object_store[entry.sha].data
                except KeyError:pass
        rules=[];macros={}
        for line in data.splitlines():
            pattern,tokens=attr_words(line)
            if pattern is None:continue
            values=[parse_attribute(t) for t in tokens]
            if pattern.startswith(b"[attr]"):
                if macro_allowed:macros[pattern[6:]]=values
                else:LOG.warning("忽略子目录中不允许定义的属性宏: %s",path)
            elif pattern.startswith(b"!"):
                raise StopPush(f".gitattributes 不允许负模式: {path}")
            else:
                try:rules.append((AttrPattern(pattern),values))
                except ValueError as exc:raise StopPush(f"属性模式无效: {path}: {exc}") from exc
        self.cache[key]=(rules,macros)
        return rules,macros
    def get(self,rel):
        parts=rel.split(b"/")
        levels=[(self.global_path,rel,None,True)]
        for i in range(len(parts)):
            name=b"/".join(parts[:i]+[b".gitattributes"])
            levels.append((self.root/os.fsdecode(name),b"/".join(parts[i:]),name,i==0))
        levels.append((self.info,rel,None,True))
        loaded=[(self.load(p,key,macros),local) for p,local,key,macros in levels]
        definitions={b"binary":[(b"diff",False),(b"merge",False),(b"text",False)]}  # 内建 binary 宏
        for (_,macros),_ in loaded:definitions.update(macros)
        result={}
        def apply(values,seen=frozenset()):
            for name,value in values:
                result[name]=value
                if value is True and name in definitions:
                    if name in seen:raise StopPush("属性宏循环引用: "+text(name))
                    apply(definitions[name],seen|{name})
        for (rules,_),local in loaded:
            for pattern,values in rules:
                if pattern.match(local):apply(values)
        return {k:v for k,v in result.items() if v is not None}  # 未指定状态不参与生效判断
# ============================ LFS ============================
def pointer_bytes(oid,size):
    return POINTER_PREFIX+b"oid sha256:"+os.fsencode(oid)+b"\nsize "+os.fsencode(size)+b"\n"
def pointer_info(data):
    if not data.startswith(POINTER_PREFIX):return None
    try:
        oid=None;size=None
        for line in data[len(POINTER_PREFIX):].splitlines():
            if line.startswith(b"oid sha256:"):oid=line[11:].decode()
            elif line.startswith(b"size "):size=int(line[5:])
        if oid and size and re.fullmatch(r"[0-9a-f]{64}",oid):return oid,size
    except ValueError:pass
    return None
class LfsCache:
    # LFS 真实内容快照缓存（临时目录），键为 SHA-256
    def __init__(s,root):
        s.dir=Path(root);s.dir.mkdir(parents=True,exist_ok=True)
    def path(s,oid):return s.dir/oid
    def has(s,oid,size):
        p=s.path(oid)
        return p.is_file() and not p.is_symlink() and p.stat().st_size==size
    def require(s,oid,size):
        p=s.path(oid)
        if not p.is_file() or p.is_symlink():
            raise StopPush(f"远端需要 LFS {oid}，但本地缓存不存在；恢复原文件/缓存后再推送，不能只发送指针")
        if p.stat().st_size!=size:
            raise StopPush(f"LFS 缓存大小不符: {oid} 期望 {size} 实际 {p.stat().st_size}")
        return p
    def put(s,path):
        # 【教训/修复】L988 先打开写句柄再打开读句柄并比对 stat，Windows 下互相干扰误报；
        # 现在只持有一个源文件句柄：读取→计算 SHA-256→写临时文件→原子 rename。
        path=Path(path)
        with regular_reader(path) as (f,size):
            head=f.read(512)
            if head.startswith(POINTER_PREFIX):
                # 【no-process】工作区文件本身就是指针：不重复哈希、不运行 clean，只校验真实内容在缓存里
                pi=pointer_info(head)
                if pi is None:
                    f.seek(0);pi=pointer_info(f.read(1024))
                if pi is None:raise StopPush(f"文件内容是不完整的 LFS 指针: {path}")
                s.require(*pi)
                return pointer_bytes(*pi)
            f.seek(0)
            fd,tmp=tempfile.mkstemp(prefix=".purepush-lfs-",dir=s.dir)
            try:
                h=hashlib.sha256();total=0
                with os.fdopen(fd,"wb") as out:
                    while True:
                        block=f.read(1024*1024)
                        if not block:break
                        h.update(block);total+=len(block);out.write(block)
                    out.flush();os.fsync(out.fileno())
                oid=h.hexdigest();dest=s.path(oid)
                os.replace(tmp,dest)
                LOG.debug("LFS 本地快照: %s (%s)",oid[:12],human(total))
                return pointer_bytes(oid,total)
            finally:
                with suppress(FileNotFoundError):os.unlink(tmp)
# ============================ 内容规范化 ============================
def normalize_blob(data,attrs,old,repo,config,path,renormalize=False):
    # 只做内建 text/eol/autocrlf/ident 转换；未知外部 filter 或编码转换明确报错，不冒险静默改变内容
    if attrs.get(b"working-tree-encoding") not in (None,False):raise StopPush(f"暂不支持 working-tree-encoding，拒绝静默改变文件内容: {os.fsdecode(path)}")
    selected=attrs.get(b"filter")
    if selected not in (None,False,b"lfs"):raise StopPush(f"不执行外部 filter={text(selected)}: {os.fsdecode(path)}")
    if attrs.get(b"ident") is True:data=re.sub(rb"\$Id:[^$\r\n]*\$",b"$Id$",data)
    text_attr=attrs.get(b"text");eol=attrs.get(b"eol");auto=cfg(config,b"core",b"autocrlf",b"false").lower()
    if text_attr is None and b"crlf" in attrs:text_attr=attrs[b"crlf"] is not False  # 旧式 crlf 属性：仅显式 false 才关闭文本转换
    if text_attr is False or (text_attr is None and eol is None and auto not in (b"true",b"input")):return data
    automatic=text_attr!=True and not (text_attr is None and eol in (b"lf",b"crlf"))
    nonprint=sum(data.count(bytes([b])) for b in range(32) if b not in (8,9,10,12,13,27))+data.count(b"\x7f")
    # text=auto 的二进制启发式：NUL / 混合换行 / 大量不可打印字符 → 视为二进制，原样存储
    if automatic and (b"\0" in data or data.count(b"\r")!=data.count(b"\r\n") or nonprint>(len(data)-nonprint)//128):return data
    if automatic and old is not None and not renormalize and old.mode!=0o160000:
        if b"\r\n" in repo.object_store[old.sha].data:return data  # 旧内容已是 CRLF 且未强制 renormalize → 保持
    converted=data.replace(b"\r\n",b"\n")  # 文本文件规范形式为 LF
    safe=cfg(config,b"core",b"safecrlf",b"false").lower()
    core_eol=cfg(config,b"core",b"eol",b"native")
    checkout_crlf=eol==b"crlf" or (eol is None and (auto==b"true" or (auto!=b"input" and (core_eol==b"crlf" or (core_eol==b"native" and os.name=="nt")))))
    restored=converted.replace(b"\n",b"\r\n") if checkout_crlf else converted
    if safe in (b"true",b"warn") and restored!=data:
        if safe==b"true":raise StopPush(f"core.safecrlf 拒绝不可逆换行转换: {os.fsdecode(path)}")
        LOG.warning("换行转换不可逆: %s",os.fsdecode(path))
    return converted
def exec_mode(st,old,config):
    fm=yes(config,(b"core",),b"filemode",os.name!="nt")  # Windows 默认无执行位概念
    if fm and st.st_mode&0o111:return 0o100755
    if not fm and old is not None and old.mode==0o100755:return 0o100755
    return 0o100644
# ============================ 工作区扫描 ============================
def walk_candidates(repo,index,manager,config):
    # 已跟踪路径绕过忽略规则；父目录被忽略也不能漏掉其中已跟踪文件的修改或删除
    root=Path(repo.path);tracked=dict(index.items())
    ignorecase=yes(config,(b"core",),b"ignorecase",False)
    lookup={os.fsdecode(k).casefold():k for k in tracked} if ignorecase else {}
    files={};skipped=0;count=0;last=time.monotonic()
    validator=get_path_element_validator(config)
    def folded(rel):return os.fsdecode(rel).casefold() if ignorecase else os.fsdecode(rel)
    parents={folded(b"/".join(p.split(b"/")[:i])) for p in tracked for i in range(1,len(p.split(b"/")))}
    def old_key(rel):return rel if rel in tracked else lookup.get(os.fsdecode(rel).casefold())
    def add(path):
        nonlocal skipped,count,last
        rel=os.fsencode(path.relative_to(root).as_posix())
        old=old_key(rel);count+=1
        if not validate_path(rel,validator):raise StopPush(f"无效 Git 路径: {path}")
        if old is None and is_ignored_strict(manager,os.fsdecode(rel)):skipped+=1;return
        files[rel]=(path,old)
        if time.monotonic()-last>=1:LOG.info("扫描文件: %d | 排除: %d | 当前: %s",count,skipped,os.fsdecode(rel));last=time.monotonic()
    def onerror(error):raise error
    for base,dirs,names in os.walk(root,topdown=True,followlinks=False,onerror=onerror):
        current=Path(base);keep=[]
        for name in dirs:
            path=current/name
            rel=os.fsencode(path.relative_to(root).as_posix())
            if (name.casefold() if os.name=="nt" else name)==".git":continue
            if path.is_symlink():add(path);continue  # 符号链接只作为条目，绝不跟随进入
            if folded(rel) not in parents and old_key(rel) is None and is_ignored_strict(manager,os.fsdecode(rel)):skipped+=1;continue
            if os.name=="nt" and os.path.isjunction(str(path)):raise StopPush(f"拒绝遍历 Windows junction: {path}")
            if (path/".git").exists() or (old_key(rel) is not None and tracked[old_key(rel)].mode==0o160000):
                add(path);continue  # 子仓库/子模块 → gitlink
            keep.append(name)
        dirs[:]=keep
        for name in names:
            if (name.casefold() if os.name=="nt" else name)!=".git":add(current/name)
    LOG.info("扫描完成: %d 项 | 未跟踪且被忽略: %d 项",count,skipped)
    return files
# ============================ 暂存与提交 ============================
def stage_all(repo,index,a,config,cache):
    # 替代 porcelain add：直接写 Blob 与索引项，因此永远不会触发 filter.lfs.process
    root=Path(repo.path)
    if any(not isinstance(e,IndexEntry) for _,e in index.items()):raise StopPush("索引存在未解决冲突，拒绝自动提交")
    if any(stat.S_ISDIR(e.mode) or e.skip_worktree for _,e in index.items()):raise StopPush("稀疏索引或 skip-worktree 不受支持，请先展开工作区")
    if any(ext.signature[:1].islower() for ext in (getattr(index,"_extensions",[]) or [])):raise StopPush("存在不支持的必需索引扩展（例如分裂/稀疏索引），拒绝丢弃其数据")
    manager=ignore_manager(repo,config)
    files=walk_candidates(repo,index,manager,config)
    attrs=Attributes(repo,config,index)
    old_entries=dict(index.items())
    payloads=0;seen=set()
    for rel,(path,oldkey) in list(files.items()):
        old=old_entries.get(oldkey) if oldkey is not None else None
        if not a.untracked and old is None:continue  # 未加 -u 时只处理已跟踪文件
        st=path.lstat()
        try:target=os.readlink(str(path))
        except OSError:target=None
        if target is not None:
            blob=Blob.from_string(os.fsencode(target))  # 符号链接存目标字符串，mode 120000
            if old is not None and old.mode==0o120000 and old.sha==blob.id:entry=old
            else:
                repo.object_store.add_object(blob)
                entry=index_entry_from_stat(st,blob.id,mode=0o120000)
        elif not stat.S_ISREG(st.st_mode):
            entry=old if (old is not None and old.mode==0o160000) else None  # gitlink 保留；fifo 等跳过
            if entry is None:continue
        elif old is not None and old.mode==0o160000:
            entry=old
        else:
            effective=attrs.get(rel)
            is_lfs=effective.get(b"filter")==b"lfs" or (not a.no_auto_lfs and st.st_size>=a.lfs_threshold)
            if is_lfs:
                old_pi=None
                if old is not None and old.mode in (0o100644,0o100755):
                    try:old_pi=pointer_info(repo.object_store[old.sha].data)
                    except KeyError:old_pi=None
                if old_pi is not None and cache.has(old_pi[0],old_pi[1]):
                    entry=old  # 【no-process】旧条目已是指针且缓存完好：不重读文件、不二次 clean
                else:
                    ptr=cache.put(path)
                    blob=Blob.from_string(ptr)
                    if old is not None and old.sha==blob.id:entry=old
                    else:
                        repo.object_store.add_object(blob)
                        entry=index_entry_from_stat(st,blob.id,mode=exec_mode(st,old,config))
                        payloads+=1
            else:
                data=normalize_blob(read_regular(path),effective,old,repo,config,rel,a.renormalize)
                if len(data)>a.max_blob_size:
                    raise StopPush(f"普通 Blob 超过允许大小 {human(a.max_blob_size)}: {os.fsdecode(rel)} {human(len(data))}；请为其配置 LFS(.gitattributes filter=lfs)后重试")
                blob=Blob.from_string(data);mode=exec_mode(st,old,config)
                if old is not None and old.sha==blob.id and old.mode==mode:entry=old
                else:
                    repo.object_store.add_object(blob)
                    entry=index_entry_from_stat(st,blob.id,mode=mode)
        if oldkey is not None and oldkey!=rel:
            with suppress(KeyError):del index[oldkey]  # 大小写/重命名残留
        index[rel]=entry;seen.add(rel)
        trace(a,"暂存: %s",os.fsdecode(rel))
    for rel in list(index):
        if rel in seen:continue
        e=index[rel];keep=False
        if e.mode in (0o100644,0o100755):
            try:keep=pointer_info(repo.object_store[e.sha].data) is not None
            except KeyError:keep=False
        if not keep:
            del index[rel];trace(a,"暂存删除: %s",os.fsdecode(rel))
        # 上面被保留的 = 已跟踪 LFS 指针文件在工作区被删除 → 忽略该删除（无法校验内容，保留指针）
    LOG.info("索引暂存完成 | LFS 新快照: %d | 未调用任何外部过滤器",payloads)
def build_tree(store,mapping):
    # mapping {path:(sha,mode)} → 递归构造树；目录名按 git 规则以 \0 参与排序
    if not mapping:return EMPTY_TREE
    root={}
    for path,(sha,mode) in mapping.items():
        parts=path.split(b"/");d=root
        for p in parts[:-1]:d=d.setdefault(p,{})
        d[parts[-1]]=(sha,mode)
    def flush(d):
        t=Tree();t.entries=[]
        for n,v in sorted(d.items(),key=lambda kv:kv[0].replace(b"/",b"\x00")):
            if isinstance(v,dict):t.entries.append((n,0o040000,flush(v)))
            else:t.entries.append((n,v[1],v[0]))
        return store.add_object(t)
    return flush(root)
def tree_map(repo,head):
    if not head:return {}
    return {e.path:(e.sha,e.mode) for e in iter_tree_contents(repo.object_store,repo[head].tree)}
def is_ancestor(store,anc,desc,cap=200000):
    # 快进判断：anc 能否从 desc 的祖先链到达（本地缺对象 → 视为分叉，需要 --force）
    seen=set();stack=[desc]
    while stack:
        sha=stack.pop()
        if sha==anc:return True
        if sha in seen or len(seen)>=cap:continue
        seen.add(sha)
        try:obj=store[sha]
        except KeyError:continue
        if hasattr(obj,"parents"):stack.extend(obj.parents)
    return False
def check_repo_state(repo,config):
    # 合并/变基/浅克隆/替换历史必须先由用户处理，不把不完整状态静默变成普通提交
    if repo.bare:raise StopPush("自动暂存 push 需要非 bare 工作区")
    if cfg(config,b"extensions",b"objectformat",b"sha1")!=b"sha1":raise StopPush("此版本明确只处理 SHA-1 Git 仓库；LFS 内容仍使用 SHA-256")
    if repo.get_shallow():raise StopPush("浅仓库尚未支持，请先补全历史，以免错误判断快进关系")
    if cfg(config,b"extensions",b"partialclone"):raise StopPush("部分克隆尚未支持，请先补全对象；不启动隐式下载")
    for section in config.sections():
        if section[:1]==(b"remote",) and yes(config,section,b"promisor",False):raise StopPush("promisor 部分克隆尚未支持")
    if yes(config,(b"core",),b"sparsecheckout",False) or yes(config,(b"core",),b"splitindex",False):raise StopPush("不自动修改稀疏检出或分裂索引仓库")
    for name in ("MERGE_HEAD","CHERRY_PICK_HEAD","REVERT_HEAD","rebase-merge","rebase-apply","sequencer"):
        if (Path(repo.controldir())/name).exists():raise StopPush(f"仓库操作尚未结束: {name}，请先处理")
    if yes(config,(b"commit",),b"gpgsign",False):raise StopPush("配置要求签名提交，但纯标准库版本不调用签名程序；请显式修改仓库配置后再试")
    if (Path(repo.commondir())/"info"/"grafts").exists() or any(r.startswith(b"refs/replace/") for r in repo.refs.keys()):raise StopPush("存在 grafts/replace refs，拒绝按替换历史自动提交")
def commit_staged(repo,index,a,identity,expected):
    # 按最终暂存 Blob 大小拆分提交（LFS 只按指针大小计）；完成所有树后再更新分支
    refname=None;head=None
    if expected is not None:
        refname,chain=expected
        head=chain[-1][1]
        if repo.refs.follow(b"HEAD")!=expected:raise StopPush("暂存期间本地 HEAD 已变化，拒绝将旧工作区提交到新分支")
    else:
        refname=b"refs/heads/"+os.fsencode(a.branch or "master")
    flat=tree_map(repo,head)
    target={p:(e.sha,e.mode) for p,e in index.items()}
    changed=sorted((set(flat)|set(target)),key=lambda p:(p in target,p))  # 删除先于新增，避免中间树冲突
    changed=[p for p in changed if flat.get(p)!=target.get(p)]
    if not changed:
        LOG.info("暂存区为空，不创建空提交");return [],None
    LOG.info("变更文件: %d 个 | 前 10 项: %s",len(changed),[os.fsdecode(p) for p in changed[:10]])
    store=repo.object_store
    def size_of(sha):
        try:return len(store[sha].data)
        except Exception:return 0
    batches=[];cur=[];tot=0
    for p in changed:
        sz=size_of((target if p in target else flat)[p][0])
        if cur and tot+sz>a.max_commit_size:batches.append(cur);cur=[];tot=0
        cur.append(p);tot+=sz
    if cur:batches.append(cur)
    if len(batches)>1:LOG.warning("暂存内容将拆分为 %d 个提交（单提交上限 %s）",len(batches),human(a.max_commit_size))
    ids=[];parent=head
    now=int(time.time());tz=int(datetime.now().astimezone().utcoffset().total_seconds())
    base_msg=a.message or ("auto "+time.strftime("%Y-%m-%d %H:%M:%S"))
    for i,paths in enumerate(batches,1):
        for p in paths:
            if p in target:flat[p]=target[p]
            else:flat.pop(p,None)
        tree=build_tree(store,flat)
        msg=base_msg if len(batches)==1 else f"【{i}/{len(batches)}】文件数: {len(paths)} {base_msg}"
        c=Commit()
        c.tree=tree;c.parents=[parent] if parent else []
        c.author=identity;c.committer=identity
        c.commit_time=now;c.commit_time_tz_offset=tz
        c.author_time=now;c.author_time_tz_offset=tz
        c.message=msg.encode("utf-8")
        parent=store.add_object(c);ids.append(parent)
        if refname:repo.refs[refname]=parent
        LOG.info("已创建提交: %s %s",parent.decode()[:12],msg)
    return ids,None
def prepare(repo,a,identity,cache):
    try:expected=repo.refs.follow(b"HEAD")
    except MissingReference:expected=None  # 全新仓库：无父提交
    index=repo.open_index()
    config=repo.get_config_stack()
    check_repo_state(repo,config)
    stage_all(repo,index,a,config,cache)
    lock=repo.lock_db("index")
    try:write_index_dict(lock,dict(index.items()),version=3)
    finally:lock.close()
    ids,_=commit_staged(repo,index,a,identity,expected)
    return ids,None
def resolve_identity(config,user,remote):
    # 优先仓库/全局 user.name+email；其次用 URL 用户名（GitHub 用 noreply 邮箱）
    try:
        name=text(cfg(config,b"user",b"name",b""));email=text(cfg(config,b"user",b"email",b""))
    except Exception:name=email=""
    if name and email:return f"{name} <{email}>".encode()
    if user:
        host=(urlsplit(remote).hostname or "") if "://" in remote else ""
        domain="users.noreply.github.com" if "github.com" in host else "localhost"
        return f"{user} <{user}@{domain}>".encode()
    return b"push <push@localhost>"
# ============================ 网络层（socket/ssl，实时速度+连接详情+看门狗） ============================
def retry_delay(value):
    # Retry-After：秒数或 HTTP 日期
    if not value:return 0.0
    value=str(value).strip()
    try:return max(0.0,min(float(value),300.0))
    except ValueError:pass
    try:
        dt=parsedate_to_datetime(value)
        if dt is not None:return max(0.0,min(dt.timestamp()-time.time(),300.0))
    except Exception:pass
    return 1.0
class TransferMonitor:
    # 实时进度 + 低速看门狗：速度 < low_speed_limit 持续 low_speed_time，或完全无数据，则 shutdown 连接
    def __init__(s,sock,a,desc,total=None,recv=False,detail=""):
        s.sock=sock;s.a=a;s.desc=desc;s.total=total;s.recv=recv;s.detail=detail
        s.sent=0;s.rcvd=0;s.t0=time.monotonic();s.last_t=s.t0;s.last_b=0;s.cur=0.0
        s.slow_since=None;s.closed=False;s.reason=""
        s.progress=bool(getattr(a,"progress",False))
        if s.progress:
            s._stop=threading.Event()
            s._thr=threading.Thread(target=s._run,daemon=True)
            s._thr.start()
    def observe(s,n_sent=0,n_recv=0):
        if n_sent:s.sent+=n_sent
        if n_recv:s.rcvd+=n_recv
        s._check()
    def _check(s):
        now=time.monotonic();b=s.sent+s.rcvd;dt=now-s.last_t
        if dt<0.02:return
        speed=(b-s.last_b)/dt if dt>0 else 0.0
        s.cur=speed if speed>0 else s.cur*0.5
        if b==s.last_b and dt>=s.a.low_speed_time:s.kill("停滞无数据")
        elif speed<s.a.low_speed_limit:
            if s.slow_since is None:s.slow_since=now
            if now-s.slow_since>=s.a.low_speed_time:s.kill(f"速度 {speed:.0f}B/s 低于阈值 {s.a.low_speed_limit}B/s")
        else:s.slow_since=None
        s.last_b=b;s.last_t=now
    def kill(s,reason):
        if s.closed:return
        s.closed=True;s.reason=reason
        with contextlib.suppress(Exception):s.sock.shutdown(socket.SHUT_RDWR)
    def line(s):
        b=s.sent+s.rcvd
        parts=[("%s %s %s"%("↓" if s.recv else "↑",s.desc,human(b)))]
        if s.total:parts.append("/%s (%.1f%%)"%(human(s.total),b*100.0/max(1,s.total)))
        dt=time.monotonic()-s.t0
        parts.append("当前 %s/s 平均 %s/s"%(human(s.cur or (b/dt if dt>0 else 0)),human(b/dt if dt>0 else 0)))
        if s.total and (s.cur or 0)>1:parts.append("剩余 ~%ds"%(max(0,int((s.total-b)/max(1.0,s.cur)))))
        if s.detail:parts.append("[%s]"%s.detail)
        return "  ".join(parts)
    def _run(s):
        while not s._stop.wait(s.a.progress_interval):
            try:
                s._check()  # 线程兼做看门狗：即使没有数据到达也能发现停滞
                out=sys.stdout
                if out.isatty():out.write("\r\x1b[2K"+s.line());out.flush()
                else:out.write(s.line()+"\n");out.flush()
            except Exception:pass
    def stop(s):
        if getattr(s,"progress",False):
            s._stop.set();s._thr.join(0.3)
            try:
                out=sys.stdout
                out.write(("\r\x1b[2K" if out.isatty() else "")+s.line()+"\n");out.flush()
            except Exception:pass
class Resp:
    # 2xx 响应体封装：惰性读入（支持 Content-Length / chunked / 读到 EOF），读取计入监控
    def __init__(s,status,headers,sock,mon,chunked,cl,rf):
        s.status=status;s.headers=headers;s.mon=mon
        s._file=rf;s.sock=sock  # 【关键】必须复用请求阶段同一个读流，否则缓冲里已读走的响应字节会丢失
        s._chunked=chunked;s._cl=cl
        s._data=None;s._pos=0;s._closed=False
    def _read_n(s,n):
        out=b""
        while len(out)<n:
            d=s._file.read(n-len(out))
            if not d:break
            s.mon.observe(0,len(d));out+=d
        return out
    def _fill(s):
        if s._data is not None:return
        if s._closed:raise NetworkFailure("连接已关闭")
        buf=io.BytesIO()
        if s._chunked:
            while True:
                line=s._file.readline(8192)
                if not line:break
                line=line.strip()
                if not line:continue
                size=int(line.split(b";")[0],16)
                s.mon.observe(0,len(line)+2)
                if size==0:
                    while True:
                        tr=s._file.readline(8192)
                        if tr in (b"\r\n",b"\n",b""):break
                    break
                buf.write(s._read_n(size));s._file.read(2)
        elif s._cl is not None:
            buf.write(s._read_n(s._cl))
        else:
            while True:
                d=s._file.read(65536)
                if not d:break
                s.mon.observe(0,len(d));buf.write(d)
        s._data=buf.getvalue();s._pos=0
    def read(s,n=-1):
        s._fill()
        if n is None or n<0:chunk=s._data[s._pos:];s._pos=len(s._data)
        else:chunk=s._data[s._pos:s._pos+n];s._pos+=len(chunk)
        return chunk
    def close(s):
        if s._closed:return
        s._closed=True
        s.mon.stop()
        with contextlib.suppress(Exception):s._file.close()
        with contextlib.suppress(Exception):s.sock.close()
class Transport:
    # 标准库 HTTP 客户端：新建连接、TLS、重定向(≤6, 跨源丢令牌)、chunked 响应、看门狗
    def __init__(s,a,auth=None):
        s.a=a;s.auth=auth;s.request_count=0
    def close(s):pass
    def _file_request(s,mon,method,target,hdrs,body,rf,expected_sha256):
        def send_line(line):
            data=line+b"\r\n";mon.observe(len(data));sock.sendall(data)
        send_line(("%s %s HTTP/1.1"%(method,target)).encode("ascii","replace"))
        for k,v in hdrs.items():send_line(f"{k}: {v}".encode("latin-1","replace"))
        send_line(b"")
        h=hashlib.sha256() if expected_sha256 else None
        if body is not None:
            if isinstance(body,(bytes,bytearray)):
                mon.observe(len(body));sock.sendall(bytes(body))
                if h:h.update(body)
            else:
                while True:
                    chunk=body.read(1024*1024)
                    if not chunk:break
                    mon.observe(len(chunk));sock.sendall(chunk)
                    if h:h.update(chunk)
                    if mon.closed:break
                if mon.closed:raise NetworkFailure(f"低速看门狗中止上传: {mon.reason}")
        if h and h.hexdigest()!=expected_sha256:raise StopPush(f"上传内容 SHA-256 不匹配: {expected_sha256}（LFS 缓存损坏？）")
        status_line=rf.readline(8192)
        if not status_line:raise NetworkFailure("连接被重置，未收到响应 (empty reply)")
        m=re.match(rb"HTTP/\d\.\d (\d{3})",status_line)
        status=int(m.group(1)) if m else 0
        resp_hdrs={}
        while True:
            line=rf.readline(8192)
            mon.observe(0,len(line))
            if line in (b"\r\n",b"\n",b""):break
            if b":" in line:
                k,v=line.split(b":",1);resp_hdrs[k.strip().lower().decode()]=v.strip().decode("utf-8","replace")
        return status,resp_hdrs,rf
    def request(s,method,url,headers=None,data=None,desc="HTTP",allow_error=False,total=None,expected_sha256=None):
        # data: None | bytes | 文件对象(从头读到 EOF)；total: 期望发送总字节(用于进度%)
        a=s.a;s.request_count+=1
        cur_method=method;cur_headers=dict(headers or {});cur_data=data
        suppress_auth=False
        for hop in range(6):
            p=urlsplit(url)
            if p.scheme not in ("http","https"):raise StopPush(f"不支持的 URL 方案: {p.scheme}")
            host=p.hostname
            if not host:raise StopPush("URL 缺少主机")
            port=p.port or (443 if p.scheme=="https" else 80)
            target=(p.path or "/")+((f"?{p.query}") if p.query else "")
            try:peer=socket.create_connection((host,port),timeout=a.timeout)
            except (socket.timeout,TimeoutError):raise NetworkFailure(f"连接超时 {host}:{port} (>{a.timeout}s)")
            except OSError as e:raise NetworkFailure(f"连接失败 {host}:{port}: {e}")
            sock=peer;detail=f"{host}:{port}"
            if p.scheme=="https":
                try:
                    sock=ssl.create_default_context().wrap_socket(peer,server_hostname=host)
                    detail=f"{detail} TLS:{sock.version()}/{sock.cipher()[0]}"
                except ssl.SSLError as e:
                    with contextlib.suppress(Exception):peer.close()
                    raise NetworkFailure(f"TLS 握手失败 {host}:{port}: {e}")
            LOG.info("→ 连接 %s → %s 已建立",f"{host}:{port}",sock.getpeername())
            mon=TransferMonitor(sock,a,desc,total=total,detail=detail)
            def cleanup():
                mon.stop()
                with contextlib.suppress(Exception):sock.close()
            try:
                hdrs={"Host":host if port in (80,443) else f"{host}:{port}",
                      "User-Agent":f"purepush/1.0 (dulwich {pkg_version('dulwich')}; python-stdlib)",
                      "Accept":"*/*","Accept-Encoding":"identity","Connection":"close"}
                if cur_headers:hdrs.update(cur_headers)
                if s.auth and not suppress_auth:hdrs["Authorization"]=s.auth
                if isinstance(cur_data,(bytes,bytearray)):hdrs["Content-Length"]=str(len(cur_data))
                elif cur_data is not None and hasattr(cur_data,"read"):
                    try:hdrs["Content-Length"]=str(os.fstat(cur_data.fileno()).st_size-cur_data.tell())
                    except Exception:hdrs["Content-Length"]=str(os.fstat(cur_data.fileno()).st_size)
                rf=sock.makefile("rb")
                status,resp_hdrs=s._file_request(mon,cur_method,target,hdrs,cur_data,rf,expected_sha256)
                LOG.info("← %s HTTP %d (已传 %s / 已收 %s / %.1fs)",desc,status,human(mon.sent),human(mon.rcvd),time.monotonic()-mon.t0)
                if 300<=status<400:
                    loc=resp_hdrs.get("location")
                    if not loc:raise NetworkFailure(f"重定向缺少 Location: HTTP {status}")
                    cleanup()
                    new_url=urljoin(url,loc)
                    if urlsplit(new_url).netloc.lower()!=p.netloc.lower():
                        suppress_auth=True  # 【安全】跨源重定向：令牌不外泄
                        LOG.warning("跨源重定向 %s → %s，已丢弃认证头",safe_url(url),safe_url(new_url))
                    if status==303:cur_method="GET";cur_data=None
                    with contextlib.suppress(Exception):cur_data.seek(0)  # 重放请求体
                    url=new_url
                    continue
                if status>=400:
                    body=b""
                    try:
                        while len(body)<65536:
                            d=rf.read(65536)
                            if not d:break
                            mon.observe(0,len(d));body+=d
                    except Exception:pass
                    detail=body[:600].decode("utf-8","replace")
                    delay=retry_delay(resp_hdrs.get("retry-after"))
                    if allow_error:return Resp(status,resp_hdrs,sock,mon,"chunked" in resp_hdrs.get("transfer_encoding","").lower(),None,rf)  # 交给调用方读取/关闭
                    cleanup()
                    raise HTTPFailure(status,url,detail,delay)
                cl=resp_hdrs.get("content_length")
                return Resp(status,resp_hdrs,sock,mon,"chunked" in resp_hdrs.get("transfer_encoding","").lower(),int(cl) if cl and cl.isdigit() else None,rf)
            except (HTTPFailure,NetworkFailure):
                cleanup();raise
            except (socket.timeout,TimeoutError):
                cleanup();raise NetworkFailure(f"{desc} 超时 (>{a.timeout}s 无响应)")
            except (ssl.SSLError,ConnectionError,http.client.HTTPException) as e:
                cleanup()
                raise NetworkFailure(f"{desc} 连接错误: {redact(repr(e))}"+(f" (看门狗: {mon.reason})" if mon.closed else ""))
            except OSError as e:
                cleanup()
                raise NetworkFailure(f"{desc} I/O 错误: {redact(repr(e))}"+(f" (看门狗: {mon.reason})" if mon.closed else ""))
def retry(a,desc,operation):
    # 幂等操作的指数退避重试：408/429/5xx 与连接级错误可重试；401/403/404 等立即上抛
    for attempt in range(1,a.retries+1):
        LOG.info("===== %s (尝试 %d/%d) =====",redact(desc),attempt,a.retries)
        try:return operation()
        except HTTPFailure as e:
            if e.code in RETRY_HTTP and attempt<a.retries:
                delay=e.retry_after or a.retry_base*2**(attempt-1)
                LOG.warning("HTTP %d，%.1fs 后重试",e.code,delay);time.sleep(delay);continue
            raise
        except NetworkFailure as e:
            if attempt<a.retries:
                delay=e.retry_after or a.retry_base*2**(attempt-1)
                LOG.warning("网络失败: %s，%.1fs 后重试",redact(e),delay);time.sleep(delay);continue
            raise
# ============================ Git Smart HTTP（手工 receive-pack，掌握全部进度） ============================
def pkt_line(data):return b"%04x"%(len(data)+4)+data
def pkt_split(data):
    out=[];i=0
    while i+4<=len(data):
        h=data[i:i+4]
        if not re.fullmatch(rb"[0-9a-f]{4}",h):return out,data[i:]
        ln=int(h,16)
        if ln==0:return out,data[i+4:]  # flush：其后为裸 report-status
        out.append(data[i+4:i+ln]);i+=ln
    return out,data[i:]
def git_info_refs(net,remote):
    # GET info/refs?service=git-receive-pack → (refs{name:sha}, 服务器能力集合)
    resp=net.request("GET",remote.rstrip("/")+"/info/refs?service=git-receive-pack",headers={"Accept":"application/x-git-receive-pack-advertisement"},desc="读取远端引用")
    raw=resp.read();resp.close()
    lines=pkt_split(raw)[0]
    if lines and lines[0].startswith(b"git-receive-pack"):lines=lines[1:]
    refs={};caps=set()
    for i,line in enumerate(lines):
        try:sha,name=line.split(b" ",1)
        except ValueError:continue
        if not re.fullmatch(rb"[0-9a-f]{40}",sha):continue
        if i==0 and b"\x00" in name:
            name,c=name.split(b"\x00",1)
            caps={c.decode() for c in c.split(b" ") if c}
        refs[name]=sha
    return refs,caps
def parse_receive_response(raw,has_status):
    # 解析 side-band-64k + report-status（兼容无 side-band 的旧式响应）
    payloads,tail=pkt_split(raw)
    errors=[]
    for pl in payloads:
        if pl.startswith(b"git-receive-pack"):continue
        ch=pl[:1]
        if ch==b"\x01" and pl[1:]:LOG.debug("远端进度: %s",pl[1:].decode("utf-8","replace"))
        elif ch==b"\x02":errors.append(pl[1:])
    if errors:raise StopPush("服务端错误: "+b" | ".join(errors).decode("utf-8","replace"))
    txt=tail.decode("utf-8","replace").strip("\n")
    lines=[l for l in txt.split("\n") if l.strip()]
    if not lines:raise StopPush("服务器响应为空，无法判断推送结果")
    if not has_status:
        bad=[l for l in lines if l.startswith("ng ")]
        if bad:raise StopPush("推送被拒绝: "+"; ".join(bad))
        return [tuple(l.split(" ")[1:]) for l in lines if l.startswith("ok ")]
    if not lines[0].startswith("unpack "):raise StopPush(f"无法识别的推送状态: {txt[:300]}")
    if lines[0]!="unpack ok":raise StopPush("服务器解包失败: "+lines[0])
    n=int(lines[1]) if len(lines)>1 and lines[1].strip().isdigit() else 0
    ok=[];bad=[]
    for l in (lines[2:2+n] if n else lines[2:]):
        parts=l.split(" ")
        if parts and parts[0]=="ok":ok.append(tuple(parts[1:]))
        else:bad.append(l)
    if bad:raise StopPush("推送被拒绝: "+"; ".join(bad))
    return ok
def git_push_pack(net,url,update,caps,a,pack_iter):
    base=url.rstrip("/")
    chosen=[c for c in (b"report-status",b"side-band-64k",b"of-delta") if c in caps]
    if a.atomic:
        if b"atomic" in caps:chosen.append(b"atomic")
        else:LOG.warning("服务器未通告 atomic 能力，忽略 --atomic")
    if b"report-status" not in chosen:LOG.warning("服务器未通告 report-status，按旧式推送响应解析")
    body=bytearray()
    for i,(ref,(old,new)) in enumerate(update.items()):
        line=b"%s %s %s"%((old or b"0"*40),(new or b"0"*40),ref)
        if i==0:line+=b"\x00"+b" ".join(chosen)  # 首行携带能力协商
        body+=pkt_line(line)
    body+=b"0000"
    fd,tmp=tempfile.mkstemp(prefix="pushpack-")  # pack 落盘：Content-Length 精确，避免 chunked 兼容问题
    pack_bytes=0
    try:
        with os.fdopen(fd,"wb") as out:
            out.write(bytes(body))
            for chunk in pack_iter:
                out.write(chunk);pack_bytes+=len(chunk)
            out.flush();os.fsync(out.fileno())
        total=len(body)+pack_bytes
        LOG.info("pack 就绪: 共 %s（协议头 %s）",human(total),human(len(body)))
        with open(tmp,"rb") as f:
            resp=net.request("POST",base+"/git-receive-pack",headers={"Content-Type":"application/x-git-receive-pack-request","Git-Protocol":"version=0"},data=f,desc=f"推送 pack {human(total)}",total=total)
        raw=resp.read();resp.close()
        LOG.info("推送响应已接收: %s",human(len(raw)))
    finally:
        with contextlib.suppress(FileNotFoundError):os.unlink(tmp)
    return parse_receive_response(raw,b"report-status" in chosen)
def outgoing_lfs(repo,cache,head,a):
    # 遍历 head 树：指针 → 需要上传的 {oid:size}；普通 Blob 超上限 → 致命
    need={}
    for entry in iter_tree_contents(repo.object_store,repo[head].tree):
        if entry.mode not in (0o100644,0o100755):continue
        data=repo.object_store[entry.sha].data
        pi=pointer_info(data)
        if pi is not None:need[pi[0]]=pi[1]
        elif len(data)>a.max_blob_size:
            raise StopPush(f"普通 Blob 超过允许大小 {human(a.max_blob_size)}: {os.fsdecode(entry.path)} {human(len(data))}；请为其配置 LFS 后重试")
    return need
def lfs_batch_url(remote):
    p=urlsplit(remote)
    base=urlunsplit((p.scheme,p.netloc,(p.path or "/").removesuffix(".git"),"",""))
    return base.rstrip("/")+"/info/lfs/objects/batch"
def upload_lfs(net,batch_url,need,cache,ref,done,batch_size=200):
    # LFS batch 协议：batch 查询 → PUT/POST 上传(带签名头) → verify；已存在则跳过
    a=net.a
    items=[(o,s) for o,s in need.items() if (o,s) not in done]
    for o,s in items:cache.require(o,s)  # 【fail-fast】先查本地缓存，避免白白走网络
    if not items:return
    total=sum(s for _,s in items);t0=time.monotonic()
    LOG.info("LFS 批量上传: %d 个对象 共 %s → %s",len(items),human(total),safe_url(batch_url))
    done_bytes=0
    for i in range(0,len(items),batch_size):
        chunk=items[i:i+batch_size]
        payload=json.dumps({"transfer":"application/vnd.git-lfs","objects":[{"oid":o,"size":sz} for o,sz in chunk]}).encode()
        resp=net.request("POST",batch_url,headers={"Content-Type":LFS_JSON,"Accept":LFS_JSON,"Git-Protocol":"version=0"},data=payload,desc=f"LFS 批次 {i//batch_size+1}")
        body=resp.read();resp.close()
        try:data=json.loads(body)
        except ValueError:raise StopPush(f"LFS 批次响应不是 JSON: {body[:200]!r}")
        by_oid={o.get("oid"):o for o in (data.get("objects") or [])}
        for oid,size in chunk:
            obj=by_oid.get(oid)
            if obj is None:raise StopPush(f"LFS 服务器未返回 {oid} 的结果: {body[:300]!r}")
            if obj.get("error"):raise StopPush(f"LFS {oid[:12]} 服务器错误: {obj['error']}")
            actions=obj.get("actions") or {}
            if "upload" not in actions:
                done.add((oid,size));done_bytes+=size
                LOG.info("LFS 已存在，跳过: %s (%s)",oid[:12],human(size));continue
            up=actions["upload"];path=cache.path(oid)
            def put_once(_up=up,_oid=oid,_size=size,_path=path):
                hdrs=dict(_up.get("header") or {});hdrs.setdefault("Content-Type","application/octet-stream")
                with open(_path,"rb") as f:
                    resp2=net.request(_up.get("method","PUT").upper(),_up["href"],headers=hdrs,data=f,desc=f"LFS {_oid[:12]} {human(_size)}",total=_size,expected_sha256=_oid)  # 上传同时校验 SHA-256
                    code=resp2.status;resp2.read();resp2.close()
                if code not in (200,201,204,409):raise NetworkFailure(f"LFS 上传返回 HTTP {code}")
            retry(a,f"LFS 上传 {oid[:12]}",put_once)
            verify=actions.get("verify")
            if verify:
                vhdrs=dict(verify.get("header") or {})
                vresp=net.request(verify.get("method","GET").upper(),verify["href"],headers=vhdrs,desc=f"LFS 校验 {oid[:12]}")
                vcode=vresp.status;vresp.read();vresp.close()
                if vcode==404:
                    LOG.warning("LFS 校验 404（对象丢失），重新上传: %s",oid[:12])
                    retry(a,f"LFS 补传 {oid[:12]}",put_once)
                elif vcode!=200:raise NetworkFailure(f"LFS 校验返回 HTTP {vcode}")
            done.add((oid,size));done_bytes+=size
            LOG.info("LFS 上传完成: %s (%s)",oid[:12],human(size))
    dt=time.monotonic()-t0
    LOG.info("LFS 完成: 共 %s | 耗时 %.1fs | 平均 %s/s",human(done_bytes),dt,human(done_bytes/dt if dt>0 else 0))
def push_target(repo,a,net,remote,ref,head,batch_url,cache,done):
    if not head:raise StopPush("没有可推送的提交（工作区无变化则不会创建提交）")
    head_b=head if isinstance(head,bytes) else os.fsencode(head)
    def op():
        refs,caps=git_info_refs(net,remote)
        old=refs.get(ref)
        LOG.info("远端状态: %s → %s",text(ref),old.decode()[:12] if old else "不存在")
        if old==head_b:
            LOG.info("一切最新: 本地与远端 %s 均为 %s，无需推送",text(ref),head_b.decode()[:12]);return []
        if old and not a.force and not is_ancestor(repo.object_store,old,head_b):
            raise StopPush(f"非快进: 远端 {old.decode()[:12]} 不是本地 {head_b.decode()[:12]} 的祖先（历史已分叉）；如要覆盖远端请加 --force")
        result=git_push_pack(net,remote,{ref:(old,head_b)},caps,a,repo.pack_objects([head_b]))
        LOG.info("git 数据推送完成: %s",result)
        need=outgoing_lfs(repo,cache,head_b,a)
        todo={o:sz for o,sz in need.items() if (o,sz) not in done}
        if todo:upload_lfs(net,batch_url,todo,cache,ref,done)
        elif need:LOG.info("LFS %d 个对象已在 done 集合（幂等去重），跳过",len(need))
        return result
    retry(a,f"推送 {safe_url(remote)} {text(ref)}",op)
# ============================ 命令行 ============================
def parse_args(argv):
    p=argparse.ArgumentParser(prog="pure_push",description="dulwich + 标准库的全功能 push（自动暂存/LFS/重试/实时速度）")
    p.add_argument("cmd",nargs="?",default="push",choices=["push"],help="当前只实现 push")
    p.add_argument("url",nargs="?",default="",help="https://user:token@host/owner/repo[.git][/tree/分支]")
    p.add_argument("branch",nargs="?",default="",help="可选分支名（默认当前 HEAD 分支）")
    p.add_argument("-v","--verbose",type=int,default=2,help="日志级别 0..3（3 显示逐文件明细与实时进度）")
    p.add_argument("-u","--untracked",action=argparse.BooleanOptionalAction,default=True,help="暂存未跟踪且未被忽略的文件（默认开，--no-untracked 关闭）")
    p.add_argument("--lfs-threshold",default="100MiB",help="达到该大小自动 LFS 化（默认 100MiB，GitHub 上限）")
    p.add_argument("--max-blob",default="100MiB",help="普通 Blob 上限（默认 100MiB）")
    p.add_argument("--max-commit-size",default="1900MiB",help="单提交大小上限，超过自动拆分（默认 1900MiB）")
    p.add_argument("--no-auto-lfs",action="store_true",help="关闭按阈值自动 LFS，仅 filter=lfs 生效")
    p.add_argument("--message",default="",help="提交信息（默认 auto 时间戳）")
    p.add_argument("--renormalize",action="store_true",help="强制按 .gitattributes 重新规范化已跟踪文本")
    p.add_argument("--force",action="store_true",help="允许覆盖远端（非快进）")
    p.add_argument("--dry-run",action="store_true",help="本地完整提交但不推送（可 git reset --hard 回滚）")
    p.add_argument("--atomic",action="store_true",help="服务器支持时要求原子推送")
    p.add_argument("--push-option",action="append",default=[],help="（记录用；当前协议层不发送 push option）")
    p.add_argument("--timeout",type=int,default=45,help="连接/读超时秒数（默认 45）")
    p.add_argument("--low-speed-limit",type=int,default=10,help="低速阈值 B/s（默认 10）")
    p.add_argument("--low-speed-time",type=int,default=60,help="低速持续多少秒后断开（默认 60）")
    p.add_argument("--progress-interval",type=float,default=0.5,help="进度输出间隔秒（默认 0.5）")
    p.add_argument("--retries",type=int,default=4,help="网络重试次数（默认 4）")
    p.add_argument("--identity",default="",help="提交身份 'Name <email>'（默认取 git 配置或 URL 用户名）")
    p.add_argument("--no-progress",action="store_true",help="关闭实时进度行")
    p.add_argument("--self-test",action="store_true",help="运行完整自检套件")
    a=p.parse_args(argv)
    a.retry_base=1.0  # 指数退避基数（测试里调小）
    return a
def parse_push_url(url,explicit_branch=""):
    if url.startswith("file://"):return url,None,None,explicit_branch
    p=urlsplit(url)
    if p.scheme not in ("http","https"):raise StopPush(f"不支持的远程方案: {p.scheme}（仅 http/https/file）")
    user=unquote(p.username or "");password=unquote(p.password or "")
    if password:remember(password)
    parts=[unquote(q) for q in p.path.strip("/").split("/") if q]
    if len(parts)<2:raise StopPush("URL 形如 https://host/owner/repo(.git)，可带 /tree/<分支>")
    repo=parts[1].removesuffix(".git")
    branch=explicit_branch or ""
    if not branch and len(parts)>=3 and parts[0] in ("tree","blob"):
        branch=parts[2]
        LOG.warning("网页路径只用于定位仓库与分支；推送范围仍是整个本地仓库")
    clean=urlunsplit((p.scheme,p.netloc,"/"+parts[0]+"/"+repo+".git","",""))
    return clean,user,password,branch
def local_push(repo,a,url,ref,head):
    from dulwich.client import LocalGitClient
    path=url[len("file://"):]
    c=LocalGitClient()
    refs=c.get_remote_refs(path)
    old=refs.get(ref)
    if old==head:LOG.info("本地远端已是最新: %s",text(ref));return
    if old and not a.force and not is_ancestor(repo.object_store,old,head):
        raise StopPush(f"非快进: 本地远端 {text(old)[:12]} 与本地分叉，覆盖需 --force")
    c.send_pack(path,{ref:(old,head)},repo.pack_objects([head]))
    LOG.info("本地推送完成: %s → %s",text(ref),text(head)[:12])
def main(a):
    setup_logging(a.verbose)
    t0=time.monotonic()
    try:
        if a.cmd!="push":raise StopPush("当前只实现了 push")
        if not a.url:raise StopPush("缺少远程 URL，用法: pure_push.py -v 3 -u push https://user:token@host/owner/repo")
        remote,user,password,branch=parse_push_url(a.url,a.branch)
        LOG.info("Dulwich 版本: %s | 网络: Python 标准库 socket/ssl/http（无外部依赖）",pkg_version("dulwich"))
        root=Path.cwd()
        try:repo=Repo(str(root))
        except NotGitRepository:raise StopPush(f"当前目录不是 Git 仓库: {root}")
        config=repo.get_config_stack()
        a.lfs_threshold=parse_size(a.lfs_threshold)
        a.max_blob_size=parse_size(a.max_blob_size)
        a.max_commit_size=parse_size(a.max_commit_size)
        if not branch:
            try:branch=text(repo.refs.follow(b"HEAD")[0])[len("refs/heads/"):]
            except MissingReference:branch="master"
        a.branch=branch
        ref=b"refs/heads/"+os.fsencode(branch)
        identity=os.fsencode(a.identity) if a.identity else resolve_identity(config,user,remote)
        a.progress=(a.verbose>=3 or sys.stdout.isatty()) and not a.no_progress
        if a.push_option:LOG.warning("当前协议层不发送 push option: %s",a.push_option)
        LOG.info("仓库路径: %s",root)
        LOG.info("远程地址: %s | 分支: %s",safe_url(remote),branch)
        LOG.info("LFS 阈值: %.2f MiB | 最大普通 Blob: %.2f MiB",a.lfs_threshold/2**20,a.max_blob_size/2**20)
        LOG.info("连接超时: %ds | 低速: %dB/s 持续 %ds | 每 %.2fs 输出",a.timeout,a.low_speed_limit,a.low_speed_time,a.progress_interval)
        LOG.info("提交身份: %s",text(identity))
        cache=LfsCache(Path(tempfile.gettempdir())/"purepush_lfs")
        old_head=repo.refs.get(ref)
        ids,_=prepare(repo,a,identity,cache)
        head=repo.refs.get(ref) or (ids[-1] if ids else None)  # 显式指定的新分支：提交落在 HEAD 分支，这里把它指过来
        if head is None:
            LOG.info("工作区无变化，未创建提交，无可推送内容");return 0
        if repo.refs.get(ref) is None:
            repo.refs[ref]=head
            LOG.info("已创建本地分支 %s 指向 %s",branch,text(head)[:12])
        if a.dry_run:
            LOG.warning("dry-run: 本地已创建提交 %s（回滚: git reset --hard %s），未推送",text(head)[:12],text(old_head)[:12] if old_head else "(无)")
            return 0
        auth=("Basic "+base64.b64encode(f"{user}:{password}".encode()).decode()) if password else None
        net=Transport(a,auth)
        try:
            if remote.startswith("file://"):
                LOG.warning("file:// 远程无 LFS batch 服务：仅推送指针对象，不上传真实内容")
                local_push(repo,a,remote,ref,head)
            else:
                push_target(repo,a,net,remote,ref,head,lfs_batch_url(remote),cache,set())
        finally:net.close()
        LOG.info("推送成功 %s，总耗时 %.1fs",stime(),time.monotonic()-t0)
        return 0
    except StopPush as e:
        LOG.error("失败: %s",redact(e));return 1
    except NetworkFailure as e:
        LOG.error("网络失败: %s",redact(e));return 1
    except KeyboardInterrupt:
        LOG.warning("用户手动终止");return 130
# ============================ 自检（--self-test） ============================
def make_args(**kw):
    d=dict(cmd="push",url="",branch="master",verbose=1,untracked=True,lfs_threshold=512,max_blob_size=10485760,max_commit_size=1200,no_auto_lfs=False,message="t",renormalize=False,force=False,dry_run=False,atomic=False,push_option=[],timeout=10,low_speed_limit=10,low_speed_time=2,progress_interval=0.05,retries=3,retry_base=0.01,identity="",progress=False)
    d.update(kw)
    return argparse.Namespace(**d)
class Base(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)/"repo"
        self.root.mkdir()
        self.repo=Repo.init(str(self.root),mkdir=True)
        self.a=make_args()
        self.identity=b"Test <test@example.com>"
        self.cache=LfsCache(Path(self.temp.name)/"lfs")
    def tearDown(self):
        try:self.repo.close()
        finally:self.temp.cleanup()
    def write(self,rel,data):
        p=self.root/rel
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(data)
    def stage(self):return prepare(self.repo,self.a,self.identity,self.cache)
    def blob_of(self,key):
        e=self.repo.open_index()[key]
        return self.repo.object_store[e.sha].data
def start_git_server(bare_dir):
    # 【修复】L988 用 MemoryRepo 作后端：1.2.15 的 server 会调 add_thin_pack(max_input_size=...)，
    # MemoryObjectStore 没有该参数 → 500。现在用磁盘 bare 仓库的真实 Repo（DiskObjectStore 支持该参数）；
    # DictBackend 的键必须与 URL 中的仓库名一致（test.git），GitBackend([绝对路径]) 会匹配不上。
    from dulwich.server import DictBackend
    from dulwich.web import make_wsgi_app
    from wsgiref.simple_server import WSGIRequestHandler,make_server
    class Quiet(WSGIRequestHandler):
        def log_message(self,*args):pass
    server_app_repo=Repo(str(bare_dir))
    app=make_wsgi_app(DictBackend({"test.git":server_app_repo}))
    server=make_server("127.0.0.1",0,app,handler_class=Quiet)
    server._pp_repo=server_app_repo  # 停服时关闭，避免 Windows 上句柄占用导致临时目录清理失败
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    return server,f"http://127.0.0.1:{server.server_port}/test.git"
def stop_git_server(server):
    server.shutdown();server.server_close()
    with contextlib.suppress(Exception):server._pp_repo.close()
class TestStatSignature(Base):
    def test_sig_stable_and_change_detected(self):
        p=self.root/"sig.txt"
        p.write_bytes(b"hello world")
        self.assertEqual(sig2(os.stat(p)),sig2(os.lstat(p)))
        fd=os.open(str(p),os.O_RDONLY)
        try:self.assertEqual(sig2(os.stat(p)),sig2(os.fstat(fd)))  # 旧的全字段签名在这里就会误报
        finally:os.close(fd)
        with self.assertRaises(StopPush) as cm:
            with regular_reader(p) as (f,_):
                with open(p,"ab") as g:g.write(b"X");g.flush()
                f.read()
        self.assertIn("变化",str(cm.exception))
        self.assertEqual(read_regular(self.root/"sig.txt"),b"hello worldX")
class TestAttr(Base):
    def test_c_quote_and_macro(self):
        self.write(".gitattributes",b'"pa th" filter=lfs\n[attr]mymacro filter=lfs diff=lfs merge=lfs -text\n*.dat mymacro\n')
        attrs=Attributes(self.repo,self.repo.get_config_stack(),self.repo.open_index())
        self.assertEqual(attrs.get(b"pa th").get(b"filter"),b"lfs")  # C 引号路径
        d=attrs.get(b"x.dat")
        self.assertEqual(d.get(b"filter"),b"lfs")
        self.assertEqual(d.get(b"diff"),b"lfs")
        self.assertEqual(d.get(b"merge"),b"lfs")
        self.assertFalse(d.get(b"text"))  # -text = 显式取消
        self.assertIsNone(attrs.get(b"other.txt").get(b"filter"))
    def test_macro_cycle_rejected(self):
        self.write(".gitattributes",b'[attr]a b\n[attr]b a\nx.dat a\n')
        attrs=Attributes(self.repo,self.repo.get_config_stack(),self.repo.open_index())
        with self.assertRaises(StopPush):attrs.get(b"x.dat")
class TestIgnore(Base):
    def test_global_exclude_precedence(self):
        g=Path(self.temp.name)/"global_excl"
        g.write_bytes(b"*.tmp\n")
        info=self.root/".git"/"info";info.mkdir(exist_ok=True)
        (info/"exclude").write_bytes(b"!a.tmp\n")
        self.write("nested/.gitignore",b"!b.tmp\n")
        self.write(".gitignore",b"b.tmp\n")
        self.write("x.tmp",b"x");self.write("a.tmp",b"a");self.write("b.tmp",b"b");self.write("nested/b.tmp",b"nb")
        cfgf=self.root/".git"/"config"
        cfgf.write_bytes(cfgf.read_bytes()+f"[core]\n\texcludesfile = {g}\n".encode())
        m=ignore_manager(self.repo,self.repo.get_config_stack())
        self.assertTrue(is_ignored_strict(m,"x.tmp"))        # 全局规则
        self.assertFalse(is_ignored_strict(m,"a.tmp"))       # info/exclude 覆盖全局
        self.assertTrue(is_ignored_strict(m,"b.tmp"))        # 根 .gitignore
        self.assertFalse(is_ignored_strict(m,"nested/b.tmp"))  # 嵌套 .gitignore 再覆盖
    def test_magic_patterns_and_parent_dir_rule(self):
        self.write(".gitignore",b"**/cache\nlogs/\n!logs/keep.txt\nsrc/*.o\n**/keepme.txt\n*~\n")
        self.write("cache",b"c");self.write("sub/cache",b"c")
        self.write("logs/drop.txt",b"d");self.write("logs/keep.txt",b"k")
        self.write("src/a.o",b"o");self.write("src/lib.a",b"a");self.write("src/x.c",b"x")
        self.write("deep/nest/keepme.txt",b"k")
        self.write("file~",b"t")
        m=ignore_manager(self.repo,self.repo.get_config_stack())
        for rel in ("cache","sub/cache","logs/drop.txt","logs/keep.txt","src/a.o","deep/nest/keepme.txt","file~"):
            self.assertTrue(is_ignored_strict(m,rel),rel)
        # 【教训】logs/ 整个目录被忽略 → 即使有 !logs/keep.txt 也不能重新包含（git 规则）
        for rel in ("src/lib.a","src/x.c"):
            self.assertFalse(is_ignored_strict(m,rel),rel)
class TestHistoryPointer(Base):
    def test_pointer_lifecycle(self):
        self.write("large.bin",b"q"*600)  # > 阈值 512 → 自动 LFS
        self.stage()
        e=self.repo.open_index()[b"large.bin"]
        data=self.repo.object_store[e.sha].data
        oid,size=pointer_info(data)
        self.assertIsNotNone(oid);self.assertEqual(size,600)
        self.assertEqual(self.cache.path(oid).read_bytes(),b"q"*600)
        (self.root/"large.bin").unlink()  # 删除真实文件
        self.stage()  # 【ignore-lfs-delete】指针条目必须保留
        e2=self.repo.open_index()[b"large.bin"]
        self.assertEqual(e2.sha,e.sha)
        need=outgoing_lfs(self.repo,{},self.repo.head(),self.a)
        self.assertEqual(need[oid],size)
        # no_auto_lfs：超阈值但没有 filter=lfs → 保持普通 Blob → 受 max_blob 限制
        self.a.no_auto_lfs=True
        self.write("oversize",b"z"*512)
        self.stage()
        self.a.max_blob_size=400
        with self.assertRaises(StopPush):outgoing_lfs(self.repo,{},self.repo.head(),self.a)
class TestIgnoreLfsDelete(Base):
    def test_full_scenario(self):
        self.write("tracked.tmp",b"old");self.stage()
        self.write("tracked.tmp",b"new")  # 已跟踪文件：即使后来被 ignore 也照常提交修改
        self.write(".gitignore",b"*.tmp\n!keep.tmp\nblocked/\n!blocked/no.txt\nselect/*\n!select/keep.txt\nignored-large.bin\n")
        self.write("drop.tmp",b"drop");self.write("keep.tmp",b"keep")
        self.write("blocked/no.txt",b"no");self.write("select/keep.txt",b"yes");self.write("select/no.txt",b"no")
        self.write("ignored-large.bin",b"x"*600)
        self.write("has space.bin",b"a"*600)  # 带空格 + 超阈值 → LFS
        self.write(".gitattributes",b"*.lfs filter=lfs diff=lfs merge=lfs -text\n")
        self.write("small.lfs",b"x")
        self.write("nested/.gitignore",b"!stay.tmp\n")
        self.write("nested/stay.tmp",b"stay")
        self.stage()
        index=self.repo.open_index()
        self.assertEqual(self.repo.object_store[index[b"tracked.tmp"].sha].data,b"new")
        for k in (b"drop.tmp",b"blocked/no.txt",b"select/no.txt",b"ignored-large.bin"):
            self.assertNotIn(k,index)  # 被忽略 / 父目录被忽略
        for k in (b"keep.tmp",b"select/keep.txt",b"nested/stay.tmp",b"has space.bin",b"small.lfs",b".gitignore",b".gitattributes"):
            self.assertIn(k,index)
        need=outgoing_lfs(self.repo,self.cache,self.repo.head(),self.a)
        self.assertEqual(len(need),2)  # 只有两个 LFS 对象
class TestWatchdog(unittest.TestCase):
    def test_slow_and_stall(self):
        class Dummy:
            closed=False
            def shutdown(self,how):self.closed=True
        a=make_args(progress_interval=0.01,low_speed_limit=10,low_speed_time=0.06,progress=False)
        s1=Dummy()
        m1=TransferMonitor(s1,a,"slow",total=10**9)
        t=time.monotonic()
        while not s1.closed and time.monotonic()-t<3:
            m1.observe(n_sent=1)
            time.sleep(0.15)  # ≈7B/s < 10B/s
        self.assertTrue(s1.closed)
        s2=Dummy()
        m2=TransferMonitor(s2,a,"stall",total=10**9)
        m2.observe(n_sent=1000)
        time.sleep(0.03);m2._check()  # 先落一次基线（dt<0.02 的观察会被跳过）
        time.sleep(0.1)
        m2._check()  # 完全无数据也触发
        self.assertTrue(s2.closed)
        s3=Dummy()
        m3=TransferMonitor(s3,a,"fast")
        for _ in range(10):
            m3.observe(n_sent=100000)
            time.sleep(0.02)
        self.assertFalse(s3.closed)  # 健康速度不误杀
class TestMissingCacheAndCli(Base):
    def test_missing_lfs_cache_failfast(self):
        ptr=pointer_bytes("a"*64,10)
        blob=Blob.from_string(ptr);sha=self.repo.object_store.add_object(blob)
        tmpf=self.root/"ghost";tmpf.write_bytes(b"g")
        index=self.repo.open_index()
        index[b"ghost"]=index_entry_from_stat(os.stat(tmpf),sha,mode=0o100644)
        cache=LfsCache(Path(self.temp.name)/"empty_lfs")
        net=Transport(make_args(),None)
        with self.assertRaises(StopPush) as cm:
            upload_lfs(net,"http://127.0.0.1:9/batch",{"a"*64:10},cache,b"refs/heads/master",set())
        self.assertIn("缓存",str(cm.exception))
    def test_cli_and_url(self):
        a=parse_args(["-v","3","-u","push","https://qgbcs:ghp_7xxx@github.com/qgbcs/_"])
        self.assertEqual(a.verbose,3);self.assertTrue(a.untracked);self.assertEqual(a.cmd,"push")
        remote,user,password,branch=parse_push_url(a.url,a.branch)
        self.assertEqual(remote,"https://github.com/qgbcs/_.git")
        self.assertEqual((user,password),("qgbcs","ghp_7xxx"))
        self.assertEqual(branch,"master")
        self.assertEqual(resolve_identity(None,"qgbcs",remote),b"qgbcs <qgbcs@users.noreply.github.com>")
        self.assertNotIn("ghp_7xxx",safe_url("https://qgbcs:ghp_7xxx@github.com/qgbcs/_.git"))
class TestNetwork(Base):
    def test_retry_http_and_lfs(self):
        from http.server import BaseHTTPRequestHandler
        from socketserver import ThreadingHTTPServer
        counters={};stored={};token="Basic unit-test-secret"
        test=self
        class Handler(BaseHTTPRequestHandler):
            protocol_version="HTTP/1.1"
            def log_message(self,*args):pass
            def reply(self,code,body,headers=None):
                self.send_response(code)
                for k,v in (headers or {}).items():self.send_header(k,v)
                self.send_header("Content-Length",str(len(body)));self.end_headers()
                self.wfile.write(body)
            def do_GET(self):
                counters[self.path]=counters.get(self.path,0)+1
                if self.path=="/flaky" and counters[self.path]==1:self.reply(503,b"retry");return
                if self.path=="/unauthorized":self.reply(401,b"denied");return
                if self.path=="/redirect":self.reply(302,b"",{"Location":f"http://localhost:{self.server.server_port}/auth-check"});return
                if self.path=="/same-redirect":self.reply(307,b"",{"Location":"/auth-check"});return
                if self.path=="/auth-check":self.reply(200,self.headers.get("Authorization","").encode());return
                self.reply(200,b"ok")
            def do_PUT(self):
                data=self.rfile.read(int(self.headers["Content-Length"]))
                stored[hashlib.sha256(data).hexdigest()]=data
                counters["put-path"]=self.path
                self.reply(200,b"")
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path=="/verify":
                    test.assertEqual(len(stored[data["oid"]]),data["size"])
                    self.reply(200,b"{}");return
                objects=[]
                for item in data["objects"]:
                    item=dict(item)
                    if item["oid"] not in stored:
                        item["actions"]={"upload":{"href":f"http://127.0.0.1:{self.server.server_port}/upload?signature=kept"},"verify":{"href":f"http://127.0.0.1:{self.server.server_port}/verify"}}
                    objects.append(item)
                self.reply(200,json.dumps({"objects":objects}).encode())
        server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f"http://127.0.0.1:{server.server_port}"
        net=Transport(self.a,token)
        def get(path):
            r=net.request("GET",base+path)
            try:return r.read()
            finally:r.close()
        try:
            self.assertEqual(retry(self.a,"测试重试",lambda:get("/flaky")),b"ok")
            self.assertEqual(counters["/flaky"],2)  # 503 重试一次
            with self.assertRaises(HTTPFailure):retry(self.a,"测试认证",lambda:get("/unauthorized"))
            self.assertEqual(counters["/unauthorized"],1)  # 401 不重试
            self.assertEqual(get("/redirect"),b"")  # 跨源重定向丢弃令牌
            self.assertEqual(get("/same-redirect"),token.encode())  # 同源重定向保留令牌
            self.write("payload",b"binary"*100)
            oid,size=pointer_info(self.cache.put(self.root/"payload"))
            done=set()
            upload_lfs(net,base+"/batch",{oid:size},self.cache,b"refs/heads/main",done)
            self.assertIn((oid,size),done)
            self.assertEqual(stored[oid],b"binary"*100)
            self.assertEqual(counters["put-path"],"/upload?signature=kept")  # 签名保留
            done.clear()
            upload_lfs(net,base+"/batch",{oid:size},self.cache,b"refs/heads/main",done)  # 已存在 → 跳过上传
            self.assertIn((oid,size),done)
        finally:
            net.close();server.shutdown();server.server_close();thread.join(timeout=2)
class TestSplitAndPush(Base):
    def test_split_commits_and_wsgi_push(self):
        for i in range(5):self.write(f"file{i}",b"x"*(300+i))
        self.a.max_commit_size=800
        commits,_=self.stage()
        self.assertEqual(len(commits),3)
        self.assertIn("【1/3】",self.repo[commits[0]].message.decode())
        head=self.repo.head()
        bare_dir=Path(self.temp.name)/"bare"
        bare=Repo.init_bare(str(bare_dir),mkdir=True)
        server,url=start_git_server(bare_dir)
        try:
            net=Transport(self.a,None)
            try:push_target(self.repo,self.a,net,url,b"refs/heads/master",head,url+"/info/lfs/objects/batch",self.cache,set())
            finally:net.close()
            self.assertEqual(bare.refs.get(b"refs/heads/master"),head)
        finally:
            stop_git_server(server);bare.close()
class TestIdempotentPush(Base):
    def test_push_twice(self):
        self.write("http-file",b"smart-http")
        self.stage()
        head=self.repo.head()
        bare_dir=Path(self.temp.name)/"bare2"
        bare=Repo.init_bare(str(bare_dir),mkdir=True)
        server,url=start_git_server(bare_dir)
        try:
            net=Transport(self.a,None)
            try:
                for _ in range(2):
                    push_target(self.repo,self.a,net,url,b"refs/heads/master",head,url+"/info/lfs/objects/batch",self.cache,set())
            finally:net.close()
            self.assertEqual(bare.refs.get(b"refs/heads/master"),head)  # 第二次幂等无操作
        finally:
            stop_git_server(server);bare.close()
class TestFastForward(Base):
    def test_non_ff_rejected_then_force(self):
        self.write("f1",b"one")
        self.stage()
        head=self.repo.head()
        bare_dir=Path(self.temp.name)/"bare3"
        bare=Repo.init_bare(str(bare_dir),mkdir=True)
        server,url=start_git_server(bare_dir)
        net=Transport(self.a,None)
        try:
            push_target(self.repo,self.a,net,url,b"refs/heads/master",head,url+"/info/lfs/objects/batch",self.cache,set())
            # 让远端分叉：在 bare 上追加一个提交
            blob=Blob.from_string(b"remote");bs=bare.object_store.add_object(blob)
            t=Tree();t.entries=[(b"extra",0o100644,bs)];ts=bare.object_store.add_object(t)
            c=Commit()
            c.tree=ts;c.parents=[head]
            c.author=b"R <r@x>";c.committer=b"R <r@x>"
            c.commit_time=1700000000;c.commit_time_tz_offset=0
            c.author_time=1700000000;c.author_time_tz_offset=0
            c.message=b"remote"
            rs=bare.object_store.add_object(c)
            bare.refs[b"refs/heads/master"]=rs
            self.a.force=False
            with self.assertRaises(StopPush) as cm:
                push_target(self.repo,self.a,net,url,b"refs/heads/master",head,url+"/info/lfs/objects/batch",self.cache,set())
            self.assertIn("非快进",str(cm.exception))
            # force：先删远端引用再推（等效覆盖，避免服务端 FF 策略差异）
            del bare.refs[b"refs/heads/master"]
            self.a.force=True
            push_target(self.repo,self.a,net,url,b"refs/heads/master",head,url+"/info/lfs/objects/batch",self.cache,set())
            self.assertEqual(bare.refs.get(b"refs/heads/master"),head)
        finally:
            net.close();stop_git_server(server);bare.close()
class TestSymlink(Base):
    def test_does_not_walk_target(self):
        outside=Path(self.temp.name)/"outside"
        outside.mkdir()
        (outside/"inside.txt").write_bytes(b"zzz")
        try:
            os.symlink(str(outside),str(self.root/"linkdir"))
            os.symlink("real.txt",str(self.root/"flink"))
        except (OSError,PermissionError):
            self.skipTest("环境无权限创建符号链接")
        self.write("real.txt",b"r")
        self.stage()
        index=self.repo.open_index()
        self.assertEqual(index[b"linkdir"].mode,0o120000)
        self.assertEqual(self.repo.object_store[index[b"linkdir"].sha].data,os.fsencode(str(outside)))
        self.assertEqual(index[b"flink"].mode,0o120000)
        self.assertEqual(self.repo.object_store[index[b"flink"].sha].data,b"real.txt")
        self.assertNotIn(b"linkdir/inside.txt",index)  # 绝不跟随链接进入
class TestUrlAndRetry(unittest.TestCase):
    def test_parse(self):
        r,u,pw,b=parse_push_url("https://u:p@github.com/o/r.git")
        self.assertEqual(r,"https://github.com/o/r.git");self.assertEqual((u,pw,b),("u","p",""))
        r,u,pw,b=parse_push_url("https://github.com/o/r/tree/dev2/x")
        self.assertEqual(r,"https://github.com/o/r.git");self.assertEqual(b,"dev2")
        r,u,pw,b=parse_push_url("https://github.com/o/r")
        self.assertEqual(r,"https://github.com/o/r.git")
        with self.assertRaises(StopPush):parse_push_url("ssh://git@github.com/o/r")
    def test_redact(self):
        s=safe_url("https://u:secretpw@github.com/o/r.git?x=1")
        self.assertNotIn("secretpw",s)
    def test_classification_and_delay(self):
        self.assertIn(500,RETRY_HTTP);self.assertIn(429,RETRY_HTTP);self.assertIn(502,RETRY_HTTP)
        for c in (400,401,403,404,409,413):self.assertNotIn(c,RETRY_HTTP)
        self.assertEqual(retry_delay("3"),3.0)
        from email.utils import format_datetime
        d=retry_delay(format_datetime(datetime.now().astimezone()+timedelta(seconds=30)))
        self.assertTrue(25<d<35)
    def test_retry_exhausts_then_raises(self):
        a=make_args(retries=2,timeout=1,retry_base=0.01)
        net=Transport(a,None)
        with self.assertRaises(NetworkFailure):
            retry(a,"死端口",lambda:net.request("GET","http://127.0.0.1:9/x","t"))
class TestEol(Base):
    def test_normalize_and_renormalize(self):
        self.write(".gitattributes",b"keep_crlf.txt -text\ni.txt ident\n")
        self.write("win.txt",b"line1\r\nline2\r\n")
        self.write("bin.dat",b"\x00\x01\r\n\r\n")
        self.write("keep_crlf.txt",b"a\r\nb\r\n")
        self.write("i.txt",b"Id: $Id:abc123$ ok\n")
        self.stage()
        self.assertEqual(self.blob_of(b"win.txt"),b"line1\nline2\n")  # 自动文本 CRLF→LF
        self.assertEqual(self.blob_of(b"bin.dat"),b"\x00\x01\r\n\r\n")  # 二进制不动
        self.assertEqual(self.blob_of(b"keep_crlf.txt"),b"a\r\nb\r\n")  # -text 不动
        self.assertIn(b"$Id$",self.blob_of(b"i.txt"))  # ident
        self.assertNotIn(b"abc123",self.blob_of(b"i.txt"))
        store=self.repo.object_store
        old_blob=Blob.from_string(b"old\r\ncrlf\r\n");old_sha=store.add_object(old_blob)
        class E:mode=0o100644;sha=old_sha
        cfg=self.repo.get_config_stack()
        self.assertEqual(normalize_blob(b"old\r\ncrlf\r\n",{},E(),self.repo,cfg,b"n.txt",True),b"old\ncrlf\n")
        self.assertEqual(normalize_blob(b"old\r\ncrlf\r\n",{},E(),self.repo,cfg,b"n.txt",False),b"old\r\ncrlf\r\n")
        with self.assertRaises(StopPush):
            normalize_blob(b"x",{b"filter":b"external"},None,self.repo,cfg,b"f.txt",False)
def self_test():
    setup_logging(0)
    for stream in (sys.stdout,sys.stderr):
        with contextlib.suppress(Exception):stream.reconfigure(errors="replace")
    suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1
if __name__=="__main__":
    _a=parse_args(sys.argv[1:])
    for _st in (sys.stdout,sys.stderr):
        with contextlib.suppress(Exception):_st.reconfigure(errors="replace")
    sys.exit(self_test() if _a.self_test else main(_a))

r'''


C:\Users\Administrator\Documents\energetic>
C:\Users\Administrator\Documents\energetic>C:\QGB\anaconda3\python D:\test\github\dulwich_git\L1441.py --self-test
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1441.py", line 18, in <module>
    from dulwich.errors import MissingReference,NotGitRepository
ImportError: cannot import name 'MissingReference' from 'dulwich.errors' (C:\QGB\anaconda3\Lib\site-packages\dulwich\errors.py)

'''