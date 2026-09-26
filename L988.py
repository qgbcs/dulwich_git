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
class StopPush(RuntimeError):pass
class NetworkFailure(RuntimeError):pass
class HTTPFailure(StopPush):
    def __init__(self,code,url,detail="",retry_after=0):
        super().__init__(f"HTTP {code} {safe_url(url)} {detail}");self.code=int(code);self.retry_after=retry_after
def remember(secret):
    if secret and len(str(secret))>3:SECRETS.add(str(secret))
def safe_url(value): # 所有日志去除 URL 用户信息和查询串，签名上传地址不会泄露令牌。
    try:
        p=urlsplit(str(value));host=p.hostname or "";host=f"[{host}]" if ":" in host else host
        return urlunsplit((p.scheme,host+(f":{p.port}" if p.port else ""),p.path,"",""))
    except ValueError:return "[URL 已隐藏]"
def redact(value):
    text=str(value)
    for secret in sorted(SECRETS,key=len,reverse=True):text=text.replace(secret,"***")
    text=re.sub(r"https?://[^\s\"'<>]+",lambda m:safe_url(m.group()),text)
    return text.replace("\x1b","\\x1b")
class SafeFormatter(logging.Formatter):
    def format(self,record):return redact(super().format(record)) # 连异常堆栈也统一脱敏，不使用会打印原始 body 的 http.client debuglevel。
def setup_logging(v):
    handler=logging.StreamHandler(sys.stdout);handler.setFormatter(SafeFormatter("%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s","%Y-%m-%d %H:%M:%S"))
    LOG.handlers[:]=[handler];LOG.propagate=False;LOG.setLevel({0:logging.ERROR,1:logging.WARNING,2:logging.INFO}.get(v,logging.DEBUG))
def trace(a,message,*values):
    if a.trace:LOG.log(logging.DEBUG if a.verbose>=3 else logging.INFO,message,*values)
def cfg(config,section,key,default=b""):
    section=(section,) if isinstance(section,bytes) else section
    try:return config.get(section,key)
    except KeyError:return default
def text(value):return value.decode("utf-8","surrogateescape") if isinstance(value,bytes) else str(value)
def yes(config,section,key,default=False):return config.get_boolean(section,key,default)
def human(n):
    units=("B","KiB","MiB","GiB","TiB");i=0;n=float(n)
    while n>=1024 and i<len(units)-1:n/=1024;i+=1
    return f"{n:.2f} {units[i]}"
def parse_size(value):
    m=re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmgt]?)(?:i?b)?\s*",str(value),re.I)
    if not m:raise argparse.ArgumentTypeError("大小应为字节数或 100MB、1.5GiB 等格式")
    return int(float(m[1])*1024**("kmgt".find(m[2].lower())+1 if m[2] else 0))
def stamp():return datetime.now().strftime("%Y-%m-%d__%H.%M.%S__.%f")[:-3]
def split_credentials(raw): # username/password 分别 URL 解码，主机名与端口始终只从 hostname/port 读取。
    p=urlsplit(raw);user=unquote(p.username) if p.username is not None else None;password=unquote(p.password) if p.password is not None else None
    remember(password);remember(p.password)
    if p.scheme not in ("http","https") or not p.hostname:raise StopPush("纯标准库版本仅支持 HTTP(S)；SSH 需要额外实现，不能偷偷启动 ssh")
    host=p.hostname;host=f"[{host}]" if ":" in host else host;port=p.port
    return urlunsplit((p.scheme,host+(f":{port}" if port else ""),p.path,p.query,"")),user,password
def origin(url):
    p=urlsplit(url);return p.scheme,p.hostname,p.port or (443 if p.scheme=="https" else 80)
def basic(user,password):
    if password is None:return None
    if ":" in (user or ""):raise StopPush("Basic 认证用户名不能含冒号")
    value="Basic "+base64.b64encode(f"{user or 'x-access-token'}:{password}".encode()).decode();remember(value);remember(value[6:]);return value
def normalize_remote(raw):
    clean,user,password=split_credentials(raw);p=urlsplit(clean);branch=None;parts=p.path.strip("/").split("/")
    if p.query:raise StopPush("仓库 URL 不应包含查询串；请使用仓库首页地址，而不是带参数的网页地址")
    if p.hostname in ("github.com","www.github.com"):
        if len(parts)<2 or not all(parts[:2]):raise StopPush("GitHub URL 必须包含 owner/repository")
        if len(parts)>2:
            branch=unquote(parts[3] if parts[2] in ("tree","blob") and len(parts)>3 else parts[2]);LOG.warning("网页路径只用于定位仓库，推送范围仍是整个本地仓库；含斜杠的分支请显式指定 --branch")
        clean=urlunsplit((p.scheme,p.netloc,"/"+"/".join(parts[:2]).removesuffix(".git")+".git","",""))
    return clean.rstrip("/"),user,password,branch
