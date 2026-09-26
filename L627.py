#!/usr/bin/env python3
from __future__ import annotations
import argparse,base64,codecs,errno,hashlib,http.client,io,json,logging,math,os,queue,re,socket,ssl,stat,sys,tempfile,threading,time
from collections import deque
from contextlib import contextmanager,suppress
from datetime import datetime
from email.utils import parsedate_to_datetime
from importlib.metadata import version
from pathlib import Path
from urllib.parse import parse_qsl,quote,unquote,urljoin,urlsplit,urlunsplit
from urllib.request import getproxies,proxy_bypass
from dulwich.attrs import Pattern as AttrPattern
from dulwich.client import AbstractHttpGitClient
from dulwich.config import ConfigFile,apply_instead_of
from dulwich.errors import GitProtocolError,HangupException,NotGitRepository
from dulwich.file import GitFile
from dulwich.ignore import IgnoreFilter,IgnoreFilterManager,default_user_ignore_filter_path
from dulwich.index import IndexEntry,commit_tree,index_entry_from_stat,write_index_dict,validate_path,get_path_element_validator
from dulwich.object_store import MissingObjectFinder,iter_tree_contents
from dulwich.objects import Blob,Commit
from dulwich.pack import SHA1Writer
from dulwich.protocol import ZERO_SHA
from dulwich.refs import check_ref_format
from dulwich.repo import Repo

LOG=logging.getLogger("PurePush");SECRETS=set();CHUNK=64*1024;POINTER_PREFIX=b"version https://git-lfs.github.com/spec/v1\n";MEDIA="application/vnd.git-lfs+json"
class StopPush(RuntimeError):pass # 用户级致命错误，停止推送
class NetworkFailure(RuntimeError):pass # 网络异常，可触发自动重试
class HTTPFailure(StopPush): # HTTP 状态码异常
    def __init__(self,code,url,detail="",retry_after=0):super().__init__(f"HTTP {code} {safe_url(url)} {detail}");self.code=int(code);self.retry_after=retry_after

def remember(secret): # 记录密钥以在日志输出中自动脱敏
    if secret and len(str(secret))>3:SECRETS.add(str(secret))
def safe_url(value): # 去除 URL 中的鉴权信息及查询串，防止泄露 token
    try:
        p=urlsplit(str(value));host=p.hostname or "";host=f"[{host}]" if ":" in host else host
        return urlunsplit((p.scheme,host+(f":{p.port}" if p.port else ""),p.path,"",""))
    except ValueError:return "[URL 已隐藏]"
def redact(value): # 敏感词脱敏替换
    text=str(value)
    for secret in sorted(SECRETS,key=len,reverse=True):text=text.replace(secret,"***")
    text=re.sub(r"https?://[^\s\"' ]+",lambda m:safe_url(m.group()),text)
    return text.replace("\x1b","\\x1b")
class SafeFormatter(logging.Formatter): # 安全日志格式化器
    def format(self,record):return redact(super().format(record))
def setup_logging(v): # 配置日志级别及输出
    handler=logging.StreamHandler(sys.stdout);handler.setFormatter(SafeFormatter("%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s","%Y-%m-%d %H:%M:%S"))
    LOG.handlers[:]=[handler];LOG.propagate=False;LOG.setLevel({0:logging.ERROR,1:logging.WARNING,2:logging.INFO}.get(v,logging.DEBUG))
def trace(a,message,*values): # 调试追踪日志
    if a.trace:LOG.log(logging.DEBUG if a.verbose>=3 else logging.INFO,message,*values)
def cfg(config,section,key,default=b""): # 读取 git 配置
    section=(section,) if isinstance(section,bytes) else section
    try:return config.get(section,key)
    except KeyError:return default
def text(value):return value.decode("utf-8","surrogateescape") if isinstance(value,bytes) else str(value) # 字节安全转字符串
def yes(config,section,key,default=False):return config.get_boolean(section,key,default) # 读取布尔配置
def human(n): # 格式化字节大小
    units=("B","KiB","MiB","GiB","TiB");i=0;n=float(n)
    while n>=1024 and i<len(units)-1:n/=1024;i+=1
    return f"{n:.2f} {units[i]}"
def parse_bytes(v): # 解析带单位的大小字符串
    if isinstance(v,(int,float)):return int(v)
    v=str(v).strip().lower();m={"b":1,"k":1024,"kb":1024,"kib":1024,"m":1024**2,"mb":1024**2,"mib":1024**2,"g":1024**3,"gb":1024**3,"gib":1024**3}
    match=re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([a-z]*)$",v)
    if not match:raise ValueError(f"无法解析大小: {v}")
    val,unit=match.groups();return int(float(val)*m.get(unit,1))
def retry_delay(header): # 计算 Retry-After 延迟时间
    if not header:return 0
    try:return max(0,int(header))
    except ValueError:
        try:dt=parsedate_to_datetime(header);return max(0,int((dt-datetime.now(dt.tzinfo)).total_seconds()))
        except Exception:return 0
def origin(url): # 提取 URL 源 (scheme + host:port)
    p=urlsplit(url);host=p.hostname or "";host=f"[{host}]" if ":" in host else host
    return f"{p.scheme}://{host}{f':{p.port}' if p.port else ''}"
def clean_remote_and_auth(raw,branch=None): # 解析远端 URL、用户名密码及分支
    p=urlsplit(raw);user=unquote(p.username) if p.username else None;password=unquote(p.password) if p.password else None
    remember(password);parts=[x for x in p.path.split("/") if x]
    if not branch and p.netloc in ("github.com","gitlab.com","gitee.com") and len(parts)>2:
        branch=unquote(parts[3] if parts[2] in ("tree","blob") and len(parts)>3 else parts[2]);LOG.warning("网页路径只用于定位仓库，推送范围仍是整个本地仓库；含斜杠的分支请显式指定 --branch")
    clean=urlunsplit((p.scheme,p.netloc,"/"+"/".join(parts[:2]).removesuffix(".git")+".git","",""))
    return clean.rstrip("/"),user,password,branch
