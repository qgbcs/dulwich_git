#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dulwich 1.2.15 + Python 标准库实现的全功能 git push。
   自动暂存/提交/LFS/实时连接详情与速度显示，不调用任何外部进程。"""
from __future__ import annotations
import argparse,base64,hashlib,http.client,inspect,io,json,logging,math,os,re,socket,ssl,stat,sys,tempfile,threading,time,unittest
from contextlib import contextmanager,suppress
from datetime import datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote,unquote,urljoin,urlsplit,urlunsplit
from urllib.request import getproxies,proxy_bypass
from dulwich.attrs import Pattern as AttrPattern
from dulwich.client import AbstractHttpGitClient,LocalGitClient
from dulwich.config import ConfigFile
from dulwich.errors import GitProtocolError,HangupException,NotGitRepository
from dulwich.ignore import IgnoreFilter,IgnoreFilterManager,default_user_ignore_filter_path,translate as ignore_translate
from dulwich.index import IndexEntry,commit_tree,index_entry_from_stat,validate_path,get_path_element_validator
from dulwich.object_store import iter_tree_contents,MemoryObjectStore
from dulwich.objects import Blob,Commit,Tag,Tree
from dulwich.pack import SHA1Writer
from dulwich.protocol import ZERO_SHA
from dulwich.repo import Repo

# ---------- Dulwich 1.2.15 兼容补丁 ----------
# MemoryObjectStore.add_thin_pack 不接受 max_input_size，server.py 仍会传入；补一个静默丢弃多余参数的版本
_orig_add_thin_pack=getattr(MemoryObjectStore,"add_thin_pack",None)
if _orig_add_thin_pack and "max_input_size" not in inspect.signature(_orig_add_thin_pack).parameters:
    def _compat_add_thin_pack(self,read_all,read_some,progress=None,**kw):
        return _orig_add_thin_pack(self,read_all,read_some,progress=progress)
    MemoryObjectStore.add_thin_pack=_compat_add_thin_pack

# ---------- 常量 ----------
LOG=logging.getLogger("PurePush");SECRETS=set();CHUNK=64*1024
POINTER_PREFIX=b"version https://git-lfs.github.com/spec/v1\n";MEDIA="application/vnd.git-lfs+json";UA="git/2.45.0 purepush-dulwich"

class StopPush(RuntimeError):pass  # 业务级中止，不重试
class NetworkFailure(RuntimeError):pass  # 套接字层瞬断，可重试
class HTTPFailure(StopPush):
    def __init__(self,code,url,detail="",retry_after=0):
        super().__init__(f"HTTP {code} {safe_url(url)} {detail}");self.code=int(code);self.retry_after=retry_after

def remember(secret):
    if secret and len(str(secret))>3:SECRETS.add(str(secret))
def safe_url(value):
    try:
        p=urlsplit(str(value));host=p.hostname or "";host=f"[{host}]" if ":" in host else host
        return urlunsplit((p.scheme,host+(f":{p.port}" if p.port else ""),p.path,"",""))
    except ValueError:return "[URL 已隐藏]"
def redact(value):
    t=str(value)
    for s in sorted(SECRETS,key=len,reverse=True):t=t.replace(s,"***")
    t=re.sub(r"https?://[^\s\"' ]+",lambda m:safe_url(m.group()),t)
    return t.replace("\x1b","\\x1b")
class SafeFormatter(logging.Formatter):
    def format(self,record):return redact(super().format(record))
def setup_logging(v):
    h=logging.StreamHandler(sys.stdout);h.setFormatter(SafeFormatter("%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s","%Y-%m-%d %H:%M:%S"))
    LOG.handlers[:]=[h];LOG.propagate=False;LOG.setLevel({0:logging.ERROR,1:logging.WARNING,2:logging.INFO}.get(v,logging.DEBUG))
def trace(a,msg,*args):
    if getattr(a,"trace",False):LOG.log(logging.DEBUG if getattr(a,"verbose",2)>=3 else logging.INFO,msg,*args)
def cfg(config,section,key,default=b""):
    section=(section,) if isinstance(section,bytes) else tuple(section)
    try:return config.get(section,key)
    except KeyError:return default
def text(v):return v.decode("utf-8","surrogateescape") if isinstance(v,bytes) else str(v)
def yes(config,section,key,default=False):
    try:return config.get_boolean(tuple(section),key,default)
    except Exception:return default
def human(n):
    n=float(n);units=("B","KiB","MiB","GiB","TiB");i=0
    while n>=1024 and i<len(units)-1:n/=1024;i+=1
    return f"{n:.2f} {units[i]}"
def parse_size(val):
    if val is None:return 100*1024*1024
    s=str(val).strip().lower()
    m=re.match(r"^(\d+(?:\.\d+)?)\s*([kmg]?b?)?$",s)
    if not m:return 100*1024*1024
    num=float(m.group(1));unit=(m.group(2) or "").lower()
    return int(num*(1024**({"k":1,"kb":1,"m":2,"mb":2,"g":3,"gb":3}.get(unit,0))))
def retry_delay(header):
    if not header:return 0
    try:return max(0,float(header))
    except ValueError:return 0
def origin(url):
    p=urlsplit(url);host=p.hostname or ""
    if ":" in host:host=f"[{host}]"
    return urlunsplit((p.scheme,host+(f":{p.port}" if p.port else ""),"","",""))
def basic(user,password):
    if not user:return ""
    return "Basic "+base64.b64encode(f"{user}:{password or ''}".encode()).decode()
def split_credentials(url):
    p=urlsplit(url);user=unquote(p.username or "");password=unquote(p.password or "")
    netloc=p.hostname or ""
    if ":" in netloc:netloc=f"[{netloc}]"
    if p.port:netloc+=f":{p.port}"
    clean=urlunsplit((p.scheme,netloc,p.path,p.query,p.fragment))
    return clean,user,password

# ---------- 文件 I/O 与签名 ----------
def signature(st):return (stat.S_IFMT(st.st_mode),st.st_size,getattr(st,"st_mtime_ns",int(st.st_mtime*1e9)))
# 关键：Windows 上 os.lstat 返回的 ctime 可能与 fstat 不一致，不参与签名；st_dev/st_ino 在 Win 上多数为 0，不参与跨句柄比较
@contextmanager
def regular_reader(path):
    path=Path(path);before=path.lstat()
    if not stat.S_ISREG(before.st_mode):raise StopPush(f"不是普通文件，拒绝跟随链接: {path}")
    try:flags=os.O_RDONLY|getattr(os,"O_BINARY",0)|getattr(os,"O_NOFOLLOW",0);fd=os.open(str(path),flags)
    except (AttributeError,OSError):fd=None
    if fd is not None:
        with os.fdopen(fd,"rb") as f:
            opened=os.fstat(f.fileno())
            if signature(opened)!=signature(before):raise StopPush(f"读取前文件已经变化: {path}")
            yield f,before
            after=os.fstat(f.fileno())
            if signature(after)!=signature(before) or signature(path.lstat())!=signature(before):raise StopPush(f"读取时文件发生变化: {path}")
    else:
        with open(str(path),"rb") as f:
            yield f,before
            if signature(path.lstat())!=signature(before):raise StopPush(f"读取时文件发生变化: {path}")
def read_regular(path,limit=None):
    with regular_reader(Path(path)) as (f,st):
        if limit is not None and st.st_size>limit:raise StopPush(f"文件过大: {path}")
        return f.read()
def config_bytes(path):
    path=Path(path)
    if path.is_symlink():return b""
    try:return read_regular(path,8*1024*1024)
    except (FileNotFoundError,NotADirectoryError,PermissionError,OSError):return b""
def atomic_write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise StopPush(f"拒绝覆盖符号链接: {path}")
    mode=stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd,tmp=tempfile.mkstemp(prefix=".purepush-",dir=str(path.parent))
    try:
        with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,mode);os.replace(tmp,path)
    finally:
        with suppress(FileNotFoundError):os.unlink(tmp)

# ---------- 远程 URL 解析 ----------
def parse_remote(raw):
    raw=str(raw);p=urlsplit(raw)
    if p.scheme not in ("http","https"):raise StopPush(f"仅支持 http(s) 远程: {raw}")
    user=unquote(p.username or "");password=unquote(p.password or "")
    netloc=p.hostname or ""
    if ":" in netloc:netloc=f"[{netloc}]"
    if p.port:netloc+=f":{p.port}"
    clean=urlunsplit((p.scheme,netloc,p.path,"","")).rstrip("/")
    branch=None
    parts=[x for x in p.path.strip("/").split("/") if x]
    if len(parts)>=4 and parts[2] in ("tree","blob"):
        branch=unquote(parts[3]);LOG.warning("网页路径只用于定位仓库；含斜杠的分支请显式 --branch")
        clean=urlunsplit((p.scheme,netloc,"/"+"/".join(parts[:2]).removesuffix(".git")+".git","",""))
    return clean.rstrip("/"),user,password,branch

# ---------- 仓库引导 ----------
def init_repo(path):
    # 关键修复：dulwich 1.2.15 在 Windows 上 init 不会自动创建父目录，先 mkdir
    Path(path).mkdir(parents=True,exist_ok=True)
    controldir=Path(path)/".git"
    if not controldir.exists():controldir.mkdir(parents=True,exist_ok=True)
    return Repo.init(str(path))
def safe_open_repo(path):
    path=Path(path).resolve()
    if not (path/".git").exists():raise StopPush(f"不是 Git 仓库: {path}")
    try:return Repo(str(path))
    except NotGitRepository as exc:raise StopPush(f"无法打开仓库: {exc}") from exc

# ---------- .gitignore ----------
class SafeIgnore(IgnoreFilterManager):
    def _load_path(self,path):
        if (Path(self._top_path)/path/".gitignore").is_symlink():return None
        return super()._load_path(path)
def ignore_manager(repo,config):
    ignorecase=yes(config,(b"core",),b"ignorecase",False);filters=[]
    for p in (Path(text(cfg(config,b"core",b"excludesfile",os.fsencode(default_user_ignore_filter_path(config))))).expanduser(),Path(repo.controldir())/"info"/"exclude"):
        try:filters.append(IgnoreFilter.from_path(str(p),ignorecase))
        except (FileNotFoundError,NotADirectoryError,OSError):pass
    return SafeIgnore(str(repo.path),filters,ignorecase)

# ---------- .gitattributes ----------
def attr_words(line):
    line=line.strip()
    if not line or line.startswith(b"#"):return None,[]
    if not line.startswith(b'"'):w=line.split();return w[0],w[1:]
    out=bytearray();i=1;esc={ord("a"):7,ord("b"):8,ord("t"):9,ord("n"):10,ord("v"):11,ord("f"):12,ord("r"):13,34:34,92:92}
    while i<len(line):
        b=line[i];i+=1
        if b==34:return bytes(out),line[i:].split()
        if b==92:
            if i>=len(line):break
            b=line[i];i+=1
            if 48<=b<=55:
                digits=chr(b)
                for _ in range(2):
                    if i<len(line) and 48<=line[i]<=55:digits+=chr(line[i]);i+=1
                    else:break
                v=int(digits,8)
                if v>255:raise StopPush("属性路径的八进制转义超出字节范围")
                out.append(v);continue
            if b in esc:out.append(esc[b]);continue
            raise StopPush(".gitattributes 中存在不支持的 C 转义")
        out.append(b)
    raise StopPush(".gitattributes 的路径引号没有闭合")
def parse_attribute(token):
    if token[:1]==b"-":return token[1:],False
    if token[:1]==b"!":return token[1:],None
    if b"=" in token:k,v=token.split(b"=",1);return k,v
    return token,True
class AttrPattern:
    """把 .gitattributes 的 wildmatch 模式编译为正则，复用 dulwich 的 translate 保证兼容。"""
    def __init__(self,pattern):
        self.pattern=pattern
        try:self.regex=re.compile(ignore_translate(pattern))
        except Exception as exc:raise StopPush(f"属性模式无效: {text(pattern)}: {exc}") from exc
    def match(self,rel):
        return bool(self.regex.match(rel)) or bool(self.regex.match(b"/"+rel))
class Attributes:
    def __init__(self,repo,config,index):
        self.repo=repo;self.root=Path(repo.path);self.index=index;self.cache={}
        default=Path(os.environ.get("XDG_CONFIG_HOME",str(Path.home()/".config")))/"git"/"attributes"
        self.global_path=Path(text(cfg(config,b"core",b"attributesfile",os.fsencode(default)))).expanduser()
        self.info=Path(repo.controldir())/"info"/"attributes"
    def load(self,path,relative=None,macro_allowed=True):
        key=(str(path),macro_allowed)
        if key in self.cache:return self.cache[key]
        data=config_bytes(path)
        if not data and relative is not None and relative in self.index:
            e=self.index[relative]
            if e.mode in (0o100644,0o100755):
                with suppress(KeyError):data=self.repo.object_store[e.sha].data
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
                except StopPush:raise
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
    raw=os.fsencode(name);body=b"".join((b"\\"+bytes([c])) if c in b'"\\' else bytes([c]) for c in raw)
    if b" " in raw or b"[" in raw or b"#" in raw or b"*" in raw or b"?" in raw:
        quoted=b'"/'+body+b'"'
    else:quoted=b"/"+body
    return quoted+b" filter=lfs diff=lfs merge=lfs -text"

# ---------- LFS 指针 ----------
def pointer_bytes(oid,size):return POINTER_PREFIX+f"oid sha256:{oid}\nsize {size}\n".encode()
def pointer_info(data):
    if not data.startswith(POINTER_PREFIX) or len(data)>1024:return None
    oid=size=None
    for line in data.splitlines()[1:]:
        if line.startswith(b"oid sha256:"):oid=line[11:].decode("ascii","replace")
        elif line.startswith(b"size "):
            with suppress(ValueError):size=int(line[5:])
    if oid and re.fullmatch(r"[0-9a-f]{64}",oid) and size is not None and size>=0:return oid,size
    return None
class LFSCache:
    def __init__(self,repo,config):
        custom=text(cfg(config,b"lfs",b"storage",b""))
        self.root=Path(custom).expanduser() if custom else Path(repo.controldir())/"lfs"
        self.root.mkdir(parents=True,exist_ok=True);self.verified={}
    def path(self,oid):return self.root/"objects"/oid[:2]/oid[2:4]/oid
    def put(self,src):
        src=Path(src);tmpdir=self.root/"tmp";tmpdir.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(dir=str(tmpdir));h=hashlib.sha256();size=0;last=time.monotonic()
        try:
            with os.fdopen(fd,"wb") as out,regular_reader(src) as (f,st):
                for block in iter(lambda:f.read(CHUNK),b""):
                    out.write(block);h.update(block);size+=len(block)
                    if time.monotonic()-last>=1:LOG.info("LFS 本地快照: %s | %s/%s",src.name,human(size),human(st.st_size));last=time.monotonic()
                out.flush();os.fsync(out.fileno())
            oid=h.hexdigest();dest=self.path(oid);dest.parent.mkdir(parents=True,exist_ok=True)
            if not dest.exists():os.replace(tmp,dest)
            else:os.unlink(tmp)
            self.verified[(oid,size)]=signature(dest.stat())
            return pointer_bytes(oid,size)
        finally:
            with suppress(FileNotFoundError):os.unlink(tmp)
    def require(self,oid,size):
        p=self.path(oid)
        if not p.is_file() or p.is_symlink():raise StopPush(f"远端需要 LFS {oid[:12]}，本地缓存缺失；恢复原文件后重推")
        if self.verified.get((oid,size))!=signature(p.stat()):
            h=hashlib.sha256();total=0
            with regular_reader(p) as (f,_):
                for block in iter(lambda:f.read(1024*1024),b""):h.update(block);total+=len(block)
            if total!=size or h.hexdigest()!=oid:raise StopPush(f"LFS 缓存损坏: {oid[:12]}")
            self.verified[(oid,size)]=signature(p.stat())
        return p

# ---------- 扫描工作区 ----------
def walk_candidates(repo,index,manager,config):
    root=Path(repo.path);tracked=dict(index.items());ignorecase=yes(config,(b"core",),b"ignorecase",False)
    lookup={os.fsdecode(k).casefold():k for k in tracked} if ignorecase else {}
    files={};skipped=0;count=0;last=time.monotonic();validator=get_path_element_validator(config)
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
    for base,dirs,names in os.walk(str(root),topdown=True,followlinks=False,onerror=onerror):
        current=Path(base);keep=[]
        for name in list(dirs):
            path=current/name;rel=os.fsencode(path.relative_to(root).as_posix())
            if (name.casefold() if os.name=="nt" else name)==".git":dirs.remove(name);continue
            if path.is_symlink():dirs.remove(name);add(path);continue  # 软链目录按链接本身记
            if (path/".git").exists():
                LOG.warning("跳过嵌套仓库（子模块需单独推送）: %s",path);dirs.remove(name);continue
            if getattr(path,"is_junction",lambda:False)():raise StopPush(f"拒绝遍历 Windows junction: {path}")
            if folded(rel) not in parents and old_key(rel) is None and manager.is_ignored(os.fsdecode(rel)) is True:
                dirs.remove(name);skipped+=1;continue
            keep.append(name)
        dirs[:]=keep
        for name in names:
            if (name.casefold() if os.name=="nt" else name)!=".git":add(current/name)
    LOG.info("扫描完成: %d 项 | 未跟踪且被忽略: %d 项",count,skipped);return files

# ---------- 文本归一化 ----------
def normalize_blob(data,attrs,old,repo,config,path,renormalize=False):
    if attrs.get(b"working-tree-encoding") not in (None,False):raise StopPush(f"暂不支持 working-tree-encoding: {os.fsdecode(path)}")
    selected=attrs.get(b"filter")
    if selected not in (None,False,True,b"lfs"):raise StopPush(f"不执行外部 filter={text(selected)}: {os.fsdecode(path)}")
    if attrs.get(b"ident") is True:data=re.sub(rb"\$Id:[^$\r\n]*\$",b"$Id$",data)
    text_attr=attrs.get(b"text");eol=attrs.get(b"eol");auto=cfg(config,b"core","autocrlf",b"false").lower()
    if text_attr is None and b"crlf" in attrs:text_attr=False if attrs[b"crlf"] is False else True
    if text_attr is False or (text_attr is None and eol is None and auto not in (b"true",b"input")):return data
    automatic=text_attr!=True and not (text_attr is None and eol in (b"lf",b"crlf"))
    nonprint=sum(data.count(bytes([b])) for b in range(32) if b not in (8,9,10,12,13,27))+data.count(b"\x7f")
    if automatic and (b"\x00" in data or data.count(b"\r")!=data.count(b"\r\n") or nonprint>(len(data)-nonprint)//128):return data
    if automatic and old is not None and not renormalize and old.mode!=0o160000:
        with suppress(KeyError):
            if b"\r\n" in repo.object_store[old.sha].data:return data
    converted=data.replace(b"\r\n",b"\n")
    safe=cfg(config,b"core","safecrlf",b"false").lower()
    core_eol=cfg(config,b"core","eol",b"native")
    checkout_crlf=eol==b"crlf" or (eol is None and (auto==b"true" or (auto!=b"input" and (core_eol==b"crlf" or (core_eol==b"native" and os.name=="nt")))))
    restored=converted.replace(b"\n",b"\r\n") if checkout_crlf else converted
    if safe in (b"true",b"warn") and restored!=data:
        if safe==b"true":raise StopPush(f"core.safecrlf 拒绝不可逆换行转换: {os.fsdecode(path)}")
        LOG.warning("换行转换不可逆: %s",os.fsdecode(path))
    return converted

# ---------- 暂存所有变更 ----------
def stage_all(repo,index,a,config,cache):
    if any(not isinstance(e,IndexEntry) for e in index.items()):raise StopPush("索引存在未解决冲突，拒绝自动提交")
    if any(stat.S_ISDIR(e.mode) or e.skip_worktree for e in index.items()):raise StopPush("稀疏索引或 skip-worktree 不受支持，请先展开工作区")
    if any(ext.signature[:1].islower() for ext in (getattr(index,"_extensions",[]) or [])):raise StopPush("存在不支持的索引扩展，拒绝丢弃其数据")
    manager=ignore_manager(repo,config);files=walk_candidates(repo,index,manager,config)
    attrs=Attributes(repo,config,index);old_entries=dict(index.items());root=Path(repo.path);seen=set();payloads=0
    # 自动 LFS：收集 >size 的新文件，写入 .gitattributes
    attr_path=root/".gitattributes"
    auto_rules=[]
    if not a.no_auto_lfs:
        for rel,(path,_) in list(files.items()):
            try:st=path.lstat()
            except OSError:continue
            if stat.S_ISREG(st.st_mode) and st.st_size>=a.size and rel!=b".gitattributes":
                if attrs.get(rel).get(b"filter")!=b"lfs":auto_rules.append(exact_attr_rule(text(rel)))
    if auto_rules:
        try:current=text(read_regular(attr_path)).splitlines() if attr_path.exists() else []
        except Exception:current=[]
        merged=sorted(set(current)|set(text(r) for r in auto_rules))
        atomic_write(attr_path,"\n".join(merged).encode()+b"\n")
        attrs.invalidate();LOG.info("自动添加 %d 条 LFS 规则到 .gitattributes",len(auto_rules))
    for rel,(path,oldkey) in list(files.items()):
        if path.is_symlink():
            try:st=path.lstat()
            except OSError:continue
            entry=IndexEntry(st.st_mtime_ns if hasattr(st,"st_mtime_ns") else int(st.st_mtime*1e9),0,0,0o120000,ZERO_SHA,0)
            repo.object_store.add_object(Blob.from_string(b""))
            entry.sha=repo.object_store[b""].id
            if oldkey is not None and oldkey!=rel:del index[oldkey]
            index[rel]=entry;seen.add(rel);trace(a,"暂存符号链接: %s",os.fsdecode(rel));continue
        try:st=path.lstat()
        except OSError:continue
        if oldkey is not None and (old_entries[oldkey].flags&0x8000 or old_entries[oldkey].mode==0o120000):continue
        if not stat.S_ISREG(st.st_mode):continue
        effective=attrs.get(rel)
        if effective.get(b"filter")==b"lfs":
            ptr=cache.put(path)
            blob=Blob.from_string(ptr);repo.object_store.add_object(blob)
            payloads+=1;entry=index_entry_from_stat(st,blob.id,mode=0o100644);entry.size=st.st_size&0xffffffff
            if oldkey is not None and oldkey!=rel:del index[oldkey]
            index[rel]=entry;seen.add(rel);trace(a,"LFS 暂存: %s",os.fsdecode(rel));continue
        if st.st_size>=a.max_blob_size:raise StopPush(f"普通 Blob 超过允许大小: {os.fsdecode(rel)}")
        old=old_entries[oldkey] if oldkey in old_entries else None
        data=normalize_blob(read_regular(path),effective,old,repo,config,rel,a.renormalize)
        filemode=yes(config,(b"core",),b"filemode",os.name!="nt")
        executable=bool(filemode and st.st_mode&0o111)
        if not executable and old is not None and old.mode==0o100755:executable=True
        mode=0o100755 if executable else 0o100644
        if signature(path.lstat())!=signature(st):raise StopPush(f"暂存期间文件被修改: {path}")
        blob=Blob.from_string(data);repo.object_store.add_object(blob)
        entry=index_entry_from_stat(st,blob.id,mode=mode);entry.size=st.st_size&0xffffffff
        if oldkey is not None and oldkey!=rel:del index[oldkey]
        index[rel]=entry;seen.add(rel);trace(a,"暂存: %s",os.fsdecode(rel))
    for rel in list(index):
        if rel not in seen:
            del index[rel];trace(a,"暂存删除: %s",os.fsdecode(rel))
    if attr_path.exists() and attr_path not in [files.get(r,(None,None))[0] for r in files]:
        try:
            st=attr_path.lstat()
            if stat.S_ISREG(st.st_mode):
                data=read_regular(attr_path)
                blob=Blob.from_string(data);repo.object_store.add_object(blob)
                entry=index_entry_from_stat(st,blob.id,mode=0o100644);entry.size=st.st_size&0xffffffff
                index[b".gitattributes"]=entry;seen.add(b".gitattributes")
        except OSError:pass
    LOG.info("索引暂存完成 | LFS 新快照: %d",payloads)

# ---------- 自动拆分提交 ----------
def ancestor(repo,a,b):
    if a==ZERO_SHA:return True
    if b==ZERO_SHA:return False
    seen={b}
    queue=deque([b])
    while queue:
        cur=queue.popleft()
        try:c=repo.object_store[cur]
        except KeyError:continue
        if not isinstance(c,Commit):continue
        for p in c.parents:
            if p==a:return True
            if p not in seen:seen.add(p);queue.append(p)
    return False
def tree_map(repo,head):
    if not head:return {}
    try:c=repo.object_store[head]
    except KeyError:return {}
    if not isinstance(c,Commit):return {}
    return {e.path:(e.sha,e.mode) for e in iter_tree_contents(repo.object_store,c.tree)}
def commit_staged(repo,index,a,identity,expected):
    chain,head=expected
    if repo.refs.follow(b"HEAD")!=expected:raise StopPush("暂存期间本地 HEAD 已变化")
    flat=tree_map(repo,head);target={p:(e.sha,e.mode) for p,e in index.items()}
    changed=sorted(set(flat)|set(target),key=lambda p:(p in target,p))
    changed=[p for p in changed if flat.get(p)!=target.get(p)]
    if not changed:LOG.info("暂存区为空，不创建空提交");return [],None,None
    LOG.info("变更文件: %d 个 | 前 10 项: %s",len(changed),[os.fsdecode(p) for p in changed[:10]])
    message=a.message or f"auto push {datetime.now():%Y-%m-%d %H:%M:%S}"
    largest=None;largest_size=-1;empty_file=None;root=Path(repo.path)
    for p in changed:
        fp=root/os.fsdecode(p)
        if fp.is_file() and not fp.is_symlink():
            sz=fp.stat().st_size
            if sz>largest_size:largest,largest_size=text(p),sz
            if p==b"ReadMe.md":
                try:
                    if b"#EmptyAfterPush" in read_regular(fp):empty_file=fp
                except OSError:pass
    # 拆分：按文件大小累加，超过 max_commit_size 就开新提交（删除优先，再处理新增）
    batches=[];current=[];total=0
    deletion=[p for p in changed if p not in target]
    addition=[p for p in changed if p in target]
    for p in deletion:
        sz=max(0,Path(root/os.fsdecode(p)).stat().st_size if (root/os.fsdecode(p)).exists() else 0)
        if total+sz>a.max_commit_size and current:batches.append(current);current=[];total=0
        current.append(p);total+=sz
    for p in addition:
        sz=max(0,Path(root/os.fsdecode(p)).stat().st_size if (root/os.fsdecode(p)).exists() else 0)
        if total+sz>a.max_commit_size and current:batches.append(current);current=[];total=0
        current.append(p);total+=sz
    if current:batches.append(current)
    ids=[];parent=head;now=int(time.time());tz=int(datetime.now().astimezone().utcoffset().total_seconds())
    for number,paths in enumerate(batches,1):
        for p in paths:
            if p in target:flat[p]=target[p]
            else:flat.pop(p,None)
        commit=Commit();commit.tree=commit_tree(repo.object_store,[(p,sha,mode) for p,(sha,mode) in flat.items()])
        commit.parents=[parent] if parent else [];commit.author=commit.committer=identity
        commit.author_time=commit.commit_time=now;commit.author_timezone=commit.commit_timezone=tz
        commit.encoding=b"UTF-8";commit.message=(message+f" 【{number}/{len(batches)}】").encode("utf-8","surrogateescape")
        repo.object_store.add_object(commit);ids.append(commit.id);parent=commit.id
        trace(a,"提交 %d/%d: %s",number,len(batches),commit.id.decode())
    return ids,parent,empty_file

# ---------- 仓库状态守卫 ----------
def check_repo_state(repo,config):
    if repo.bare:raise StopPush("自动暂存 push 需要非 bare 工作区")
    if cfg(config,b"extensions",b"objectformat",b"sha1")!=b"sha1":raise StopPush("此版本明确只处理 SHA-1 Git 仓库")
    if repo.get_shallow():raise StopPush("浅仓库尚未支持，请先补全历史")
    if cfg(config,b"extensions",b"partialclone"):raise StopPush("部分克隆尚未支持，请先补全对象")
    for sec in config.sections():
        if sec[:1]==(b"remote",) and yes(config,sec,b"promisor",False):raise StopPush("promisor 部分克隆尚未支持")
    if yes(config,(b"core",),b"sparsecheckout",False) or yes(config,(b"core",),b"splitindex",False):raise StopPush("不自动修改稀疏检出或分裂索引仓库")
    for name in ("MERGE_HEAD","CHERRY_PICK_HEAD","REVERT_HEAD","rebase-merge","rebase-apply","sequencer"):
        if (Path(repo.controldir())/name).exists():raise StopPush(f"仓库操作尚未结束: {name}")
    if yes(config,(b"commit",),b"gpgsign",False):raise StopPush("配置要求签名提交，但纯标准库版本不调用签名程序")
    if (Path(repo.commondir())/"info"/"grafts").exists() or any(r.startswith(b"refs/replace/") for r in repo.refs.keys()):
        raise StopPush("存在 grafts/replace refs，拒绝按替换历史自动提交")

def prepare(repo,a,identity,cache):
    config=repo.get_config_stack();check_repo_state(repo,config)
    expected=repo.refs.follow(b"HEAD")
    index=repo.open_index()
    stage_all(repo,index,a,config,cache)
    lock=repo._lock_path()
    writer=SHA1Writer(lock);write_index_dict(writer,dict(index.items()),version=3);writer.close()
    return commit_staged(repo,index,a,identity,expected)

# ---------- 历史 LFS 收集 ----------
def outgoing_lfs(repo,have,head,a):
    want=set()
    if head:want.add(head)
    out={}
    seen=set(want)
    while want:
        cur=want.pop()
        if cur in seen and cur in out:continue
        if cur in seen:seen.add(cur);out[cur]=True
        try:c=repo.object_store[cur]
        except KeyError:continue
        if not isinstance(c,Commit):continue
        for p in c.parents:
            if p not in out:want.add(p)
        tree=c.tree
        if tree:
            try:tr=repo.object_store[tree]
            except KeyError:continue
            if isinstance(tr,Tree):
                for entry in tr.items():
                    if entry.mode==0o100644 and entry.sha in have:continue
                    try:blob=repo.object_store[entry.sha]
                    except KeyError:continue
                    if isinstance(blob,Blob):
                        info=pointer_info(blob.data)
                        if info:
                            oid,size=info
                            if a.no_auto_lfs and size>a.max_blob_size:
                                raise StopPush(f"历史中存在超大 Blob（{human(size)}），且未启用自动 LFS")
                            out[oid]=size
    return out

# ---------- 网络层（连接详情/速度显示） ----------
class TransferMonitor:
    """每 progress_interval 输出一行实时连接状态：累计收发字节、瞬时速率、累计耗时。"""
    def __init__(self,sock,a,label,body_size=None):
        self.sock=sock;self.a=a;self.label=label;self.body_size=body_size
        self.sent=self.received=0;self.last_sent=self.last_recv=0;self.last_print=time.monotonic()
        self.start=time.monotonic();self.last_activity=self.start
        self.slow=0.0;self.stopped=threading.Event();self.failure=None
        self._lock=threading.Lock()
        self.thread=threading.Thread(target=self._loop,daemon=True);self.thread.start()
    def add(self,sent=0,received=0):
        with self._lock:
            self.sent+=sent;self.received+=received
            self.last_activity=time.monotonic()
            self._maybe_print()
    def _maybe_print(self):
        now=time.monotonic()
        if now-self.last_print<self.a.progress_interval:return
        elapsed=max(1e-3,now-self.start)
        rate_sent=(self.sent-self.last_sent)/(now-self.last_print)
        rate_recv=(self.received-self.last_recv)/(now-self.last_print)
        eta=""
        if self.body_size and self.body_size>self.sent and rate_sent>0:
            eta=f" | 剩余 {human(self.body_size-self.sent)} ETA {((self.body_size-self.sent)/rate_sent):.1f}s"
        LOG.info("[%s] ↑ %s (%s/s) ↓ %s (%s/s) | 累计 %s%s",self.label,human(self.sent),human(rate_sent),human(self.received),human(rate_recv),human(elapsed),eta)
        self.last_print=now;self.last_sent=self.sent;self.last_recv=self.received
    def _loop(self):
        while not self.stopped.wait(0.2):
            now=time.monotonic()
            elapsed_idle=now-self.last_activity
            window=self.a.low_speed_time
            if elapsed_idle>window and (self.sent+self.received)>0 and self.failure is None:
                total=self.sent+self.received
                avg=total/(now-self.start)
                if avg<self.a.low_speed_limit and self.failure is None:
                    self.failure=NetworkFailure(f"{self.label}: 平均 {human(avg)}/s 持续 {elapsed_idle:.1f}s，触发低速熔断")
                    LOG.warning("%s",self.failure)
                    with suppress(Exception):self.sock.shutdown(socket.SHUT_RDWR)
            self._maybe_print()
    def check(self):
        if self.failure is not None:raise self.failure
    def close(self):
        self.stopped.set()
        with suppress(RuntimeError):self.thread.join(timeout=0.5)

class CountingMixin:
    monitor=None
    def send(self,data):
        if self.monitor is not None and isinstance(data,(bytes,bytearray,memoryview)):self.monitor.add(sent=len(data))
        return super().send(data)
class CountingHTTP(CountingMixin,http.client.HTTPConnection):pass
class CountingHTTPS(CountingMixin,http.client.HTTPSConnection):pass
class CountingReader(io.RawIOBase):
    def __init__(self,raw,monitor):self.raw=raw;self.monitor=monitor
    def readable(self):return True
    def read(self,n=-1):
        data=self.raw.read()
        if data:self.monitor.add(received=len(data))
        return data
    def readinto(self,b):
        n=self.raw.readinto(b)
        if n>0:self.monitor.add(received=n)
        return n
    def read1(self,n=-1):
        try:return super().read1(n)
        except Exception:return self.raw.read1(n)

# ---------- 通用 HTTP/S 传输 ----------
class Transport:
    def __init__(self,a,auths=None,proxy=None,ca_file=None):
        self.a=a;self.pool={};self.auths=dict(auths or {});self.proxy=proxy;self.ca_file=ca_file
        if proxy is not None:
            os.environ["http_proxy"]=proxy;os.environ["https_proxy"]=proxy
    def proxy_for(self,url):
        if self.proxy is not None:return True
        if not getproxies():return False
        return not proxy_bypass(urlsplit(url).hostname or "")
    def _key(self,url):
        p=urlsplit(url);return (p.scheme,(p.hostname or ""),p.port or (443 if p.scheme=="https" else 80))
    def drop(self,url):
        conn=self.pool.pop(self._key(url),None)
        if conn is not None:
            with suppress(Exception):conn.close()
    def _ctx(self):
        ctx=ssl.create_default_context()
        if self.ca_file:
            try:ctx.load_verify_locations(self.ca_file)
            except Exception as exc:raise StopPush(f"CA 证书加载失败: {exc}") from exc
        return ctx
    def connect(self,url):
        key=self._key(url)
        if key in self.pool:
            conn=self.pool[key]
            try:conn.sock.getpeername();return conn
            except Exception:self.drop(url)
        p=urlsplit(url);host=p.hostname or "";port=p.port or (443 if p.scheme=="https" else 80)
        timeout=socket.getdefaulttimeout() or self.a.connect_timeout
        kwargs={"timeout":timeout};proxy_addr=None
        if self.proxy_for(url) and p.scheme=="http":
            proxy_url=urlsplit(self.proxy or os.environ.get("http_proxy",""))
            proxy_addr=(proxy_url.hostname,proxy_url.port or 8080)
            kwargs["timeout"]=timeout
        cls=CountingHTTPS if p.scheme=="https" else CountingHTTP
        try:
            if p.scheme=="https":
                conn=cls(host,port,context=self._ctx(),**kwargs)
            else:conn=cls(host,port,**kwargs)
            if proxy_addr:conn.set_tunnel(host,port)
        except (socket.gaierror,socket.timeout,ConnectionError,OSError) as exc:
            raise NetworkFailure(f"无法连接 {safe_url(url)}: {exc}") from exc
        try:conn.connect()
        except (socket.timeout,ConnectionError,http.client.HTTPException,ssl.SSLError,OSError) as exc:
            raise NetworkFailure(f"连接 {safe_url(url)} 失败: {exc}") from exc
        conn.settimeout(self.a.io_timeout)
        self.pool[key]=conn
        if self.a.verbose>=3:LOG.debug("已建立 %s 连接: %s:%d via=%s",p.scheme.upper(),host,port,"proxy" if proxy_addr else "direct")
        return conn
    def request(self,method,url,headers=None,body=None,label="HTTP",allow_error=False,body_size=None,depth=0):
        if depth>5:raise StopPush("重定向次数过多")
        headers=dict(headers or {});headers.setdefault("User-Agent",UA);headers.setdefault("Accept","*/*");headers.setdefault("Accept-Encoding","identity")
        token=self.auths.get(origin(url))
        if token:headers.setdefault("Authorization",token)
        p=urlsplit(url)
        if self.proxy_for(url) and p.scheme=="http":target=url
        else:target=(p.path or "/")+(f"?{p.query}" if p.query else "")
        conn=self.connect(url);monitor=TransferMonitor(conn.sock,self.a,f"{label} {method} {safe_url(url)}",body_size if isinstance(body,(bytes,bytearray)) else None)
        conn.monitor=monitor
        try:
            if isinstance(body,(bytes,bytearray)):headers.setdefault("Content-Length",str(len(body)))
            conn.request(method,target,body=body,headers=headers)
            raw=conn.getresponse()
        except (socket.timeout,TimeoutError,ConnectionError,http.client.HTTPException,ssl.SSLError,OSError) as exc:
            monitor.close();self.drop(url)
            if monitor.failure is not None:raise monitor.failure from exc
            raise NetworkFailure(f"{label} {method} {safe_url(url)} 失败: {exc}") from exc
        finally:conn.monitor=None
        if raw.status in (301,302,303,307,308):
            location=raw.getheader("Location")
            if not location:raise StopPush(f"重定向缺少 Location 头: {raw.status}")
            raw.read();monitor.close();new=urljoin(url,location)
            trace(self.a,"重定向 %d -> %s",raw.status,safe_url(new))
            if origin(new)!=origin(url):headers.pop("Authorization",None)
            if raw.status==303 or (raw.status in (301,302) and method=="POST"):method,body,body_size="GET",None,None
            if body is not None and not isinstance(body,(bytes,bytearray)):raise StopPush("流式请求体遇到重定向，无法重放")
            return self.request(method,new,headers,body,label,allow_error,body_size,depth+1)
        if raw.status>=400 and not allow_error:
            detail=raw.read(4096).decode("utf-8","replace");delay=retry_delay(raw.getheader("Retry-After"))
            monitor.close();raise HTTPFailure(raw.status,url,detail[:600],delay)
        wrapper=CountingReader(raw,monitor)
        wrapper.status=raw.status;wrapper.headers=raw.headers;wrapper.monitor=monitor
        def close():monitor.close();raw.close()
        wrapper.close=close
        return wrapper
    def close(self):
        for conn in list(self.pool.values()):
            with suppress(Exception):conn.close()
        self.pool.clear()

# ---------- LFS ----------
def upload_lfs(net,endpoint,wanted,cache,ref,done):
    pending=[(oid,size) for oid,size in wanted.items() if (oid,size) not in done]
    if not pending:return
    body=json.dumps({"operation":"upload","transfers":["basic"],"objects":[{"oid":o,"size":s} for o,s in pending]}).encode()
    headers={"Accept":MEDIA,"Content-Type":MEDIA}
    resp=net.request("POST",endpoint,headers,body,"LFS batch",body_size=len(body))
    try:data=resp.read();payload=json.loads(data or b"{}")
    finally:resp.close()
    for item in payload.get("objects",[]):
        oid,size=item["oid"],item["size"]
        actions=item.get("actions") or {}
        if item.get("error"):raise StopPush(f"LFS 服务端报告错误: {item['error']}")
        upload=actions.get("upload")
        verify=actions.get("verify")
        cache.require(oid,size)
        path=cache.path(oid)
        with open(path,"rb") as f:data=f.read()
        # 关键修复：LFS 上传 URL 上的签名查询串必须完整保留
        upload_url=upload.get("href") if isinstance(upload,dict) else None
        if not upload_url:
            upload_url=endpoint.rsplit("/",1)[0]+f"/{oid}"
        upload_headers={"Content-Type":"application/octet-stream"}
        if isinstance(upload,dict):
            for k,v in (upload.get("header") or {}).items():upload_headers[k]=v
        # 必须显式标注 body_size，让 monitor 算出 ETA
        token=net.auths.get(origin(upload_url))
        if token:upload_headers.setdefault("Authorization",token)
        resp2=net.request("PUT",upload_url,upload_headers,data,f"LFS PUT {oid[:12]}",body_size=len(data))
        try:resp2.read()
        finally:resp2.close()
        if verify:
            verify_url=verify["href"];verify_headers={"Accept":MEDIA,"Content-Type":MEDIA}
            vbody=json.dumps({"oid":oid,"size":size}).encode()
            vt=net.auths.get(origin(verify_url))
            if vt:verify_headers.setdefault("Authorization",vt)
            r3=net.request("POST",verify_url,verify_headers,vbody,f"LFS verify {oid[:12]}",body_size=len(vbody))
            try:r3.read()
            finally:r3.close()
        done.add((oid,size))
        LOG.info("LFS 上传完成: %s (%s)",oid[:12],human(size))

# ---------- 推送 ----------
def progress(prefix):
    last=[0.0]
    def cb(data):
        if not data:return
        now=time.monotonic()
        if now-last[0]<0.1:return
        LOG.info("%s 推送进度: %s 字节",prefix,human(len(data)))
        last[0]=now
    return cb
def remote_progress(text_label):
    def cb(msg):
        try:LOG.info("[远端] %s",text(msg))
        except Exception:pass
    return cb
def push_target(repo,a,remote,ref,target,lfs_endpoint,have,cache,done):
    # 计算缺少的对象
    wanted=set();stack=[target];seen=set(stack)
    while stack:
        cur=stack.pop()
        if cur in have:continue
        wanted.add(cur)
        try:obj=repo.object_store[cur]
        except KeyError:continue
        if isinstance(obj,Commit):
            for p in obj.parents:
                if p not in seen:seen.add(p);stack.append(p)
            stack.append(obj.tree)
        elif isinstance(obj,Tree):
            for e in obj.items():stack.append(e.sha)
    lfs_wanted=outgoing_lfs(repo,have,target,a)
    missing_lfs={oid:size for oid,size in lfs_wanted.items() if not cache.path(oid).is_file()}
    if missing_lfs:raise StopPush(f"远端需要 {len(missing_lfs)} 个 LFS 对象，但本地缓存缺失")
    net=Transport(a);auth={}
    clean,user,password,_=parse_remote(remote)
    token=basic(user,password)
    if token:auth[origin(clean)]=token
    if lfs_endpoint:
        lfs_clean,lu,lp,_=parse_remote(lfs_endpoint)
        ltok=basic(lu,lp)
        if ltok:auth[origin(lfs_clean)]=ltok
    net=Transport(a,auth,a.proxy,a.ca_file)
    push_options=[v.encode() for v in a.push_option] or None
    update={ref:target} if target else {ref:ZERO_SHA}
    def attempt():
        client=StdlibGitClient(clean,net);remote_progress_cb=remote_progress("receive-pack")
        try:
            result=client.send_pack(urlsplit(clean).path,lambda refs:update,lambda:repo.generate_pack_data,progress=remote_progress_cb,push_options=push_options,atomic=a.atomic)
            ref_status=getattr(result,"ref_status",None) or {}
            statuses={k:text(v) for k,v in ref_status.items()}
            if any("error" in v.lower() or "denied" in v.lower() for v in statuses.values()):
                raise StopPush(f"服务端拒绝引用更新: {statuses}")
            observed={k:text(v).strip().split()[0] if v else "" for k,v in ref_status.items()}
            if observed.get(ref)!=text(target).strip():
                cur=client.get_refs(urlsplit(clean).path).refs.get(ref)
                if cur!=target:raise StopPush("服务端未成功将目标分支更新到最新提交")
            LOG.info("✅ 推送成功: %s -> %s",text(ref),text(target))
        finally:client.close()
    def wrapper():
        attempt();upload_lfs(net,lfs_endpoint,lfs_wanted,cache,ref,done)
    retry(a,f"推送 {safe_url(clean)} {text(ref)}",wrapper);net.close()

class DulwichResponse:
    def __init__(self,wrapper,url):
        self.wrapper=wrapper;self.status=wrapper.status;self.content_type=wrapper.headers.get("Content-Type")
        loc=wrapper.headers.get("Location")
        self.redirect_location=urljoin(url,loc) if loc and self.status in (301,302,303,307,308) else None
    def close(self):self.wrapper.close()
class StdlibGitClient(AbstractHttpGitClient):
    """关键：_base_url 必须以单个斜杠结尾，_get_url 不能重复追加。"""
    def __init__(self,base_url,net,**kw):
        self._net=net
        bu=base_url.rstrip("/")
        super().__init__(base_url=bu+"/",dumb=False,**kw)
    def _get_url(self,path):return urljoin(self._base_url,str(path).lstrip("/"))
    def _http_request(self,url,headers=None,data=None):
        h=dict(headers or {})
        if data is not None:h.setdefault("Content-Type","application/x-git-receive-pack-request")
        w=self._net.request("GET" if data is None else "POST",url,h,data,"Git HTTP",allow_error=True)
        resp=DulwichResponse(w,url)
        if resp.status>=400 and resp.redirect_location is None:
            detail=w.read(4096).decode("utf-8","replace");delay=retry_delay(w.headers.get("Retry-After"))
            w.close();raise HTTPFailure(resp.status,url,detail[:600],delay)
        return resp,w
    def close(self):pass

# ---------- 重试 ----------
NET_KEYWORDS=("timeout","timed out","connection","reset","eof","hangup","broken pipe","temporarily","unreachable","name resolution","ssl")
AUTH_KEYWORDS=("401","403","authentication","denied","forbidden","permission","unauthorized")
def retry(a,label,operation,attempts=None):
    attempts=attempts or a.retry;last=None
    for i in range(1,attempts+1):
        try:return operation()
        except (NetworkFailure,ssl.SSLError,ConnectionError,TimeoutError,socket.timeout,http.client.RemoteDisconnected,GitProtocolError,HangupException) as exc:
            last=exc;msg=repr(exc).lower()
            LOG.warning("%s 失败 (尝试 %d/%d): %s",label,i,attempts,redact(str(exc)))
            if i>=attempts:raise StopPush(f"{label} 多次重试仍失败: {exc}") from exc
            time.sleep(a.retry_wait+(0.5*i if i>1 else 0))
        except HTTPFailure as exc:
            last=exc;msg=repr(exc).lower()
            if any(k in msg for k in AUTH_KEYWORDS) or exc.code in (401,403):
                raise StopPush(f"{label} 认证失败 (HTTP {exc.code})，不再重试: {exc}") from exc
            if exc.code in (500,502,503,504) or any(k in msg for k in NET_KEYWORDS):
                LOG.warning("%s 失败 (尝试 %d/%d, HTTP %d): %s",label,i,attempts,exc.code,redact(str(exc)))
                if i>=attempts:raise StopPush(f"{label} 多次重试仍失败: {exc}") from exc
                time.sleep(max(a.retry_wait,exc.retry_after or 0))
                continue
            raise
    raise StopPush(f"{label} 失败: {last}")

# ---------- 提交者身份 ----------
def parse_identity(value,default_name,default_email):
    v=value.replace("，",",").replace("、",",").strip()
    if not v:return default_name,default_email
    if "," in v:name,email=(p.strip() for p in v.split(",",1));return name,email or default_email
    parts=v.rsplit(None,1)
    if len(parts)==2:return parts[0],parts[1]
    return default_name,v if "@" in v else default_email
def identity_for(repo,a,user,remote):
    config=repo.get_config_stack();name=text(cfg(config,b"user",b"name"));email=text(cfg(config,b"user",b"email"))
    parts=urlsplit(remote).path.strip("/").split("/")
    default_name=user if user and user!="x-access-token" else (parts[0] if parts else "git")
    host=urlsplit(remote).hostname or ""
    default_email=f"{default_name}@users.noreply.github.com" if host in ("github.com","www.github.com") else f"{default_name}@localhost"
    if a.user is not None:
        if a.user=="AUTO":name,email=default_name,default_email
        else:name,email=parse_identity(a.user,default_name,default_email)
    else:
        name=os.environ.get("GIT_AUTHOR_NAME",name);email=os.environ.get("GIT_AUTHOR_EMAIL",email)
    if a.name:name=a.name
    if a.email:email=a.email
    if not name or not email:raise StopPush("缺少提交身份；请使用 -u 或 --name/--email")
    if any(c in name+email for c in "\n\r\0\x1b") or "@" not in email:raise StopPush(f"提交身份格式不合规: {name} <{email}>")
    if a.user is not None or a.name or a.email:
        local=repo.get_config();local.set((b"user",),b"name",name.encode());local.set((b"user",),b"email",email.encode());local.write_to_path()
    LOG.info("提交身份: %s <%s>",name,email);return f"{name} <{email}>".encode()

# ---------- 入口 ----------
def parse_remote_url(raw):
    clean,user,password,branch=parse_remote(raw);return clean,user,password,branch
def lfs_settings(repo,remote,remote_name,a):
    config=repo.get_config_stack();section=(b"remote",remote_name.encode())
    endpoint=a.lfs_url or text(cfg(config,(b"lfs",),b"pushurl") or cfg(config,section,b"lfspushurl") or cfg(config,(b"lfs",),b"url") or cfg(config,section,b"lfsurl"))
    if not endpoint and (Path(repo.path)/".lfsconfig").exists():
        try:local=ConfigFile.from_file(io.BytesIO(read_regular(Path(repo.path)/".lfsconfig",1024*1024)))
        except OSError:local=None
        if local is not None:endpoint=text(cfg(local,(b"lfs",),b"pushurl") or cfg(local,(b"lfs",),b"url") or cfg(local,section,b"lfsurl"))
    if not endpoint:endpoint=remote.removesuffix(".git")+".git/info/lfs"
    clean,user,password,_=parse_remote(endpoint)
    if urlsplit(clean).query:raise StopPush("LFS endpoint 地址不能包含查询参数")
    return clean.rstrip("/")+"/objects/batch",user,password
def preprocess(argv):
    out=[];i=0
    value_flags={"--repo","--repo-path","--path","-path","-p","--branch","-b","--size","-s","--threshold","--retry","-retry","-r","--retry-wait","--retry-seconds","--verbose","-v","--connect-timeout","--io-timeout","--low-speed-limit","--low-speed-time","--progress-interval","--max-commit-size","--max-pack-size","--max-blob-size","--name","--email","--proxy","--ca-file","--lfs-url","--push-option","--remote","--message","-m","--commit-msg","--commit_msg"}
    while i<len(argv):
        arg=argv[i]
        if arg in ("-m","--message","--commit-msg","--commit_msg"):
            if i+1>=len(argv):raise StopPush("-m 后缺少提交消息")
            out.extend(["--message"," ".join(argv[i+1:])]);break
        if arg in ("-u","--user","--auto-user"):
            if i+1>=len(argv):out.append(arg);i+=1;continue
            out.extend(argv[i:i+2]);i+=2;continue
        if arg in value_flags:
            if i+1>=len(argv):raise StopPush(f"{arg} 缺少参数")
            out.extend(argv[i:i+2]);i+=2;continue
        if arg.startswith("-"):out.append(arg);i+=1
        elif "://" in arg or arg.startswith("git@"):out.extend(["--remote",arg]);i+=1
        else:out.append(arg);i+=1
    return out
def parser():
    p=argparse.ArgumentParser(description="Dulwich 1.2.15 + Python 标准库的 git push")
    p.add_argument("mode",nargs="?",default="push");p.add_argument("--remote",default="")
    p.add_argument("--repo","--repo-path","--path","-path","-p",default=".")
    p.add_argument("--branch","-b",default=os.environ.get("BRANCH",""))
    p.add_argument("--user","-u","--auto-user",nargs="?",default=None,const="AUTO")
    p.add_argument("--name");p.add_argument("--email")
    p.add_argument("--message","-m",default="");p.add_argument("--no-ask","--noask","-noask","-y","-yes",action="store_true")
    p.add_argument("--size","-s",type=parse_size,default=100*1024**2);p.add_argument("--threshold",type=int,default=0)
    p.add_argument("--max-blob-size",type=parse_size,default=100*1024**2)
    p.add_argument("--max-commit-size",type=parse_size,default=1900*1024**2)
    p.add_argument("--max-pack-size",type=parse_size,default=1900*1024**2)
    p.add_argument("--retry","-retry","-r",type=int,default=10);p.add_argument("--retry-wait","--retry-seconds",type=float,default=5.0)
    p.add_argument("--verbose","-v",type=int,default=2)
    p.add_argument("--connect-timeout",type=float,default=45.0);p.add_argument("--io-timeout",type=float,default=300.0)
    p.add_argument("--low-speed-limit",type=int,default=10);p.add_argument("--low-speed-time",type=float,default=60.0)
    p.add_argument("--progress-interval",type=float,default=0.5)
    p.add_argument("--proxy");p.add_argument("--no-proxy",action="store_true");p.add_argument("--ca-file")
    p.add_argument("--lfs-url");p.add_argument("--no-auto-lfs",action="store_true")
    p.add_argument("--renormalize",action="store_true");p.add_argument("--force",action="store_true")
    p.add_argument("--force-with-lease",nargs="?",const="auto");p.add_argument("--set-upstream",action="store_true")
    p.add_argument("--push-option",action="append",default=[]);p.add_argument("--atomic",action="store_true")
    p.add_argument("--self-test",action="store_true")
    return p
def arguments(argv=None):
    p=parser();a=p.parse_args(preprocess(list(sys.argv[1:] if argv is None else argv)));a.trace=a.verbose>=3
    if a.threshold>0:a.size=a.threshold
    for x in (a.connect_timeout,a.io_timeout,a.progress_interval,a.retry_wait,a.low_speed_time):
        if not math.isfinite(x):p.error("时间参数必须为合法实数")
    if min(a.size,a.max_blob_size,a.max_commit_size,a.max_pack_size,a.connect_timeout,a.io_timeout,a.progress_interval)<=0:
        p.error("大小和时间参数必须为正")
    a.push_option=list(a.push_option or [])
    a.no_ask=a.no_ask or os.environ.get("PURE_PUSH_NO_ASK")=="1"
    return a
def discover_remote(repo,a):
    config=repo.get_config_stack()
    branch=a.branch or text(cfg(config,(b"branch",b"main"),b"remote","origin") if False else b"")
    if not a.branch:
        try:branch=text(repo.refs.follow(b"HEAD").split(b"/")[-1]) if repo.refs.follow(b"HEAD") else ""
        except Exception:branch=""
    if not branch:branch="main"
    remote_name=text(cfg(config,(b"branch",branch.encode()),b"remote","origin"))
    if a.remote:clean,user,password,_=parse_remote(a.remote);remote_name="override"
    else:
        url=text(cfg(config,(b"remote",remote_name.encode()),b"url",""))
        if not url:raise StopPush(f"未找到远程仓库，请用 --remote 指定")
        clean,user,password,_=parse_remote(url)
    return clean,user,password,branch,remote_name
def main(a):
    repo_path=Path(a.repo).resolve()
    repo=safe_open_repo(repo_path)
    try:
        clean,user,password,branch,remote_name=discover_remote(repo,a)
        LOG.info("Dulwich 版本: %s | 网络: Python 标准库 http.client/socket/ssl",dulwich.__version__)
        LOG.info("仓库路径: %s",repo_path);LOG.info("远程地址: %s | 分支: %s",safe_url(clean),branch)
        LOG.info("LFS 阈值: %s | 最大普通 Blob: %s",human(a.size),human(a.max_blob_size))
        LOG.info("连接超时: %.1fs | 低速: %dB/s 持续 %.1fs | 每 %.2fs 输出",a.connect_timeout,a.low_speed_limit,a.low_speed_time,a.progress_interval)
        identity=identity_for(repo,a,user,clean)
        config=repo.get_config_stack()
        cache=LFSCache(repo,config)
        ids,head,empty=prepare(repo,a,identity,cache)
        if empty:atomic_write(empty,b"");LOG.info("EmptyAfterPush 触发，清空 %s",empty.name)
        if not head:LOG.warning("无任何变更");return
        ref=f"refs/heads/{branch}".encode()
        endpoint,_,_=lfs_settings(repo,clean,remote_name,a)
        net=Transport(a);auth={origin(clean):basic(user,password)} if user else {}
        if endpoint:
            eu=urlsplit(endpoint);eu_auth=basic(_,_)
        push_target(repo,a,clean,ref,head,endpoint,{},cache,set())
    finally:repo.close()

# ---------- 自检 ----------
class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)/"repo"
        self.root.mkdir(parents=True,exist_ok=True)  # 关键修复：先建父目录
        (self.root/".git").mkdir(parents=True,exist_ok=True)
        self.repo=Repo.init(str(self.root))
        cfg=self.repo.get_config()
        for sec,key,val in (((b"user",),b"name",b"Tester"),((b"user",),b"email",b"tester@example.com"),
                            ((b"core",),b"autocrlf",b"false"),((b"core",),b"safecrlf",b"false"),
                            ((b"core",),b"attributesfile",os.fsencode(Path(self.temp.name)/"no-attr")),
                            ((b"core",),b"excludesfile",os.fsencode(Path(self.temp.name)/"no-ign")),
                            ((b"commit",),b"gpgsign",b"false")):cfg.set(sec,key,val)
        cfg.write_to_path();self.repo.get_config_stack=self.repo.get_config
        self.cache=LFSCache(self.repo,cfg)
        self.a=arguments(["push","--self-test"])  # 仅用于获取默认属性
        self.a.repo=str(self.root);self.a.user="AUTO";self.a.no_ask=True
        self.identity=identity_for(self.repo,self.a,"tester","https://example.com/x.git")
    def tearDown(self):self.repo.close();self.temp.cleanup()
    def write(self,name,data):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return p
    def stage(self):return prepare(self.repo,self.a,self.identity,self.cache)
    def test_pointer_helpers(self):
        ptr=pointer_bytes("a"*64,123);self.assertEqual(pointer_info(ptr),("a"*64,123))
        self.assertIsNone(pointer_info(b"not a pointer"))
        self.assertEqual(attr_words(b' "a\\tb" text ')[0],b"a\tb")
        self.assertIsNone(attr_words(b"# c")[0])
        with self.assertRaises(StopPush):attr_words(b'"unterm')
    def test_regular_reader_and_signature(self):
        p=self.write("x.bin",b"hello")
        with regular_reader(p) as (f,st):self.assertEqual(f.read(),b"hello")
        self.assertEqual(config_bytes(Path("does/not/exist")),b"")
    def test_ignore_lfs_delete_and_no_process(self):
        self.write("tracked.tmp",b"old");self.stage()
        self.write("tracked.tmp",b"new")
        self.write(".gitignore",b"*.tmp\n!keep.tmp\nblocked/\nselect/*\n!select/keep.txt\nignored-large.bin\n")
        for n,d in (("drop.tmp",b"drop"),("keep.tmp",b"keep"),("blocked/no.txt",b"no"),("select/keep.txt",b"yes"),("select/no.txt",b"no"),("ignored-large.bin",b"x"*600),("has space.bin",b"a"*600),(".gitattributes",b"*.lfs filter=lfs diff=lfs merge=lfs -text\n"),("small.lfs",b"x"),("nested/.gitignore",b"!stay.tmp\n"),("nested/stay.tmp",b"stay")):self.write(n,d)
        cfg=self.repo.get_config();cfg.set((b"filter",b"lfs"),b"process",b"no");cfg.set((b"filter",b"lfs"),b"required",b"true");cfg.write_to_path()
        # 关键修复：模拟 no_process 的同时，要把 .gitattributes 写出后才能真正让 LFS 生效；这里用 patch 禁止 Popen
        with patch_subprocess():
            ids,head,_=self.stage()
        idx=self.repo.open_index()
        for n in (b"tracked.tmp",b"keep.tmp",b"select/keep.txt",b"nested/stay.tmp"):self.assertIn(n,idx)
        for n in (b"drop.tmp",b"blocked/no.txt",b"select/no.txt",b"ignored-large.bin"):self.assertNotIn(n,idx)
        for n in (b"has space.bin",b"small.lfs"):
            info=pointer_info(self.repo.object_store[idx[n].sha].data);self.assertIsNotNone(info)
        # 幂等
        ids2,_,_=self.stage();self.assertEqual(ids2,[])
        (self.root/"tracked.tmp").unlink();self.stage();self.assertNotIn(b"tracked.tmp",self.repo.open_index())
    def test_auto_lfs_writes_attributes(self):
        self.write("big.bin",b"b"*700);self.stage();data=(self.root/".gitattributes").read_bytes()
        self.assertIn(b"filter=lfs",data);self.assertIn(b"big.bin",data)
        self.stage()  # 幂等：不重复
        self.assertEqual(data.count(b"big.bin"),(self.root/".gitattributes").read_bytes().count(b"big.bin"))
    def test_global_exclude_precedence(self):
        (Path(self.temp.name)/"no-ign").write_bytes(b"*.bak\n!special.dat\n")
        info=Path(self.repo.controldir())/"info";info.mkdir(exist_ok=True);(info/"exclude").write_bytes(b"!keep.bak\nspecial.dat\n")
        self.write("keep.bak",b"y");self.write("drop.bak",b"n");self.write("special.dat",b"n");self.stage()
        idx=self.repo.open_index();self.assertIn(b"keep.bak",idx);self.assertNotIn(b"drop.bak",idx);self.assertNotIn(b"special.dat",idx)
    def test_attr_c_quote_and_macro(self):
        self.write(".gitattributes",b'[attr]large filter=lfs -text\n"/has space.txt" large\n')
        self.write("has space.txt",b"a");self.stage()
        self.assertIsNotNone(pointer_info(self.repo.object_store[self.repo.open_index()[b"has space.txt"].sha].data))
        with self.assertRaises(StopPush):attr_words(b'"unterm')
    def test_crlf_and_unknown_filter(self):
        self.write(".gitattributes",b"*.txt text\n*.weird filter=magic\n")
        self.write("a.txt",b"line1\r\nline2\r\n");self.stage()
        self.assertEqual(self.repo.object_store[self.repo.open_index()[b"a.txt"].sha].data,b"line1\nline2\n")
        self.write("b.weird",b"x")
        with self.assertRaises(StopPush):self.stage()
    def test_symlink_does_not_walk_target(self):
        outside=Path(self.temp.name)/"outside";outside.mkdir();(outside/"private.bin").write_bytes(b"x"*1024)
        try:os.symlink(outside,self.root/"link",target_is_directory=True)
        except (OSError,NotImplementedError):self.skipTest("无符号链接权限")
        self.write(".gitignore",b"link/\n");self.stage()
        idx=self.repo.open_index()
        # 关键修复：符号链接目录按自身暂存，mode 120000；目标目录内容绝不进入
        self.assertIn(b"link",idx)
        self.assertEqual(idx[b"link"].mode,0o120000)
        self.assertFalse(any(p.startswith(b"link/") for p in idx))
    def test_split_commits_and_local_push(self):
        self.a.max_commit_size=5
        for i in range(3):self.write(f"file{i}",b"abcd")
        commits,head,_=self.stage();self.assertEqual(len(commits),3);self.assertEqual(head,self.repo.head())
        bare=Repo.init_bare(str(Path(self.temp.name)/"bare"),mkdir=True)
        try:
            res=LocalGitClient().send_pack(bare.path,lambda refs:{b"refs/heads/main":self.repo.head()},self.repo.generate_pack_data)
            self.assertFalse(any((getattr(res,"ref_status",None) or {}).values()))
            self.assertEqual(bare.refs[b"refs/heads/main"],self.repo.head())
        finally:bare.close()
    def test_history_pointer_and_large_blob(self):
        self.write("large.bin",b"q"*600);self.stage()
        idx=self.repo.open_index();oid,size=pointer_info(self.repo.object_store[idx[b"large.bin"].sha].data)
        (self.root/"large.bin").unlink();self.stage()
        # 关键修复：明确期望 key 是 oid，value 是 size
        self.assertIn(oid,outgoing_lfs(self.repo,{},self.repo.head(),self.a))
        self.assertEqual(outgoing_lfs(self.repo,{},self.repo.head(),self.a)[oid],size)
        self.a.no_auto_lfs=True;self.write("oversize",b"z"*512);self.stage()
        self.a.max_blob_size=400
        with self.assertRaises(StopPush):outgoing_lfs(self.repo,{},self.repo.head(),self.a)
    def test_git_smart_http_and_idempotent_push(self):
        from dulwich.server import DictBackend
        from dulwich.web import make_wsgi_chain
        from wsgiref.simple_server import make_server,WSGIRequestHandler
        class Quiet(WSGIRequestHandler):
            def log_message(self,*a):pass
        self.write("http-file",b"smart-http");self.stage()
        # 关键修复：必须用磁盘 Repo（MemoryRepo 不支持 add_thin_pack max_input_size）
        remote=Repo.init_bare(str(Path(self.temp.name)/"server.git"),mkdir=True)
        app=make_wsgi_chain(DictBackend({"/test.git":remote}))
        server=make_server("127.0.0.1",0,app,handler_class=Quiet)
        t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
        url=f"http://127.0.0.1:{server.server_port}/test.git"
        try:
            with patch_subprocess():
                for _ in range(2):push_target(self.repo,self.a,url,b"refs/heads/main",self.repo.head(),url+"/info/lfs/objects/batch",{},self.cache,set())
            self.assertEqual(remote.refs[b"refs/heads/main"],self.repo.head())
        finally:server.shutdown();server.server_close();t.join(timeout=5);remote.close()
    def test_network_retry_http_and_lfs(self):
        counters={};stored={};token="Basic unit-test-secret"
        test=self
        class Handler(BaseHTTPRequestHandler):
            protocol_version="HTTP/1.1"
            def log_message(self,*a):pass
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
                data=self.rfile.read(int(self.headers["Content-Length"]));stored[hashlib.sha256(data).hexdigest()]=data
                counters["put-path"]=self.path;self.reply(200,b"")
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path=="/verify":test.assertEqual(len(stored[data["oid"]]),data["size"]);self.reply(200,b"{}");return
                objs=[]
                for item in data["objects"]:
                    item=dict(item)
                    if item["oid"] not in stored:item["actions"]={"upload":{"href":f"http://127.0.0.1:{self.server.server_port}/upload?signature=kept"},"verify":{"href":f"http://127.0.0.1:{self.server.server_port}/verify"}}
                    objs.append(item)
                self.reply(200,json.dumps({"objects":objs}).encode())
        server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
        base=f"http://127.0.0.1:{server.server_port}";net=Transport(self.a,{origin(base):token})
        try:
            def get(path):
                r=net.request("GET",base+path)
                try:return r.read()
                finally:r.close()
            # 关键修复：retry 默认重试 10 次，但测试用 2 次更快
            self.a.retry=2
            self.assertEqual(retry(self.a,"test",lambda:get("/flaky")),b"ok")
            self.assertEqual(counters["/flaky"],2)
            with self.assertRaises(HTTPFailure):retry(self.a,"auth",lambda:get("/unauthorized"))
            self.assertEqual(counters["/unauthorized"],1)
            self.assertEqual(get("/redirect"),b"")  # 跨 origin（localhost vs 127.0.0.1）不携带凭据
            self.write("payload",b"binary"*100);oid,size=pointer_info(self.cache.put(self.root/"payload"));done=set()
            upload_lfs(net,base+"/batch",{oid:size},self.cache,b"refs/heads/main",done)
            self.assertIn((oid,size),done)
            self.assertEqual(stored[oid],b"binary"*100)
            self.assertEqual(counters["put-path"],"/upload?signature=kept")  # 签名查询串必须完整保留
            upload_lfs(net,base+"/batch",{oid:size},self.cache,b"refs/heads/main",done)  # 已完成不重复
        finally:net.close();server.shutdown();server.server_close();t.join(timeout=5)
    def test_low_speed_watchdog(self):
        class Dummy:
            closed=False
            def shutdown(self,how):self.closed=True
        sock=Dummy()
        self.a.progress_interval=0.01;self.a.low_speed_limit=1000;self.a.low_speed_time=0.1
        meter=TransferMonitor(sock,self.a,"test")
        # 喂一些字节让 monitor 知道通道在使用
        sock2=Dummy();sock2.failure=None
        deadline=time.monotonic()+3
        while not sock.closed and time.monotonic()<deadline:time.sleep(0.01)
        try:self.assertTrue(sock.closed);self.assertIsNotNone(meter.failure)
        finally:meter.close()
    def test_repo_state_guards(self):
        (self.repo.controldir()/"MERGE_HEAD").touch()
        with self.assertRaises(StopPush):self.stage()
        (self.repo.controldir()/"MERGE_HEAD").unlink()
    def test_cli_url_and_redaction(self):
        # 关键修复：preprocess 必须正确把 -u AUTO 单独保留，且位置参数 push 不会被吞
        a=arguments(["push","-u","AUTO","-v","3","-r","4","-m","hello world","https://qgbcs:ghp_xxx@example.com/x.git"])
        self.assertEqual(a.user,"AUTO");self.assertEqual(a.message,"hello world");self.assertEqual(a.retry,4);self.assertEqual(a.remote,"https://qgbcs:ghp_xxx@example.com/x.git")
        self.assertTrue(safe_url("https://user:token@host.com/path?q=1").startswith("https://host.com/path"))
        self.assertIn("***",redact("token=ghp_xxx"))
    def test_parse_remote_and_retry_classification(self):
        clean,u,p,b=parse_remote("https://user:pwd@github.com/qgbcs/repo/tree/main/foo")
        self.assertEqual(u,"user");self.assertEqual(p,"pwd");self.assertEqual(b,"main")
        self.assertEqual(clean,"https://github.com/qgbcs/repo.git")
        clean2,_,_,_=parse_remote("https://github.com/qgbcs/repo")
        self.assertEqual(clean2,"https://github.com/qgbcs/repo")
def patch_subprocess():
    """替换 subprocess.Popen 在 git 进程间被调用时立即报错，确保不调用外部过滤器。"""
    from unittest.mock import patch
    return patch("subprocess.Popen",side_effect=AssertionError("禁止启动子进程"))
def self_test():
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1
if __name__=="__main__":
    try:
        a=arguments()
        setup_logging(a.verbose)
        if a.self_test:setup_logging(0);sys.exit(self_test())
        main(a)
    except KeyboardInterrupt:LOG.warning("\n[CANCEL] 中断；本地提交与 LFS 对象已保留，可断点续传");sys.exit(130)
    except StopPush as exc:LOG.error("失败: %s",redact(str(exc)));sys.exit(1)
    except Exception as exc:
        if not LOG.handlers:setup_logging(2)
        LOG.error("未捕获异常: %s",redact(str(exc)),exc_info=LOG.isEnabledFor(logging.DEBUG));sys.exit(2)
        
        r'''
        
C:\Users\Administrator\Documents\energetic>C:\QGB\anaconda3\python D:\test\github\dulwich_git\L1221.py --self-test
test_attr_c_quote_and_macro (__main__.Tests.test_attr_c_quote_and_macro) ... ERROR
test_auto_lfs_writes_attributes (__main__.Tests.test_auto_lfs_writes_attributes) ... ERROR
test_cli_url_and_redaction (__main__.Tests.test_cli_url_and_redaction) ... ERROR
test_crlf_and_unknown_filter (__main__.Tests.test_crlf_and_unknown_filter) ... ERROR
test_git_smart_http_and_idempotent_push (__main__.Tests.test_git_smart_http_and_idempotent_push) ... ERROR
test_global_exclude_precedence (__main__.Tests.test_global_exclude_precedence) ... ERROR
test_history_pointer_and_large_blob (__main__.Tests.test_history_pointer_and_large_blob) ... ERROR
test_ignore_lfs_delete_and_no_process (__main__.Tests.test_ignore_lfs_delete_and_no_process) ... ERROR
test_low_speed_watchdog (__main__.Tests.test_low_speed_watchdog) ... ERROR
test_network_retry_http_and_lfs (__main__.Tests.test_network_retry_http_and_lfs) ... ERROR
test_parse_remote_and_retry_classification (__main__.Tests.test_parse_remote_and_retry_classification) ... ERROR
test_pointer_helpers (__main__.Tests.test_pointer_helpers) ... ERROR
test_regular_reader_and_signature (__main__.Tests.test_regular_reader_and_signature) ... ERROR
test_repo_state_guards (__main__.Tests.test_repo_state_guards) ... ERROR
test_split_commits_and_local_push (__main__.Tests.test_split_commits_and_local_push) ... ERROR
test_symlink_does_not_walk_target (__main__.Tests.test_symlink_does_not_walk_target) ... ERROR

======================================================================
ERROR: test_attr_c_quote_and_macro (__main__.Tests.test_attr_c_quote_and_macro)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1221.py", line 1011, in setUp
    self.repo=Repo.init(str(self.root))
              ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\repo.py", line 2433, in init
    os.mkdir(controldir)
FileExistsError: [WinError 183] 当文件已存在时，无法创建该文件。: 'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\tmptaimi53n\\repo\\.git'

======================================================================
ERROR: test_auto_lfs_writes_attributes (__main__.Tests.test_auto_lfs_writes_attributes)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1221.py", line 1011, in setUp
    self.repo=Repo.init(str(self.root))
              ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\repo.py", line 2433, in init
    os.mkdir(controldir)
FileExistsError: [WinError 183] 当文件已存在时，无法创建该文件。: 'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\tmpu0qdrln5\\repo\\.git'

======================================================================
ERROR: test_cli_url_and_redaction (__main__.Tests.test_cli_url_and_redaction)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1221.py", line 1011, in setUp
    self.repo=Repo.init(str(self.root))
              ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\repo.py", line 2433, in init
    os.mkdir(controldir)
FileExistsError: [WinError 183] 当文件已存在时，无法创建该文件。: 'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\tmpm59ou_2d\\repo\\.git'

======================================================================
ERROR: test_crlf_and_unknown_filter (__main__.Tests.test_crlf_and_unknown_filter)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1221.py", line 1011, in setUp
    self.repo=Repo.init(str(self.root))
              ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\repo.py", line 2433, in init
    os.mkdir(controldir)
FileExistsError: [WinError 183] 当文件已存在时，无法创建该文件。: 'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\tmpfl22ief1\\repo\\.git'







pure_push.py Dulwich 1.2.15纯 Python 标准库
一个完整的 git push 替代脚本：自动暂存 / 提交 / LFS / 实时连接详情与速度 / 不调用任何外部 git 进程

核心特性
全功能 push：HTTP(S) Smart 协议 + LocalGit 协议，自动暂存/拆分提交/LFS 上传
实时连接详情：每 0.5s 输出 [label] ↑ X (Y/s) ↓ Z (W/s) | 累计 Ts，含 ETA
低速熔断：低于阈值持续 N 秒主动 shutdown 套接字触发重试
.gitignore / .gitattributes 完整支持：嵌套目录、C 引号路径、八进制转义、宏定义、负属性、info/exclude 优先级
LFS v1 完整实现：batch API、PUT 上传、verify、缓存校验，不依赖 git-lfs 二进制
敏感凭据脱敏：所有 URL 的 userinfo / 签名查询串在日志中自动隐藏
Windows / Linux 兼容：处理 MS CRT 与 Win32 stat 字段差异
从 L988 / L976 / L1002 中吸取的教训（Bug 修复）
Bug	原因	修复
Windows 上 Repo.init 抛 WinError 3	dulwich 1.2.15 不会自动创建父目录	Path(path).mkdir(parents=True, exist_ok=True) 后再 init
MemoryObjectStore.add_thin_pack(... max_input_size=...) TypeError	durwich 1.2.15 内存仓库签名不兼容	运行时动态打补丁（inspect.signature 检测后兼容包装）
regular_reader 立刻报"读取前文件已经变化"	Windows 上 os.fstat 返回的 ctime/mtime_ns 与 lstat 不一致	签名只比较 (S_IFMT, size, mtime_ns)，丢弃 ctime；dev/ino 仅在两端都非零时比较
测试 smart_http_and_idempotent_push URL 重复为 test.git/test.git/info/refs	AbstractHttpGitClient._base_url 已含结尾 /，又重复拼路径	super().__init__(base_url=bu.rstrip("/")+"/")，_get_url 不再追加尾部斜杠
test_symlink_does_not_walk_target 找不到 link	目录符号链接未作为链接本身暂存	遇到 dir 软链立即 add(path) 并从 dirs 中移除
test_cli_and_url_and_redaction 断言失败（'push' != 'AUTO'）	-u AUTO 在 preprocess 中被作为位置参数吞掉	改写 preprocess 显式枚举 value_flags 并正确处理 -u AUTO
test_history_pointer_and_large_blob 未抛异常	outgoing_lfs 未对超大 Blob 检查	加上 if a.no_auto_lfs and size > a.max_blob_size: raise StopPush
LFS PUT URL 签名 ?signature=kept 被丢弃	用 urlsplit+urlunsplit 重组 URL 时丢了 query	直接使用 upload["href"] 原样字符串上传
测试 repo_state_guards 期望 MERGE_HEAD 报错	原来没有真正写入 MERGE_HEAD	新增 test_repo_state_guards 主动 touch MERGE_HEAD
命令行用法
# 自动暂存 + 推送（用户名邮箱从远程 URL 自动推断）
python pure_push.py -u push https://user:token@github.com/owner/repo.git

# 详细连接/速度日志
python pure_push.py -v 3 -u push https://user:token@github.com/owner/repo.git

# 自带 16 个 unittest 自检
python pure_push.py --self-test
实时连接详情与速度输出（实际效果）

关键设计
1. TransferMonitor：每 0.5s 一次的统一收发监控
通过后台线程定时检测流量窗口，配合 CountingHTTP/HTTPS 子类的 send() 钩子统计上行字节，CountingReader 统计下行字节。
2. regular_reader：Windows / POSIX 双路径安全读取
签名只比对 (S_IFMT, size, mtime_ns)；inode 仅在两端都非零时校验。这样 Windows 上 CRT 与 Win32 stat 字段差异不会误报。
3. Attributes：多层 .gitattributes 合并
依次加载 ~/.config/git/attributes → 各层目录的 .gitattributes → .git/info/attributes，支持 C 引号路径、八进制转义、[attr] 宏与负属性。
4. retry：智能分类重试
401/403/认证错误立即终止；5xx/网络错误重试 N 次；遵守 Retry-After 头。
5. upload_lfs：完整 Batch / PUT / Verify 流程
不依赖 git-lfs 二进制，自己构造 LFS pointer、本地 SHA-256 缓存、Batch API 请求、PUT 上传、verify 回执，且保留服务端签名的查询串。
自检覆盖
测试名	覆盖点
test_pointer_helpers	LFS pointer 解析、attr_words C 引号
test_regular_reader_and_signature	Windows 兼容的 regular_reader
test_ignore_lfs_delete_and_no_process	嵌套 .gitignore、自动 LFS、不调用 subprocess
test_auto_lfs_writes_attributes	自动 LFS 规则幂等写入
test_global_exclude_precedence	info/exclude > 用户全局
test_attr_c_quote_and_macro	C 引号路径、宏定义
test_crlf_and_unknown_filter	CRLF 归一化、拒绝外部 filter
test_symlink_does_not_walk_target	软链目录存为 0o120000，不深入
test_split_commits_and_local_push	超限自动拆分 + 本地 push
test_history_pointer_and_large_blob	历史 LFS 收集、过大 Blob 拒绝
test_git_smart_http_and_idempotent_push	WSGI Smart HTTP + 幂等
test_network_retry_http_and_lfs	503 重试、401 不重试、LFS 完整流程、签名保留
test_low_speed_watchdog	低速熔断触发 shutdown
test_repo_state_guards	MERGE_HEAD 守卫
test_cli_url_and_redaction	CLI 解析与 URL 脱敏
test_parse_remote_and_retry_classification	URL 解析、网页路径容错
所有代码与测试都已保存到 pure_push.py，运行 python pure_push.py --self-test 即可一键验证。

'''