def atomic_write(path,data): # 临时文件与目标同目录，失败不留下半写配置；不覆盖符号链接。
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise StopPush(f"拒绝覆盖符号链接: {path}")
    mode=stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644;fd,tmp=tempfile.mkstemp(prefix=".purepush-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,mode);os.replace(tmp,path)
    finally:
        with suppress(FileNotFoundError):os.unlink(tmp)
def signature(st):return st.st_dev,st.st_ino,st.st_mode,st.st_size,st.st_mtime_ns,st.st_ctime_ns
@contextmanager
def regular_reader(path):
    before=path.lstat()
    if not stat.S_ISREG(before.st_mode):raise StopPush(f"不是普通文件，拒绝跟随链接: {path}")
    fd=os.open(path,os.O_RDONLY|getattr(os,"O_BINARY",0)|getattr(os,"O_NOFOLLOW",0))
    with os.fdopen(fd,"rb") as f:
        if signature(os.fstat(f.fileno()))!=signature(before):raise StopPush(f"读取前文件已经变化: {path}")
        yield f,before
        if signature(os.fstat(f.fileno()))!=signature(before) or signature(path.lstat())!=signature(before):raise StopPush(f"读取时文件发生变化，请重试本地操作: {path}")
def read_regular(path,limit=None):
    with regular_reader(Path(path)) as (f,st):
        if limit is not None and st.st_size>limit:raise StopPush(f"配置文件过大: {path}")
        return f.read()
def config_bytes(path):
    path=Path(path)
    if path.is_symlink():return b""
    try:return read_regular(path,8*1024*1024)
    except (FileNotFoundError,NotADirectoryError):return b""
class SafeIgnore(IgnoreFilterManager): # 1.2.15 的 True 表示忽略，False 表示 ! 规则重新包含，None 表示没有匹配。
    def _load_path(self,path):
        if (Path(self._top_path)/path/".gitignore").is_symlink():return None
        return super()._load_path(path)
    def _is_dir(self,path):
        p=Path(self._top_path)/path;return path.endswith("/") or (p.is_dir() and not p.is_symlink())
def ignore_manager(repo,config):
    ignorecase=yes(config,(b"core",),b"ignorecase",False);filters=[]
    for path in (Path(default_user_ignore_filter_path(config)).expanduser(),Path(repo.controldir())/"info"/"exclude"):
        try:filters.append(IgnoreFilter.from_path(path,ignorecase)) # 从低到高排列，info/exclude 优先于用户全局规则，再由各级 .gitignore 覆盖。
        except FileNotFoundError:pass
    return SafeIgnore(str(repo.path),filters,ignorecase)
def attr_words(line): # Dulwich 1.2.15 的简单 split 不识别带空格的 C 引号路径，因此先解码首字段再交给其 wildmatch。
    line=line.strip()
    if not line or line.startswith(b"#"):return None,[]
    if not line.startswith(b'"'):
        words=line.split();return words[0],words[1:]
    out=bytearray();i=1;esc={ord("a"):7,ord("b"):8,ord("t"):9,ord("n"):10,ord("v"):11,ord("f"):12,ord("r"):13,34:34,92:92}
    while i<len(line):
        b=line[i];i+=1
        if b==34:
            if i<len(line) and line[i] not in b" \t":raise StopPush(".gitattributes 引号后缺少空白")
            return bytes(out),line[i:].split()
        if b==92:
            if i>=len(line):break
            b=line[i];i+=1
            if 48<=b<=55:
                number=bytes([b])
                for _ in range(2):
                    if i<len(line) and 48<=line[i]<=55:number+=line[i:i+1];i+=1
                    else:break
                b=int(number,8)
                if b>255:raise StopPush("属性路径的八进制转义超出字节范围")
            elif b in esc:b=esc[b]
            else:raise StopPush(".gitattributes 中存在不支持的 C 转义")
        out.append(b)
    raise StopPush(".gitattributes 的路径引号没有闭合")
def parse_attribute(token):
    if token[:1] in (b"-",b"!"):return token[1:],False if token[:1]==b"-" else None
    if b"=" in token:return tuple(token.split(b"=",1))
    return token,True
class Attributes: # 按全局、根目录、嵌套目录、info/attributes 的优先级合并属性，支持取消属性与顶层宏。
    def __init__(self,repo,config,index):
        self.repo=repo;self.root=Path(repo.path);self.index=index;self.cache={};self.global_path=Path(text(cfg(config,b"core",b"attributesfile",os.fsencode(Path(os.environ.get("XDG_CONFIG_HOME",str(Path.home()/".config")))/"git"/"attributes")))).expanduser();self.info=Path(repo.controldir())/"info"/"attributes"
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
    def get(self,rel):
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
def exact_attr_rule(name):
    pattern=b"/"+b"".join((b"\\"+bytes([b])) if b in b"\\*?[]" else bytes([b]) for b in os.fsencode(name))
    quoted=b'"'+b"".join(bytes([b]) if 32<=b<127 and b not in (34,92) else (b"\\"+bytes([b]) if b in (34,92) else f"\\{b:03o}".encode()) for b in pattern)+b'"'
    return quoted+b" filter=lfs diff=lfs merge=lfs -text"
def pointer_info(data):
    if data.startswith(POINTER_PREFIX.rstrip(b"\n")+b"\r\n"):data=data.replace(b"\r\n",b"\n")
    if not data.startswith(POINTER_PREFIX):return None
    match=re.fullmatch(rb"version https://git-lfs.github.com/spec/v1\noid sha256:([0-9a-f]{64})\nsize (0|[1-9][0-9]*)\n?",data)
    if not match:raise StopPush("发现无效或带扩展的 LFS 指针；拒绝将指针再次作为普通文件上传")
    return match[1].decode(),int(match[2])
def pointer_bytes(oid,size):return POINTER_PREFIX+f"oid sha256:{oid}\nsize {size}\n".encode()
class LFSCache:
    def __init__(self,repo,config):
        storage=cfg(config,b"lfs",b"storage");common=Path(repo.commondir()).resolve();base=Path(text(storage)).expanduser() if storage else common/"lfs"
        if not base.is_absolute():base=common/base
        self.base=base;self.verified={}
    def path(self,oid):
        if not re.fullmatch(r"[a-f0-9]{64}",oid):raise StopPush("无效的 LFS SHA256")
        return self.base/"objects"/oid[:2]/oid[2:4]/oid
    def put(self,path): # 对工作区文件生成稳定快照，上传只读快照，不依赖上传时工作文件仍未变化。
        temp=self.base/"tmp";temp.mkdir(parents=True,exist_ok=True);fd,name=tempfile.mkstemp(prefix="purepush-",dir=temp);h=hashlib.sha256();size=0;last=time.monotonic()
        try:
            with os.fdopen(fd,"wb") as out,regular_reader(path) as (f,st):
                for block in iter(lambda:f.read(1024*1024),b""):
                    out.write(block);h.update(block);size+=len(block)
                    if time.monotonic()-last>=1:LOG.info("LFS 本地快照: %s | %s/%s",path.name,human(size),human(st.st_size));last=time.monotonic()
                out.flush();os.fsync(out.fileno())
            oid=h.hexdigest();dest=self.path(oid);dest.parent.mkdir(parents=True,exist_ok=True);os.replace(name,dest);self.verified[oid,size]=signature(dest.stat());return pointer_bytes(oid,size)
        finally:
            with suppress(FileNotFoundError):os.unlink(name)
    def require(self,oid,size):
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
def walk_candidates(repo,index,manager,config): # 已跟踪路径绕过忽略规则；父目录被忽略也不能漏掉其中已跟踪文件的修改或删除。
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
            keep.append(name) # 判断目录本身而非 dir/ 的内容；已跟踪后代必须继续扫描，dir/* + !dir/keep 也不会被提前剪掉。
        dirs[:]=keep
        for name in names:
            if (name.casefold() if os.name=="nt" else name)!=".git":add(current/name)
    LOG.info("扫描完成: %d 项 | 未跟踪且被忽略: %d 项",count,skipped);return files
def normalize_blob(data,attrs,old,repo,config,path,renormalize=False): # 只做内建 text/eol/autocrlf/ident 转换，未知过滤器或编码转换明确报错，不冒险存入原始数据。
    if attrs.get(b"working-tree-encoding") not in (None,False):raise StopPush(f"暂不支持 working-tree-encoding，拒绝静默改变文件内容: {os.fsdecode(path)}")
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
def stage_all(repo,index,a,config,cache): # 替代 porcelain.add：直接写 Blob 和 dataclass 索引项，因此永远不会触发 filter.lfs.process。
    if any(not isinstance(entry,IndexEntry) for _,entry in index.items()):raise StopPush("索引存在未解决冲突，拒绝自动提交")
    if any(stat.S_ISDIR(entry.mode) or entry.skip_worktree for _,entry in index.items()):raise StopPush("稀疏索引或 skip-worktree 不受支持，请先展开工作区")
    if any(ext.signature[:1].islower() for ext in (getattr(index,"_extensions",[]) or [])):raise StopPush("存在不支持的必需索引扩展（例如分裂/稀疏索引），拒绝丢弃其数据")
    manager=ignore_manager(repo,config);files=walk_candidates(repo,index,manager,config);attrs=Attributes(repo,config,index);auto_rules={};old_entries=dict(index.items());root=Path(repo.path)
    for rel,(path,oldkey) in list(files.items()):
        st=path.lstat()
        if oldkey is not None and (old_entries[oldkey].flags&0x8000 or old_entries[oldkey].mode==0o120000):continue
        if not stat.S_ISREG(st.st_mode) or st.st_size<a.size or a.no_auto_lfs or path.name in (".gitattributes",".gitignore",".gitmodules",".lfsconfig"):continue
        if st.st_size<=1024 and pointer_info(read_regular(path)):continue
        if attrs.get(rel).get(b"filter")==b"lfs":continue
        target=path.parent/".gitattributes";key=os.fsencode(target.relative_to(root).as_posix())
        if key not in old_entries and manager.is_ignored(os.fsdecode(key)) is True:raise StopPush(f"自动 LFS 需要暂存 {os.fsdecode(key)}，但它被忽略；请先调整忽略规则")
        auto_rules.setdefault(target,set()).add(exact_attr_rule(path.name))
    for target,rules in auto_rules.items():
        if target.is_symlink():raise StopPush(f"属性文件不能是符号链接: {target}")
        original=config_bytes(target);lines=set(original.splitlines());extra=sorted(rules-lines)
        if extra:atomic_write(target,original+(b"\n" if original and not original.endswith(b"\n") else b"")+b"\n".join(extra)+b"\n")
        key=os.fsencode(target.relative_to(root).as_posix());files[key]=(target,key if key in old_entries else None)
        LOG.info("新增精确 LFS 规则: %s | %d 条",target.relative_to(root),len(extra))
    attrs.cache.clear();seen={p for p,e in old_entries.items() if e.flags&0x8000};payloads=0
    for p,e in old_entries.items():
        if e.mode==0o160000 and not (root/os.fsdecode(p)).exists():seen.add(p);LOG.warning("子模块未检出或工作树缺失，保留 gitlink: %s",os.fsdecode(p))
    for rel,(path,oldkey) in sorted(files.items()):
        old=old_entries.get(oldkey);st=path.lstat();mode=0o100644
        if old is not None and old.flags&0x8000:seen.add(oldkey);continue
        if stat.S_ISDIR(st.st_mode):
            if (path/".git").exists():
                with Repo(str(path)) as sub:
                    try:oid=sub.head()
                    except KeyError:
                        if old is not None:raise StopPush(f"已跟踪子模块没有有效 HEAD: {path}")
                        LOG.warning("跳过未提交的嵌套仓库: %s",path);continue
                if old is None:LOG.warning("仅记录嵌套仓库 gitlink，不会上传其内部文件: %s",path)
                entry=index_entry_from_stat(st,oid,mode=0o160000)
            elif old is not None and old.mode==0o160000:seen.add(oldkey);continue
            else:continue
        else:
            if stat.S_ISLNK(st.st_mode):data=os.fsencode(os.readlink(path));mode=0o120000
            elif stat.S_ISREG(st.st_mode):
                effective=attrs.get(rel)
                if effective.get(b"filter") not in (None,False,b"lfs"):raise StopPush(f"不调用外部 filter: {os.fsdecode(rel)}")
                if effective.get(b"working-tree-encoding") not in (None,False):raise StopPush(f"不支持 working-tree-encoding: {os.fsdecode(rel)}")
                if old is not None and old.mode==0o120000 and not yes(config,(b"core",),b"symlinks",True):data=read_regular(path);mode=0o120000
                elif effective.get(b"filter")==b"lfs":
                    data=read_regular(path) if st.st_size<=1024 else None
                    if data is None or pointer_info(data) is None:data=cache.put(path);payloads+=1
                    mode=0o100755 if (yes(config,(b"core",),b"filemode",os.name!="nt") and st.st_mode&0o111) or (not yes(config,(b"core",),b"filemode",os.name!="nt") and old is not None and old.mode==0o100755) else 0o100644
                else:
                    if st.st_size>=a.max_blob_size:raise StopPush(f"普通 Blob 超过允许大小: {os.fsdecode(rel)}；LFS 规则可能被 .git/info/attributes 覆盖")
                    data=normalize_blob(read_regular(path),effective,old,repo,config,rel,a.renormalize)
                    mode=0o100755 if (yes(config,(b"core",),b"filemode",os.name!="nt") and st.st_mode&0o111) or (not yes(config,(b"core",),b"filemode",os.name!="nt") and old is not None and old.mode==0o100755) else 0o100644
            else:raise StopPush(f"不支持的文件类型: {path}")
            if signature(path.lstat())!=signature(st):raise StopPush(f"暂存期间文件被修改: {path}")
            blob=Blob.from_string(data);repo.object_store.add_object(blob);entry=index_entry_from_stat(st,blob.id,mode=mode);entry.size=st.st_size&0xffffffff
            if mode in (0o100644,0o100755) and attrs.get(rel).get(b"filter")==b"lfs" and pointer_info(data) is None:raise StopPush(f"LFS 暂存验证失败: {path}")
        if oldkey is not None and oldkey!=rel:del index[oldkey]
        index[rel]=entry;seen.add(rel);trace(a,"暂存: %s",os.fsdecode(rel))
    for rel in list(index):
        if rel not in seen:del index[rel];trace(a,"暂存删除: %s",os.fsdecode(rel))
    LOG.info("索引暂存完成 | LFS 新快照: %d | 未调用任何外部过滤器",payloads)
def tree_map(repo,head):
    if not head:return {}
    return {e.path:(e.sha,e.mode) for e in iter_tree_contents(repo.object_store,repo[head].tree)}
def check_repo_state(repo,config): # 合并、变基、浅克隆及替换历史必须先由用户处理，不把不完整状态静默变成普通提交。
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
def commit_staged(repo,index,a,identity,expected): # 按最终暂存 Blob 大小分组，LFS 只按指针大小计算；完成所有树后再比较并更新 HEAD。
    chain,head=expected
    if repo.refs.follow(b"HEAD")!=expected:raise StopPush("暂存期间本地 HEAD 已变化，拒绝将旧工作区提交到新分支")
    flat=tree_map(repo,head);target={p:(e.sha,e.mode) for p,e in index.items()};changed=sorted((set(flat)|set(target)),key=lambda p:(p in target,p));changed=[p for p in changed if flat.get(p)!=target.get(p)]
    if not changed:LOG.info("暂存区为空，不创建空提交");return [],None
    LOG.info("变更文件: %d 个 | 前 10 项: %s",len(changed),[os.fsdecode(p) for p in changed[:10]]);message=a.message;largest=None;largest_size=-1;empty=None;root=Path(repo.path)
    for p in changed:
        fp=root/os.fsdecode(p)
        if fp.is_file() and not fp.is_symlink():
            size=fp.stat().st_size
            if size>largest_size:largest,largest_size=os.fsdecode(p),size
            if p==b"ReadMe.md" and size<1024*1024:
                data=read_regular(fp)
                if b"#EmptyAfterPush" in data:empty=hashlib.sha256(data).hexdigest()
    if not message:message=(f"[{largest} {largest_size}B] " if largest else "")+f"{stamp()} {Path(__file__).name[-20:]} auto"
    batches=[];current=[];total=0
    for p in changed:
        size=repo.object_store[target[p][0]].raw_length() if p in target and target[p][1]!=0o160000 else 0
        if current and total+size>a.max_commit_size:batches.append(current);current=[];total=0
        current.append(p);total+=size
    if current:batches.append(current)
    ids=[];parent=head;now=int(time.time());tz=int(datetime.now().astimezone().utcoffset().total_seconds())
    for number,paths in enumerate(batches,1):
        for p in paths:
            if p in target:flat[p]=target[p]
            else:flat.pop(p,None) # 删除先于新增分组，文件与目录互换时不会构造冲突的中间树。
        commit=Commit();commit.tree=commit_tree(repo.object_store,[(p,sha,mode) for p,(sha,mode) in flat.items()]);commit.parents=[parent] if parent else [];commit.author=commit.committer=identity;commit.author_time=commit.commit_time=now;commit.author_timezone=commit.commit_timezone=tz;commit.encoding=b"UTF-8";commit.message=((f"[{number}/{len(batches)}] 文件数:{len(paths)} " if len(batches)>1 else "")+message).encode("utf-8")
        commit.check();repo.object_store.add_object(commit);ids.append(commit.id);parent=commit.id;LOG.info("准备提交 %d/%d: %s",number,len(batches),commit.id.decode())
    if repo.refs.follow(b"HEAD")[0]!=chain:raise StopPush("本地 HEAD 分支在暂存期间改变，拒绝更新")
    options={"committer":identity,"timestamp":now,"timezone":tz,"message":b"commit: "+message.encode("utf-8").splitlines()[0]}
    updated=repo.refs.add_if_new(b"HEAD",parent,**options) if head is None else repo.refs.set_if_equals(b"HEAD",head,parent,**options)
    if not updated:raise StopPush("本地 HEAD 被其他进程更新，未覆盖其提交")
    return ids,empty
def prepare(repo,a,identity,cache): # 索引锁覆盖读取、扫描与写入全过程；失败只撤销本进程的锁，保留已生成的对象供恢复。
    config=repo.get_config_stack();check_repo_state(repo,config);lock=GitFile(repo.index_path(),"wb") # 尊重 index.lock；不猜测锁是否过期，也不删除别人的锁。
    try:
        expected=repo.refs.follow(b"HEAD");index=repo.open_index();stage_all(repo,index,a,config,cache);writer=SHA1Writer(lock);write_index_dict(writer,dict(index.items()),version=3);ids,empty=commit_staged(repo,index,a,identity,expected);writer.close();return ids,empty
    except BaseException:
        lock.abort();raise
def network_error(exc):
    if isinstance(exc,ssl.SSLCertVerificationError):return StopPush("TLS 证书校验失败；请配置 --ca-file，不会自动关闭校验")
    if isinstance(exc,ssl.SSLError) and not isinstance(exc,(ssl.SSLEOFError,ssl.SSLZeroReturnError)):return StopPush("TLS 握手/协议错误: "+str(exc))
    if isinstance(exc,OSError) and not isinstance(exc,(ConnectionError,TimeoutError,socket.gaierror,ssl.SSLError)):
        codes={errno.ETIMEDOUT,errno.ECONNRESET,errno.ECONNABORTED,errno.ECONNREFUSED,errno.EHOSTUNREACH,errno.ENETUNREACH,errno.ENETDOWN,errno.ENETRESET,errno.EPIPE,errno.EAGAIN,errno.ENOBUFS,10051,10054,10060,10061,10065}
        if exc.errno not in codes and getattr(exc,"winerror",None) not in codes:return StopPush(f"本地网络配置/资源错误（不重试）: {exc}")
    if not isinstance(exc,(OSError,http.client.HTTPException)):return StopPush(f"非网络程序错误（不重试）: {exc}")
    return NetworkFailure(f"{type(exc).__name__}: {exc}")
def resolve_connect(host,port,a):
    started=time.monotonic();deadline=started+a.connect_timeout;answer=queue.Queue(maxsize=1)
    def resolve():
        try:answer.put((socket.getaddrinfo(host,port,0,socket.SOCK_STREAM),None))
        except Exception as exc:answer.put((None,exc))
    trace(a,"== DNS: %s:%s",host,port);threading.Thread(target=resolve,daemon=True).start()
    while True:
        remaining=deadline-time.monotonic()
        if remaining<=0:raise NetworkFailure("DNS/连接总超时")
        try:addresses,error=answer.get(timeout=min(1,remaining));break
        except queue.Empty:trace(a,"== DNS 等待: %s | %.1fs",host,time.monotonic()-started)
    if error:raise network_error(error)
    trace(a,"== DNS 完成: %s | %s | %.3fs",host,list(dict.fromkeys(x[4][0] for x in addresses)),time.monotonic()-started);last=None
    for index,(family,kind,protocol,_,address) in enumerate(addresses):
        remaining=deadline-time.monotonic()
        if remaining<=0:break
        sock=socket.socket(family,kind,protocol);sock.settimeout(min(remaining,max(1,remaining/(len(addresses)-index))));trace(a,"== Trying %s:%s",address[0],address[1]);attempt=time.monotonic() # 为后续 IPv4/IPv6 地址保留预算，避免第一个黑洞地址耗尽整个超时。
        try:
            sock.connect(address);trace(a,"== Connected %s -> %s | %.3fs",sock.getsockname(),sock.getpeername(),time.monotonic()-attempt);sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1);return sock,deadline
        except OSError as exc:
            last=exc;trace(a,"== TCP 失败: %s | %s",address,exc);sock.close();failure=network_error(exc)
            if isinstance(failure,StopPush):raise failure from exc
    raise NetworkFailure(f"TCP 连接失败或超时: {last or host}")
