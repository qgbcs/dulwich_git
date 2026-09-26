#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dulwich 1.2.15 + Python 标准库全功能 git push。自动暂存/提交/gitignore/gitattributes/LFS/拆分提交/重试/实时连接与速度。不调用外部 git/lfs 进程。"""
from __future__ import annotations
import argparse,base64,hashlib,http.client,inspect,io,json,logging,math,os,re,shutil,socket,ssl,stat,sys,tempfile,threading,time,unittest
from contextlib import contextmanager,suppress
from datetime import datetime,timedelta,timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote,unquote,urljoin,urlsplit,urlunsplit
from urllib.request import getproxies,proxy_bypass
from dulwich.attrs import Pattern as AttrPattern
from dulwich.client import AbstractHttpGitClient,LocalGitClient
from dulwich.errors import GitProtocolError,HangupException,NotGitRepository
from dulwich.ignore import IgnoreFilter,IgnoreFilterManager,default_user_ignore_filter_path
from dulwich.index import IndexEntry,commit_tree,index_entry_from_stat,validate_path,get_path_element_validator
from dulwich.object_store import MemoryObjectStore,iter_tree_contents
from dulwich.objects import Blob,Commit,Tag,Tree
from dulwich.protocol import ZERO_SHA
from dulwich.repo import Repo
_orig_add_thin=getattr(MemoryObjectStore,"add_thin_pack",None) # 1.2.15 MemoryObjectStore.add_thin_pack 无 max_input_size，server.py 仍会传入
if _orig_add_thin and "max_input_size" not in inspect.signature(_orig_add_thin).parameters:
    def _compat_add_thin(self,read_all,read_some,progress=None,**kw):
        return _orig_add_thin(self,read_all,read_some,progress=progress)
    MemoryObjectStore.add_thin_pack=_compat_add_thin
LOG=logging.getLogger("PurePush");SECRETS=set();CHUNK=64*1024
POINTER_PREFIX=b"version https://git-lfs.github.com/spec/v1\n";MEDIA="application/vnd.git-lfs+json";UA="git/2.45.0 purepush-dulwich"
RETRY_HTTP={408,425,429,500,502,503,504}
class StopPush(RuntimeError):pass # 业务致命错误，不重试
class NetworkFailure(RuntimeError):pass # 套接字/超时等可重试
class HTTPFailure(StopPush):
    def __init__(self,code,url,detail="",retry_after=0):
        super().__init__(f"HTTP {code} {safe_url(url)} {detail}");self.code=int(code);self.retry_after=retry_after
def remember(secret):
    if secret and len(str(secret))>3:SECRETS.add(str(secret))
def safe_url(value):
    try:
        p=urlsplit(str(value));host=p.hostname or "";host=f"[{host}]" if ":" in host else host
        return urlunsplit((p.scheme,host+(f":{p.port}" if p.port else ""),p.path,"","")) # 去掉 userinfo 与 query，LFS 签名不进日志
    except ValueError:return "[URL 已隐藏]"
def redact(value):
    t=str(value)
    for s in sorted(SECRETS,key=len,reverse=True):t=t.replace(s,"***")
    t=re.sub(r"https?://[^\s\"'<>]+",lambda m:safe_url(m.group()),t)
    return t.replace("\x1b","\\x1b")
class SafeFormatter(logging.Formatter):
    def format(self,record):return redact(super().format(record))
def setup_logging(v):
    h=logging.StreamHandler(sys.stdout);h.setFormatter(SafeFormatter("%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s","%Y-%m-%d %H:%M:%S"))
    LOG.handlers[:]=[h];LOG.propagate=False;LOG.setLevel({0:logging.ERROR,1:logging.WARNING,2:logging.INFO}.get(v,logging.DEBUG))
def text(v):return v.decode("utf-8","surrogateescape") if isinstance(v,bytes) else str(v)
def cfg(config,section,key,default=b""):
    section=(section,) if isinstance(section,bytes) else tuple(section)
    try:return config.get(section,key)
    except Exception:return default
def yes(config,section,key,default=False):
    try:return config.get_boolean(tuple(section) if not isinstance(section,tuple) else section,key,default)
    except Exception:return default
def human(n):
    n=float(n);units=("B","KiB","MiB","GiB","TiB");i=0
    while n>=1024 and i<len(units)-1:n/=1024;i+=1
    return f"{n:.2f} {units[i]}"
def parse_size(val):
    m=re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmgt]?)(?:i?b)?\s*",str(val),re.I)
    if not m:raise argparse.ArgumentTypeError(f"无法解析大小: {val}")
    return int(float(m[1])*1024**("kmgt".find(m[2].lower())+1 if m[2] else 0))
def stamp():return datetime.now().strftime("%Y-%m-%d__%H.%M.%S__.")+f"{int(time.time()*1000)%1000:03d}"
def origin(url):
    p=urlsplit(url);return p.scheme,p.hostname,p.port or (443 if p.scheme=="https" else 80) # 凭据按 origin 隔离
def basic(user,password):
    if password is None and not user:return None
    if ":" in (user or ""):raise StopPush("Basic 认证用户名不能含冒号")
    val="Basic "+base64.b64encode(f"{user or 'x-access-token'}:{password or ''}".encode()).decode("ascii");remember(val);remember(val[6:]);return val
def looks_like_url(s):return isinstance(s,str) and (s.startswith(("http://","https://","git@")) or "://" in s)
def split_credentials(raw):
    p=urlsplit(raw);user=unquote(p.username) if p.username is not None else None;password=unquote(p.password) if p.password is not None else None
    remember(password);remember(p.password)
    if p.scheme not in ("http","https") or not p.hostname:raise StopPush("仅支持 HTTP(S)；SSH 请改用 https:// 地址")
    host=p.hostname;host=f"[{host}]" if ":" in host else host
    return urlunsplit((p.scheme,host+(f":{p.port}" if p.port else ""),p.path,p.query,"")),user,password
def normalize_remote(raw):
    raw=str(raw).strip().strip("\"'")
    if raw.startswith("git@") and "://" not in raw:host,_,path=raw[4:].partition(":");raw=f"https://{host}/{path}"
    if "://" not in raw:raw="https://github.com/"+raw.lstrip("/")
    clean,user,password=split_credentials(raw);p=urlsplit(clean);branch=None;parts=[x for x in p.path.strip("/").split("/") if x]
    if p.query:raise StopPush("仓库 URL 不应包含查询串")
    if len(parts)<2 or not all(parts[:2]):raise StopPush("远程地址必须包含 owner/repository")
    if len(parts)>2:
        branch=unquote(parts[3] if parts[2] in ("tree","blob") and len(parts)>3 else parts[2]);LOG.warning("网页路径只用于定位仓库，含斜杠的分支请显式 --branch")
    path="/"+ "/".join(parts[:2]);path=path[:-4] if path.endswith(".git") else path
    return urlunsplit((p.scheme,p.netloc,path+".git","","")).rstrip("/"),user,password,branch
def atomic_write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise StopPush(f"拒绝覆盖符号链接: {path}")
    mode=stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644;fd,tmp=tempfile.mkstemp(prefix=".purepush-",dir=str(path.parent))
    try:
        with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,mode);os.replace(tmp,path)
    finally:
        with suppress(FileNotFoundError):os.unlink(tmp)
def signature(st):
    # 教训：L988 比较 st_dev/st_ino/st_ctime_ns，Windows 上 lstat 与 fstat 这些字段经常不一致，误报「读取前文件已经变化」
    ns=getattr(st,"st_mtime_ns",None)
    if ns is None:ns=int(st.st_mtime*1e9)
    return (st.st_size,ns) # git 索引真正稳定的是 size+mtime
@contextmanager
def regular_reader(path):
    path=Path(path);before=path.lstat()
    if not stat.S_ISREG(before.st_mode):raise StopPush(f"不是普通文件，拒绝跟随链接: {path}")
    flags=os.O_RDONLY|getattr(os,"O_BINARY",0)|getattr(os,"O_NOFOLLOW",0)
    try:fd=os.open(str(path),flags)
    except OSError:fd=os.open(str(path),os.O_RDONLY|getattr(os,"O_BINARY",0))
    with os.fdopen(fd,"rb") as f:
        opened=os.fstat(f.fileno())
        if signature(opened)!=signature(before):raise StopPush(f"读取前文件已经变化: {path}")
        yield f,before
        after=os.fstat(f.fileno())
        if signature(after)!=signature(before) or signature(path.lstat())!=signature(before):raise StopPush(f"读取时文件发生变化，请重试: {path}")
def read_regular(path,limit=None):
    with regular_reader(Path(path)) as (f,st):
        if limit is not None and st.st_size>limit:raise StopPush(f"文件过大: {path}")
        return f.read()
def config_bytes(path):
    path=Path(path)
    if path.is_symlink():return b"" # 配置/忽略/属性绝不跟随符号链接
    try:return read_regular(path,8*1024*1024)
    except (FileNotFoundError,NotADirectoryError,PermissionError,OSError):return b""
def init_repo_dir(path):
    # 教训：dulwich 1.2.15 Repo.init(path, mkdir=True) 在目录已存在时 WinError 183；预建 .git 再 init 同样 183；目录不存在则 WinError 3
    path=Path(path);path.mkdir(parents=True,exist_ok=True)
    return Repo.init(str(path)) # mkdir=False：只创建 path/.git，path 必须已存在且其中没有 .git
class SafeIgnore(IgnoreFilterManager):
    def _load_path(self,path):
        if (Path(self._top_path)/path/".gitignore").is_symlink():return None
        return super()._load_path(path)
    def _is_dir(self,path):
        p=Path(self._top_path)/path;return path.endswith("/") or (p.is_dir() and not p.is_symlink())
def ignore_manager(repo,config):
    ignorecase=yes(config,(b"core",),b"ignorecase",os.name=="nt");filters=[]
    default=default_user_ignore_filter_path(config)
    for p in (Path(text(cfg(config,b"core",b"excludesfile",os.fsencode(default) if default else b""))).expanduser(),Path(repo.controldir())/"info"/"exclude"):
        try:filters.append(IgnoreFilter.from_path(str(p),ignorecase)) # 低优先级在前：全局 excludesfile → info/exclude → 各级 .gitignore
        except (FileNotFoundError,NotADirectoryError,OSError):pass
    return SafeIgnore(str(repo.path),filters,ignorecase)