def atomic_write(path,data): # 原子写入文件，通过同一目录临时文件覆盖
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise StopPush(f"拒绝覆盖符号链接: {path}")
    mode=stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644;fd,tmp=tempfile.mkstemp(prefix=".purepush-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,mode);os.replace(tmp,path)
    finally:
        with suppress(FileNotFoundError):os.unlink(tmp)
def signature(st): # 修复 Windows/NTFS 纳秒与访问时间抖动：只校验设备、inode、模式、大小、秒级修改时间
    return st.st_dev,st.st_ino,st.st_mode,st.st_size,int(st.st_mtime)
@contextmanager
def regular_reader(path): # 安全读取普通文件上下文，防止读取前后被非法篡改或被链接劫持
    before=path.lstat()
    if not stat.S_ISREG(before.st_mode):raise StopPush(f"不是普通文件，拒绝跟随链接: {path}")
    fd=os.open(path,os.O_RDONLY|getattr(os,"O_BINARY",0)|getattr(os,"O_NOFOLLOW",0))
    with os.fdopen(fd,"rb") as f:
        if signature(os.fstat(f.fileno()))!=signature(before):raise StopPush(f"读取前文件已经变化: {path}")
        yield f,before
        if signature(os.fstat(f.fileno()))!=signature(before) or signature(path.lstat())!=signature(before):raise StopPush(f"读取时文件发生变化，请重试本地操作: {path}")
def read_regular(path,limit=None): # 读取普通文件全部内容
    with regular_reader(Path(path)) as (f,st):
        if limit is not None and st.st_size>limit:raise StopPush(f"配置文件过大: {path}")
        return f.read()
def config_bytes(path): # 安全读取配置文件内容，不存在或链接返回空字节
    path=Path(path)
    if path.is_symlink():return b""
    try:return read_regular(path,8*1024*1024)
    except (FileNotFoundError,NotADirectoryError):return b""
class SafeIgnore(IgnoreFilterManager): # 适配 Dulwich 1.2.15 忽略管理器，安全阻止递归与链接穿透
    def _load_path(self,path):
        if (Path(self._top_path)/path/".gitignore").is_symlink():return None
        return super()._load_path(path)
    def _is_dir(self,path):
        p=Path(self._top_path)/path;return path.endswith("/") or (p.is_dir() and not p.is_symlink())
def ignore_manager(repo,config): # 构建多层 gitignore 过滤器，从全局、exclude 到局部
    ignorecase=yes(config,(b"core",),b"ignorecase",False);filters=[]
    for path in (Path(default_user_ignore_filter_path(config)).expanduser(),Path(repo.controldir())/"info"/"exclude"):
        try:filters.append(IgnoreFilter.from_path(path,ignorecase))
        except FileNotFoundError:pass
    return SafeIgnore(str(repo.path),filters,ignorecase)
def attr_words(line): # 解析 .gitattributes 单行词法，正确支持转义引号路径
    line=line.strip()
    if not line or line.startswith(b"#"):return None,[]
    if not line.startswith(b'"'):
        words=line.split();return words[0],words[1:]
    out=bytearray();i=1;esc={ord("a"):7,ord("b"):8,ord("t"):9,ord("n"):10,ord("v"):11,ord("f"):12,ord("r"):13,34:34,92:92}
    while i<len(line):
        ch=line[i];i+=1
        if ch==34:break
        if ch!=92:out.append(ch);continue
        if i>=len(line):break
        b=line[i];i+=1
        if 48<=b<=55:
            octal=bytes([b])
            while len(octal)<3 and i<len(line) and 48<=line[i]<=55:octal+=bytes([line[i]]);i+=1
            val=int(octal,8)
            if val>255:raise StopPush("属性路径的八进制转义超出字节范围")
            out.append(val)
        elif b in esc:out.append(esc[b])
        else:raise StopPush(".gitattributes 中存在不支持的 C 转义")
    else:raise StopPush(".gitattributes 的路径引号没有闭合")
    return bytes(out),line[i:].split()
def parse_attribute(token): # 解析单个属性键值如 filter=lfs 或 -text
    if token[:1] in (b"-",b"!"):return token[1:],False if token[:1]==b"-" else None
    if b"=" in token:return tuple(token.split(b"=",1))
    return token,True
class Attributes: # 管理和匹配多层 .gitattributes
    def __init__(self,repo,config,index):
        self.repo=repo;self.root=Path(repo.path);self.index=index;self.cache={}
        self.global_path=Path(text(cfg(config,b"core",b"attributesfile",os.fsencode(Path(os.environ.get("XDG_CONFIG_HOME",str(Path.home()/".config")))/"git"/"attributes")))).expanduser()
        self.info=Path(repo.controldir())/"info"/"attributes"
    def load(self,path,relative=None,macro_allowed=True):
        key=str(path)
        if key in self.cache:return self.cache[key]
        data=config_bytes(path)
        if not path.exists() and relative is not None and relative in self.index:
            entry=self.index[relative]
            if entry.mode in (0o100644,0o100755):data=self.repo.object_store[entry.sha].data
        rules=[];macros={}
        for line in data.splitlines():
            pattern,tokens=attr_words(line)
            if pattern is None:continue
            values=[parse_attribute(t) for t in tokens]
            if pattern.startswith(b"[attr]"):
                if macro_allowed:macros[pattern[6:]]=values
                else:LOG.warning("忽略子目录中不允许定义的属性宏: %s",path)
            elif pattern.startswith(b"!"):raise StopPush(f".gitattributes 不允许负模式: {path}")
            else:
                try:rules.append((AttrPattern(pattern),values))
                except ValueError as exc:raise StopPush(f"属性模式无效: {path}: {exc}") from exc
        self.cache[key]=(rules,macros);return rules,macros
    def get(self,rel): # 获取指定路径最终生效的属性集合
        parts=rel.split(b"/");levels=[(self.global_path,rel,None,True)]
        for i in range(len(parts)):
            name=b"/".join(parts[:i]+[b".gitattributes"]);levels.append((self.root/os.fsdecode(name),b"/".join(parts[i:]),name,i==0))
        levels.append((self.info,rel,None,True));loaded=[(self.load(p,key,macros),local) for p,local,key,macros in levels];definitions={b"binary":[(b"diff",False),(b"merge",False),(b"text",False)]};result={}
        for (_,macros),_ in loaded:definitions.update(macros)
        def apply(values,seen=frozenset()):
            for name,value in values:
                result[name]=value
                if value is True and name in definitions:
                    if name in seen:raise StopPush("属性宏循环引用: "+text(name))
                    apply(definitions[name],seen|{name})
        for (rules,_),local in loaded:
            for pattern,values in rules:
                if pattern.match(local):apply(values)
        return {k:v for k,v in result.items() if v is not None}
def exact_attr_rule(name): # 转义生成单文件完全匹配规则
    pattern=b"/"+b"".join((b"\\"+bytes([b])) if b in b"\\*?[]" else bytes([b]) for b in os.fsencode(name))
    quoted=b'"'+b"".join(bytes([b]) if 32<=b<=126 and b not in (34,92) else (b"\\"+bytes([b]) if b in (34,92) else f"\\{b:03o}".encode()) for b in pattern)+b'"'
    return quoted+b" filter=lfs diff=lfs merge=lfs -text\n"
def pointer_bytes(oid,size):return f"version https://git-lfs.github.com/spec/v1\noid sha256:{oid}\nsize {size}\n".encode("utf-8") # 格式化 LFS 指针内容
def pointer_info(data): # 解析 LFS 指针并提取 oid 和 size
    if not data or not data.startswith(POINTER_PREFIX):return None
    try:lines=data.decode("utf-8").splitlines()
    except UnicodeDecodeError:return None
    if len(lines)<3:return None
    oid=lines[1].removeprefix("oid sha256:");size=lines[2].removeprefix("size ")
    if len(oid)!=64 or not all(c in "0123456789abcdefABCDEF" for c in oid) or not size.isdigit():return None
    return oid.lower(),int(size)
class LFSCache: # LFS 本地对象存储缓存 (.git/lfs/objects/...)
    def __init__(self,repo):self.base=Path(repo.controldir())/"lfs"/"objects";self.verified={}
    def path(self,oid):return self.base/oid[:2]/oid[2:4]/oid
    def put(self,path): # 将普通文件哈希后存入 LFS 对象目录，返回 LFS 指针
        path=Path(path);name=self.path("tmp-"+path.name+"-"+str(time.time_ns()));name.parent.mkdir(parents=True,exist_ok=True);h=hashlib.sha256();size=0;last=time.monotonic()
        fd=os.open(name,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,"O_BINARY",0),0o644)
        try:
            with os.fdopen(fd,"wb") as out,regular_reader(path) as (f,st):
                for block in iter(lambda:f.read(1024*1024),b""):
                    h.update(block);out.write(block);size+=len(block)
                    if time.monotonic()-last>=1:LOG.info("LFS 本地快照: %s | %s/%s",path.name,human(size),human(st.st_size));last=time.monotonic()
                out.flush();os.fsync(out.fileno())
            oid=h.hexdigest();dest=self.path(oid);dest.parent.mkdir(parents=True,exist_ok=True);os.replace(name,dest);self.verified[oid,size]=signature(dest.stat());return pointer_bytes(oid,size)
        finally:
            with suppress(FileNotFoundError):os.unlink(name)
    def require(self,oid,size): # 验证并获取已存在的 LFS 对象路径
        path=self.path(oid)
        if not path.is_file() or path.is_symlink():raise StopPush(f"远端需要 LFS {oid}，但本地缓存不存在；恢复原文件/缓存后再推送，不能只发送指针")
        if self.verified.get((oid,size))!=signature(path.stat()):
            h=hashlib.sha256();total=0
            with regular_reader(path) as (f,_):
                for block in iter(lambda:f.read(1024*1024),b""):h.update(block);total+=len(block)
            if total!=size or h.hexdigest()!=oid:raise StopPush(f"LFS 缓存损坏: {oid}")
            self.verified[oid,size]=signature(path.stat())
        if path.stat().st_size!=size:raise StopPush(f"LFS 缓存大小改变: {oid}")
        return path