def header_log(a,direction,name,value):
    lower=name.lower();sensitive=any(word in lower for word in ("authorization","cookie","token","signature","secret"));shown="***" if sensitive else value
    if lower=="location":shown=safe_url(value) if "://" in value else value.split("?",1)[0].split("#",1)[0]
    if sensitive:remember(value)
    trace(a,"%s header, %d bytes: %s: %s",direction,len((name+": "+str(value)+"\r\n").encode("latin1","replace")),name,shown)
class TransferMonitor:
    def __init__(self,sock,a,label):
        self.sock=sock;self.a=a;self.label=label;self.lock=threading.Lock();self.done=threading.Event();self.failure=None;self.sent=0;self.received=0;self.phase="等待";self.total=0;self.started=time.monotonic();self.phase_start=self.started;self.phase_count=0;self.last=(self.started,0);self.history=deque([(self.started,0)]);self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def switch(self,phase,total=0):
        with self.lock:self.phase=phase;self.total=total;self.phase_start=time.monotonic();self.phase_count=0;self.last=(self.phase_start,0);self.history=deque([self.last])
    def add(self,count,upload=False):
        with self.lock:
            self.phase_count+=count
            if upload:self.sent+=count
            else:self.received+=count
    def run(self): # 独立线程在 send/read 阻塞时继续显示 0 B/s，并在滑动时间窗持续低速时中断真实 socket。
        while not self.done.wait(self.a.progress_interval):
            with self.lock:
                now=time.monotonic();n=self.phase_count;phase=self.phase;elapsed=now-self.phase_start;instant=(n-self.last[1])/max(now-self.last[0],.001);self.last=(now,n);self.history.append((now,n));window=self.a.low_speed_time
                while len(self.history)>1 and self.history[1][0]<=now-window:self.history.popleft()
                slow=window>0 and self.a.low_speed_limit>0 and elapsed>=window and (n-self.history[0][1])/max(now-self.history[0][0],.001)<self.a.low_speed_limit;total=self.total
            LOG.info("[%s] %s %s%s | 当前 %s/s | 平均 %s/s | %.1fs",self.label,phase,human(n),("/"+human(total)) if total else "",human(instant),human(n/max(elapsed,.001)),elapsed)
            if slow:
                self.failure=f"{phase}持续 {window}s 低于 {self.a.low_speed_limit}B/s";LOG.warning("[%s] %s",self.label,self.failure)
                with suppress(OSError):self.sock.shutdown(socket.SHUT_RDWR)
                return
    def check(self):
        if self.failure:raise NetworkFailure(self.failure)
    def close(self):
        self.done.set();self.thread.join(timeout=max(1,self.a.progress_interval+1))