def is_ignored_strict(manager,rel):
    # git 语义：父目录已被忽略时，子路径不能用 ! 重新包含（blocked/ + !blocked/no.txt 仍忽略）
    rel=rel.replace("\\","/").lstrip("/")
    parts=rel.split("/")
    for i in range(1,len(parts)):
        parent="/".join(parts[:i])
        if manager.is_ignored(parent) is True:return True
    return manager.is_ignored(rel) is True
def attr_words(line):
    line=line.strip()
    if not line or line.startswith(b"#"):return None,[]
    if not line.startswith(b'"'):
        w=line.split();return w[0],w[1:]
    out=bytearray();i=1;esc={ord("a"):7,ord("b"):8,ord("t"):9,ord("n"):10,ord("v"):11,ord("f"):12,ord("r"):13,34:34,92:92}
    while i<len(line): # C 引号路径，dulwich 简单 split 无法解析带空格的属性路径
        b=line[i];i+=1
        if b==34:
            if i<len(line) and line[i] not in b" \t":raise StopPush(".gitattributes 引号后缺少空白")
            return bytes(out),line[i:].split()
        if b!=92:out.append(b);continue
        if i>=len(line):break
        b=line[i];i+=1
        if 48<=b<=55:
            digits=bytes([b])
            while len(digits)<3 and i<len(line) and 48<=line[i]<=55:digits+=bytes([line[i]]);i+=1
            v=int(digits,8)
            if v>255:raise StopPush("属性路径的八进制转义超出字节范围")
            out.append(v);continue
        if b in esc:out.append(esc[b]);continue
        raise StopPush(".gitattributes 中存在不支持的 C 转义")
    raise StopPush(".gitattributes 的路径引号没有闭合")
def parse_attribute(token):
    if token[:1]==b"-":return token[1:],False
    if token[:1]==b"!":return token[1:],None
    if b"=" in token:return tuple(token.split(b"=",1))
    return token,True
class Attributes:
    def __init__(self,repo,config,index):
        self.repo=repo;self.root=Path(repo.path);self.index=index;self.cache={}
        default=Path(os.environ.get("XDG_CONFIG_HOME",str(Path.home()/".config")))/"git"/"attributes"
        self.global_path=Path(text(cfg(config,b"core",b"attributesfile",os.fsencode(default)))).expanduser()
        self.info=Path(repo.controldir())/"info"/"attributes"
    def invalidate(self):self.cache.clear()
    def load(self,path,relative=None,macro_allowed=True):
        key=(str(path),macro_allowed)
        if key in self.cache:return self.cache[key]
        data=config_bytes(path)
        if not data and relative is not None and relative in self.index:
            e=self.index[relative]
            if e.mode in (0o100644,0o100755):
                with suppress(KeyError):data=self.repo.object_store[e.sha].data # 工作区缺文件时回退到索引 Blob
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
                except Exception as exc:raise StopPush(f"属性模式无效: {path}: {exc}") from exc
        self.cache[key]=(rules,macros);return rules,macros
    def get(self,rel):
        parts=rel.split(b"/");levels=[(self.global_path,rel,None,True)]
        for i in range(len(parts)):
            name=b"/".join(parts[:i]+[b".gitattributes"]);levels.append((self.root/os.fsdecode(name),b"/".join(parts[i:]),name,i==0))
        levels.append((self.info,rel,None,True))
        loaded=[(self.load(p,key,macro),local) for p,local,key,macro in levels]
        definitions={b"binary":[(b"diff",False),(b"merge",False),(b"text",False)]};result={}
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
    raw=os.fsencode(name.replace("\\","/"));body=b"".join((b"\\"+bytes([c])) if c in b'"\\' else bytes([c]) for c in raw)
    quoted=(b'"/'+body+b'"') if (b" " in raw or b"[" in raw or b"#" in raw or b"*" in raw or b"?" in raw) else (b"/"+body)
    return quoted+b" filter=lfs diff=lfs merge=lfs -text"
def pointer_bytes(oid,size):return POINTER_PREFIX+f"oid sha256:{oid}\nsize {size}\n".encode()
def pointer_info(data):
    if data.startswith(POINTER_PREFIX.rstrip(b"\n")+b"\r\n"):data=data.replace(b"\r\n",b"\n")
    if not data.startswith(POINTER_PREFIX) or len(data)>1024:return None
    oid=size=None
    for line in data.splitlines()[1:]:
        if line.startswith(b"oid sha256:"):oid=line[11:].decode("ascii","replace")
        elif line.startswith(b"size "):
            with suppress(ValueError):size=int(line[5:])
        elif line:return None # 拒绝带扩展字段的指针，避免把指针再当普通文件上传
    if oid and re.fullmatch(r"[0-9a-f]{64}",oid) and size is not None and size>=0:return oid,size
    return None
class LFSCache:
    def __init__(self,repo,config):
        custom=text(cfg(config,b"lfs",b"storage",b"")) if config is not None else ""
        self.root=Path(custom).expanduser() if custom else Path(repo.controldir())/"lfs";self.verified={}
        self.root.mkdir(parents=True,exist_ok=True)
    def path(self,oid):
        if not re.fullmatch(r"[a-f0-9]{64}",oid):raise StopPush("无效的 LFS SHA256")
        return self.root/"objects"/oid[:2]/oid[2:4]/oid
    def put(self,src):
        src=Path(src);tmpdir=self.root/"tmp";tmpdir.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix="purepush-",dir=str(tmpdir));h=hashlib.sha256();size=0;last=time.monotonic()
        try:
            with os.fdopen(fd,"wb") as out,regular_reader(src) as (f,st): # 先读源再写快照，避免 Windows 双句柄干扰
                for block in iter(lambda:f.read(CHUNK),b""):
                    out.write(block);h.update(block);size+=len(block)
                    if time.monotonic()-last>=1:LOG.info("LFS 本地快照: %s | %s/%s",src.name,human(size),human(st.st_size));last=time.monotonic()
                out.flush();os.fsync(out.fileno())
            oid=h.hexdigest();dest=self.path(oid);dest.parent.mkdir(parents=True,exist_ok=True)
            if dest.exists():os.unlink(tmp)
            else:os.replace(tmp,dest)
            self.verified[(oid,size)]=signature(dest.stat());return pointer_bytes(oid,size)
        finally:
            with suppress(FileNotFoundError):os.unlink(tmp)
    def require(self,oid,size):
        p=self.path(oid)
        if not p.is_file() or p.is_symlink():raise StopPush(f"远端需要 LFS {oid[:12]}，本地缓存缺失；恢复原文件后重推，不能只发指针")
        if self.verified.get((oid,size))!=signature(p.stat()):
            h=hashlib.sha256();total=0
            with regular_reader(p) as (f,_):
                for block in iter(lambda:f.read(1024*1024),b""):h.update(block);total+=len(block)
            if total!=size or h.hexdigest()!=oid:raise StopPush(f"LFS 缓存损坏: {oid[:12]}")
            self.verified[(oid,size)]=signature(p.stat())
        if p.stat().st_size!=size:raise StopPush(f"LFS 缓存大小改变: {oid[:12]}")
        return p
def walk_candidates(repo,index,manager,config):
    root=Path(repo.path);tracked=dict(index.items());ignorecase=yes(config,(b"core",),b"ignorecase",os.name=="nt")
    lookup={os.fsdecode(k).casefold():k for k in tracked} if ignorecase else {}
    files={};skipped=0;count=0;last=time.monotonic();validator=get_path_element_validator(config)
    def folded(rel):return os.fsdecode(rel).casefold() if ignorecase else os.fsdecode(rel)
    parents={folded(b"/".join(p.split(b"/")[:i])) for p in tracked for i in range(1,len(p.split(b"/")))}
    def old_key(rel):return rel if rel in tracked else lookup.get(os.fsdecode(rel).casefold())
    def add(path):
        nonlocal skipped,count,last
        rel=os.fsencode(path.relative_to(root).as_posix());old=old_key(rel);count+=1
        if not validate_path(rel,validator):raise StopPush(f"无效 Git 路径: {path}")
        if old is None and is_ignored_strict(manager,os.fsdecode(rel)):skipped+=1;return # 已跟踪路径绕过忽略
        files[rel]=(path,old)
        if time.monotonic()-last>=1:LOG.info("扫描文件: %d | 排除: %d | 当前: %s",count,skipped,os.fsdecode(rel));last=time.monotonic()
    def onerror(error):raise error
    for base,dirs,names in os.walk(str(root),topdown=True,followlinks=False,onerror=onerror):
        current=Path(base);keep=[]
        for name in list(dirs):
            path=current/name;rel=os.fsencode(path.relative_to(root).as_posix())
            if (name.casefold() if os.name=="nt" else name)==".git":continue
            if path.is_symlink():add(path);continue # 目录软链只记自身，绝不跟随进入
            if (path/".git").exists():LOG.warning("跳过嵌套仓库: %s",path);continue
            if getattr(path,"is_junction",lambda:False)() or (os.name=="nt" and os.path.isjunction(str(path))):raise StopPush(f"拒绝遍历 Windows junction: {path}")
            if folded(rel) not in parents and old_key(rel) is None and is_ignored_strict(manager,os.fsdecode(rel)):skipped+=1;continue
            if old_key(rel) is not None and tracked[old_key(rel)].mode==0o160000:add(path);continue
            keep.append(name)
        dirs[:]=keep
        for name in names:
            if (name.casefold() if os.name=="nt" else name)!=".git":add(current/name)
    LOG.info("扫描完成: %d 项 | 未跟踪且被忽略: %d 项",count,skipped);return files