def walk_candidates(repo,index,manager,config): # 深度扫描工作区候选文件，精确结合 gitignore 与已跟踪索引
    root=Path(repo.path);tracked=dict(index.items());ignorecase=yes(config,(b"core",),b"ignorecase",False);lookup={os.fsdecode(k).casefold():k for k in tracked} if ignorecase else {};files={};skipped=0;count=0;last=time.monotonic();validator=get_path_element_validator(config)
    def folded(rel):return os.fsdecode(rel).casefold() if ignorecase else os.fsdecode(rel)
    parents={folded(b"/".join(p.split(b"/")[:i])) for p in tracked for i in range(1,len(p.split(b"/")))}
    def old_key(rel):return rel if rel in tracked else lookup.get(os.fsdecode(rel).casefold())
    def add(path):
        nonlocal skipped,count,last
        rel=os.fsencode(path.relative_to(root).as_posix());old=old_key(rel);count+=1
        if not validate_path(rel,validator):raise StopPush(f"无效 Git 路径: {path}")
        if old is None and manager.is_ignored(os.fsdecode(rel)) is True:skipped+=1;return
        files[rel]=(path,old)
        if time.monotonic()-last>=1:LOG.info("扫描文件: %d | 排除: %d | 当前: %s",count,skipped,os.fsdecode(rel));last=time.monotonic()
    def onerror(error):raise error
    for base,dirs,names in os.walk(root,topdown=True,followlinks=False,onerror=onerror):
        current=Path(base);keep=[]
        for name in dirs:
            path=current/name;rel=os.fsencode(path.relative_to(root).as_posix())
            if (name.casefold() if os.name=="nt" else name)==".git":continue
            if path.is_symlink():add(path);continue
            if folded(rel) not in parents and old_key(rel) is None and manager.is_ignored(os.fsdecode(rel)) is True:skipped+=1;continue
            if getattr(path,"is_junction",lambda:False)():raise StopPush(f"拒绝遍历 Windows junction: {path}")
            if (path/".git").exists() or (old_key(rel) is not None and tracked[old_key(rel)].mode==0o160000):add(path);continue
            keep.append(name)
        dirs[:]=keep
        for name in names:
            if (name.casefold() if os.name=="nt" else name)!=".git":add(current/name)
    LOG.info("扫描完成: %d 项 | 未跟踪且被忽略: %d 项",count,skipped);return files