class Response: # 提供 Dulwich AbstractHttpGitClient 所需的响应接口，同时把响应读取和连接释放纳入监测。
    def __init__(self,raw,connection,meter,net,url,original):
        self.raw=raw;self.connection=connection;self.meter=meter;self.net=net;self.url=url;self.status=raw.status;self.headers=raw.headers;self.content_type=raw.getheader("Content-Type");self.redirect_location=url if url!=original else "";self.expected=raw.length;self.received=0;self.closed=False
    def geturl(self):return self.url
    def read(self,amt=None):
        if amt is None or amt<0:
            parts=[]
            while True:
                block=self.read(CHUNK)
                if not block:break
                parts.append(block)
            return b"".join(parts)
        if amt==0:return b""
        self.meter.check()
        try:data=self.raw.read(amt)
        except (OSError,http.client.HTTPException) as exc:self.meter.check();raise network_error(exc) from exc
        self.meter.check();self.received+=len(data);self.meter.add(len(data))
        if not data and self.expected is not None and self.received<self.expected:raise NetworkFailure("HTTP 响应未达到声明的 Content-Length")
        return data
    def close(self):
        if self.closed:return
        self.closed=True;self.meter.close();self.raw.close();self.connection.close();self.net.live.discard(self);trace(self.net.a,"== Connection closed: %s | 上传 %s | 接收 %s",safe_url(self.url),human(self.meter.sent),human(self.meter.received))
@contextmanager
def request_body(data): # 把 pack 迭代器落入临时文件以避免整包常驻内存，也让 307/308 重定向可以安全重放请求体。
    owned=None
    try:
        if data is None:yield None,0,0;return
        if isinstance(data,(bytes,bytearray,memoryview)):owned=io.BytesIO(data);stream=owned
        elif hasattr(data,"read") and hasattr(data,"seek"):stream=data
        else:
            owned=tempfile.TemporaryFile();stream=owned;size=0;last=time.monotonic();LOG.info("准备 Git 请求体到临时文件，尚未开始网络上传")
            for block in data:
                stream.write(block);size+=len(block)
                if time.monotonic()-last>=1:LOG.info("PACK 本地准备: %s",human(size));last=time.monotonic()
            stream.seek(0)
        start=stream.tell();stream.seek(0,2);length=stream.tell()-start;stream.seek(start);yield stream,length,start
    finally:
        if owned is not None:owned.close()
class Transport: # Git 与 LFS 共用标准库传输层；默认校验证书，凭据仅绑定明确授权的 origin，不使用 urllib3。
    def __init__(self,a,auths=None,require_tls=False):self.a=a;self.auths=auths or {};self.live=set();self.require_tls=require_tls
    def close(self):
        for response in list(self.live):response.close()
    def proxy(self,url):
        if self.a.no_proxy:return None
        p=urlsplit(url);raw=self.a.proxy
        if raw is None:
            if proxy_bypass(p.hostname):return None
            proxies=getproxies();raw=proxies.get(p.scheme) or proxies.get("all")
        if not raw:return None
        raw=raw if "://" in raw else "http://"+raw;clean,user,password=split_credentials(raw);proxy=urlsplit(clean)
        if proxy.scheme!="http":raise StopPush("只支持 HTTP 代理及其 CONNECT；不支持 HTTPS/SOCKS 代理")
        return proxy,basic(user,password)
    def socket(self,url):
        p=urlsplit(url);target_port=p.port or (443 if p.scheme=="https" else 80);proxy=self.proxy(url);host=proxy[0].hostname if proxy else p.hostname;port=(proxy[0].port or 80) if proxy else target_port;sock,deadline=resolve_connect(host,port,self.a)
        expired=threading.Event()
        def cancel_connect():
            expired.set()
            with suppress(OSError):sock.shutdown(socket.SHUT_RDWR)
        guard=threading.Timer(max(.001,deadline-time.monotonic()),cancel_connect);guard.daemon=True;guard.start()
        try:
            if proxy and p.scheme=="https":
                authority=(f"[{p.hostname}]" if ":" in p.hostname else p.hostname)+f":{target_port}";headers={"Host":authority}
                if proxy[1]:headers["Proxy-Authorization"]=proxy[1]
                trace(self.a,"=> CONNECT %s HTTP/1.1",authority)
                for key,value in headers.items():header_log(self.a,"=> Send",key,value)
                sock.sendall((f"CONNECT {authority} HTTP/1.1\r\n"+"".join(f"{k}: {v}\r\n" for k,v in headers.items())+"\r\n").encode("latin1"));response=http.client.HTTPResponse(sock,method="CONNECT");response.begin();trace(self.a,"<= Proxy HTTP %d",response.status)
                for key,value in response.getheaders():header_log(self.a,"<= Recv",key,value)
                status=response.status;response.close()
                if status!=200:raise HTTPFailure(status,url,"代理 CONNECT 失败")
            if p.scheme=="https":
                remaining=deadline-time.monotonic()
                if remaining<=0:raise NetworkFailure("TLS 握手前连接总超时")
                sock.settimeout(remaining);trace(self.a,"== TLS handshake: SNI=%s | 校验证书=开启",p.hostname);context=ssl.create_default_context(cafile=self.a.ca_file);sock=context.wrap_socket(sock,server_hostname=p.hostname);trace(self.a,"== TLS: %s | %s | peer=%s",sock.version(),sock.cipher()[0],sock.getpeername());trace(self.a,"== Certificate expires: %s",sock.getpeercert().get("notAfter","unknown"))
            if expired.is_set():raise NetworkFailure("TCP/CONNECT/TLS 总连接超时")
            sock.settimeout(self.a.io_timeout);return sock,proxy
        except (OSError,http.client.HTTPException) as exc:
            sock.close()
            if expired.is_set():raise NetworkFailure("TCP/CONNECT/TLS 总连接超时") from exc
            raise network_error(exc) from exc
        except BaseException:sock.close();raise
        finally:guard.cancel()
    def request(self,method,url,headers=None,data=None,label="HTTP",allow_error=False):
        original=url;extra={str(k).lower():str(v) for k,v in (headers or {}).items()}
        with request_body(data) as (stream,length,start):
            if method=="POST" and urlsplit(url).path.endswith("/git-receive-pack") and length>self.a.max_pack_size:raise StopPush(f"Git 请求体 {human(length)} 超过 --max-pack-size；分段提交不保证历史 pack 足够小，请先处理未推送历史")
            for redirect in range(6):
                p=urlsplit(url)
                if p.scheme not in ("http","https") or not p.hostname or p.username is not None:raise StopPush("HTTP 请求地址无效或包含未拆分的凭据")
                if self.require_tls and p.scheme!="https":raise StopPush("拒绝将 HTTPS 仓库凭据或 LFS 数据降级到 HTTP")
                if any(c in url for c in "\r\n\0"):raise StopPush("URL 包含控制字符")
                for key,value in parse_qsl(p.query):
                    if any(word in key.lower() for word in ("signature","credential","token","secret")):remember(value)
                sock,proxy=self.socket(url);connection=http.client.HTTPConnection(p.hostname,p.port or (443 if p.scheme=="https" else 80));connection.sock=sock;meter=TransferMonitor(sock,self.a,label);wrapper=None
                try:
                    target=(p.path or "/")+("?"+p.query if p.query else "");target=quote(target,safe="/%:@!$&'()*+,;=-._~?[]")
                    if proxy and p.scheme=="http":target=urlunsplit((p.scheme,p.netloc,target,"",""))
                    outgoing={"user-agent":"purepush/2 dulwich/1.2.15","accept":"*/*","accept-encoding":"identity","pragma":"no-cache",**extra};outgoing.pop("host",None);outgoing.pop("transfer-encoding",None);outgoing.pop("expect",None);outgoing.pop("proxy-authorization",None);outgoing["connection"]="close"
                    if "authorization" not in outgoing and origin(url) in self.auths:outgoing["authorization"]=self.auths[origin(url)]
                    if p.scheme=="http" and "authorization" in outgoing and p.hostname not in ("127.0.0.1","localhost","::1"):raise StopPush("不通过明文 HTTP 发送认证凭据；请改用 HTTPS")
                    if proxy and p.scheme=="http" and proxy[1]:outgoing["proxy-authorization"]=proxy[1]
                    if stream is not None:outgoing["content-length"]=str(length)
                    else:outgoing.pop("content-length",None)
                    hostname=p.hostname.encode("idna").decode();outgoing["host"]=(f"[{hostname}]" if ":" in hostname else hostname)+(f":{p.port}" if p.port else "")
                    trace(self.a,"=> %s %s HTTP/1.1",method,safe_url(url));connection.putrequest(method,target,skip_host=True,skip_accept_encoding=True)
                    for key,value in outgoing.items():header_log(self.a,"=> Send",key,value);connection.putheader(key,value)
                    meter.switch("上传",length)
                    try:connection.endheaders()
                    except OSError as exc:meter.check();raise network_error(exc) from exc
                    if stream is not None:
                        stream.seek(start);remaining=length;upload_start=time.monotonic()
                        while remaining:
                            block=stream.read(min(CHUNK,remaining))
                            if not block:raise StopPush("本地请求体在发送时被截断，拒绝发送错误 Content-Length")
                            view=memoryview(block)
                            while view:
                                meter.check()
                                try:n=sock.send(view)
                                except OSError as exc:meter.check();raise network_error(exc) from exc
                                if n<=0:raise NetworkFailure("socket 在发送请求体时关闭")
                                meter.add(n,True);remaining-=n;view=view[n:] # 只在 send 返回后计量，不将生成器产出的字节当成上传成功。
                        LOG.log(logging.INFO if length>=CHUNK else logging.DEBUG,"[%s] 请求体已交给 socket: %s | 平均 %s/s；等待服务端确认",label,human(length),human(length/max(time.monotonic()-upload_start,.001)))
                    meter.switch("等待响应/接收")
                    try:raw=connection.getresponse()
                    except (OSError,http.client.HTTPException) as exc:meter.check();raise network_error(exc) from exc
                    meter.check();trace(self.a,"<= HTTP/%s %d %s","1.1" if raw.version==11 else "1.0",raw.status,raw.reason)
                    for key,value in raw.getheaders():header_log(self.a,"<= Recv",key,value)
                    wrapper=Response(raw,connection,meter,self,url,original);self.live.add(wrapper)
                    if raw.status in (301,302,303,307,308):
                        location=raw.getheader("Location");wrapper.close()
                        if not location:raise StopPush("HTTP 重定向没有 Location")
                        new=urljoin(url,location)
                        if p.scheme=="https" and urlsplit(new).scheme!="https":raise StopPush("拒绝 HTTPS 降级重定向")
                        if method not in ("GET","HEAD") and raw.status not in (307,308):raise StopPush("拒绝可能改变上传方法的 301/302/303；请使用最终仓库/LFS 地址")
                        if origin(new)!=origin(url):extra={k:v for k,v in extra.items() if k in ("accept","content-type","git-protocol")};trace(self.a,"== 跨源重定向，移除原请求认证及自定义头")
                        url=new;continue
                    if not allow_error and not 200<=raw.status<300:
                        body=wrapper.read(4096).decode("utf-8","replace");delay=retry_delay(raw.getheader("Retry-After"));wrapper.close();raise HTTPFailure(raw.status,url,body[:600],delay)
                    if raw.getheader("Content-Encoding", "identity").lower() not in ("identity",""):wrapper.close();raise StopPush("服务端忽略 Accept-Encoding: identity，暂不处理压缩 HTTP 响应")
                    return wrapper
                except BaseException:
                    if wrapper is not None:wrapper.close()
                    else:meter.close();connection.close()
                    raise
            raise StopPush("HTTP 重定向超过 5 次")