def normalize_blob(data,attrs,old,repo,config,path,renormalize=False):
    if attrs.get(b"working-tree-encoding") not in (None,False):raise StopPush(f"暂不支持 working-tree-encoding: {os.fsdecode(path)}")
    selected=attrs.get(b"filter")
    if selected not in (None,False,True,b"lfs"):raise StopPush(f"不执行外部 filter={text(selected)}: {os.fsdecode(path)}")
    if attrs.get(b"ident") is True:data=re.sub(rb"\$Id:[^$\r\n]*\$",b"$Id$",data)
    text_attr=attrs.get(b"text");eol=attrs.get(b"eol");auto=cfg(config,b"core",b"autocrlf",b"false").lower()
    if text_attr is None and b"crlf" in attrs:text_attr=False if attrs[b"crlf"] is False else True
    if text_attr is False or (text_attr is None and eol is None and auto not in (b"true",b"input")):return data
    automatic=text_attr!=True and not (text_attr is None and eol in (b"lf",b"crlf"))
    nonprint=sum(data.count(bytes([b])) for b in range(32) if b not in (8,9,10,12,13,27))+data.count(b"\x7f")
    if automatic and (b"\0" in data or data.count(b"\r")!=data.count(b"\r\n") or nonprint>(len(data)-nonprint)//128):return data
    if automatic and old is not None and not renormalize and old.mode!=0o160000:
        with suppress(KeyError):
            if b"\r\n" in repo.object_store[old.sha].data:return data
    converted=data.replace(b"\r\n",b"\n");safe=cfg(config,b"core",b"safecrlf",b"false").lower();core_eol=cfg(config,b"core",b"eol",b"native")
    checkout_crlf=eol==b"crlf" or (eol is None and (auto==b"true" or (auto!=b"input" and (core_eol==b"crlf" or (core_eol==b"native" and os.name=="nt")))))
    restored=converted.replace(b"\n",b"\r\n") if checkout_crlf else converted
    if safe in (b"true",b"warn") and restored!=data:
        if safe==b"true":raise StopPush(f"core.safecrlf 拒绝不可逆换行转换: {os.fsdecode(path)}")
        LOG.warning("换行转换不可逆: %s",os.fsdecode(path))
    return converted
def exec_mode(st,old,config):
    fm=yes(config,(b"core",),b"filemode",os.name!="nt")
    if fm and st.st_mode&0o111:return 0o100755
    if not fm and old is not None and old.mode==0o100755:return 0o100755
    return 0o100644
def make_entry(path,sha,mode):
    st=path.lstat() if hasattr(path,"lstat") else os.lstat(str(path))
    try:return index_entry_from_stat(st,sha,mode=mode)
    except TypeError:return index_entry_from_stat(st,sha)
def save_index(index):
    w=getattr(index,"write",None)
    if callable(w):w();return
    from dulwich.file import GitFile
    from dulwich.pack import SHA1Writer
    from dulwich.index import write_index_dict
    f=GitFile(index.path if hasattr(index,"path") else index._filename,"wb")
    try:
        wr=SHA1Writer(f);write_index_dict(wr,dict(index.items()));wr.close()
    except Exception:
        with suppress(Exception):f.abort()
        raise
def stage_all(repo,index,a,config,cache):
    if any(not isinstance(e,IndexEntry) for _,e in index.items()):raise StopPush("索引存在未解决冲突，拒绝自动提交")
    if any(stat.S_ISDIR(e.mode) or getattr(e,"skip_worktree",False) for _,e in index.items()):raise StopPush("稀疏索引或 skip-worktree 不受支持")
    if any(ext.signature[:1].islower() for ext in (getattr(index,"_extensions",[]) or [])):raise StopPush("存在不支持的必需索引扩展，拒绝丢弃其数据")
    manager=ignore_manager(repo,config);files=walk_candidates(repo,index,manager,config);attrs=Attributes(repo,config,index)
    old_entries=dict(index.items());root=Path(repo.path);auto_rules={}
    for rel,(path,oldkey) in list(files.items()):
        st=path.lstat();old=old_entries.get(oldkey) if oldkey is not None else None
        if old is not None and (old.flags&0x8000):continue # assume-unchanged 不改
        if not stat.S_ISREG(st.st_mode):continue
        if getattr(a,"no_auto_lfs",False):continue
        effective=attrs.get(rel)
        if effective.get(b"filter")==b"lfs":continue
        if st.st_size>=a.size:auto_rules[rel]=exact_attr_rule(os.fsdecode(rel)) # 超阈值自动写入精确路径 LFS 规则
    if auto_rules:
        target=root/".gitattributes";existing=config_bytes(target)
        lines=set(existing.splitlines());append=b"".join(rule+b"\n" for rel,rule in sorted(auto_rules.items()) if rule not in lines)
        if append:
            data=existing+(b"" if not existing or existing.endswith(b"\n") else b"\n")+append
            atomic_write(target,data);LOG.info("自动追加 %d 条 LFS 规则到 .gitattributes",append.count(b"\n"))
        attrs.invalidate();files[b".gitattributes"]=(target,b".gitattributes" if b".gitattributes" in old_entries else old_key_safe(old_entries,b".gitattributes"))
    seen=set()
    for rel,(path,oldkey) in list(files.items()):
        st=path.lstat();old=old_entries.get(oldkey) if oldkey is not None else None;seen.add(rel if oldkey is None else oldkey)
        if old is not None and (old.flags&0x8000):continue
        if stat.S_ISLNK(st.st_mode):
            target=os.readlink(str(path));blob=Blob.from_string(os.fsencode(str(target).replace("\\","/")));repo.object_store.add_object(blob)
            index[rel]=make_entry(path,blob.id,0o120000);continue
        if not stat.S_ISREG(st.st_mode):
            if old is not None and old.mode==0o160000:continue
            LOG.warning("跳过非普通文件: %s",path);continue
        effective=attrs.get(rel);use_lfs=effective.get(b"filter")==b"lfs" or (not getattr(a,"no_auto_lfs",False) and st.st_size>=a.size)
        if use_lfs:
            data=cache.put(path)
        else:
            if st.st_size>a.max_blob_size:raise StopPush(f"普通 Blob 超过允许大小: {os.fsdecode(rel)} ({human(st.st_size)})")
            data=normalize_blob(read_regular(path),effective,old,repo,config,rel,getattr(a,"renormalize",False))
        blob=Blob.from_string(data);repo.object_store.add_object(blob)
        if old is not None and old.sha==blob.id and old.mode in (0o100644,0o100755) and not getattr(a,"renormalize",False):
            index[rel]=old;continue # 内容未变保持原索引项
        index[rel]=make_entry(path,blob.id,exec_mode(st,old,config) if not use_lfs else 0o100644)
        if oldkey is not None and oldkey!=rel:
            with suppress(KeyError):del index[oldkey] # 忽略大小写时旧路径键换成规范键
    for rel in list(dict(index.items())):
        if rel not in seen:
            e=index[rel]
            if getattr(e,"skip_worktree",False) or (e.flags&0x8000):continue
            del index[rel] # 工作区消失的已跟踪文件从索引删除
    save_index(index)
def old_key_safe(old_entries,rel):
    return rel if rel in old_entries else None
def check_repo_state(repo,config):
    cd=Path(repo.controldir())
    for name in ("MERGE_HEAD","CHERRY_PICK_HEAD","REBASE_HEAD","REBASE_MERGE","BISECT_LOG"):
        if (cd/name).exists():raise StopPush(f"仓库处于未完成状态 ({name})，拒绝自动提交")
    if yes(config,(b"commit",),b"gpgsign",False):raise StopPush("commit.gpgsign 已启用，本工具不签名提交")
def tz_offset():
    lt=time.localtime()
    if hasattr(lt,"tm_gmtoff") and lt.tm_gmtoff is not None:return int(lt.tm_gmtoff)
    return -int(time.altzone if time.daylight and lt.tm_isdst else time.timezone)
def head_info(repo):
    try:
        chain,sha=repo.refs.follow(b"HEAD");return chain,sha
    except (KeyError,ValueError):
        sym=repo.refs.get_symrefs().get(b"HEAD",b"refs/heads/master");return [b"HEAD",sym],None # unborn 分支不能用 refs[HEAD]
def tree_from_mapping(store,mapping):
    items=[(p,m,s) for p,(m,s) in mapping.items()]
    if not items:return store.add_object(Tree())
    try:return commit_tree(store,items) # 1.2.15 支持 (path, mode, sha) 列表直接建树
    except TypeError:pass
    def build(prefix):
        tree=Tree();subs={}
        for path,mode,sha in items:
            if prefix and not path.startswith(prefix+b"/"):continue
            rest=path[len(prefix)+1:] if prefix else path
            if b"/" in rest:subs[rest.split(b"/",1)[0]]=1
            elif rest:tree.add(rest,mode,sha)
        for sub in subs:
            child=build(prefix+b"/"+sub if prefix else sub);tree.add(sub,0o040000,child)
        return store.add_object(tree)
    return build(b"")
def mapping_from_tree(store,tree_sha):
    out={}
    if not tree_sha:return out
    for item in iter_tree_contents(store,tree_sha):
        if hasattr(item,"path"):out[item.path]=(item.mode,item.sha)
        else:out[item[0]]=(item[1],item[2])
    return out
def commit_object(repo,tree,parents,identity,message):
    c=Commit();c.tree=tree;c.parents=list(parents);c.author=c.committer=identity
    now=int(time.time());off=tz_offset();c.author_time=c.commit_time=now;c.author_timezone=c.commit_timezone=off
    c.encoding=b"UTF-8";c.message=message if isinstance(message,bytes) else message.encode("utf-8")
    repo.object_store.add_object(c);return c.id
def commit_staged(repo,index,a,identity,expected):
    chain,head=expected if isinstance(expected,tuple) else head_info(repo)
    mapping={rel:(e.mode,e.sha) for rel,e in index.items()}
    old_map=mapping_from_tree(repo.object_store,repo.object_store[head].tree) if head else {}
    changed=[]
    for p,v in mapping.items():
        if old_map.get(p)!=v:changed.append((p,repo.object_store[v[1]].raw_length() if hasattr(repo.object_store[v[1]],"raw_length") else len(getattr(repo.object_store[v[1]],"data",b""))))
    for p in old_map:
        if p not in mapping:changed.append((p,0))
    empty_flag=False
    if b"ReadMe.md" in mapping:
        with suppress(Exception):
            if b"#EmptyAfterPush" in repo.object_store[mapping[b"ReadMe.md"][1]].data:empty_flag=True
    if not changed:return [],head,empty_flag
    total=sum(sz for _,sz in changed)
    batches=[]
    if total<=a.max_commit_size:batches=[None] # None 表示一次性提交当前完整索引
    else:
        cur,cs=[],0
        for p,sz in sorted(changed):
            if cur and cs+sz>a.max_commit_size:batches.append(cur);cur,cs=[],0
            cur.append(p);cs+=sz
        if cur:batches.append(cur)
        LOG.warning("暂存约 %s，超过单提交上限 %s，拆成 %d 个提交",human(total),human(a.max_commit_size),len(batches))
    msg=a.message or ""
    if not msg:
        max_p,max_s=None,-1
        for p,sz in changed:
            if sz>max_s:max_s=sz;max_p=p
        msg=(f"[{os.fsdecode(max_p)} {max_s}B] {stamp()} auto" if max_p is not None else f"auto {stamp()}")
    ids=[];parent=head;running=dict(old_map)
    if batches==[None]:
        tree=tree_from_mapping(repo.object_store,mapping);cid=commit_object(repo,tree,[parent] if parent else [],identity,msg);ids.append(cid);parent=cid
    else:
        n=len(batches)
        for i,batch in enumerate(batches,1):
            for p in batch:
                if p in mapping:running[p]=mapping[p]
                else:running.pop(p,None)
            tree=tree_from_mapping(repo.object_store,running)
            part=f"【{i}/{n}】文件数：{len(batch)} {msg}"
            cid=commit_object(repo,tree,[parent] if parent else [],identity,part);ids.append(cid);parent=cid
    target=chain[-1] if chain else b"HEAD"
    if head:
        if not repo.refs.set_if_equals(target,head,ids[-1]):raise StopPush("更新本地分支失败：分支已被其他进程推进")
    else:repo.refs[target]=ids[-1]
    return ids,ids[-1],empty_flag
def prepare(repo,a,identity,cache):
    config=repo.get_config_stack() if hasattr(repo,"get_config_stack") else repo.get_config();check_repo_state(repo,config)
    expected=head_info(repo);index=repo.open_index();stage_all(repo,index,a,config,cache);ids,head,empty=commit_staged(repo,index,a,identity,expected)
    return ids,head,empty
def reachable(store,shas):
    seen=set();q=list(shas)
    while q:
        s=q.pop()
        if s in seen or s in (None,ZERO_SHA):continue
        seen.add(s)
        try:obj=store[s]
        except KeyError:continue
        if isinstance(obj,Commit):q.append(obj.tree);q.extend(obj.parents)
        elif isinstance(obj,Tree):
            for item in obj.items():q.append(item.sha if hasattr(item,"sha") else item[2])
        elif isinstance(obj,Tag):q.append(obj.object[1])
    return seen
def ancestor(repo,old,new):
    if old in (None,ZERO_SHA):return True
    if old==new:return True
    return old in reachable(repo.object_store,[new])
def outgoing_lfs(repo,remote_refs,local_head,a):
    if not local_head:return {}
    have=[s for s in (remote_refs or {}).values() if s and s!=ZERO_SHA and s in repo.object_store]
    missing=reachable(repo.object_store,[local_head])-reachable(repo.object_store,have);objects={}
    for sha in missing:
        obj=repo.object_store[sha]
        if not isinstance(obj,Blob):continue
        info=pointer_info(obj.data)
        if info:objects[info[0]]=info[1]
        elif len(obj.data)>a.max_blob_size:raise StopPush(f"提交历史中存在大于阈值的普通 Blob: {text(sha)[:12]} ({human(len(obj.data))})")
    return objects
def retry_delay(header):
    if not header:return 0
    with suppress(ValueError):return max(0.0,float(header))
    try:
        dt=parsedate_to_datetime(header)
        if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
        return max(0.0,(dt-datetime.now(dt.tzinfo)).total_seconds())
    except Exception:return 0
def is_retryable(exc):
    if isinstance(exc,HTTPFailure):return exc.code in RETRY_HTTP
    if isinstance(exc,(NetworkFailure,TimeoutError,socket.timeout,ConnectionError,HangupException,GitProtocolError,http.client.HTTPException,OSError)):return True
    return False
class TransferMonitor:
    def __init__(self,sock,a,label,total=None):
        self.sock=sock;self.a=a;self.label=label;self.total=total;self.lock=threading.Lock()
        self.sent=0;self.recv=0;self.start=time.monotonic();self.last=self.start;self.last_bytes=0;self.slow=0.0;self.failure=None;self.stopped=threading.Event()
        self.thread=threading.Thread(target=self._run,daemon=True);self.thread.start()
    def add(self,sent=0,recv=0):
        with self.lock:self.sent+=sent;self.recv+=recv
        self.check()
    def _run(self):
        while not self.stopped.wait(max(0.01,self.a.progress_interval)):
            now=time.monotonic()
            with self.lock:sent,recv,last,last_b=self.sent,self.recv,self.last,self.last_bytes
            dt=now-last;moved=(sent+recv)-last_b;speed=moved/dt if dt>0 else 0
            elapsed=now-self.start
            extra=""
            if self.total:extra=f" | 总计 {human(sent)}/{human(self.total)}"+(f" ETA {(self.total-sent)/speed:.0f}s" if speed>0 and sent<self.total else "")
            LOG.info("[%s] ↑ %s (%s/s) ↓ %s (%s/s) | 累计 %.1fs%s",self.label,human(sent),human(speed),human(recv),human(speed if recv else 0),elapsed,extra)
            with self.lock:
                self.last=now;self.last_bytes=sent+recv
                if self.a.low_speed_time>0:
                    if speed<self.a.low_speed_limit:self.slow+=dt
                    else:self.slow=0
                    if self.slow>=self.a.low_speed_time and self.failure is None:
                        self.failure=NetworkFailure(f"{self.label}: 低于 {self.a.low_speed_limit} B/s 持续 {self.slow:.1f}s，主动断开重试")
                        LOG.warning("%s",self.failure)
                        with suppress(Exception):self.sock.shutdown(socket.SHUT_RDWR)
    def check(self):
        if self.failure is not None:raise self.failure
    def close(self):
        self.stopped.set()
        with suppress(RuntimeError):self.thread.join(timeout=1)
class CountingMixin:
    monitor=None
    def send(self,data):
        if self.monitor is not None and isinstance(data,(bytes,bytearray,memoryview)):
            self.monitor.add(sent=len(data));self.monitor.check()
        return super().send(data)
class CountingHTTP(CountingMixin,http.client.HTTPConnection):pass
class CountingHTTPS(CountingMixin,http.client.HTTPSConnection):pass
class CountingReader(io.RawIOBase):
    def __init__(self,raw,monitor):self.raw=raw;self.monitor=monitor
    def readable(self):return True
    def read(self,n=-1):
        data=self.raw.read() if n is None or n<0 else self.raw.read(n)
        if data and self.monitor is not None:self.monitor.add(recv=len(data))
        if self.monitor is not None:self.monitor.check()
        return data
    def readinto(self,b):
        data=self.read(len(b));b[:len(data)]=data;return len(data)
    def close(self):
        with suppress(Exception):self.raw.close()
class FileFeeder:
    def __init__(self,path,size,monitor):self.f=open(path,"rb");self.left=size;self.monitor=monitor;self._len=size
    def read(self,n=CHUNK):
        if self.left<=0:return b""
        data=self.f.read(min(n if n and n>0 else CHUNK,self.left));self.left-=len(data)
        if self.monitor is not None:self.monitor.add(sent=len(data));self.monitor.check()
        return data
    def __len__(self):return self._len
    def close(self):
        with suppress(Exception):self.f.close()
class IterBody:
    def __init__(self,it,monitor):self.it=iter(it);self.buf=b"";self.monitor=monitor # 字节计数交给 CountingMixin.send，避免与 read 重复统计
    def read(self,n=-1):
        if n is None or n<0:
            parts=[self.buf];self.buf=b""
            for chunk in self.it:parts.append(chunk)
            data=b"".join(parts)
            if self.monitor is not None:self.monitor.check()
            return data
        while len(self.buf)<n:
            try:chunk=next(self.it)
            except StopIteration:break
            self.buf+=chunk
        if self.monitor is not None:self.monitor.check()
        out=self.buf[:n];self.buf=self.buf[n:];return out
class _Hdr(dict):
    def __init__(self,pairs):
        super().__init__();self._l={}
        for k,v in pairs:self[k]=v;self._l[k.lower()]=v
    def get(self,key,default=None):
        if key in self:return super().get(key,default)
        return self._l.get(str(key).lower(),default)
class HTTPResp:
    def __init__(self,raw,url,monitor):
        self.status=raw.status;self.headers=_Hdr(raw.getheaders());self.content_type=raw.getheader("Content-Type")
        loc=raw.getheader("Location") or "";self.redirect_location=urljoin(url,loc) if loc else "";self._raw=raw;self._url=url;self._monitor=monitor
        self.fp=CountingReader(raw,monitor)
    def read(self,amt=None):return self.fp.read(-1 if amt is None else amt)
    def close(self):
        with suppress(Exception):self._raw.close()
    def geturl(self):return self._url
    def getheader(self,name,default=None):return self.headers.get(name,default)
class Transport:
    def __init__(self,a,auths=None):
        self.a=a;self.auths=auths or {};self.pool={};self.context=None
    def ssl_context(self):
        if self.context is None:
            ctx=ssl.create_default_context(cafile=getattr(self.a,"ca_file",None)) if getattr(self.a,"ca_file",None) else ssl.create_default_context()
            ctx.minimum_version=ssl.TLSVersion.TLSv1_2;ctx.check_hostname=True;ctx.verify_mode=ssl.CERT_REQUIRED
            with suppress(Exception):ctx.set_alpn_protocols(["http/1.1"])
            self.context=ctx
        return self.context
    def proxy_for(self,url):
        if getattr(self.a,"no_proxy",False):return None
        p=urlsplit(url)
        if getattr(self.a,"proxy",None):return self.a.proxy
        with suppress(Exception):
            if proxy_bypass(p.hostname or ""):return None
        return getproxies().get(p.scheme)
    def connect(self,url,label="HTTP"):
        p=urlsplit(url);key=(p.scheme,p.hostname,p.port,self.proxy_for(url));conn=self.pool.get(key)
        if conn is not None:return conn
        proxy=self.proxy_for(url);timeout=self.a.connect_timeout;started=time.monotonic()
        if proxy:
            pp=urlsplit(proxy);cls=CountingHTTPS if pp.scheme=="https" else CountingHTTP
            conn=cls(pp.hostname,pp.port or (443 if pp.scheme=="https" else 80),timeout=timeout)
            if p.scheme=="https":
                hdrs={"Proxy-Authorization":basic(unquote(pp.username or ""),unquote(pp.password or ""))} if pp.username else None
                conn.set_tunnel(p.hostname,p.port or 443,headers=hdrs)
            conn.connect()
        else:
            cls=CountingHTTPS if p.scheme=="https" else CountingHTTP
            kw={"timeout":timeout}
            if p.scheme=="https":kw["context"]=self.ssl_context()
            conn=cls(p.hostname,p.port or (443 if p.scheme=="https" else 80),**kw);conn.connect()
        conn.sock.settimeout(getattr(self.a,"io_timeout",300))
        with suppress(Exception):conn.sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        peer="";info=""
        with suppress(Exception):peer="%s:%s"%conn.sock.getpeername()[:2]
        if isinstance(conn.sock,ssl.SSLSocket):
            c=conn.sock.cipher() or ("","","") ;cert=conn.sock.getpeercert() or {}
            subject=dict(x[0] for x in cert.get("subject",()) if x)
            info=f" | TLS {conn.sock.version()} {c[0]} | CN={subject.get('commonName','?')} 到期 {cert.get('notAfter','?')}"
        LOG.info("已连接 %s (%s)%s | 耗时 %.0f ms%s",p.hostname,peer,f" 经代理 {safe_url(proxy)}" if proxy else "",(time.monotonic()-started)*1000,info)
        self.pool[key]=conn;return conn
    def drop(self,url):
        p=urlsplit(url);key=(p.scheme,p.hostname,p.port,self.proxy_for(url));conn=self.pool.pop(key,None)
        if conn is not None:
            with suppress(Exception):conn.close()
    def request(self,method,url,headers=None,body=None,label="HTTP",allow_error=False,body_size=None,depth=0):
        if depth>5:raise StopPush("重定向次数过多")
        headers=dict(headers or {});headers.setdefault("User-Agent",UA);headers.setdefault("Accept-Encoding","identity")
        token=self.auths.get(origin(url))
        if token:headers.setdefault("Authorization",token)
        p=urlsplit(url);proxy=self.proxy_for(url)
        target=url if (proxy and p.scheme=="http") else (p.path or "/")+(f"?{p.query}" if p.query else "") # LFS 签名查询串必须原样保留
        conn=self.connect(url,label);meter=TransferMonitor(conn.sock,self.a,label,total=body_size);conn.monitor=meter
        send_body=body;chunked=False
        if isinstance(body,(bytes,bytearray)):headers["Content-Length"]=str(len(body));body_size=len(body);meter.total=body_size
        elif isinstance(body,FileFeeder):headers["Content-Length"]=str(len(body));send_body=body
        elif body is not None and not isinstance(body,(bytes,bytearray)):
            send_body=IterBody(body,meter);chunked=True;headers.pop("Content-Length",None)
        try:
            conn.request(method,target,body=send_body,headers=headers,encode_chunked=chunked)
            raw=conn.getresponse();resp=HTTPResp(raw,url,meter)
            if resp.status in (301,302,303,307,308) and resp.redirect_location:
                loc=resp.redirect_location;resp.close()
                if origin(loc)!=origin(url):headers.pop("Authorization",None) # 跨 origin 不转发凭据
                nxt="GET" if resp.status in (301,302,303) and method!="HEAD" else method
                meter.close();return self.request(nxt,loc,headers,None if nxt=="GET" else body,label,allow_error,body_size,depth+1)
            if not allow_error and resp.status>=400:
                detail=resp.read(600).decode("utf-8","replace");delay=retry_delay(raw.getheader("Retry-After"));resp.close()
                raise HTTPFailure(resp.status,url,detail[:600],delay)
            return resp
        except (HTTPFailure,StopPush):raise
        except Exception as exc:
            self.drop(url);raise NetworkFailure(str(exc)) from exc
        finally:meter.close()
    def close(self):
        for conn in list(self.pool.values()):
            with suppress(Exception):conn.close()
        self.pool.clear()
class StdHttpGitClient(AbstractHttpGitClient):
    def __init__(self,base_url,net):
        super().__init__(base_url=base_url.rstrip("/")+"/") # 仓库路径已含在 base_url
        self.net=net
    def _get_url(self,path):
        return self._base_url # 教训：再把 /test.git 拼进去会变成 test.git/test.git/info/refs
    def _http_request(self,url,headers=None,data=None,raise_for_status=True,**kw):
        resp=self.net.request("GET" if data is None else "POST",url,headers or {},data,"Git HTTP",allow_error=not raise_for_status)
        if raise_for_status and resp.status==404:resp.close();raise NotGitRepository(url)
        if raise_for_status and resp.status!=200:
            detail=resp.read(600).decode("utf-8","replace");delay=retry_delay(resp.getheader("Retry-After"));resp.close()
            raise HTTPFailure(resp.status,url,detail[:600],delay)
        return resp,resp.read
def retry(a,label,operation):
    attempt=0;last=None
    while True:
        try:return operation()
        except Exception as exc:
            last=exc
            if not is_retryable(exc):raise
            attempt+=1
            if attempt>a.retry:raise
            delay=getattr(exc,"retry_after",0) or a.retry_wait*(2**(attempt-1))
            LOG.warning("[%s] %s，%.1fs 后重试 (%d/%d)",label,redact(str(exc)),delay,attempt,a.retry);time.sleep(delay)
def upload_lfs(net,batch_url,objects,cache,ref,done):
    needed=[(oid,size) for oid,size in objects.items() if (oid,size) not in done]
    if not needed:return
    LOG.info("LFS batch: %d 个对象 → %s",len(needed),safe_url(batch_url))
    payload={"operation":"upload","transfers":["basic"],"ref":{"name":text(ref)},"objects":[{"oid":o,"size":s} for o,s in needed]}
    def batch():
        r=net.request("POST",batch_url,{"Content-Type":MEDIA,"Accept":MEDIA},json.dumps(payload).encode(),"LFS Batch")
        try:return json.loads(r.read().decode("utf-8"))
        finally:r.close()
    resp=retry(net.a,"LFS Batch",batch)
    for item in resp.get("objects",[]):
        oid,size=item["oid"],item["size"]
        if item.get("error"):raise StopPush(f"LFS 对象被拒绝: {oid[:12]} {item['error']}")
        actions=item.get("actions") or {}
        if "upload" in actions:
            up=actions["upload"];up_url=up["href"];hdrs=dict(up.get("header") or {}) # href 原样使用，保留 ?signature=
            local=cache.require(oid,size)
            LOG.info("上传 LFS %s (%s)",oid[:12],human(size))
            def put():
                feeder=FileFeeder(str(local),size,None)
                try:
                    r=net.request("PUT",up_url,hdrs,feeder,f"LFS PUT {oid[:8]}",body_size=size)
                    r.read();r.close()
                finally:feeder.close()
            retry(net.a,f"LFS PUT {oid[:8]}",put)
        if "verify" in actions:
            v=actions["verify"];hdrs=dict(v.get("header") or {});hdrs["Content-Type"]=MEDIA
            def verify():
                r=net.request("POST",v["href"],hdrs,json.dumps({"oid":oid,"size":size}).encode(),"LFS Verify");r.read();r.close()
            retry(net.a,f"LFS Verify {oid[:8]}",verify)
        done.add((oid,size))
def lfs_batch_url(repo,config,remote,a,auths):
    if getattr(a,"lfs_url",None):return a.lfs_url.rstrip("/")+("/objects/batch" if not a.lfs_url.rstrip("/").endswith("batch") else "")
    custom=text(cfg(config,(b"lfs",),b"url",b""))
    if custom:return custom.rstrip("/")+"/objects/batch"
    return remote+"/info/lfs/objects/batch"
def push_target(repo,a,remote,ref,head_sha,batch_url,auths,cache,done_lfs,lease=None):
    net=Transport(a,auths)
    try:
        client=StdHttpGitClient(remote,net)
        def attempt():
            def update(refs):
                old=refs.get(ref,ZERO_SHA) or ZERO_SHA
                if old==head_sha:return {ref:head_sha} # 幂等：远端已是同一提交
                if lease is not None and old!=lease:raise StopPush(f"force-with-lease 失败：远端 {text(ref)} 不是期望值")
                if old not in (ZERO_SHA,None) and not getattr(a,"force",False):
                    if old in repo.object_store and not ancestor(repo,old,head_sha):raise StopPush(f"非快进：远端 {text(ref)} 已分叉，需 --force")
                return {ref:head_sha}
            def generate(have,want,ofs_delta=False,progress=None):
                return repo.generate_pack_data(have,want,ofs_delta=ofs_delta,progress=progress)
            def remote_progress(msg):
                if msg:LOG.info("远端: %s",redact(text(msg).strip()))
            result=client.send_pack("/",update,generate,progress=remote_progress,push_options=[v.encode() for v in (getattr(a,"push_option",None) or [])] or None,atomic=getattr(a,"atomic",False))
            status=getattr(result,"ref_status",None) or {}
            err=status.get(ref)
            if err:raise StopPush(f"远端拒绝 {text(ref)}: {err}")
            return result
        def whole():
            refs={}
            with suppress(Exception):
                ls=client.get_refs("/")
                refs=dict(getattr(ls,"refs",None) or ls)
            lfs_objs=outgoing_lfs(repo,refs,head_sha,a)
            if lfs_objs:upload_lfs(net,batch_url,lfs_objs,cache,ref,done_lfs)
            return attempt()
        retry(a,f"推送 {safe_url(remote)} {text(ref)}",whole)
    finally:net.close()
def parse_identity(text_in,default_name,default_email):
    s=(text_in or "").strip()
    if not s:return default_name,default_email
    m=re.match(r"\s*(.+?)\s*[<,]\s*([^>]+)>?\s*$",s)
    if m:return m.group(1).strip(),m.group(2).strip()
    if "@" in s and " " not in s:return default_name,s
    return s,default_email
def identity_for(repo,a,user,remote):
    if getattr(a,"name",None) and getattr(a,"email",None):return f"{a.name} <{a.email}>".encode()
    config=repo.get_config_stack() if hasattr(repo,"get_config_stack") else repo.get_config()
    name=text(cfg(config,b"user",b"name",b""));email=text(cfg(config,b"user",b"email",b""))
    owner=user or (urlsplit(remote).path.strip("/").split("/")[0] if remote else "")
    default_email=f"{owner}@users.noreply.github.com" if owner else "user@localhost"
    if a.user in ("AUTO",True) or (a.user and a.user!="AUTO" and not name):
        name=name or owner or "user";email=email or default_email
    if getattr(a,"name",None):name=a.name
    if getattr(a,"email",None):email=a.email
    if not name or not email:
        if getattr(a,"no_ask",False):name=name or owner or "user";email=email or default_email
        else:
            try:inp=input(f"提交身份 (默认 {name or owner} <{email or default_email}>): ")
            except EOFError:inp=""
            name,email=parse_identity(inp,name or owner or "user",email or default_email)
    ident=f"{name} <{email}>".encode();remember(email);return ident
def preprocess(raw):
    modes={"push"};no_ask={"--noask","-noask","--no-ask","-y","-yes"}
    url_idx={i for i,arg in enumerate(raw) if looks_like_url(arg)};new=[];need_auto=False;i=0
    while i<len(raw):
        arg=raw[i]
        if arg in ("-u","--user","--auto-user"):
            if i+1<len(raw):
                nxt=raw[i+1]
                if (i+1) in url_idx:new.extend(["--user","AUTO","--remote",nxt]);i+=2;continue
                if nxt in no_ask or nxt in modes or nxt.startswith("-"):need_auto=True;i+=1;continue # -u push → AUTO，push 留给 mode
                new.extend(["--user",nxt]);i+=2;continue
            need_auto=True;i+=1;continue
        if arg in ("-m","--commit-msg","--commit_msg","--message"):
            rest=raw[i+1:]
            if rest and not rest[0].startswith("-"):new.extend(["--message"," ".join(rest)]);i=len(raw);continue
            new.append("--message");i+=1;continue
        if looks_like_url(arg):new.extend(["--remote",arg]);i+=1;continue
        new.append(arg);i+=1
    if need_auto:new.extend(["--user","AUTO"])
    return new
def parser():
    p=argparse.ArgumentParser(description="dulwich 1.2.15 纯 Python push")
    p.add_argument("mode",nargs="?",default="push",choices=["push"])
    p.add_argument("--remote",default="")
    p.add_argument("--repo","--repo-path","--path","-path","-p",default=".")
    p.add_argument("--branch","-b",default=os.environ.get("BRANCH"))
    p.add_argument("--user","-u","--auto-user",nargs="?",const="AUTO")
    p.add_argument("--name");p.add_argument("--email")
    p.add_argument("--message","-m","--commit-msg","--commit_msg",default="")
    p.add_argument("--no-ask","--noask","-noask","-y","-yes",action="store_true")
    p.add_argument("--size","-s",type=parse_size,default=100*1024**2)
    p.add_argument("--threshold",type=int,default=0)
    p.add_argument("--max-blob-size",type=parse_size,default=100*1024**2)
    p.add_argument("--max-commit-size",type=parse_size,default=1900*1024**2)
    p.add_argument("--retry","-retry","-r",type=int,default=10)
    p.add_argument("--retry-wait","--retry-seconds",type=float,default=5.0)
    p.add_argument("--verbose","-v",type=int,default=2)
    p.add_argument("--connect-timeout",type=float,default=45.0)
    p.add_argument("--io-timeout",type=float,default=300.0)
    p.add_argument("--low-speed-limit",type=int,default=10)
    p.add_argument("--low-speed-time",type=float,default=60.0)
    p.add_argument("--progress-interval",type=float,default=0.5)
    p.add_argument("--proxy");p.add_argument("--no-proxy",action="store_true");p.add_argument("--ca-file")
    p.add_argument("--lfs-url");p.add_argument("--no-auto-lfs",action="store_true");p.add_argument("--renormalize",action="store_true")
    p.add_argument("--force",action="store_true");p.add_argument("--force-with-lease",nargs="?",const="auto")
    p.add_argument("--push-option",action="append",default=[]);p.add_argument("--atomic",action="store_true")
    p.add_argument("--self-test",action="store_true")
    return p
def arguments(argv=None):
    raw=list(sys.argv[1:] if argv is None else argv);p=parser();a=p.parse_args(preprocess(raw));a.trace=a.verbose>=3
    if a.threshold>0:a.size=a.threshold
    if min(a.size,a.max_blob_size,a.max_commit_size,a.connect_timeout,a.io_timeout,a.progress_interval)<=0:p.error("体积与超时必须 > 0")
    return a
def open_repo(path,a):
    root=Path(path).expanduser().resolve()
    if not root.exists():root.mkdir(parents=True,exist_ok=True)
    gitdir=root/".git"
    if gitdir.exists() or ((root/"HEAD").exists() and (root/"objects").exists()):
        try:return Repo(str(root)),root
        except NotGitRepository as exc:raise StopPush(f"无法打开仓库: {exc}") from exc
    if a.mode=="push":
        LOG.warning("当前目录尚未初始化 Git 仓库: %s",root)
        if not a.no_ask and sys.stdin.isatty():
            ans=input("是否执行 git init 初始化当前目录？[Y/n]: ").strip().lower()
            if ans not in ("","y","yes"):raise StopPush("已取消初始化")
        repo=init_repo_dir(root);LOG.info("已初始化空 Git 仓库");return repo,root
    raise StopPush(f"不是 Git 仓库: {root}")
def main(a=None):
    a=arguments() if a is None else a
    try:ver=__import__("dulwich").__version__
    except Exception:ver="1.2.15"
    LOG.info("Dulwich 版本: %s | 网络: Python 标准库 http.client/socket/ssl",ver)
    repo,root=open_repo(a.repo,a)
    try:
        config=repo.get_config();configured=text(cfg(config,(b"remote",b"origin"),b"url"))
        raw_remote=a.remote or configured
        if not raw_remote:raise StopPush("缺少远程仓库 URL")
        remote,user,password,inferred=normalize_remote(raw_remote)
        if raw_remote!=configured:
            config.set((b"remote",b"origin"),b"url",remote.encode());config.set((b"remote",b"origin"),b"fetch",b"+refs/heads/*:refs/remotes/origin/*");config.write_to_path()
        chain,head_sha=head_info(repo);head_ref=chain[-1] if chain else b"refs/heads/master"
        branch=a.branch or (text(head_ref).removeprefix("refs/heads/") if head_ref.startswith(b"refs/heads/") else (inferred or "master"))
        target_ref=b"refs/heads/"+os.fsencode(branch)
        LOG.info("仓库路径: %s",root);LOG.info("远程地址: %s | 分支: %s",safe_url(remote),branch)
        LOG.info("LFS 阈值: %s | 最大普通 Blob: %s",human(a.size),human(a.max_blob_size))
        LOG.info("连接超时: %.0fs | 低速: %dB/s 持续 %.0fs | 每 %.2fs 输出",a.connect_timeout,a.low_speed_limit,a.low_speed_time,a.progress_interval)
        auths={};token=basic(user,password)
        if token:auths[origin(remote)]=token
        identity=identity_for(repo,a,user,remote);LOG.info("提交身份: %s",text(identity))
        cache=LFSCache(repo,config);ids,current,empty=prepare(repo,a,identity,cache)
        current=current or (repo.head() if head_sha or ids else None)
        if not current or current==ZERO_SHA:raise StopPush("本地分支没有任何提交可供推送")
        batch=lfs_batch_url(repo,config,remote,a,auths);done=set()
        push_target(repo,a,remote,target_ref,current,batch,auths,cache,done)
        if empty:
            p=root/"ReadMe.md"
            if p.is_file() and not p.is_symlink():
                with suppress(OSError):p.write_bytes(b"");LOG.info("EmptyAfterPush: 已清空 ReadMe.md")
        LOG.info("推送成功")
    finally:
        with suppress(Exception):repo.close()
def self_test():
    from unittest.mock import patch
    setup_logging(0)
    class Tests(unittest.TestCase):
        def setUp(self):
            self._env={k:os.environ.get(k) for k in ("HOME","USERPROFILE","XDG_CONFIG_HOME","GIT_CONFIG_GLOBAL","GIT_CONFIG_NOSYSTEM","GIT_CONFIG_SYSTEM")}
            self.temp_dir=tempfile.mkdtemp(prefix="dulwich_push_") # 与 repo_init.py 相同：mkdtemp 得到已存在空目录
            self.addCleanup(self._cleanup)
            os.environ["HOME"]=self.temp_dir;os.environ["USERPROFILE"]=self.temp_dir;os.environ["XDG_CONFIG_HOME"]=self.temp_dir
            os.environ["GIT_CONFIG_NOSYSTEM"]="1";os.environ.pop("GIT_CONFIG_GLOBAL",None);os.environ.pop("GIT_CONFIG_SYSTEM",None)
            self.root=Path(self.temp_dir)/"repo";self.root.mkdir() # 先建工作目录
            self.repo=Repo.init(str(self.root)) # mkdir=False，正确写法；不要预建 .git，不要 mkdir=True
            cfgf=self.repo.get_config()
            none=os.fsencode(str(Path(self.temp_dir)/"none"))
            for sec,key,val in (((b"user",),b"name",b"test"),((b"user",),b"email",b"test@example.com"),((b"core",),b"autocrlf",b"false"),((b"core",),b"safecrlf",b"false"),((b"core",),b"attributesfile",none),((b"core",),b"excludesfile",none),((b"commit",),b"gpgsign",b"false")):cfgf.set(sec,key,val)
            cfgf.write_to_path()
            self.a=arguments(["push","--repo",str(self.root),"--no-ask","-v","0","--progress-interval","0.05","--low-speed-time","0","--size","512","--max-blob-size","1048576","--max-commit-size","1900m","--connect-timeout","5","--retry","3","--retry-wait","0.05","--remote","https://example.invalid/u/r"])
            self.identity=b"test <test@example.com>";self.cache=LFSCache(self.repo,cfgf)
        def _cleanup(self):
            with suppress(Exception):self.repo.close()
            shutil.rmtree(self.temp_dir,ignore_errors=True)
            for k,v in self._env.items():
                if v is None:os.environ.pop(k,None)
                else:os.environ[k]=v
        def write(self,name,data):
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return p
        def stage(self):return prepare(self.repo,self.a,self.identity,self.cache)
        def test_repo_init_windows_and_unborn_head(self):
            git_dir=self.root/".git";self.assertTrue(git_dir.is_dir())
            raw=self.repo.refs.read_ref(b"HEAD");self.assertIn(b"ref: refs/heads/",raw) # unborn：不能用 refs[HEAD]
            self.assertEqual(self.repo.refs.get_symrefs()[b"HEAD"],b"refs/heads/master")
            with self.assertRaises(KeyError):self.repo.refs[b"refs/heads/master"]
            extra=Path(self.temp_dir)/"another";extra.mkdir();r2=Repo.init(str(extra));self.addCleanup(r2.close)
            self.assertTrue((extra/".git").is_dir())
        def test_regular_reader_stable_and_changed(self):
            p=self.write("x.bin",b"hello");self.assertEqual(read_regular(p),b"hello") # Windows 上不应误报变化
            self.assertEqual(signature(os.stat(p)),signature(os.lstat(p)))
            fd=os.open(str(p),os.O_RDONLY|getattr(os,"O_BINARY",0))
            try:self.assertEqual(signature(os.stat(p)),signature(os.fstat(fd)))
            finally:os.close(fd)
            self.assertEqual(config_bytes(self.root/"missing"),b"")
            with self.assertRaises(StopPush):
                with regular_reader(p) as (f,_):
                    f.read();p.write_bytes(b"changed-content-xx")
        def test_gitattributes_reread_after_write(self):
            self.write("big.bin",b"b"*700);self.stage() # 自动写 .gitattributes 后立刻再读，正是 energetic 仓库踩中的路径
            data=(self.root/".gitattributes").read_bytes();self.assertIn(b"filter=lfs",data);self.assertIn(b"big.bin",data)
            self.stage();self.assertEqual(data.count(b"big.bin"),(self.root/".gitattributes").read_bytes().count(b"big.bin"))
        def test_ignore_lfs_delete_and_no_process(self):
            self.write("tracked.tmp",b"old");self.stage();self.write("tracked.tmp",b"new")
            self.write(".gitignore",b"*.tmp\n!keep.tmp\nblocked/\n!blocked/no.txt\nselect/*\n!select/keep.txt\nignored-large.bin\n")
            for n,d in (("drop.tmp",b"drop"),("keep.tmp",b"keep"),("blocked/no.txt",b"no"),("select/keep.txt",b"yes"),("select/no.txt",b"no"),("ignored-large.bin",b"x"*600),("has space.bin",b"a"*600),(".gitattributes",b"*.lfs filter=lfs diff=lfs merge=lfs -text\n"),("small.lfs",b"x"),("nested/.gitignore",b"!stay.tmp\n"),("nested/stay.tmp",b"stay")):self.write(n,d)
            cfgf=self.repo.get_config();cfgf.set((b"filter",b"lfs"),b"process",b"must-not-execute");cfgf.set((b"filter",b"lfs"),b"required",b"true");cfgf.write_to_path()
            with patch("subprocess.Popen",side_effect=AssertionError("禁止启动子进程")):self.stage()
            index=self.repo.open_index()
            for n in (b"tracked.tmp",b"keep.tmp",b"select/keep.txt",b"nested/stay.tmp"):self.assertIn(n,index)
            for n in (b"drop.tmp",b"blocked/no.txt",b"select/no.txt",b"ignored-large.bin"):self.assertNotIn(n,index)
            for n in (b"has space.bin",b"small.lfs"):
                info=pointer_info(self.repo.object_store[index[n].sha].data);self.assertIsNotNone(info,n)
            self.assertEqual(self.stage()[0],[]) # 幂等
            (self.root/"tracked.tmp").unlink();self.stage();self.assertNotIn(b"tracked.tmp",self.repo.open_index())
        def test_global_exclude_precedence(self):
            (Path(self.temp_dir)/"none").write_bytes(b"*.bak\n!special.dat\n")
            info=Path(self.repo.controldir())/"info";info.mkdir(exist_ok=True);(info/"exclude").write_bytes(b"!keep.bak\nspecial.dat\n")
            self.write("keep.bak",b"y");self.write("drop.bak",b"n");self.write("special.dat",b"n");self.stage();index=self.repo.open_index()
            self.assertIn(b"keep.bak",index);self.assertNotIn(b"drop.bak",index);self.assertNotIn(b"special.dat",index)
        def test_attr_c_quote_and_macro(self):
            self.write(".gitattributes",b'[attr]large filter=lfs -text\n"/has space.txt" large\n');self.write("has space.txt",b"a");self.stage()
            self.assertIsNotNone(pointer_info(self.repo.object_store[self.repo.open_index()[b"has space.txt"].sha].data))
            self.assertEqual(attr_words(b'"a\\tb.txt" text')[0],b"a\tb.txt");self.assertEqual(attr_words(b"# comment")[0],None)
            with self.assertRaises(StopPush):attr_words(b'"unterminated text')
        def test_crlf_and_unknown_filter(self):
            self.write(".gitattributes",b"*.txt text\n*.weird filter=magic\n");self.write("a.txt",b"line1\r\nline2\r\n");self.stage()
            self.assertEqual(self.repo.object_store[self.repo.open_index()[b"a.txt"].sha].data,b"line1\nline2\n")
            self.write("b.weird",b"x")
            with self.assertRaises(StopPush):self.stage()
        def test_symlink_does_not_walk_target(self):
            outside=Path(self.temp_dir)/"outside";outside.mkdir();(outside/"private.bin").write_bytes(b"x"*1024)
            try:os.symlink(str(outside),str(self.root/"link"),target_is_directory=True)
            except (OSError,NotImplementedError,AttributeError):self.skipTest("当前系统不允许创建符号链接")
            self.write(".gitignore",b"link/\n");self.stage();index=self.repo.open_index()
            self.assertIn(b"link",index);self.assertEqual(index[b"link"].mode,0o120000);self.assertFalse(any(p.startswith(b"link/") for p in index))
        def test_split_commits_and_local_push(self):
            self.a.max_commit_size=5
            for i in range(3):self.write(f"file{i}",b"abcd")
            commits,head,_=self.stage();self.assertEqual(len(commits),3);self.assertEqual(head,self.repo.head())
            bare=Repo.init_bare(str(Path(self.temp_dir)/"bare"),mkdir=True)
            try:
                res=LocalGitClient().send_pack(bare.path,lambda refs:{b"refs/heads/main":self.repo.head()},self.repo.generate_pack_data)
                self.assertFalse(any((getattr(res,"ref_status",None) or {}).values()));self.assertEqual(bare.refs[b"refs/heads/main"],self.repo.head())
            finally:bare.close()
        def test_history_pointer_and_large_blob(self):
            self.write("large.bin",b"q"*600);self.stage();index=self.repo.open_index();oid,size=pointer_info(self.repo.object_store[index[b"large.bin"].sha].data)
            (self.root/"large.bin").unlink();self.stage();self.assertEqual(outgoing_lfs(self.repo,{},self.repo.head(),self.a)[oid],size)
            self.a.no_auto_lfs=True;self.write("oversize",b"z"*700);self.stage();self.a.max_blob_size=400
            with self.assertRaises(StopPush):outgoing_lfs(self.repo,{},self.repo.head(),self.a)
        def test_git_smart_http_and_idempotent_push(self):
            from dulwich.server import DictBackend
            try:
                from dulwich.web import make_wsgi_app as make_app
            except ImportError:
                from dulwich.web import make_wsgi_chain as make_app
            from wsgiref.simple_server import make_server,WSGIRequestHandler
            class Quiet(WSGIRequestHandler):
                def log_message(self,*args):pass
            self.write("http-file",b"smart-http");self.stage()
            remote=Repo.init_bare(str(Path(self.temp_dir)/"server.git"),mkdir=True) # 必须用磁盘仓库，MemoryRepo.add_thin_pack 不接受 max_input_size
            app=make_app(DictBackend({"test.git":remote}));server=make_server("127.0.0.1",0,app,handler_class=Quiet)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();url=f"http://127.0.0.1:{server.server_port}/test.git"
            try:
                with patch("subprocess.Popen",side_effect=AssertionError("禁止启动子进程")):
                    for _ in range(2):push_target(self.repo,self.a,url,b"refs/heads/main",self.repo.head(),url+"/info/lfs/objects/batch",{},self.cache,set())
                self.assertEqual(remote.refs[b"refs/heads/main"],self.repo.head())
            finally:
                server.shutdown();server.server_close();thread.join(timeout=5);remote.close()
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
            server=ThreadingHTTPServer(("127.0.0.1",0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f"http://127.0.0.1:{server.server_port}";net=Transport(self.a,{origin(base):token})
            def get(path):
                r=net.request("GET",base+path)
                try:return r.read()
                finally:r.close()
            try:
                self.assertEqual(retry(self.a,"测试重试",lambda:get("/flaky")),b"ok");self.assertEqual(counters["/flaky"],2)
                with self.assertRaises(HTTPFailure):retry(self.a,"测试认证",lambda:get("/unauthorized"))
                self.assertEqual(counters["/unauthorized"],1);self.assertEqual(get("/redirect"),b"") # localhost vs 127.0.0.1 不带 Authorization
                self.write("payload",b"binary"*100);oid,size=pointer_info(self.cache.put(self.root/"payload"));done=set()
                upload_lfs(net,base+"/batch",{oid:size},self.cache,b"refs/heads/main",done)
                self.assertIn((oid,size),done);self.assertEqual(stored[oid],b"binary"*100);self.assertEqual(counters["put-path"],"/upload?signature=kept")
                upload_lfs(net,base+"/batch",{oid:size},self.cache,b"refs/heads/main",done)
            finally:net.close();server.shutdown();server.server_close();thread.join(timeout=5)
        def test_low_speed_watchdog(self):
            class Dummy:
                closed=False
                def shutdown(self,how):self.closed=True
            sock=Dummy();self.a.progress_interval=.01;self.a.low_speed_time=.05;self.a.low_speed_limit=10
            meter=TransferMonitor(sock,self.a,"test");deadline=time.monotonic()+3
            while not sock.closed and time.monotonic()<deadline:time.sleep(.01)
            try:self.assertTrue(sock.closed);self.assertIsNotNone(meter.failure);self.assertTrue(is_retryable(meter.failure))
            finally:meter.close()
        def test_missing_lfs_cache_and_cli(self):
            with self.assertRaises(StopPush):self.cache.require("0"*64,10)
            a=arguments(["-v","3","-u","push","https://user:ghp_xxxx@github.com/user/repo","--retry","4","-m","hello","world"])
            self.assertEqual(a.user,"AUTO");self.assertEqual(a.message,"hello world");self.assertEqual(a.retry,4);self.assertEqual(a.mode,"push")
            a=arguments(["--remote=https://github.com/user/repo","--proxy=http://127.0.0.1:8080","push"]);self.assertEqual(a.proxy,"http://127.0.0.1:8080")
        def test_url_and_retry_classification(self):
            url,user,password,_=normalize_remote("https://me:ghp_xxxx@github.com/me/repo")
            self.assertEqual(url,"https://github.com/me/repo.git");self.assertEqual(password,"ghp_xxxx")
            self.assertNotIn(password,redact("failure https://me:ghp_xxxx@github.com/me/repo?q=secret"))
            self.assertEqual(normalize_remote("git@github.com:me/repo.git")[0],"https://github.com/me/repo.git")
            self.assertEqual(normalize_remote("https://github.com/me/repo/tree/dev")[3],"dev")
            self.assertFalse(is_retryable(AttributeError("programming error")));self.assertFalse(is_retryable(HTTPFailure(403,url)));self.assertTrue(is_retryable(HTTPFailure(503,url)))
            self.assertEqual(parse_size("2k"),2048);self.assertEqual(parse_identity("Tom, tom@a.com","d","d@a"),("Tom","tom@a.com"))
        def test_pointer_helpers(self):
            data=pointer_bytes("a"*64,123);self.assertEqual(pointer_info(data),("a"*64,123));self.assertIsNone(pointer_info(b"not a pointer"))
            self.assertIn(b'"/a b.bin"',exact_attr_rule("a b.bin"));self.assertIn(b"/plain.bin filter=lfs",exact_attr_rule("plain.bin"))
        def test_repo_state_guards(self):
            (Path(self.repo.controldir())/"MERGE_HEAD").write_bytes(b"x")
            with self.assertRaises(StopPush):self.stage()
            (Path(self.repo.controldir())/"MERGE_HEAD").unlink()
        def test_readme_empty_after_push(self):
            self.write("ReadMe.md",b"# Demo\n\n#EmptyAfterPush\n");ids,head,empty=self.stage();self.assertTrue(empty)
        def test_ancestor_and_ff(self):
            self.write("a",b"1");c1=self.stage()[1];self.write("a",b"2");c2=self.stage()[1]
            self.assertTrue(ancestor(self.repo,c1,c2));self.assertFalse(ancestor(self.repo,c2,c1));self.assertTrue(ancestor(self.repo,ZERO_SHA,c2))
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests));return 0 if result.wasSuccessful() else 1
if __name__=="__main__":
    try:
        with suppress(Exception):
            for st in (sys.stdout,sys.stderr):st.reconfigure(errors="replace")
        a=arguments();setup_logging(a.verbose)
        if a.self_test:setup_logging(0);sys.exit(self_test())
        main(a)
    except KeyboardInterrupt:
        LOG.warning("用户中断；已创建的提交和 LFS 快照保留，下次可以续推");sys.exit(130)
    except StopPush as exc:
        if not LOG.handlers:setup_logging(2)
        LOG.error("失败: %s",exc);sys.exit(1)
    except Exception as exc:
        if not LOG.handlers:setup_logging(2)
        LOG.error("失败: %s",exc,exc_info=LOG.isEnabledFor(logging.DEBUG));sys.exit(1)
'''


C:\Users\Administrator\Documents\energetic>C:\QGB\anaconda3\python D:\test\github\dulwich_git\L1129.py --self-test
test_ancestor_and_ff (__main__.self_test.<locals>.Tests.test_ancestor_and_ff) ... usage: L1129.py [-h] [--remote REMOTE] [--repo REPO] [--branch BRANCH] [--user [USER]] [--name NAME] [--email EMAIL] [--message MESSAGE] [--no-ask] [--size SIZE]
                [--threshold THRESHOLD] [--max-blob-size MAX_BLOB_SIZE] [--max-commit-size MAX_COMMIT_SIZE] [--retry RETRY] [--retry-wait RETRY_WAIT]
                [--verbose VERBOSE] [--connect-timeout CONNECT_TIMEOUT] [--io-timeout IO_TIMEOUT] [--low-speed-limit LOW_SPEED_LIMIT]
                [--low-speed-time LOW_SPEED_TIME] [--progress-interval PROGRESS_INTERVAL] [--proxy PROXY] [--no-proxy] [--ca-file CA_FILE] [--lfs-url LFS_URL]
                [--no-auto-lfs] [--renormalize] [--force] [--force-with-lease [FORCE_WITH_LEASE]] [--push-option PUSH_OPTION] [--atomic] [--self-test]
                [{push}]
L1129.py: error: argument --remote: expected one argument
ERROR
test_attr_c_quote_and_macro (__main__.self_test.<locals>.Tests.test_attr_c_quote_and_macro) ... usage: L1129.py [-h] [--remote REMOTE] [--repo REPO] [--branch BRANCH] [--user [USER]] [--name NAME] [--email EMAIL] [--message MESSAGE] [--no-ask] [--size SIZE]
                [--threshold THRESHOLD] [--max-blob-size MAX_BLOB_SIZE] [--max-commit-size MAX_COMMIT_SIZE] [--retry RETRY] [--retry-wait RETRY_WAIT]
                [--verbose VERBOSE] [--connect-timeout CONNECT_TIMEOUT] [--io-timeout IO_TIMEOUT] [--low-speed-limit LOW_SPEED_LIMIT]
                [--low-speed-time LOW_SPEED_TIME] [--progress-interval PROGRESS_INTERVAL] [--proxy PROXY] [--no-proxy] [--ca-file CA_FILE] [--lfs-url LFS_URL]
                [--no-auto-lfs] [--renormalize] [--force] [--force-with-lease [FORCE_WITH_LEASE]] [--push-option PUSH_OPTION] [--atomic] [--self-test]
                [{push}]
L1129.py: error: argument --remote: expected one argument
ERROR
test_crlf_and_unknown_filter (__main__.self_test.<locals>.Tests.test_crlf_and_unknown_filter) ... usage: L1129.py [-h] [--remote REMOTE] [--repo REPO] [--branch BRANCH] [--user [USER]] [--name NAME] [--email EMAIL] [--message MESSAGE] [--no-ask] [--size SIZE]
                [--threshold THRESHOLD] [--max-blob-size MAX_BLOB_SIZE] [--max-commit-size MAX_COMMIT_SIZE] [--retry RETRY] [--retry-wait RETRY_WAIT]
                [--verbose VERBOSE] [--connect-timeout CONNECT_TIMEOUT] [--io-timeout IO_TIMEOUT] [--low-speed-limit LOW_SPEED_LIMIT]
                [--low-speed-time LOW_SPEED_TIME] [--progress-interval PROGRESS_INTERVAL] [--proxy PROXY] [--no-proxy] [--ca-file CA_FILE] [--lfs-url LFS_URL]
                [--no-auto-lfs] [--renormalize] [--force] [--force-with-lease [FORCE_WITH_LEASE]] [--push-option PUSH_OPTION] [--atomic] [--self-test]
                [{push}]
L1129.py: error: argument --remote: expected one argument
ERROR



======================================================================
ERROR: test_url_and_retry_classification (__main__.self_test.<locals>.Tests.test_url_and_retry_classification)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "C:\QGB\anaconda3\Lib\argparse.py", line 1931, in parse_known_args
    namespace, args = self._parse_known_args(args, namespace)
                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\argparse.py", line 2168, in _parse_known_args
    start_index = consume_optional(start_index)
                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\argparse.py", line 2089, in consume_optional
    arg_count = match_argument(action, selected_patterns)
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\argparse.py", line 2264, in _match_argument
    raise ArgumentError(action, msg)
argparse.ArgumentError: argument --remote: expected one argument

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1129.py", line 939, in setUp
    self.a=arguments(["push","--repo",str(self.root),"--no-ask","-v","0","--progress-interval","0.05","--low-speed-time","0","--size","512","--max-blob-size","1048576","--max-commit-size","1900m","--connect-timeout","5","--retry","3","--retry-wait","0.05","--remote","https://example.invalid/u/r"])
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1129.py", line 871, in arguments
    raw=list(sys.argv[1:] if argv is None else argv);p=parser();a=p.parse_args(preprocess(raw));a.trace=a.verbose>=3
                                                                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\argparse.py", line 1895, in parse_args
    args, argv = self.parse_known_args(args, namespace)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\argparse.py", line 1933, in parse_known_args
    self.error(str(err))
  File "C:\QGB\anaconda3\Lib\argparse.py", line 2672, in error
    self.exit(2, _('%(prog)s: error: %(message)s\n') % args)
  File "C:\QGB\anaconda3\Lib\argparse.py", line 2659, in exit
    _sys.exit(status)
SystemExit: 2

----------------------------------------------------------------------
Ran 19 tests in 4.927s

FAILED (errors=19)


'''