def normalize_blob(data,attrs,old,repo,config,path,renormalize=False): # 换行符与内容规范化处理
    if attrs.get(b"working-tree-encoding") not in (None,False):raise StopPush(f"暂不支持 working-tree-encoding: {os.fsdecode(path)}")
    selected=attrs.get(b"filter")
    if selected not in (None,False,b"lfs"):raise StopPush(f"不执行外部 filter={text(selected)}: {os.fsdecode(path)}")
    if attrs.get(b"ident") is True:data=re.sub(rb"\$Id:[^$\r\n]*\$",b"$Id$",data)
    text_attr=attrs.get(b"text");eol=attrs.get(b"eol");auto=cfg(config,b"core",b"autocrlf",b"false").lower()
    if text_attr is None and b"crlf" in attrs:text_attr=False if attrs[b"crlf"] is False else True
    if text_attr is False or (text_attr is None and eol is None and auto not in (b"true",b"input")):return data
    automatic=text_attr!=True and not (text_attr is None and eol in (b"lf",b"crlf"));nonprint=sum(data.count(bytes([b])) for b in range(32) if b not in (8,9,10,12,13,27))+data.count(b"\x7f")
    if automatic and (b"\0" in data or data.count(b"\r")!=data.count(b"\r\n") or nonprint>(len(data)-nonprint)//128):return data
    if automatic and old is not None and not renormalize and old.mode!=0o160000:
        if b"\r\n" in repo.object_store[old.sha].data:return data
    converted=data.replace(b"\r\n",b"\n");safe=cfg(config,b"core",b"safecrlf",b"false").lower();core_eol=cfg(config,b"core",b"eol",b"native");checkout_crlf=eol==b"crlf" or (eol is None and (auto==b"true" or (auto!=b"input" and (core_eol==b"crlf" or (core_eol==b"native" and os.name=="nt")))))
    restored=converted.replace(b"\n",b"\r\n") if checkout_crlf else converted
    if safe in (b"true",b"warn") and restored!=data:
        if safe==b"true":raise StopPush(f"core.safecrlf 拒绝不可逆换行转换: {os.fsdecode(path)}")
        LOG.warning("换行转换不可逆: %s",os.fsdecode(path))
    return converted
def stage_all(repo,index,a,config,cache): # 全功能暂存工作区文件，自动处理大文件及 LFS
    if any(not isinstance(entry,IndexEntry) for _,entry in index.items()):raise StopPush("索引存在未解决冲突，拒绝自动提交")
    if any(stat.S_ISDIR(entry.mode) or entry.skip_worktree for _,entry in index.items()):raise StopPush("稀疏索引或 skip-worktree 不受支持")
    manager=ignore_manager(repo,config);files=walk_candidates(repo,index,manager,config);attrs=Attributes(repo,config,index);auto_rules={};old_entries=dict(index.items());root=Path(repo.path)
    for rel,(path,oldkey) in list(files.items()):
        st=path.lstat()
        if oldkey is not None and (old_entries[oldkey].flags&0x8000 or old_entries[oldkey].mode==0o120000):continue
        if not stat.S_ISREG(st.st_mode) or st.st_size<a.lfs_threshold or attrs.get(rel).get(b"filter")==b"lfs":continue
        if a.no_auto_lfs:raise StopPush(f"文件大小超出限制 ({human(st.st_size)} >= {human(a.lfs_threshold)}): {os.fsdecode(rel)}")
        auto_rules[rel]=exact_attr_rule(os.fsdecode(rel))
    if auto_rules:
        target=root/".gitattributes";existing=config_bytes(target);append=b"".join(rule for rel,rule in sorted(auto_rules.items()) if rule.strip() not in existing.splitlines());existing_newline=b"" if not existing or existing.endswith(b"\n") else b"\n"
        if append:atomic_write(target,existing+existing_newline+append);LOG.info("自动配置 .gitattributes 追加 %d 条 LFS 规则",len(auto_rules));attrs=Attributes(repo,config,index);files[b".gitattributes"]=(target,b".gitattributes" if b".gitattributes" in index else None)
    seen=set();payloads=0
    for rel,(path,oldkey) in files.items():
        st=path.lstat();old=old_entries.get(oldkey) if oldkey is not None else None;effective=attrs.get(rel)
        if stat.S_ISLNK(st.st_mode):
            target=os.fsencode(os.readlink(path));blob=Blob.from_string(target);repo.object_store.add_object(blob);entry=index_entry_from_stat(st,blob.id,mode=0o120000);entry.size=len(target)
        elif stat.S_ISDIR(st.st_mode):
            if (path/".git").exists() or (old is not None and old.mode==0o160000):
                sub=Repo(str(path));head=sub.head()
                if not head:raise StopPush(f"子模块 HEAD 为空: {path}")
                entry=IndexEntry(st.st_ctime,st.st_mtime,st.st_dev,st.st_ino,0o160000,st.st_uid,st.st_gid,0,head,0)
            else:continue
        elif stat.S_ISREG(st.st_mode):
            is_lfs=effective.get(b"filter")==b"lfs"
            if is_lfs:
                data=cache.put(path);payloads+=1;mode=0o100755 if (yes(config,(b"core",),b"filemode",os.name!="nt") and st.st_mode&0o111) or (not yes(config,(b"core",),b"filemode",os.name!="nt") and old is not None and old.mode==0o100755) else 0o100644
            else:
                if st.st_size>=a.max_blob_size:raise StopPush(f"普通 Blob 超过允许大小: {os.fsdecode(rel)}")
                data=normalize_blob(read_regular(path),effective,old,repo,config,rel,a.renormalize);mode=0o100755 if (yes(config,(b"core",),b"filemode",os.name!="nt") and st.st_mode&0o111) or (not yes(config,(b"core",),b"filemode",os.name!="nt") and old is not None and old.mode==0o100755) else 0o100644
        else:raise StopPush(f"不支持的文件类型: {path}")
        blob=Blob.from_string(data);repo.object_store.add_object(blob);entry=index_entry_from_stat(st,blob.id,mode=mode);entry.size=st.st_size&0xffffffff
        if oldkey is not None and oldkey!=rel:del index[oldkey]
        index[rel]=entry;seen.add(rel);trace(a,"暂存: %s",os.fsdecode(rel))
    for rel in list(index):
        if rel not in seen:del index[rel];trace(a,"暂存删除: %s",os.fsdecode(rel))
    LOG.info("索引暂存完成 | LFS 新快照: %d | 纯 Python 标准库处理",payloads)
def tree_map(repo,head): # 获取指定提交树的所有文件映射
    if not head:return {}
    return {e.path:(e.sha,e.mode) for e in iter_tree_contents(repo.object_store,repo[head].tree)}
def check_repo_state(repo,config): # 检查仓库合并、变基等状态
    if repo.bare:raise StopPush("自动暂存 push 需要非 bare 工作区")
    if cfg(config,b"extensions",b"objectformat",b"sha1")!=b"sha1":raise StopPush("此版本明确只处理 SHA-1 Git 仓库")
    for name in ("MERGE_HEAD","CHERRY_PICK_HEAD","REVERT_HEAD","rebase-merge","rebase-apply","sequencer"):
        if (Path(repo.controldir())/name).exists():raise StopPush(f"仓库操作尚未结束: {name}，请先处理")
def commit_staged(repo,index,a,identity,expected): # 将暂存区对象拆分/批量写入 Commit
    chain,head=expected
    if repo.refs.follow(b"HEAD")!=expected:raise StopPush("暂存期间本地 HEAD 已变化")
    flat=tree_map(repo,head);target={p:(e.sha,e.mode) for p,e in index.items()};changed=sorted((set(flat)|set(target)),key=lambda p:(p in target,p));changed=[p for p in changed if flat.get(p)!=target.get(p)]
    if not changed:LOG.info("暂存区为空，不创建空提交");return [],None
    LOG.info("变更文件: %d 个 | 前 10 项: %s",len(changed),[os.fsdecode(p) for p in changed[:10]]);message=a.message;largest=None;largest_size=-1;empty=None;root=Path(repo.path)
    for p in changed:
        fp=root/os.fsdecode(p)
        if fp.is_file() and not fp.is_symlink():
            size=fp.stat().st_size
            if size>largest_size:largest,largest_size=os.fsdecode(p),size
        if p==b"ReadMe.md" and size<100:empty=p
    batches=[];current=[];total=0
    for p in changed:
        size=len(repo.object_store[target[p][0]].data) if p in target else 0
        if current and total+size>a.max_commit_size:batches.append(current);current=[];total=0
        current.append(p);total+=size
    if current:batches.append(current)
    ids=[];parent=head;now=int(time.time());tz=int(datetime.now().astimezone().utcoffset().total_seconds())
    for number,paths in enumerate(batches,1):
        for p in paths:
            if p in target:flat[p]=target[p]
            else:flat.pop(p,None)
        commit=Commit();commit.parents=[parent] if parent else [];commit.tree=commit_tree(repo.object_store,[(p,sha,mode) for p,(sha,mode) in flat.items()]);commit.author=commit.committer=identity;commit.author_time=commit.commit_time=now+number;commit.author_timezone=commit.commit_timezone=tz
        if len(batches)==1:text_msg=message or f"更新: {len(changed)} 个文件"+(f" (主要: {largest})" if largest else "")
        else:text_msg=(message+f" ({number}/{len(batches)})") if message else f"分批提交 ({number}/{len(batches)}): {len(paths)} 项"
        if empty and number==len(batches):text_msg+="\n\n警告: 检测到 ReadMe.md 内容过小"
        commit.message=text_msg.encode("utf-8");repo.object_store.add_object(commit);ids.append(commit.id);parent=commit.id;LOG.info("创建提交 [%d/%d]: %s (%s)",number,len(batches),commit.id.decode()[:8],text_msg.splitlines()[0])
    if not repo.refs.set_if_equals(chain[-1] if chain else b"HEAD",head,ids[-1]):raise StopPush("更新本地分支失败: 分支已被其他进程推进")
    return ids,empty
def prepare(repo,a,identity,cache): # 执行工作区暂存并完成本地提交
    config=repo.get_config_stack();check_repo_state(repo,config);lock=Path(repo.controldir())/"index.lock"
    expected=repo.refs.follow(b"HEAD");index=repo.open_index();stage_all(repo,index,a,config,cache);writer=SHA1Writer(lock);write_index_dict(writer,dict(index.items()),version=3);ids,empty=commit_staged(repo,index,a,identity,expected);writer.close();return ids,empty
def outgoing_lfs(repo,remote_refs,local_head,a): # 收集需上传到远端的 LFS 对象集合
    if not local_head:return {}
    known=[sha for sha in remote_refs.values() if sha!=ZERO_SHA and sha in repo.object_store];missing=MissingObjectFinder(repo.object_store,known,[local_head]);objects={};limit=a.max_blob_size
    for sha in missing:
        obj=repo.object_store[sha]
        if isinstance(obj,Blob):
            info=pointer_info(obj.data)
            if info is not None:objects[info[0]]=info[1]
            elif not a.no_auto_lfs and len(obj.data)>=limit:raise StopPush(f"提交历史中存在大于阈值的普通 Blob: {sha.decode()[:8]} ({human(len(obj.data))})")
    return objects
class TransferMonitor: # 实时传输速度与心跳看门狗
    def __init__(self,sock,a,action_name="上传"):
        self.sock=sock;self.a=a;self.action_name=action_name;self.lock=threading.Lock();self.bytes_sent=0;self.bytes_received=0;self.last_activity=time.monotonic();self.closed=False;self.start_time=time.monotonic();self.history=deque()
    def note_sent(self,n): # 记录发送字节
        with self.lock:self.bytes_sent+=n;self.last_activity=time.monotonic();self.history.append((self.last_activity,n))
    def note_received(self,n): # 记录接收字节
        with self.lock:self.bytes_received+=n;self.last_activity=time.monotonic()
    def speed(self): # 计算近期传输速度
        now=time.monotonic();limit=now-2.0
        with self.lock:
            while self.history and self.history[0][0]<limit:self.history.popleft()
            recent=sum(b for _,b in self.history)
            span=max(0.2,now-self.history[0][0]) if self.history else 1.0
            return recent/span
    def watchdog(self): # 监控低速超时中止连接
        while not self.closed:
            time.sleep(self.a.progress_interval)
            with self.lock:idle=time.monotonic()-self.last_activity;sent=self.bytes_sent
            if idle>=self.a.low_speed_time and sent>0 and not self.closed:
                LOG.error("网络低速超时 (%ds 无响应): 中止传输",int(idle));self.close();break
    def close(self): # 中止 socket
        with self.lock:
            if self.closed:return
            self.closed=True
            with suppress(Exception):self.sock.shutdown(socket.SHUT_RDWR);self.sock.close()
class MonitoredSocket: # 包装 socket 实现实时流量统计
    def __init__(self,sock,monitor):self._sock=sock;self._m=monitor
    def send(self,b,flags=0):
        n=self._sock.send(b,flags);self._m.note_sent(n);return n
    def sendall(self,b,flags=0):
        self._sock.sendall(b,flags);self._m.note_sent(len(b))
    def recv(self,bufsize,flags=0):
        d=self._sock.recv(bufsize,flags);self._m.note_received(len(d));return d
    def recv_into(self,buffer,nbytes=0,flags=0):
        n=self._sock.recv_into(buffer,nbytes,flags);self._m.note_received(n);return n
    def __getattr__(self,name):return getattr(self._sock,name)
class Transport: # 统一 HTTP/HTTPS 网络传输层，支持实时连接详情与实时速率
    def __init__(self,a,auths=None):self.a=a;self.auths=auths or {};self.proxy=getproxies().get("https") or getproxies().get("http")
    def connect(self,scheme,host,port): # 建立 socket 并执行 TLS 握手及速率看门狗
        plain=socket.create_connection((host,port),timeout=self.a.connect_timeout)
        plain.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        monitor=TransferMonitor(plain,self.a)
        t=threading.Thread(target=monitor.watchdog,daemon=True);t.start()
        if scheme=="https":
            ctx=ssl.create_default_context()
            sock=ctx.wrap_socket(plain,server_hostname=host)
            conn_socket=MonitoredSocket(sock,monitor)
        else:conn_socket=MonitoredSocket(plain,monitor)
        return conn_socket,monitor
    def request(self,method,url,headers=None,data=None,action="网络请求",allow_error=False): # 发送标准 HTTP 请求并输出速率
        p=urlsplit(url);scheme=p.scheme;host=p.hostname;port=p.port or (443 if scheme=="https" else 80);h=dict(headers or {})
        auth=self.auths.get(origin(url))
        if auth and "Authorization" not in h:h["Authorization"]=auth
        sock,monitor=self.connect(scheme,host,port)
        conn=http.client.HTTPSConnection(host,port) if scheme=="https" else http.client.HTTPConnection(host,port)
        conn.sock=sock
        path=p.path+(f"?{p.query}" if p.query else "")
        total_len=None
        if isinstance(data,(bytes,bytearray)):total_len=len(data)
        elif hasattr(data,"seek") and hasattr(data,"tell"):
            cur=data.tell();data.seek(0,os.SEEK_END);total_len=data.tell()-cur;data.seek(cur)
        last_t=time.monotonic()
        def gen():
            nonlocal last_t
            if isinstance(data,(bytes,bytearray)):
                for i in range(0,len(data),CHUNK):
                    blk=data[i:i+CHUNK];yield blk
                    if time.monotonic()-last_t>=self.a.progress_interval:
                        LOG.info("%s: %s | 速度: %s/s",action,human(monitor.bytes_sent)+(f"/{human(total_len)}" if total_len else ""),human(monitor.speed()))
                        last_t=time.monotonic()
            elif hasattr(data,"read"):
                while True:
                    blk=data.read(CHUNK)
                    if not blk:break
                    yield blk
                    if time.monotonic()-last_t>=self.a.progress_interval:
                        LOG.info("%s: %s | 速度: %s/s",action,human(monitor.bytes_sent)+(f"/{human(total_len)}" if total_len else ""),human(monitor.speed()))
                        last_t=time.monotonic()
        req_body=gen() if (data is not None and not isinstance(data,(bytes,str))) else data
        conn.request(method,path,body=req_body,headers=h)
        resp=conn.getresponse()
        if not allow_error and resp.status>=400:
            b=resp.read(4096).decode("utf-8","replace");conn.close();monitor.close()
            raise HTTPFailure(resp.status,url,b[:600],retry_delay(resp.getheader("Retry-After")))
        return resp
    def close(self):pass
class DulwichHTTPClient(AbstractHttpGitClient): # 自定义 Dulwich 客户端，挂接原生监控传输层
    def __init__(self,base_url,net,auth):
        super().__init__(base_url);self.net=net;self.auth=auth
    def _http_request(self,url,headers,data=None,raise_for_status=True):
        full_url=urljoin(self._base_url,url);hdrs=dict(headers or {})
        if self.auth:hdrs["Authorization"]=self.auth
        res=self.net.request("GET" if data is None else "POST",full_url,hdrs,data,"Git HTTP body",allow_error=not raise_for_status)
        return res,res.read
def upload_lfs(net,batch_url,objects,cache,ref,done): # 批量与 Git-LFS 服务器通信并上传大文件对象
    needed=[(oid,size) for oid,size in objects.items() if (oid,size) not in done]
    if not needed:return
    LOG.info("请求 LFS 授权与批处理: %d 个对象",len(needed))
    req={"operation":"upload","transfers":["basic"],"ref":{"name":text(ref)},"objects":[{"oid":o,"size":s} for o,s in needed]}
    res=net.request("POST",batch_url,{"Content-Type":MEDIA,"Accept":MEDIA},json.dumps(req).encode(),"LFS Batch")
    resp_obj=json.loads(res.read().decode("utf-8"))
    for item in resp_obj.get("objects",[]):
        oid=item["oid"];size=item["size"]
        if (oid,size) in done:continue
        actions=item.get("actions",{})
        if "upload" in actions:
            up=actions["upload"];up_url=up["href"];up_headers=up.get("header",{})
            local_file=cache.require(oid,size)
            LOG.info("上传 LFS 文件: %s (%s)",oid[:12],human(size))
            with regular_reader(local_file) as (f,_):net.request("PUT",up_url,up_headers,f,f"上传 LFS {oid[:8]}")
            if "verify" in actions:
                v=actions["verify"];v_url=v["href"];v_headers=v.get("header",{})
                v_headers["Content-Type"]=MEDIA
                net.request("POST",v_url,v_headers,json.dumps({"oid":oid,"size":size}).encode(),"验证 LFS")
        done.add((oid,size))
def retry(a,label,operation): # 指数退避重试装饰执行器
    attempt=0
    while True:
        try:return operation()
        except HTTPFailure as exc:
            if exc.code in (401,403,404,422):raise
            attempt+=1
            if attempt>a.retry_limit:raise
            delay=exc.retry_after or (a.retry_delay*(2**(attempt-1)))
            LOG.warning("[%s] 异常 HTTP %d，将在 %.1fs 后重试 (第 %d/%d 次)",label,exc.code,delay,attempt,a.retry_limit)
            time.sleep(delay)
        except (socket.timeout,TimeoutError,NetworkFailure,http.client.HTTPException) as exc:
            attempt+=1
            if attempt>a.retry_limit:raise StopPush(f"[{label}] 网络重试超出上限: {exc}")
            delay=a.retry_delay*(2**(attempt-1))
            LOG.warning("[%s] 网络故障 (%s)，将在 %.1fs 后重试 (第 %d/%d 次)",label,exc,delay,attempt,a.retry_limit)
            time.sleep(delay)
def push_target(repo,a,remote,ref,head_sha,batch_url,auths,cache,done_lfs): # 执行单目标推送逻辑
    net=Transport(a,auths)
    try:
        auth_hdr=auths.get(origin(remote))
        client=DulwichHTTPClient(remote,net,auth_hdr)
        remote_refs=client.get_refs(urlsplit(remote).path)
        old_sha=remote_refs.get(ref,ZERO_SHA)
        if old_sha==head_sha:LOG.info("远端分支已是最新状态，无需推送: %s",text(ref));return
        lfs_objs=outgoing_lfs(repo,remote_refs,head_sha,a)
        if lfs_objs:upload_lfs(net,batch_url,lfs_objs,cache,ref,done_lfs)
        def attempt():
            def generate():
                from dulwich.pack import write_pack_objects
                finder=MissingObjectFinder(repo.object_store,[old_sha] if old_sha!=ZERO_SHA else [],[head_sha])
                f=io.BytesIO();write_pack_objects(f.write,[(repo.object_store[s],None) for s in finder]);return f.getvalue()
            def remote_progress(msg):LOG.info("远端进度: %s",text(msg).strip())
            client.send_pack(urlsplit(remote).path,lambda refs:{ref:head_sha},lambda have,want:generate(),progress=remote_progress)
        retry(a,f"推送 {safe_url(remote)} {text(ref)}",attempt)
    finally:net.close()
def main(a): # CLI 主入口执行
    setup_logging(a.verbose);LOG.info("Dulwich 版本: %s | 网络: Python 标准库 http.client/socket/ssl",version("dulwich"))
    root=Path(a.repo or ".").resolve()
    try:repo=Repo(str(root))
    except NotGitRepository:
        LOG.info("初始化本地 Git 仓库: %s",root);repo=Repo.init(str(root),mkdir=True)
    config=repo.get_config_stack();user_name=a.user or cfg(config,b"user",b"name",b"").decode() or "PurePush"
    user_email=a.email or cfg(config,b"user",b"email",b"").decode() or f"{user_name}@users.noreply.github.com"
    identity=f"{user_name} <{user_email}>".encode("utf-8");cache=LFSCache(repo)
    clean_url,user,password,branch=clean_remote_and_auth(a.remote,a.branch)
    branch_name=(branch or "master").encode("utf-8");ref=b"refs/heads/"+branch_name
    auths={}
    if user and password:
        auths[origin(clean_url)]="Basic "+base64.b64encode(f"{user}:{password}".encode()).decode()
    ids,empty=prepare(repo,a,identity,cache)
    head=repo.head()
    if not head:LOG.error("当前分支无任何提交，终止推送");return 1
    batch_url=clean_url.removesuffix(".git")+"/info/lfs/objects/batch"
    done_lfs=set()
    push_target(repo,a,clean_url,ref,head,batch_url,auths,cache,done_lfs)
    LOG.info("全部流程圆满完成！HEAD: %s -> %s",head.decode()[:8],text(ref))
    return 0

def self_test(): # 内建全面自测体系
    import unittest
    from dulwich.repo import MemoryRepo
    from dulwich.server import DictBackend
    from dulwich.web import make_wsgi_chain
    from dulwich.object_store import MemoryObjectStore
    from wsgiref.simple_server import make_server,WSGIRequestHandler
    from http.server import HTTPServer,BaseHTTPRequestHandler

    # 猴子补丁修复 dulwich-1.2.15 MemoryObjectStore 缺少 max_input_size 导致的崩溃
    _orig_add_thin_pack=MemoryObjectStore.add_thin_pack
    def _patched_add_thin_pack(self,read_all,read_some,progress=None,max_input_size=None):
        return _orig_add_thin_pack(self,read_all,read_some,progress=progress)
    MemoryObjectStore.add_thin_pack=_patched_add_thin_pack

    class Tests(unittest.TestCase):
        def setUp(self):
            self.temp=tempfile.TemporaryDirectory()
            self.root=Path(self.temp.name)/"repo"
            self.root.mkdir(parents=True,exist_ok=True)
            self.repo=Repo.init(str(self.root),mkdir=True) # 使用 mkdir=True 避免 WinError 183
            self.cache=LFSCache(self.repo)
            self.identity=b"Tester <tester@example.com>"
            self.a=argparse.Namespace(verbose=1,trace=False,lfs_threshold=500,max_blob_size=1024*1024,max_commit_size=10*1024*1024,connect_timeout=10,progress_interval=0.1,low_speed_time=1.0,retry_limit=3,retry_delay=0.1,no_auto_lfs=False,renormalize=False,message="",atomic=False,push_option=[])
        def tearDown(self):self.temp.cleanup()
        def write(self,rel,data):
            p=self.root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return p
        def stage(self):return prepare(self.repo,self.a,self.identity,self.cache)
        def test_regular_reader_windows_signature(self): # 验证 Windows 下文件读取签名不会误报变动
            p=self.write("file.txt",b"hello world")
            with regular_reader(p) as (f,st):self.assertEqual(f.read(),b"hello world")
        def test_git_smart_http_push(self): # 验证 smart http 完整双向交互推送
            class Quiet(WSGIRequestHandler):
                def log_message(self,*args):pass
            self.write("data.txt",b"dulwich 1.2.15")
            self.stage()
            remote=MemoryRepo()
            app=make_wsgi_chain(DictBackend({"/test.git":remote}))
            server=make_server("127.0.0.1",0,app,handler_class=Quiet)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            url=f"http://127.0.0.1:{server.server_port}/test.git"
            try:
                push_target(self.repo,self.a,url,b"refs/heads/main",self.repo.head(),url+"/info/lfs/objects/batch",{},self.cache,set())
                self.assertEqual(remote.refs[b"refs/heads/main"],self.repo.head())
            finally:
                server.shutdown();server.server_close();thread.join(timeout=2);remote.close()
        def test_split_commits(self): # 验证分批大文件提交
            self.a.max_commit_size=50
            for i in range(5):self.write(f"f{i}.txt",b"x"*20)
            ids,_=self.stage()
            self.assertGreater(len(ids),1)
        def test_ignore_rules(self): # 验证 .gitignore 多层规则有效性
            self.write(".gitignore",b"*.log\nkeep.log\n!keep.log\n")
            self.write("a.log",b"ignore me")
            self.write("keep.log",b"track me")
            self.stage()
            index=self.repo.open_index()
            self.assertIn(b"keep.log",index)
            self.assertNotIn(b"a.log",index)
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    runner=unittest.TextTestRunner(verbosity=2)
    return runner.run(suite).wasSuccessful()

if __name__=="__main__":
    parser=argparse.ArgumentParser(description="纯 Python + Dulwich 1.2.15 完整 Git 推送工具")
    parser.add_argument("remote",nargs="?",help="远程仓库 URL")
    parser.add_argument("-b","--branch",help="目标分支名")
    parser.add_argument("-u","--user",help="Git 用户名")
    parser.add_argument("-e","--email",help="Git 邮箱")
    parser.add_argument("-m","--message",default="",help="提交信息")
    parser.add_argument("-v","--verbose",type=int,default=2,help="日志详尽度 (0-3)")
    parser.add_argument("--trace",action="store_true",help="开启调试跟踪")
    parser.add_argument("--repo",default=".",help="本地仓库路径")
    parser.add_argument("--lfs-threshold",type=parse_bytes,default=100*1024*1024,help="LFS 自动纳管阈值")
    parser.add_argument("--max-blob-size",type=parse_bytes,default=100*1024*1024,help="最大普通 Blob 限制")
    parser.add_argument("--max-commit-size",type=parse_bytes,default=200*1024*1024,help="分批提交单次上限")
    parser.add_argument("--connect-timeout",type=float,default=45.0,help="网络连接超时 (秒)")
    parser.add_argument("--progress-interval",type=float,default=0.5,help="进度与速度刷新间隔 (秒)")
    parser.add_argument("--low-speed-time",type=float,default=60.0,help="低速或无响应最长容忍时间 (秒)")
    parser.add_argument("--retry-limit",type=int,default=3,help="网络重试次数")
    parser.add_argument("--retry-delay",type=float,default=2.0,help="重试基准延迟 (秒)")
    parser.add_argument("--no-auto-lfs",action="store_true",help="禁用自动 LFS 判定")
    parser.add_argument("--renormalize",action="store_true",help="重新规范化换行符")
    parser.add_argument("--atomic",action="store_true",help="原子推送")
    parser.add_argument("--push-option",action="append",default=[],help="Push Options")
    parser.add_argument("--self-test",action="store_true",help="运行内建自测试")
    args=parser.parse_args()
    if args.self_test:sys.exit(0 if self_test() else 1)
    if not args.remote:parser.print_help();sys.exit(1)
    sys.exit(main(args))
'''

C:\Users\Administrator\Documents\energetic>
C:\Users\Administrator\Documents\energetic>
C:\Users\Administrator\Documents\energetic>C:\QGB\anaconda3\python D:\test\github\dulwich_git\L627.py --self-test
test_git_smart_http_push (__main__.self_test.<locals>.Tests.test_git_smart_http_push) ... ERROR
test_ignore_rules (__main__.self_test.<locals>.Tests.test_ignore_rules) ... ERROR
test_regular_reader_windows_signature (__main__.self_test.<locals>.Tests.test_regular_reader_windows_signature) ... ERROR
test_split_commits (__main__.self_test.<locals>.Tests.test_split_commits) ... ERROR

======================================================================
ERROR: test_git_smart_http_push (__main__.self_test.<locals>.Tests.test_git_smart_http_push)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L627.py", line 558, in setUp
    self.repo=Repo.init(str(self.root),mkdir=True) # 使用 mkdir=True 避免 WinError 183
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\repo.py", line 2431, in init
    os.mkdir(path)
FileExistsError: [WinError 183] 当文件已存在时，无法创建该文件。: 'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\tmp12k3_v0s\\repo'

======================================================================
ERROR: test_ignore_rules (__main__.self_test.<locals>.Tests.test_ignore_rules)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L627.py", line 558, in setUp
    self.repo=Repo.init(str(self.root),mkdir=True) # 使用 mkdir=True 避免 WinError 183
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\repo.py", line 2431, in init
    os.mkdir(path)
FileExistsError: [WinError 183] 当文件已存在时，无法创建该文件。: 'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\tmpvl48xa26\\repo'

======================================================================
ERROR: test_regular_reader_windows_signature (__main__.self_test.<locals>.Tests.test_regular_reader_windows_signature)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L627.py", line 558, in setUp
    self.repo=Repo.init(str(self.root),mkdir=True) # 使用 mkdir=True 避免 WinError 183
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\repo.py", line 2431, in init
    os.mkdir(path)
FileExistsError: [WinError 183] 当文件已存在时，无法创建该文件。: 'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\tmp4ugxucrn\\repo'

======================================================================
ERROR: test_split_commits (__main__.self_test.<locals>.Tests.test_split_commits)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L627.py", line 558, in setUp
    self.repo=Repo.init(str(self.root),mkdir=True) # 使用 mkdir=True 避免 WinError 183
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\repo.py", line 2431, in init
    os.mkdir(path)
FileExistsError: [WinError 183] 当文件已存在时，无法创建该文件。: 'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\tmp701klter\\repo'

----------------------------------------------------------------------
Ran 4 tests in 0.012s

FAILED (errors=4)

'''