def retry_delay(value):
    if not value:return 0
    try:return min(300,max(0,float(value)))
    except ValueError:
        try:return min(300,max(0,parsedate_to_datetime(value).timestamp()-time.time()))
        except (ValueError,TypeError,OverflowError):return 0
def read_limited(response,limit=8*1024*1024):
    blocks=[];size=0
    while True:
        block=response.read(min(CHUNK,limit+1-size));size+=len(block)
        if size>limit:raise StopPush("HTTP JSON 响应超过安全大小限制")
        if not block:return b"".join(blocks)
        blocks.append(block)
def json_request(net,url,payload,headers=None,label="LFS batch"):
    response=net.request("POST",url,{"accept":MEDIA,"content-type":MEDIA,**(headers or {})},json.dumps(payload,separators=(",",":")).encode(),label)
    try:
        body=read_limited(response)
        if not body:return {}
        try:return json.loads(body)
        except ValueError as exc:raise StopPush("LFS 服务端没有返回有效 JSON") from exc
    finally:response.close()
class StdlibGitClient(AbstractHttpGitClient): # Git 协商、pack 和 side-band 仍由 Dulwich 实现，仅替换 HTTP 层。
    def __init__(self,url,net):super().__init__(url,dumb=False);self.net=net
    def _http_request(self,url,headers=None,data=None,raise_for_status=True):
        response=self.net.request("GET" if data is None else "POST",url,headers,data,"Git HTTP body",allow_error=not raise_for_status)
        if raise_for_status and response.status!=200:
            code=response.status;response.close();raise HTTPFailure(code,url)
        return response,response.read
class Progress:
    def __init__(self,prefix):self.prefix=prefix;self.decoder=codecs.getincrementaldecoder("utf-8")("replace");self.pending=""
    def __call__(self,data):
        chunk=self.decoder.decode(data) if isinstance(data,bytes) else str(data);self.pending+=chunk
        parts=re.split(r"[\r\n]",self.pending);self.pending=parts.pop()
        for line in parts:
            if line:LOG.info("%s%s",self.prefix,line)
        if len(self.pending)>4096:LOG.info("%s%s",self.prefix,self.pending);self.pending=""
    def finish(self):
        if self.pending:LOG.info("%s%s",self.prefix,self.pending);self.pending=""
def outgoing_lfs(repo,remote_refs,target,a): # 检查真正需要发送的历史对象，不只扫描当前工作区；旧提交中已删除的 LFS 文件同样会被发现。
    known={v for v in remote_refs.values() if v and v!=ZERO_SHA and v in repo.object_store};pointers={};progress=Progress("PACK 规划: ");checked=0;last=time.monotonic()
    try:
        for oid,_ in MissingObjectFinder(repo.object_store,known,{target},progress=progress):
            obj=repo.object_store[oid];checked+=1
            if isinstance(obj,Blob):
                size=obj.raw_length()
                if size>=a.max_blob_size:raise StopPush(f"未推送历史包含普通大 Blob: {oid.decode()} ({human(size)})；新增 .gitattributes 不会迁移旧提交。请先单独迁移/清理历史，不自动强推")
                if size<=1024:
                    pointer=pointer_info(obj.data)
                    if pointer:
                        key,n=pointer
                        if key in pointers and pointers[key]!=n:raise StopPush("同一 LFS OID 出现不同 size")
                        pointers[key]=n
            if time.monotonic()-last>=1:LOG.info("检查待推送历史对象: %d | LFS: %d",checked,len(pointers));last=time.monotonic()
    finally:progress.finish()
    return pointers
def upload_lfs(net,endpoint,pointers,cache,ref,done): # batch 每组最多 100 项；上传成功并完成可选 verify 后才标记成功，失败留给外层统一重试。
    pending=[{"oid":oid,"size":size} for oid,size in sorted(pointers.items()) if (oid,size) not in done]
    for start in range(0,len(pending),100):
        group=pending[start:start+100];requested={item["oid"]:item["size"] for item in group};LOG.info("LFS batch: %d 个对象 -> %s",len(group),safe_url(endpoint));answer=json_request(net,endpoint,{"operation":"upload","transfers":["basic"],"hash_algo":"sha256","ref":{"name":text(ref)},"objects":group})
        if not isinstance(answer,dict) or answer.get("transfer","basic")!="basic" or answer.get("hash_algo","sha256")!="sha256":raise StopPush("服务端要求不支持的 LFS 传输方式/哈希算法")
        objects=answer.get("objects");seen=set()
        if not isinstance(objects,list):raise StopPush("LFS batch 缺少 objects 列表")
        for item in objects:
            oid=item.get("oid");size=item.get("size")
            if oid not in requested or oid in seen or size!=requested[oid]:raise StopPush("LFS batch 返回了重复、不匹配或未知对象")
            seen.add(oid)
            if item.get("error"):
                error=item["error"];raise HTTPFailure(error.get("code",422),endpoint,str(error.get("message","LFS 对象错误")))
            actions=item.get("actions") or {};upload=actions.get("upload");verify=actions.get("verify")
            if upload:
                path=cache.require(oid,size);LOG.info("LFS 上传对象: %s | %s",oid,human(size))
                with regular_reader(path) as (stream,st):
                    if signature(st)!=cache.verified.get((oid,size)):raise StopPush("LFS 缓存在校验后被修改，拒绝上传")
                    response=net.request("PUT",upload["href"],{"content-type":"application/octet-stream",**upload.get("header",{})},stream,"LFS "+oid[:10])
                    try:read_limited(response)
                    finally:response.close()
                if verify:json_request(net,verify["href"],{"oid":oid,"size":size},verify.get("header",{}),"LFS verify")
            elif actions:raise StopPush("LFS batch 提供 actions 但没有 upload，不能假定对象已存在")
            else:LOG.info("LFS 远端已存在: %s",oid[:16])
            done.add((oid,size))
        if seen!=set(requested):raise StopPush("LFS batch 漏掉请求对象，停止引用推送")
def ancestor(repo,old,new):
    if old==ZERO_SHA or old==new:return True
    todo=[new];seen=set()
    while todo:
        sha=todo.pop()
        if sha==old:return True
        if sha in seen:continue
        seen.add(sha)
        try:obj=repo.object_store[sha]
        except KeyError:raise StopPush("本地历史缺少对象，无法安全判断快进关系")
        if isinstance(obj,Commit):todo.extend(obj.parents)
    return False
def is_retryable(exc):
    if isinstance(exc,HTTPFailure):return exc.code in (408,425,429,500,502,503,504)
    if isinstance(exc,(NetworkFailure,HangupException)):return True
    if isinstance(exc,GitProtocolError):return any(t in str(exc).lower() for t in ("unexpected eof","unexpected end","unexpectedly closed","expected flush","connection reset","remote end hung up"))
    return False
def retry(a,label,operation): # 仅网络瞬断、超时与可恢复 HTTP 状态重试；认证、证书、仓库及程序错误立即向上传播。
    for attempt in range(1,a.retry+1):
        if attempt>1:a.trace=True
        LOG.info("===== %s | 尝试 %d/%d | 间隔 %.1fs =====",label,attempt,a.retry,a.retry_wait)
        try:return operation()
        except Exception as exc:
            if not is_retryable(exc) or attempt==a.retry:raise
            delay=max(a.retry_wait,getattr(exc,"retry_after",0));LOG.warning("网络错误，%.1f 秒后重试；下一次重新探测引用和申请 LFS action: %s",delay,exc);time.sleep(delay)
def push_target(repo,a,remote,ref,target,endpoint,auths,cache,done,lease=None): # 每次重试重新读取 receive-pack 公告引用；上次响应丢失但引用已成功更新时按幂等成功处理。
    def attempt():
        net=Transport(a,auths,urlsplit(remote).scheme=="https");client=StdlibGitClient(remote,net);remote_progress=Progress("remote: ");pack_progress=Progress("PACK: ");observed={}
        try:
            def update(refs):
                old=refs.get(ref) or ZERO_SHA;observed["old"]=old
                if old==target:LOG.info("远端已是目标提交，可能上次成功后响应丢失: %s",target.decode());return {}
                if lease is not None and old!=lease:raise StopPush("force-with-lease 条件不满足，远端已变化，不会重新放宽条件")
                if not a.force and lease is None and not ancestor(repo,old,target):raise StopPush("non-fast-forward：远端不是本地目标的祖先；先获取/合并远端历史，不能靠重试解决")
                pointers=outgoing_lfs(repo,refs,target,a);upload_lfs(net,endpoint,pointers,cache,ref,done);return {ref:target} # LFS 任一对象失败就抛出异常，Git pack 不会开始发送。
            def generate(have,want,**kwargs):
                kwargs["progress"]=pack_progress;return repo.generate_pack_data({sha for sha in have if sha in repo.object_store},want,**kwargs)
            result=client.send_pack(urlsplit(remote).path,update,generate,progress=remote_progress,push_options=[v.encode() for v in a.push_option] or None,atomic=a.atomic)
            statuses=result.ref_status or {}
            if any(statuses.values()):raise StopPush("远端拒绝引用更新: "+repr(statuses))
            if observed.get("old")!=target and ref not in statuses:
                current=client.get_refs(urlsplit(remote).path).refs.get(ref)
                if current!=target:raise StopPush("服务端未确认目标引用，不能报告成功")
            LOG.info("推送成功: %s -> %s",text(ref),target.decode())
        finally:remote_progress.finish();pack_progress.finish();net.close();client.close()
    retry(a,f"推送 {safe_url(remote)} {text(ref)}",attempt)
def parse_identity(value,default_name,default_email):
    value=value.replace("，",",").replace("、",",").strip()
    if not value:return default_name,default_email
    if "," in value:name,email=(part.strip() for part in value.split(",",1))
    else:
        parts=value.rsplit(None,1);name=parts[0];email=parts[1] if len(parts)==2 else default_email
    return name,email
def identity_for(repo,a,user,remote): # -u 强制应用 URL 推导身份，仅写当前仓库配置；不加 -u 时保留已有身份或交互选择。
    config=repo.get_config_stack();name=text(cfg(config,b"user",b"name"));email=text(cfg(config,b"user",b"email"));parts=urlsplit(remote).path.strip("/").split("/");default_name=user if user and user!="x-access-token" else parts[0];default_email=f"{default_name}@users.noreply.github.com" if urlsplit(remote).hostname in ("github.com","www.github.com") else ""
    if a.user is not None:
        name,email=(default_name,default_email) if a.user=="AUTO" else parse_identity(a.user,default_name,default_email)
    else:
        name=os.environ.get("GIT_AUTHOR_NAME",name);email=os.environ.get("GIT_AUTHOR_EMAIL",email)
        if not a.no_ask and sys.stdin.isatty() and default_email and (name,email)!=(default_name,default_email):
            answer=input(f"身份 [1] {name}, {email} [2] {default_name}, {default_email}；也可输入 name,email [1]: ").strip()
            if answer=="2":name,email=default_name,default_email
            elif answer not in ("","1"):name,email=parse_identity(answer,name,email)
    name=a.name or name;email=a.email or email
    if not name or not email:raise StopPush("缺少提交身份；GitHub 可用 -u，其他服务器请用 --name/--email")
    if any(c in name+email for c in "\n\r\0<>") or "@" not in email:raise StopPush("提交姓名/邮箱格式无效")
    if a.user is not None or a.name or a.email:
        local=repo.get_config();local.set((b"user",),b"name",name.encode());local.set((b"user",),b"email",email.encode());local.write_to_path()
    LOG.info("提交身份: %s <%s>",name,email);return f"{name} <{email}>".encode()
def lfs_settings(repo,config,remote,remote_name,a,auths): # 支持独立 LFS endpoint；不同主机不继承 Git token，除非显式在该 endpoint 提供凭据。
    section=(b"remote",remote_name.encode());endpoint=a.lfs_url or text(cfg(config,(b"lfs",),b"pushurl") or cfg(config,section,b"lfspushurl") or cfg(config,(b"lfs",),b"url") or cfg(config,section,b"lfsurl"))
    if not endpoint:
        path=Path(repo.path)/".lfsconfig"
        if path.exists() and not path.is_symlink():
            local=ConfigFile.from_file(io.BytesIO(read_regular(path,1024*1024)));endpoint=text(cfg(local,(b"lfs",),b"pushurl") or cfg(local,(b"lfs",),b"url") or cfg(local,section,b"lfsurl"))
    endpoint=endpoint or remote.removesuffix(".git")+".git/info/lfs";clean,user,password=split_credentials(endpoint)
    if urlsplit(clean).query:raise StopPush("LFS endpoint 不能包含查询串；action 的签名查询串则完整保留")
    token=basic(user,password)
    if token:auths[origin(clean)]=token
    return clean.rstrip("/")+"/objects/batch"
def preprocess(argv): # 与原脚本一样，-m 后所有参数构成消息；-u 单独使用不会把 push 或 URL 吞作用户名。
    out=[];i=0;value_flags={"--repo","--repo-path","--path","-path","-p","--branch","-b","--size","-s","--threshold","--retry","-retry","-r","--retry-wait","--retry-seconds","--verbose","-v","--connect-timeout","--io-timeout","--low-speed-limit","--low-speed-time","--progress-interval","--max-commit-size","--max-pack-size","--max-blob-size","--name","--email","--proxy","--ca-file","--lfs-url","--push-option"}
    while i<len(argv):
        arg=argv[i]
        if arg in ("-m","--message","--commit-msg","--commit_msg"):
            if i+1>=len(argv):raise StopPush("-m 后缺少提交消息")
            out.extend(["--message"," ".join(argv[i+1:])]);break
        if arg in ("-u","--user","--auto-user"):
            nxt=argv[i+1] if i+1<len(argv) else ""
            if nxt and nxt!="push" and not nxt.startswith(("-","git@")) and "://" not in nxt:out.append("--user="+nxt);i+=2
            else:out.append("--user=AUTO");i+=1
            continue
        if arg=="--force-with-lease":
            nxt=argv[i+1] if i+1<len(argv) else ""
            if re.fullmatch("[0-9a-fA-F]{40}",nxt):out.append(arg+"="+nxt.lower());i+=2
            else:out.append(arg+"=auto");i+=1
            continue
        if arg=="--remote" or arg in value_flags:
            if i+1>=len(argv):raise StopPush(f"{arg} 缺少参数")
            out.extend(argv[i:i+2]);i+=2;continue
        if arg.startswith("-"):out.append(arg)
        elif "://" in arg or arg.startswith("git@"):out.extend(["--remote",arg])
        else:out.append(arg)
        i+=1
    return out
def parser():
    p=argparse.ArgumentParser(description="Dulwich 1.2.15 + Python 标准库的 HTTP(S) 自动提交与 push；不运行外部过滤器")
    p.add_argument("mode",nargs="?",choices=["push"],default="push");p.add_argument("--remote",default="");p.add_argument("--repo","--repo-path","--path","-path","-p",default=".");p.add_argument("--branch","-b",default=os.environ.get("BRANCH"));p.add_argument("--user","-u","--auto-user",nargs="?",const="AUTO");p.add_argument("--name");p.add_argument("--email");p.add_argument("--message","-m","--commit-msg","--commit_msg",default="")
    p.add_argument("--no-ask","--noask","-noask","-y","-yes",action="store_true");p.add_argument("--size","-s",type=parse_size,default=100*1024**2);p.add_argument("--threshold",type=int,default=0);p.add_argument("--max-blob-size",type=parse_size,default=100*1024**2);p.add_argument("--max-commit-size",type=parse_size,default=1900*1024**2);p.add_argument("--max-pack-size",type=parse_size,default=1900*1024**2)
    p.add_argument("--retry","-retry","-r",type=int,default=10);p.add_argument("--retry-wait","--retry-seconds",type=float,default=5);p.add_argument("--verbose","-v",type=int,default=2);p.add_argument("--connect-timeout",type=float,default=45);p.add_argument("--io-timeout",type=float,default=300);p.add_argument("--low-speed-limit",type=int,default=10);p.add_argument("--low-speed-time",type=float,default=60);p.add_argument("--progress-interval",type=float,default=.5)
    p.add_argument("--proxy");p.add_argument("--no-proxy",action="store_true");p.add_argument("--ca-file");p.add_argument("--lfs-url");p.add_argument("--no-auto-lfs",action="store_true");p.add_argument("--renormalize",action="store_true");p.add_argument("--force",action="store_true");p.add_argument("--force-with-lease",nargs="?",const="auto");p.add_argument("--set-upstream",action="store_true");p.add_argument("--push-option",action="append",default=[]);p.add_argument("--atomic",action="store_true");p.add_argument("--self-test",action="store_true")
    return p
def arguments(argv=None):
    p=parser();a=p.parse_args(preprocess(list(sys.argv[1:] if argv is None else argv)));a.trace=a.verbose>=3
    if a.threshold>0:a.size=a.threshold
    if not all(math.isfinite(x) for x in (a.connect_timeout,a.io_timeout,a.progress_interval,a.retry_wait,a.low_speed_time)):p.error("时间参数不能是 NaN 或无穷大")
    if min(a.size,a.max_blob_size,a.max_commit_size,a.max_pack_size,a.connect_timeout,a.io_timeout,a.progress_interval)<=0 or a.retry<1 or min(a.low_speed_limit,a.low_speed_time,a.retry_wait)<0:p.error("大小、超时、刷新间隔必须为正数；retry 至少为 1；低速阈值/时间及重试间隔不得为负")
    if a.force and a.force_with_lease:p.error("--force 与 --force-with-lease 不应同时使用")
    if a.force_with_lease and a.force_with_lease!="auto" and not re.fullmatch("[0-9a-f]{40}",a.force_with_lease):p.error("--force-with-lease 需要 auto 或完整 40 位预期提交 ID")
    return a
def main(a):
    installed=version("dulwich");LOG.info("Dulwich 版本: %s | 网络: Python 标准库 http.client/socket/ssl",installed)
    if installed!="1.2.15":LOG.warning("此源码按 1.2.15 接口编写，其他版本未验证")
    root=Path(a.repo).expanduser().resolve()
    if not root.is_dir():raise StopPush("指定仓库目录不存在")
    try:repo=Repo.discover(str(root))
    except NotGitRepository:
        if not a.no_ask and (not sys.stdin.isatty() or input("当前目录不是仓库，是否初始化？[Y/n]: ").strip().lower() not in ("","y","yes")):raise StopPush("已取消初始化；无人值守时使用 --no-ask")
        repo=Repo.init(str(root))
        if a.branch:repo.refs.set_symbolic_ref(b"HEAD",b"refs/heads/"+a.branch.encode())
    with repo:
        root=Path(repo.path);config=repo.get_config_stack();check_repo_state(repo,config);chain,head=repo.refs.follow(b"HEAD");local_branch=text(chain[-1][11:]) if chain[-1].startswith(b"refs/heads/") else "";tracking=text(cfg(config,(b"branch",local_branch.encode()),b"remote"));remote_name="origin";section=(b"remote",b"origin");raw=a.remote or text(cfg(config,section,b"pushurl") or cfg(config,section,b"url"))
        if not raw and tracking:remote_name=tracking;section=(b"remote",tracking.encode());raw=text(cfg(config,section,b"pushurl") or cfg(config,section,b"url"))
        if not raw:raise StopPush("没有远程 URL，也未找到 origin/tracking 配置")
        raw=apply_instead_of(config,raw,push=True);remote,user,password,url_branch=normalize_remote(raw);branch=a.branch or url_branch or local_branch
        if not branch:raise StopPush("detached HEAD 必须显式指定远程目标 --branch")
        ref=b"refs/heads/"+branch.encode();
        if not check_ref_format(ref):raise StopPush("目标分支名不合法")
        host=urlsplit(remote).hostname
        if host in ("github.com","www.github.com"):
            a.max_blob_size=min(a.max_blob_size,100*1024**2)
            if password is None:password=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN");remember(password)
            user=user or urlsplit(remote).path.strip("/").split("/")[0]
        token=basic(user,password);auths={origin(remote):token} if token else {};endpoint=lfs_settings(repo,config,remote,remote_name,a,auths)
        if a.proxy is None:a.proxy=text(cfg(config,(b"remote",remote_name.encode()),b"proxy") or cfg(config,(b"http",),b"proxy")) or None
        a.ca_file=a.ca_file or text(cfg(config,(b"http",),b"sslcainfo")) or None
        if a.ca_file:
            a.ca_file=str(Path(a.ca_file).expanduser())
            if not Path(a.ca_file).is_file():raise StopPush("--ca-file/http.sslCAInfo 指定的 CA 文件不存在")
        probe=Transport(a,auths,host in ("github.com","www.github.com"));probe.proxy(remote)
        if a.remote:
            local=repo.get_config();local.set((b"remote",remote_name.encode()),b"url",remote.encode());local.set((b"remote",remote_name.encode()),b"pushurl",remote.encode());local.set((b"remote",remote_name.encode()),b"fetch",f"+refs/heads/*:refs/remotes/{remote_name}/*".encode());local.write_to_path()
        LOG.info("仓库路径: %s",root);LOG.info("远程地址: %s | 分支: %s",safe_url(remote),branch);LOG.info("LFS 阈值: %s | 最大普通 Blob: %s",human(a.size),human(a.max_blob_size));LOG.info("连接超时: %ss | 低速: %dB/s 持续 %ss | 每 %.2fs 输出",a.connect_timeout,a.low_speed_limit,a.low_speed_time,a.progress_interval)
        identity=identity_for(repo,a,user,remote);cache=LFSCache(repo,repo.get_config_stack());journal=Path(repo.controldir())/"purepush-pending.json";prior={}
        if journal.exists():
            try:prior=json.loads(read_regular(journal,1024*1024))
            except ValueError:LOG.warning("忽略无效的续推状态文件，不删除用户 Git 对象")
        if not isinstance(prior,dict):raise StopPush("续推状态文件格式错误，请先检查 purepush-pending.json")
        ids,empty=prepare(repo,a,identity,cache)
        try:target=repo.head()
        except KeyError:raise StopPush("工作区没有可跟踪文件，仓库仍无提交，无法 push")
        key={"remote":remote,"ref":text(ref),"head":target.decode()}
        if not ids and all(prior.get(k)==v for k,v in key.items()):
            values=prior.get("commits",[])
            if not isinstance(values,list) or any(not isinstance(v,str) or not re.fullmatch("[0-9a-f]{40}",v) for v in values):raise StopPush("续推状态包含无效提交 ID")
            ids=[v.encode() for v in values];empty=prior.get("empty")
            if ids and (ids[-1]!=target or any(sha not in repo.object_store for sha in ids)):raise StopPush("续推状态与本地对象不一致")
            if any(not ancestor(repo,old,new) for old,new in zip(ids,ids[1:])):raise StopPush("续推分段不是递进的提交历史")
            if ids:LOG.info("恢复未完成的分段推送: %d 个目标",len(ids))
        ids=ids or [target];atomic_write(journal,json.dumps({**key,"commits":[v.decode() for v in ids],"empty":empty},ensure_ascii=False).encode());lease=None
        if a.force_with_lease:
            expected_ref=b"refs/remotes/"+remote_name.encode()+b"/"+branch.encode()
            if a.force_with_lease=="auto":
                try:lease=repo.refs[expected_ref]
                except KeyError:lease=ZERO_SHA
            else:lease=a.force_with_lease.encode()
        done=set()
        for position,commit in enumerate(ids,1):
            LOG.info("推送分段 %d/%d",position,len(ids));push_target(repo,a,remote,ref,commit,endpoint,auths,cache,done,lease)
            repo.refs[b"refs/remotes/"+remote_name.encode()+b"/"+branch.encode()]=commit
            if lease is not None:lease=commit
            atomic_write(journal,json.dumps({**key,"commits":[v.decode() for v in ids[position:]] or [target.decode()],"empty":empty},ensure_ascii=False).encode())
        repo.refs[b"refs/remotes/"+remote_name.encode()+b"/"+branch.encode()]=target
        if a.set_upstream and local_branch:
            local=repo.get_config();local.set((b"branch",local_branch.encode()),b"remote",remote_name.encode());local.set((b"branch",local_branch.encode()),b"merge",ref);local.write_to_path()
        if empty:
            readme=root/"ReadMe.md"
            if readme.is_file() and not readme.is_symlink() and hashlib.sha256(read_regular(readme)).hexdigest()==empty:atomic_write(readme,b"");LOG.info("EmptyAfterPush: ReadMe.md 已按标记清空，保留为工作区修改")
            else:LOG.warning("ReadMe.md 在推送后已变化或不存在，不执行清空")
        journal.unlink(missing_ok=True);LOG.info("推送成功 %s；操作结束",stamp())
def self_test(): # 自检仅使用临时仓库和本机 HTTP 服务，不读取令牌，不会推送到你的真实远端。
    import unittest
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    from unittest.mock import patch
    from dulwich.client import LocalGitClient
    class Tests(unittest.TestCase):
        def setUp(self):
            self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/"repo";self.root.mkdir();self.repo=Repo.init(str(self.root));self.a=arguments(["push","--no-ask","--no-proxy","--size","256B","--retry","2","--retry-wait","0"]);self.a.trace=False;self.a.verbose=0;self.identity=b"test <test@example.com>";config=self.repo.get_config();config.set((b"user",),b"name",b"test");config.set((b"user",),b"email",b"test@example.com");config.set((b"core",),b"autocrlf",b"false");config.set((b"core",),b"safecrlf",b"false");config.set((b"core",),b"attributesfile",os.fsencode(Path(self.temp.name)/"none-attrs"));config.set((b"core",),b"excludesfile",os.fsencode(Path(self.temp.name)/"ignore"));config.set((b"commit",),b"gpgsign",b"false");config.write_to_path()
            self.repo.get_config_stack=self.repo.get_config;self.cache=LFSCache(self.repo,config) # 隔离全局配置和 lfs.storage，自检缓存只能写入临时仓库。
        def tearDown(self):self.repo.close();self.temp.cleanup()
        def write(self,name,data):
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        def stage(self):return prepare(self.repo,self.a,self.identity,self.cache)
        def test_ignore_lfs_delete_and_no_process(self):
            self.write("tracked.tmp",b"old");self.stage();self.write("tracked.tmp",b"new");self.write(".gitignore",b"*.tmp\n!keep.tmp\nblocked/\n!blocked/no.txt\nselect/*\n!select/keep.txt\nignored-large.bin\n");self.write("drop.tmp",b"drop");self.write("keep.tmp",b"keep");self.write("blocked/no.txt",b"no");self.write("select/keep.txt",b"yes");self.write("select/no.txt",b"no");self.write("ignored-large.bin",b"x"*600);self.write("has space.bin",b"a"*600);self.write(".gitattributes",b"*.lfs filter=lfs diff=lfs merge=lfs -text\n");self.write("small.lfs",b"x");self.write("nested/.gitignore",b"!stay.tmp\n");self.write("nested/stay.tmp",b"stay")
            self.write("化学[上册].pdf",b"\0"*512)
            config=self.repo.get_config();config.set((b"filter",b"lfs"),b"process",b"must-not-execute");config.set((b"filter",b"lfs"),b"required",b"true");config.write_to_path()
            with patch("subprocess.Popen",side_effect=AssertionError("禁止启动子进程")):self.stage()
            index=self.repo.open_index()
            for name in (b"tracked.tmp",b"keep.tmp",b"select/keep.txt",b"nested/stay.tmp"):self.assertIn(name,index)
            for name in (b"drop.tmp",b"blocked/no.txt",b"select/no.txt",b"ignored-large.bin"):self.assertNotIn(name,index)
            for name in (b"has space.bin",b"small.lfs","化学[上册].pdf".encode()):
                oid,size=pointer_info(self.repo.object_store[index[name].sha].data);self.assertEqual(self.cache.path(oid).stat().st_size,size)
            self.assertEqual(self.stage()[0],[]);(self.root/"tracked.tmp").unlink();self.stage();self.assertNotIn(b"tracked.tmp",self.repo.open_index())
        def test_global_exclude_precedence(self):
            (Path(self.temp.name)/"ignore").write_bytes(b"*.bak\n!special.dat\n");info=Path(self.repo.controldir())/"info";info.mkdir(exist_ok=True);(info/"exclude").write_bytes(b"!keep.bak\nspecial.dat\n");self.write("keep.bak",b"yes");self.write("drop.bak",b"no");self.write("special.dat",b"no");self.stage();index=self.repo.open_index();self.assertIn(b"keep.bak",index);self.assertNotIn(b"drop.bak",index);self.assertNotIn(b"special.dat",index)
        def test_attr_c_quote_and_macro(self):
            self.write(".gitattributes",b"[attr]large filter=lfs -text\n\"/has space.txt\" large\n");self.write("has space.txt",b"a");self.stage();self.assertIsNotNone(pointer_info(self.repo.object_store[self.repo.open_index()[b"has space.txt"].sha].data))
        def test_symlink_does_not_walk_target(self):
            outside=Path(self.temp.name)/"outside";outside.mkdir();(outside/"private.bin").write_bytes(b"x"*1024)
            try:os.symlink(outside,self.root/"link",target_is_directory=True)
            except (OSError,NotImplementedError):self.skipTest("当前系统未授予创建符号链接的权限")
            self.write(".gitignore",b"link/\n");self.stage();index=self.repo.open_index();self.assertEqual(index[b"link"].mode,0o120000);self.assertFalse(any(p.startswith(b"link/") for p in index))
        def test_split_commits_and_local_push(self):
            self.a.max_commit_size=5
            for i in range(3):self.write(f"file{i}",b"abcd")
            commits,_=self.stage();self.assertEqual(len(commits),3);remote=Repo.init_bare(str(Path(self.temp.name)/"bare"),mkdir=True)
            try:
                client=LocalGitClient();result=client.send_pack(remote.path,lambda refs:{b"refs/heads/main":self.repo.head()},self.repo.generate_pack_data);self.assertFalse(any((result.ref_status or {}).values()));self.assertEqual(remote.refs[b"refs/heads/main"],self.repo.head())
            finally:remote.close()
        def test_history_pointer_and_large_blob(self):
            self.write("large.bin",b"q"*600);self.stage();index=self.repo.open_index();oid,size=pointer_info(self.repo.object_store[index[b"large.bin"].sha].data);(self.root/"large.bin").unlink();self.stage();self.assertEqual(outgoing_lfs(self.repo,{},self.repo.head(),self.a)[oid],size)
            self.a.no_auto_lfs=True;self.write("oversize",b"z"*512);self.stage();self.a.max_blob_size=400
            with self.assertRaises(StopPush):outgoing_lfs(self.repo,{},self.repo.head(),self.a)
        def test_git_smart_http_and_idempotent_push(self):
            from dulwich.repo import MemoryRepo
            from dulwich.server import DictBackend
            from dulwich.web import make_wsgi_chain
            from wsgiref.simple_server import make_server,WSGIRequestHandler
            class Quiet(WSGIRequestHandler):
                def log_message(self,*args):pass
            self.write("http-file",b"smart-http");self.stage();remote=MemoryRepo();app=make_wsgi_chain(DictBackend({"/test.git":remote}));server=make_server("127.0.0.1",0,app,handler_class=Quiet);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();url=f"http://127.0.0.1:{server.server_port}/test.git"
            try:
                with patch("subprocess.Popen",side_effect=AssertionError("禁止启动子进程")):
                    for _ in range(2):push_target(self.repo,self.a,url,b"refs/heads/main",self.repo.head(),url+"/info/lfs/objects/batch",{},self.cache,set())
                self.assertEqual(remote.refs[b"refs/heads/main"],self.repo.head())
            finally:server.shutdown();server.server_close();thread.join(timeout=2);remote.close()
        def test_network_retry_http_and_lfs(self):
            counters={};stored={};token="Basic unit-test-secret";test=self
            class Handler(BaseHTTPRequestHandler):
                protocol_version="HTTP/1.1"
                def log_message(self,*args):pass
                def reply(self,code,body,headers=None):
                    self.send_response(code)
                    for k,v in (headers or {}).items():self.send_header(k,v)
                    self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
                def do_GET(self):
                    counters[self.path]=counters.get(self.path,0)+1
                    if self.path=="/flaky" and counters[self.path]==1:self.reply(503,b"retry");return
                    if self.path=="/unauthorized":self.reply(401,b"denied");return
                    if self.path=="/redirect":self.reply(302,b"",{"Location":f"http://localhost:{self.server.server_port}/auth-check"});return
                    if self.path=="/auth-check":self.reply(200,self.headers.get("Authorization","").encode());return
                    self.reply(200,b"ok")
                def do_PUT(self):
                    data=self.rfile.read(int(self.headers["Content-Length"]));stored[hashlib.sha256(data).hexdigest()]=data;counters["put-path"]=self.path;self.reply(200,b"")
                def do_POST(self):
                    data=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    if self.path=="/verify":test.assertEqual(len(stored[data["oid"]]),data["size"]);self.reply(200,b"{}");return
                    objects=[]
                    for item in data["objects"]:
                        item=dict(item)
                        if item["oid"] not in stored:item["actions"]={"upload":{"href":f"http://127.0.0.1:{self.server.server_port}/upload?signature=kept"},"verify":{"href":f"http://127.0.0.1:{self.server.server_port}/verify"}}
                        objects.append(item)
                    self.reply(200,json.dumps({"objects":objects}).encode())
            server=ThreadingHTTPServer(("127.0.0.1",0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f"http://127.0.0.1:{server.server_port}";net=Transport(self.a,{origin(base):token})
            def get(path):
                response=net.request("GET",base+path)
                try:return response.read()
                finally:response.close()
            try:
                self.assertEqual(retry(self.a,"测试重试",lambda:get("/flaky")),b"ok");self.assertEqual(counters["/flaky"],2)
                with self.assertRaises(HTTPFailure):retry(self.a,"测试认证",lambda:get("/unauthorized"))
                self.assertEqual(counters["/unauthorized"],1);self.assertEqual(get("/redirect"),b"");self.write("payload",b"binary"*100);oid,size=pointer_info(self.cache.put(self.root/"payload"));done=set();upload_lfs(net,base+"/batch",{oid:size},self.cache,b"refs/heads/main",done);self.assertIn((oid,size),done);self.assertEqual(stored[oid],b"binary"*100);self.assertEqual(counters["put-path"],"/upload?signature=kept")
            finally:net.close();server.shutdown();server.server_close();thread.join(timeout=2)
        def test_low_speed_watchdog(self):
            class Dummy:
                closed=False
                def shutdown(self,how):self.closed=True
            sock=Dummy();self.a.progress_interval=.01;self.a.low_speed_time=.04;meter=TransferMonitor(sock,self.a,"test");deadline=time.monotonic()+2
            while not sock.closed and time.monotonic()<deadline:time.sleep(.01)
            try:self.assertTrue(sock.closed);self.assertIsNotNone(meter.failure)
            finally:meter.close()
        def test_missing_lfs_cache_and_cli(self):
            with self.assertRaises(StopPush):self.cache.require("0"*64,10)
            a=arguments(["-v","3","-u","push","https://user:ghp_xxxx@github.com/user/repo","--retry","4","-m","hello","world"]);self.assertEqual(a.user,"AUTO");self.assertEqual(a.message,"hello world");self.assertEqual(a.retry,4)
            a=arguments(["--remote=https://github.com/user/repo","--proxy=http://127.0.0.1:8080","push"]);self.assertEqual(a.proxy,"http://127.0.0.1:8080")
        def test_url_and_retry_classification(self):
            url,user,password,_=normalize_remote("https://me:ghp_xxxx@github.com/me/repo");self.assertEqual(url,"https://github.com/me/repo.git");self.assertEqual(password,"ghp_xxxx");self.assertNotIn(password,redact("failure https://me:ghp_xxxx@github.com/me/repo?q=secret"));self.assertFalse(is_retryable(AttributeError("programming error")));self.assertFalse(is_retryable(HTTPFailure(403,url)));self.assertTrue(is_retryable(HTTPFailure(503,url)))
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests));return 0 if result.wasSuccessful() else 1
if __name__=="__main__":
    try:
        a=arguments();setup_logging(a.verbose)
        if a.self_test:setup_logging(0);sys.exit(self_test())
        main(a)
    except KeyboardInterrupt:LOG.warning("用户中断；已创建的提交和 LFS 快照保留，下次可以续推");sys.exit(130)
    except Exception as exc:
        if not LOG.handlers:setup_logging(2)
        LOG.error("失败: %s",exc,exc_info=LOG.isEnabledFor(logging.DEBUG));sys.exit(1)
