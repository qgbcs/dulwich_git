#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dulwich 1.2.15 + Python 标准库实现的全功能 git push（自动暂存/提交/LFS/实时速度显示），不调用任何外部进程。"""
from __future__ import annotations
import argparse,base64,hashlib,http.client,io,json,logging,math,os,re,socket,ssl,stat,sys,tempfile,threading,time,unittest
from contextlib import contextmanager,suppress
from datetime import datetime
from pathlib import Path
from urllib.parse import quote,unquote,urljoin,urlsplit,urlunsplit
from urllib.request import getproxies,proxy_bypass
from dulwich.client import AbstractHttpGitClient,LocalGitClient
from dulwich.config import ConfigFile
from dulwich.errors import GitProtocolError,HangupException,NotGitRepository
from dulwich.ignore import IgnoreFilter,IgnoreFilterManager,default_user_ignore_filter_path,translate as ignore_translate
from dulwich.index import IndexEntry,index_entry_from_stat,commit_tree,validate_path,get_path_element_validator
from dulwich.object_store import iter_tree_contents
from dulwich.objects import Blob,Commit
from dulwich.protocol import ZERO_SHA
from dulwich.repo import Repo
LOG=logging.getLogger("PurePush");SECRETS=set();CHUNK=64*1024;POINTER_PREFIX=b"version https://git-lfs.github.com/spec/v1\n";MEDIA="application/vnd.git-lfs+json";UA="git/2.45.0 purepush-dulwich"  # 常量集中在此，便于自检引用
class StopPush(RuntimeError):pass  # 不可重试的致命错误
class NetworkFailure(RuntimeError):pass  # 可重试的网络瞬断
class HTTPFailure(StopPush):  # HTTP 层错误，是否重试由状态码决定
    def __init__(self,code,url,detail="",retry_after=0):super().__init__(f"HTTP {code} {safe_url(url)} {detail}");self.code=int(code);self.retry_after=retry_after
def remember(secret):
    if secret and len(str(secret))>3:SECRETS.add(str(secret))  # 登记需要在日志中抹掉的凭据
def safe_url(value):
    try:
        p=urlsplit(str(value));host=p.hostname or "";host=f"[{host}]" if ":" in host else host  # IPv6 补方括号
        return urlunsplit((p.scheme,host+(f":{p.port}" if p.port else ""),p.path,"",""))  # 丢掉 userinfo 与查询串（LFS 签名）
    except ValueError:return "[URL 已隐藏]"
def redact(value):
    t=str(value)
    for s in sorted(SECRETS,key=len,reverse=True):t=t.replace(s,"***")  # 逐个抹掉已知令牌
    t=re.sub(r"https?://[^\s\"'<>]+",lambda m:safe_url(m.group()),t)  # 任何 URL 都脱敏
    return t.replace("\x1b","\\x1b")  # 防止远端用 ANSI 控制序列污染终端
class SafeFormatter(logging.Formatter):
    def format(self,record):return redact(super().format(record))  # 连异常堆栈一起脱敏
def setup_logging(v):
    h=logging.StreamHandler(sys.stdout);h.setFormatter(SafeFormatter("%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s","%Y-%m-%d %H:%M:%S"))
    LOG.handlers[:]=[h];LOG.propagate=False;LOG.setLevel({0:logging.ERROR,1:logging.WARNING,2:logging.INFO}.get(v,logging.DEBUG))
def trace(a,msg,*args):
    if getattr(a,"trace",False):LOG.log(logging.DEBUG if a.verbose>=3 else logging.INFO,msg,*args)  # -v 3 才输出细节
def text(v):return v.decode("utf-8","surrogateescape") if isinstance(v,bytes) else str(v)
def cfg(config,section,key,default=b""):
    section=(section,) if isinstance(section,bytes) else tuple(section)
    try:return config.get(section,key)
    except KeyError:return default
def yes(config,section,key,default=False):
    try:return config.get_boolean(tuple(section),key,default)
    except Exception:return default
def human(n):
    n=float(n);units=("B","KiB","MiB","GiB","TiB");i=0
    while n>=1024 and i<len(units)-1:n/=1024;i+=1
    return f"{n:.2f} {units[i]}"
def parse_size(v):
    m=re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmgtKMGT]?)[bB]?\s*",str(v))
    if not m:raise argparse.ArgumentTypeError(f"无法解析大小: {v}")
    return int(float(m.group(1))*{"":1,"k":1024,"m":1024**2,"g":1024**3,"t":1024**4}[m.group(2).lower()])
def origin(url):
    p=urlsplit(url);return (p.scheme,p.hostname or "",p.port or (443 if p.scheme=="https" else 80))  # 认证凭据按 origin 隔离，跨主机重定向不外泄
def basic(user,password):
    if not user and not password:return ""
    return "Basic "+base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
def split_credentials(url):
    p=urlsplit(url);user=unquote(p.username or "");password=unquote(p.password or "");remember(password);remember(user if user and user!="x-access-token" else None)
    host=p.hostname or ""
    if ":" in host:host=f"[{host}]"
    return urlunsplit((p.scheme,host+(f":{p.port}" if p.port else ""),p.path,p.query,p.fragment)),user,password
def normalize_remote(url):
    url=str(url).strip().strip('"').strip("'");branch=None
    if url.startswith("git@") and "://" not in url:host,_,path=url[4:].partition(":");url=f"https://{host}/{path}"  # SSH 简写转 HTTPS，本脚本只走 HTTP(S)
    if "://" not in url:url="https://github.com/"+url.lstrip("/")  # 允许只写 user/repo
    clean,user,password=split_credentials(url);p=urlsplit(clean);parts=[x for x in p.path.split("/") if x]
    if len(parts)<2:raise StopPush(f"远程地址缺少 owner/repo: {safe_url(clean)}")
    if len(parts)>2 and parts[2] in ("tree","blob"):
        branch=unquote(parts[3]) if len(parts)>3 else None;LOG.warning("网页路径只用于定位仓库，含斜杠的分支请显式 --branch")  # 网页 URL 容错
    base="/"+"/".join(parts[:2]);base=base[:-4] if base.endswith(".git") else base
    return urlunsplit((p.scheme,p.netloc,base+".git","","")),user,password,branch
def atomic_write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise StopPush(f"拒绝覆盖符号链接: {path}")
    mode=stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644;fd,tmp=tempfile.mkstemp(prefix=".purepush-",dir=str(path.parent))
    try:
        with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,mode);os.replace(tmp,path)  # 同目录替换，异常时不留半截文件
    finally:
        with suppress(FileNotFoundError):os.unlink(tmp)
def signature(st):return (stat.S_IFMT(st.st_mode),st.st_size,st.st_mtime_ns)  # 只比较类型/大小/修改时间：Windows 的 os.fstat 不返回 ino/dev，ctime 也会漂移
def identity_pair(st):return (getattr(st,"st_dev",0),getattr(st,"st_ino",0))  # 仅当两端都提供 inode 时才比较
@contextmanager
def regular_reader(path):
    path=Path(path);before=path.lstat()
    if not stat.S_ISREG(before.st_mode):raise StopPush(f"不是普通文件，拒绝跟随链接: {path}")
    fd=os.open(str(path),os.O_RDONLY|getattr(os,"O_BINARY",0)|getattr(os,"O_NOFOLLOW",0))
    with os.fdopen(fd,"rb") as f:
        opened=os.fstat(f.fileno())
        if signature(opened)!=signature(before):raise StopPush(f"读取前文件已经变化: {path}")
        a,b=identity_pair(opened),identity_pair(before)
        if all(a) and all(b) and a!=b:raise StopPush(f"打开的不是同一个文件（可能被替换）: {path}")  # inode 可用时才校验，规避 Windows fstat 返回 0
        yield f,before
        after=os.fstat(f.fileno())
        if signature(after)!=signature(before) or signature(path.lstat())!=signature(before):raise StopPush(f"读取时文件发生变化，请重试: {path}")
def read_regular(path,limit=None):
    with regular_reader(path) as (f,st):
        if limit is not None and st.st_size>limit:raise StopPush(f"文件过大: {path}")
        return f.read()
def config_bytes(path):
    path=Path(path)
    if path.is_symlink():return b""  # 配置类文件拒绝跟随链接
    try:return read_regular(path,8*1024*1024)
    except (FileNotFoundError,NotADirectoryError,PermissionError,OSError):return b""
class SafeIgnore(IgnoreFilterManager):
    def _load_path(self,path):
        if (Path(self._top_path)/path/".gitignore").is_symlink():return None  # 不读取符号链接形式的 .gitignore
        return super()._load_path(path)
def ignore_manager(repo,config):
    ignorecase=yes(config,(b"core",),b"ignorecase",False);filters=[]
    for p in (Path(text(cfg(config,b"core",b"excludesfile",os.fsencode(default_user_ignore_filter_path(config))))).expanduser(),Path(repo.controldir())/"info"/"exclude"):
        try:filters.append(IgnoreFilter.from_path(str(p),ignorecase))  # 低优先级在前：用户全局 -> info/exclude -> 各级 .gitignore
        except (FileNotFoundError,NotADirectoryError,OSError):pass
    return SafeIgnore(str(repo.path),filters,ignorecase)
def attr_words(line):
    line=line.strip()
    if not line or line.startswith(b"#"):return None,[]
    if not line.startswith(b'"'):
        w=line.split();return w[0],w[1:]
    out=bytearray();i=1;esc={ord("a"):7,ord("b"):8,ord("t"):9,ord("n"):10,ord("v"):11,ord("f"):12,ord("r"):13,34:34,92:92,39:39}
    while i<len(line):  # 解析 C 风格引号路径，dulwich 的简单 split 做不到
        c=line[i];i+=1
        if c==34:return bytes(out),line[i:].split()
        if c!=92:out.append(c);continue
        if i>=len(line):break
        b=line[i];i+=1
        if 48<=b<=55:
            digits=chr(b)
            while len(digits)<3 and i<len(line) and 48<=line[i]<=55:digits+=chr(line[i]);i+=1
            v=int(digits,8)
            if v>255:raise StopPush(".gitattributes 八进制转义超界")
            out.append(v);continue
        if b in esc:out.append(esc[b]);continue
        raise StopPush(".gitattributes 存在不支持的 C 转义")
    raise StopPush(".gitattributes 的引号没有闭合")
def parse_attribute(token):
    if token[:1]==b"-":return token[1:],False
    if token[:1]==b"!":return token[1:],None
    if b"=" in token:k,v=token.split(b"=",1);return k,v
    return token,True
class AttrPattern:
    def __init__(self,pattern):
        self.pattern=pattern;self.regex=re.compile(ignore_translate(pattern if pattern.startswith(b"/") or b"/" in pattern.rstrip(b"/") else pattern))  # 复用 dulwich 的 wildmatch 翻译
    def match(self,rel):
        return bool(self.regex.match(rel)) or bool(self.regex.match(b"/"+rel))  # 相对本层目录匹配
class Attributes:
    """按 全局 -> 各级 .gitattributes -> info/attributes 合并属性，支持 -attr、!attr 与 [attr] 宏。"""
    def __init__(self,repo,config,index):
        self.repo=repo;self.root=Path(repo.path);self.index=index;self.cache={}
        default=Path(os.environ.get("XDG_CONFIG_HOME",str(Path.home()/".config")))/"git"/"attributes"
        self.global_path=Path(text(cfg(config,b"core",b"attributesfile",os.fsencode(default)))).expanduser();self.info=Path(repo.controldir())/"info"/"attributes"
    def invalidate(self):self.cache.clear()  # 自动 LFS 规则写入后需要重新解析
    def load(self,path,relative=None,macro_allowed=True):
        key=(str(path),macro_allowed)
        if key in self.cache:return self.cache[key]
        data=config_bytes(path)
        if not data and relative is not None and relative in self.index:
            e=self.index[relative]
            if e.mode in (0o100644,0o100755):
                with suppress(KeyError):data=self.repo.object_store[e.sha].data  # 工作区缺文件时回退到索引版本
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
                except (ValueError,re.error) as exc:raise StopPush(f"属性模式无效: {path}: {exc}") from exc
        self.cache[key]=(rules,macros);return rules,macros
    def get(self,rel):
        parts=rel.split(b"/");levels=[(self.global_path,rel,None,True)]
        for i in range(len(parts)):
            name=b"/".join(parts[:i]+[b".gitattributes"]);levels.append((self.root/os.fsdecode(name),b"/".join(parts[i:]),name,i==0))  # 深层目录不许定义宏
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
    quoted=b'"/'+body+b'"' if (b" " in raw or b"[" in raw or b"#" in raw or b"*" in raw or b"?" in raw) else b"/"+body  # 含特殊字符时用 C 引号
    return quoted+b" filter=lfs diff=lfs merge=lfs -text"
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
        custom=text(cfg(config,b"lfs",b"storage",b""));self.root=Path(custom).expanduser() if custom else Path(repo.controldir())/"lfs";self.verified={}
    def path(self,oid):return self.root/"objects"/oid[:2]/oid[2:4]/oid
    def put(self,src):
        src=Path(src);self.root.mkdir(parents=True,exist_ok=True);tmpdir=self.root/"tmp";tmpdir.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(dir=str(tmpdir));h=hashlib.sha256();size=0;last=time.monotonic()
        try:
            with os.fdopen(fd,"wb") as out,regular_reader(src) as (f,st):
                for block in iter(lambda:f.read(CHUNK),b""):
                    out.write(block);h.update(block);size+=len(block)
                    if time.monotonic()-last>=1:LOG.info("LFS 本地快照: %s | %s/%s",src.name,human(size),human(st.st_size));last=time.monotonic()
                out.flush();os.fsync(out.fileno())
            oid=h.hexdigest();dest=self.path(oid);dest.parent.mkdir(parents=True,exist_ok=True);os.replace(tmp,dest);self.verified[(oid,size)]=signature(dest.stat())
            return pointer_bytes(oid,size)
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
        return p
class Progress:
    def __init__(self,prefix,interval=.5):self.prefix=prefix;self.interval=interval;self.last=0.0;self.buffer=b""
    def __call__(self,data):
        if not data:return
        self.buffer+=data;now=time.monotonic()
        if now-self.last<self.interval and b"\n" not in data and b"\r" not in data:return
        self.last=now;line=self.buffer.replace(b"\r",b"\n").splitlines()
        self.buffer=b""
        for item in line[-1:]:
            if item.strip():LOG.info("%s%s",self.prefix,item.decode("utf-8","replace").strip())
    def finish(self):
        if self.buffer.strip():LOG.info("%s%s",self.prefix,self.buffer.decode("utf-8","replace").strip())
        self.buffer=b""
class TransferMonitor:
    """按固定间隔打印实时速度，并在长时间低速时主动 shutdown 套接字，避免 push 永久卡住。"""
    def __init__(self,sock,a,label,total=None):
        self.sock=sock;self.a=a;self.label=label;self.total=total;self.sent=0;self.recv=0;self.failure=None;self.lock=threading.Lock()
        self.start=time.monotonic();self.slow=0.0;self.stopped=threading.Event();self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def add(self,sent=0,recv=0):
        with self.lock:self.sent+=sent;self.recv+=recv
    def snapshot(self):
        with self.lock:return self.sent,self.recv
    def run(self):
        interval=max(.01,self.a.progress_interval);prev=0;prev_t=time.monotonic()
        while not self.stopped.wait(interval):
            sent,recv=self.snapshot();total=sent+recv;now=time.monotonic();dt=max(1e-6,now-prev_t);rate=(total-prev)/dt
            done=f"{human(total)}"+(f"/{human(self.total)} {min(100.0,total*100.0/max(1,self.total)):.1f}%" if self.total else "")
            LOG.info("%s | 已传 %s | 速度 %s/s | 上行 %s 下行 %s | 用时 %.1fs",self.label,done,human(rate),human(sent),human(recv),now-self.start)
            self.slow=self.slow+dt if rate<self.a.low_speed_limit else 0.0
            prev,prev_t=total,now
            if self.a.low_speed_time>0 and self.slow>=self.a.low_speed_time and self.failure is None:
                self.failure=NetworkFailure(f"{self.label}: 低于 {self.a.low_speed_limit} B/s 持续 {self.slow:.1f}s，主动断开重试")
                LOG.warning("%s",self.failure)
                with suppress(Exception):self.sock.shutdown(socket.SHUT_RDWR)  # 打断阻塞的 recv/send
                return
    def check(self):
        if self.failure is not None:raise self.failure
    def close(self):
        self.stopped.set()
        with suppress(RuntimeError):self.thread.join(timeout=1)
class CountingConnectionMixin:
    monitor=None
    def send(self,data):
        if self.monitor is not None and isinstance(data,(bytes,bytearray,memoryview)):self.monitor.add(sent=len(data))  # 统计所有出站字节（含分块头）
        return super().send(data)
class CountingHTTP(CountingConnectionMixin,http.client.HTTPConnection):pass
class CountingHTTPS(CountingConnectionMixin,http.client.HTTPSConnection):pass
class CountingReader(io.RawIOBase):
    def __init__(self,raw,monitor):self.raw=raw;self.monitor=monitor
    def readable(self):return True
    def read(self,n=-1):
        data=self.raw.read() if n is None or n<0 else self.raw.read(n)
        if data and self.monitor is not None:self.monitor.add(recv=len(data))
        if self.monitor is not None:self.monitor.check()
        return data
    def readinto(self,b):
        data=self.read(len(b))
        b[:len(data)]=data;return len(data)
    def close(self):
        with suppress(Exception):self.raw.close()
class FileFeeder:
    """带计数的上传体：http.client 对具备 read() 的对象直接 sock.sendall，必须在这里统计。"""
    def __init__(self,path,size,monitor):self.f=open(path,"rb");self.left=size;self.monitor=monitor
    def read(self,n=CHUNK):
        if self.left<=0:return b""
        data=self.f.read(min(n,self.left))
        self.left-=len(data)
        if self.monitor is not None:self.monitor.add(sent=len(data));self.monitor.check()
        return data
    def close(self):
        with suppress(Exception):self.f.close()
def retry_delay(header):
    if not header:return 0
    with suppress(ValueError):return max(0.0,float(header))
    return 0
class Transport:
    """基于 http.client / socket / ssl 的连接池：支持代理、TLS 详情打印、按 origin 的认证与实时测速。"""
    def __init__(self,a,auths,secure=True):
        self.a=a;self.auths=auths;self.secure=secure;self.pool={};self.context=None
    def ssl_context(self):
        if self.context is None:
            ctx=ssl.create_default_context(cafile=self.a.ca_file) if self.a.ca_file else ssl.create_default_context()
            ctx.minimum_version=ssl.TLSVersion.TLSv1_2;ctx.check_hostname=True;ctx.verify_mode=ssl.CERT_REQUIRED
            with suppress(Exception):ctx.set_alpn_protocols(["http/1.1"])
            self.context=ctx
        return self.context
    def proxy_for(self,url):
        if self.a.no_proxy:return None
        p=urlsplit(url)
        if self.a.proxy:return self.a.proxy
        with suppress(Exception):
            if proxy_bypass(p.hostname or ""):return None
        return getproxies().get(p.scheme)
    def connect(self,url):
        p=urlsplit(url);key=(p.scheme,p.hostname,p.port,self.proxy_for(url))
        conn=self.pool.get(key)
        if conn is not None:
            return conn
        proxy=self.proxy_for(url);timeout=self.a.connect_timeout;started=time.monotonic()
        if proxy:
            pp=urlsplit(proxy);cls=CountingHTTPS if pp.scheme=="https" else CountingHTTP
            conn=cls(pp.hostname,pp.port or (443 if pp.scheme=="https" else 80),timeout=timeout)
            if p.scheme=="https":
                conn.set_tunnel(p.hostname,p.port or 443,headers={"Proxy-Authorization":basic(unquote(pp.username or ""),unquote(pp.password or ""))} if pp.username else None)
        else:
            cls=CountingHTTPS if p.scheme=="https" else CountingHTTP
            conn=cls(p.hostname,p.port or (443 if p.scheme=="https" else 80),timeout=timeout,**({"context":self.ssl_context()} if p.scheme=="https" else {}))
        conn.connect();conn.sock.settimeout(self.a.io_timeout)
        with suppress(Exception):conn.sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        peer="";info=""
        with suppress(Exception):peer="%s:%s"%conn.sock.getpeername()[:2]
        if isinstance(conn.sock,ssl.SSLSocket):
            c=conn.sock.cipher() or ("","","");cert=conn.sock.getpeercert() or {}
            subject=dict(x[0] for x in cert.get("subject",()) if x)
            info=f" | TLS {conn.sock.version()} {c[0]} | CN={subject.get('commonName','?')} 到期 {cert.get('notAfter','?')}"
        LOG.info("已连接 %s (%s)%s | 耗时 %.0f ms%s",p.hostname,peer,f" 经代理 {safe_url(proxy)}" if proxy else "",(time.monotonic()-started)*1000,info)
        self.pool[key]=conn;return conn
    def drop(self,url):
        p=urlsplit(url);key=(p.scheme,p.hostname,p.port,self.proxy_for(url))
        conn=self.pool.pop(key,None)
        if conn is not None:
            with suppress(Exception):conn.close()
    def request(self,method,url,headers=None,body=None,label="HTTP",allow_error=False,body_size=None,depth=0):
        if depth>5:raise StopPush("重定向次数过多")
        headers=dict(headers or {});headers.setdefault("User-Agent",UA);headers.setdefault("Accept-Encoding","identity")
        token=self.auths.get(origin(url))
        if token:headers.setdefault("Authorization",token)  # 仅对同 origin 附带凭据
        p=urlsplit(url);target=url if (self.proxy_for(url) and p.scheme=="http") else (p.path or "/")+(f"?{p.query}" if p.query else "")
        conn=self.connect(url);monitor=TransferMonitor(conn.sock,self.a,f"{label} {method} {safe_url(url)}",body_size)
        conn.monitor=monitor
        try:
            if isinstance(body,(bytes,bytearray)):headers.setdefault("Content-Length",str(len(body)))
            conn.request(method,target,body=body,headers=headers)
            raw=conn.getresponse()
        except (socket.timeout,TimeoutError,ConnectionError,http.client.HTTPException,ssl.SSLError,OSError) as exc:
            monitor.close();self.drop(url)
            if monitor.failure is not None:raise monitor.failure from exc
            raise NetworkFailure(f"{label} {method} {safe_url(url)} 失败: {exc}") from exc
        finally:
            conn.monitor=None
        location=raw.getheader("Location")
        if raw.status in (301,302,303,307,308) and location:
            raw.read();monitor.close();new=urljoin(url,location)
            trace(self.a,"重定向 %d -> %s",raw.status,safe_url(new))
            if origin(new)!=origin(url):headers.pop("Authorization",None)  # 跨 origin 不转发凭据
            if raw.status==303 or (raw.status in (301,302) and method=="POST"):method,body,body_size="GET",None,None
            if body is not None and not isinstance(body,(bytes,bytearray)):raise StopPush("流式请求体遇到重定向，无法重放，请改用最终地址")
            return self.request(method,new,headers,body,label,allow_error,body_size,depth+1)
        if raw.status>=400 and not allow_error:
            detail=raw.read(4096).decode("utf-8","replace");delay=retry_delay(raw.getheader("Retry-After"));monitor.close();raise HTTPFailure(raw.status,url,detail[:600],delay)
        wrapper=CountingReader(raw,monitor);wrapper.status=raw.status;wrapper.headers=raw.headers;wrapper.monitor=monitor;wrapper.raw_response=raw
        origin_close=wrapper.close
        def close():
            monitor.close();origin_close()
        wrapper.close=close;return wrapper
    def close(self):
        for conn in list(self.pool.values()):
            with suppress(Exception):conn.close()
        self.pool.clear()
class DulwichResponse:
    def __init__(self,wrapper,url):
        self.wrapper=wrapper;self.status=wrapper.status;self.content_type=wrapper.headers.get("Content-Type");loc=wrapper.headers.get("Location")
        self.redirect_location=urljoin(url,loc) if loc and self.status in (301,302,303,307,308) else None
    def close(self):self.wrapper.close()
class StdlibGitClient(AbstractHttpGitClient):
    """把 dulwich 的智能 HTTP 协议接到自己的 http.client 传输上，从而复用测速/脱敏/重试。"""
    def __init__(self,base_url,net,**kwargs):
        self._net=net;super().__init__(base_url=base_url.rstrip("/")+"/",dumb=False,**kwargs)
    def _get_url(self,path):return urljoin(self._base_url,str(path).lstrip("/")).rstrip("/")+"/"
    def _http_request(self,url,headers=None,data=None):
        h=dict(headers or {})
        if data is not None:h.setdefault("Content-Type","application/x-git-receive-pack-request")
        w=self._net.request("GET" if data is None else "POST",url,h,data,"Git HTTP",allow_error=True)
        resp=DulwichResponse(w,url)
        if resp.status>=400 and resp.redirect_location is None:
            detail=w.read(4096).decode("utf-8","replace");delay=retry_delay(w.headers.get("Retry-After"));w.close();raise HTTPFailure(resp.status,url,detail[:600],delay)
        return resp,w.read
    def close(self):pass
def walk_candidates(repo,index,manager,config):
    """列出工作区候选文件：已跟踪路径绕过忽略规则，忽略目录中的已跟踪文件仍会被处理。"""
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
        for name in dirs:
            path=current/name;rel=os.fsencode(path.relative_to(root).as_posix())
            if (name.casefold() if os.name=="nt" else name)==".git":continue
            if path.is_symlink():add(path);continue  # 目录符号链接按链接本身存储，绝不进入目标
            if getattr(path,"is_junction",lambda:False)():raise StopPush(f"拒绝遍历 Windows junction: {path}")
            if (path/".git").exists():LOG.warning("跳过嵌套仓库（子模块需单独推送）: %s",path);continue
            if folded(rel) not in parents and old_key(rel) is None and manager.is_ignored(os.fsdecode(rel)) is True:skipped+=1;continue  # dir/* + !dir/keep 仍能进入
            keep.append(name)
        dirs[:]=keep
        for name in names:
            if (name.casefold() if os.name=="nt" else name)!=".git":add(current/name)
    LOG.info("扫描完成: %d 项 | 未跟踪且被忽略: %d 项",count,skipped);return files
def normalize_blob(data,attrs,old,repo,config,path,renormalize=False):
    """只做内建 text/eol/autocrlf/ident 处理；外部 filter 与编码转换一律报错，绝不静默改内容。"""
    if attrs.get(b"working-tree-encoding") not in (None,False):raise StopPush(f"暂不支持 working-tree-encoding: {os.fsdecode(path)}")
    selected=attrs.get(b"filter")
    if selected not in (None,False,True,b"lfs"):raise StopPush(f"不执行外部 filter={text(selected)}: {os.fsdecode(path)}")
    if attrs.get(b"ident") is True:data=re.sub(rb"\$Id:[^$\r\n]*\$",b"$Id$",data)
    text_attr=attrs.get(b"text");eol=attrs.get(b"eol");auto=cfg(config,b"core",b"autocrlf",b"false").lower()
    if text_attr is None and b"crlf" in attrs:text_attr=False if attrs[b"crlf"] is False else True
    if text_attr is False or (text_attr is None and eol is None and auto not in (b"true",b"input")):return data
    automatic=text_attr is not True and not (text_attr is None and eol in (b"lf",b"crlf"))
    nonprint=sum(data.count(bytes([b])) for b in range(32) if b not in (8,9,10,12,13,27))+data.count(b"\x7f")
    if automatic and (b"\0" in data or data.count(b"\r")!=data.count(b"\r\n") or nonprint>(len(data)-nonprint)//128):return data  # 自动判定为二进制
    if automatic and old is not None and not renormalize and old.mode!=0o160000:
        with suppress(KeyError):
            if b"\r\n" in repo.object_store[old.sha].data:return data  # 历史里本来就是 CRLF，保持一致
    converted=data.replace(b"\r\n",b"\n");safe=cfg(config,b"core",b"safecrlf",b"false").lower();core_eol=cfg(config,b"core",b"eol",b"native")
    checkout_crlf=eol==b"crlf" or (eol is None and (auto==b"true" or (auto!=b"input" and (core_eol==b"crlf" or (core_eol==b"native" and os.name=="nt")))))
    restored=converted.replace(b"\n",b"\r\n") if checkout_crlf else converted
    if safe in (b"true",b"warn") and restored!=data:
        if safe==b"true":raise StopPush(f"core.safecrlf 拒绝不可逆换行转换: {os.fsdecode(path)}")
        LOG.warning("换行转换不可逆: %s",os.fsdecode(path))
    return converted
def make_entry(st,sha,mode):
    try:return index_entry_from_stat(st,sha,mode=mode)
    except TypeError:pass
    try:
        e=index_entry_from_stat(st,sha);e.mode=mode;return e
    except TypeError:
        return IndexEntry(ctime=st.st_ctime_ns,mtime=st.st_mtime_ns,dev=st.st_dev&0xffffffff,ino=st.st_ino&0xffffffff,mode=mode,uid=getattr(st,"st_uid",0)&0xffffffff,gid=getattr(st,"st_gid",0)&0xffffffff,size=st.st_size&0xffffffff,sha=sha)
def stage_all(repo,index,a,config,cache):
    """替代 porcelain.add：直接写 Blob 和索引项，因此永远不会触发 filter.lfs.process 等外部程序。"""
    for _,entry in index.items():
        if not isinstance(entry,IndexEntry):raise StopPush("索引存在未解决冲突，拒绝自动提交")
        if stat.S_ISDIR(entry.mode) or getattr(entry,"skip_worktree",False):raise StopPush("稀疏索引/skip-worktree 不受支持")
    manager=ignore_manager(repo,config);files=walk_candidates(repo,index,manager,config);attrs=Attributes(repo,config,index)
    old_entries=dict(index.items());root=Path(repo.path);seen=set();payloads=0;auto_rules={}
    filemode=yes(config,(b"core",),b"filemode",os.name!="nt")
    def stage_one(rel,path,oldkey):
        nonlocal payloads
        st=path.lstat();old=old_entries.get(oldkey) if oldkey else None
        if stat.S_ISLNK(st.st_mode):
            data=os.fsencode(os.readlink(str(path)));mode=0o120000
        elif stat.S_ISREG(st.st_mode):
            effective=attrs.get(rel);is_lfs=effective.get(b"filter")==b"lfs"
            auto=(not a.no_auto_lfs) and (not is_lfs) and st.st_size>=a.size
            if is_lfs or auto:
                data=cache.put(path);payloads+=1
                if auto:auto_rules[rel]=os.fsdecode(rel);trace(a,"自动 LFS: %s (%s)",os.fsdecode(rel),human(st.st_size))
            else:
                if st.st_size>=a.max_blob_size:raise StopPush(f"普通 Blob 超过允许大小: {os.fsdecode(rel)} ({human(st.st_size)})；请调整 --size/--max-blob-size")
                data=normalize_blob(read_regular(path),effective,old,repo,config,rel,a.renormalize)
            executable=(filemode and bool(st.st_mode&0o111)) or ((not filemode) and old is not None and old.mode==0o100755)
            mode=0o100755 if executable else 0o100644
        else:raise StopPush(f"不支持的文件类型: {path}")
        if signature(path.lstat())!=signature(st):raise StopPush(f"暂存期间文件被修改: {path}")
        blob=Blob.from_string(data);repo.object_store.add_object(blob);entry=make_entry(st,blob.id,mode)
        with suppress(Exception):entry.size=len(data)&0xffffffff
        if mode in (0o100644,0o100755) and attrs.get(rel).get(b"filter")==b"lfs" and pointer_info(data) is None and rel not in auto_rules:raise StopPush(f"LFS 暂存验证失败: {path}")
        if oldkey is not None and oldkey!=rel:del index[oldkey]  # 仅大小写变化的重命名
        index[rel]=entry;seen.add(rel);trace(a,"暂存: %s",os.fsdecode(rel))
    for rel,(path,oldkey) in list(files.items()):
        if oldkey is not None and old_entries[oldkey].mode==0o160000:seen.add(oldkey);continue  # 子模块保持原样
        stage_one(rel,path,oldkey)
    if auto_rules:
        target=root/".gitattributes";existing=config_bytes(target);lines=existing.splitlines();add=[exact_attr_rule(n) for n in auto_rules.values()]
        new=[r for r in add if r not in lines]
        if new:
            body=existing if (not existing or existing.endswith(b"\n")) else existing+b"\n"
            atomic_write(target,body+b"\n".join(new)+b"\n");LOG.info("已为 %d 个大文件写入 .gitattributes 的 LFS 规则",len(new));attrs.invalidate()
            rel=b".gitattributes";stage_one(rel,target,rel if rel in old_entries else None)
    for rel in list(index):
        if rel in seen:continue
        path=root/os.fsdecode(rel)
        if not path.exists() and not path.is_symlink():del index[rel];trace(a,"暂存删除: %s",os.fsdecode(rel))
        elif index[rel].mode!=0o160000:del index[rel];trace(a,"暂存删除(已忽略/不可读): %s",os.fsdecode(rel))
    LOG.info("索引暂存完成 | LFS 新快照: %d | 未调用任何外部过滤器",payloads)
def tree_map(repo,head):
    if not head:return {}
    return {e.path:(e.sha,e.mode) for e in iter_tree_contents(repo.object_store,repo[head].tree)}
def check_repo_state(repo,config):
    if repo.bare:raise StopPush("自动暂存 push 需要非 bare 工作区")
    if cfg(config,b"extensions",b"objectformat",b"sha1") not in (b"sha1",b""):raise StopPush("只支持 SHA-1 仓库")
    if repo.get_shallow():raise StopPush("浅仓库尚未支持，请先补全历史")
    if cfg(config,b"extensions",b"partialclone"):raise StopPush("部分克隆尚未支持")
    if yes(config,(b"core",),b"sparsecheckout",False) or yes(config,(b"core",),b"splitindex",False):raise StopPush("稀疏检出/分裂索引仓库不自动处理")
    for name in ("MERGE_HEAD","CHERRY_PICK_HEAD","REVERT_HEAD","rebase-merge","rebase-apply","sequencer"):
        if (Path(repo.controldir())/name).exists():raise StopPush(f"仓库操作尚未结束: {name}")
    if yes(config,(b"commit",),b"gpgsign",False):raise StopPush("配置要求 GPG 签名，本脚本不调用外部签名程序")
    if (Path(repo.commondir())/"info"/"grafts").exists() or any(r.startswith(b"refs/replace/") for r in repo.refs.keys()):raise StopPush("存在 grafts/replace refs，拒绝自动提交")
def commit_staged(repo,index,a,identity,expected):
    """按暂存后的 Blob 大小切分成多个提交（LFS 只按指针大小算），全部树构建完成后再原子更新分支。"""
    chain,head=expected
    if repo.refs.follow(b"HEAD")!=expected:raise StopPush("暂存期间本地 HEAD 已变化，拒绝提交")
    ref=chain[-1] if chain and chain[-1]!=b"HEAD" else b"refs/heads/master"
    flat=tree_map(repo,head);target={p:(e.sha,e.mode) for p,e in index.items()}
    changed=[p for p in sorted(set(flat)|set(target),key=lambda p:(p in target,p)) if flat.get(p)!=target.get(p)]  # 删除排在新增前
    if not changed:LOG.info("暂存区为空，不创建空提交");return [],head
    LOG.info("变更文件: %d 个 | 前 10 项: %s",len(changed),[os.fsdecode(p) for p in changed[:10]])
    sizes={}
    for p in changed:
        sha=target.get(p,(None,))[0];sizes[p]=len(repo.object_store[sha].data) if sha else 0
    batches=[];current=[];total=0
    for p in changed:
        if current and total+sizes[p]>a.max_commit_size:batches.append(current);current=[];total=0
        current.append(p);total+=sizes[p]
    if current:batches.append(current)
    ids=[];parent=head;now=int(time.time())
    offset=datetime.now().astimezone().utcoffset();tz=int(offset.total_seconds()) if offset else 0
    for number,paths in enumerate(batches,1):
        for p in paths:
            if p in target:flat[p]=target[p]
            else:flat.pop(p,None)
        tree=commit_tree(repo.object_store,[(p,sha,mode) for p,(sha,mode) in flat.items()])
        c=Commit();c.tree=tree;c.parents=[parent] if parent else [];c.author=c.committer=identity;c.author_time=c.commit_time=now;c.author_timezone=c.commit_timezone=tz
        summary=a.message or (f"{os.fsdecode(paths[0])}" if len(paths)==1 else f"{len(paths)} files: {os.fsdecode(paths[0])} ...")
        c.message=(summary+(f" [{number}/{len(batches)}]" if len(batches)>1 else "")).encode("utf-8","surrogateescape")+b"\n"
        c.encoding=b"UTF-8";repo.object_store.add_object(c);parent=c.id;ids.append(c.id);LOG.info("提交 %d/%d: %s | 文件 %d",number,len(batches),c.id.decode()[:12],len(paths))
    if not repo.refs.set_if_equals(ref,head if head else ZERO_SHA,parent):raise StopPush("更新本地分支失败，HEAD 已被其他进程改动")
    return ids,parent
def prepare(repo,a,identity,cache):
    config=repo.get_config_stack();check_repo_state(repo,config);expected=repo.refs.follow(b"HEAD");index=repo.open_index()
    stage_all(repo,index,a,config,cache);index.write()  # 由 dulwich 用锁文件安全落盘
    return commit_staged(repo,index,a,identity,expected)
def outgoing_lfs(repo,remote_refs,target,a):
    """收集需要上传的 LFS 对象：遍历远端未知的提交，找出所有指针 Blob；顺便校验超大普通 Blob。"""
    have=set()
    for name,sha in (remote_refs or {}).items():
        if sha and sha!=ZERO_SHA and sha in repo.object_store:have.add(sha)
    seen=set();todo=[target];known_trees=set()
    for sha in list(have):
        stack=[sha]
        while stack:
            s=stack.pop()
            if s in seen or s not in repo.object_store:continue
            seen.add(s);obj=repo.object_store[s]
            if isinstance(obj,Commit):known_trees.add(obj.tree);stack.extend(obj.parents)
    pointers={};visited=set()
    while todo:
        sha=todo.pop()
        if sha in visited or sha in seen or sha not in repo.object_store:continue
        visited.add(sha);commit=repo.object_store[sha]
        if not isinstance(commit,Commit):continue
        todo.extend(commit.parents)
        if commit.tree in known_trees:continue
        for entry in iter_tree_contents(repo.object_store,commit.tree):
            if entry.mode not in (0o100644,0o100755):continue
            blob=repo.object_store[entry.sha]
            if len(blob.data)>1024:
                if len(blob.data)>=a.max_blob_size:raise StopPush(f"历史中存在超过 --max-blob-size 的普通 Blob: {os.fsdecode(entry.path)} ({human(len(blob.data))})")
                continue
            info=pointer_info(blob.data)
            if info:pointers[info[0]]=info[1]
    if pointers:LOG.info("待检查 LFS 对象: %d 个 | 合计 %s",len(pointers),human(sum(pointers.values())))
    return pointers
def upload_lfs(net,endpoint,pointers,cache,ref,done):
    """标准 LFS batch API：申请 upload/verify action，逐个上传并校验；缺失缓存直接终止，绝不只推指针。"""
    pending=[(oid,size) for oid,size in pointers.items() if (oid,size) not in done]
    if not pending:return
    for oid,size in pending:cache.require(oid,size)  # 先确认本地齐全，再开始网络请求
    for start in range(0,len(pending),100):
        chunk=pending[start:start+100]
        payload={"operation":"upload","transfers":["basic"],"ref":{"name":text(ref)},"objects":[{"oid":o,"size":s} for o,s in chunk]}
        body=json.dumps(payload).encode()
        r=net.request("POST",endpoint,{"Accept":MEDIA,"Content-Type":MEDIA},body,"LFS batch")
        try:data=json.loads(r.read().decode("utf-8","replace") or "{}")
        finally:r.close()
        objects=data.get("objects") or []
        if len(objects)!=len(chunk):raise StopPush("LFS batch 返回对象数量不符")
        for item in objects:
            oid=item.get("oid");size=int(item.get("size",-1))
            if (oid,size) not in chunk:raise StopPush("LFS batch 返回了未请求的对象")
            if item.get("error"):raise StopPush(f"LFS 服务端错误 {oid[:12]}: {item['error']}")
            actions=item.get("actions") or {}
            upload=actions.get("upload")
            if upload:
                href=upload["href"];headers=dict(upload.get("header") or {});headers.setdefault("Content-Type","application/octet-stream");headers["Content-Length"]=str(size)
                path=cache.require(oid,size);feeder=FileFeeder(path,size,None)
                LOG.info("上传 LFS %s | %s -> %s",oid[:12],human(size),safe_url(href))
                try:
                    resp=net.request("PUT",href,headers,feeder,f"LFS {oid[:12]}",body_size=size)
                    resp.read();resp.close()
                finally:feeder.close()
            verify=actions.get("verify")
            if verify:
                headers=dict(verify.get("header") or {});headers.setdefault("Content-Type",MEDIA);headers.setdefault("Accept",MEDIA)
                resp=net.request("POST",verify["href"],headers,json.dumps({"oid":oid,"size":size}).encode(),f"LFS verify {oid[:12]}");resp.read();resp.close()
            done.add((oid,size))
    missing=[o for o in pointers.items() if (o[0],o[1]) not in done]
    if missing:raise StopPush("LFS batch 漏掉请求对象，停止推送引用")
def ancestor(repo,old,new):
    if old==ZERO_SHA or old==new:return True
    todo=[new];seen=set()
    while todo:
        sha=todo.pop()
        if sha==old:return True
        if sha in seen:continue
        seen.add(sha)
        try:obj=repo.object_store[sha]
        except KeyError:raise StopPush("本地历史缺少对象，无法判断快进关系")
        if isinstance(obj,Commit):todo.extend(obj.parents)
    return False
def is_retryable(exc):
    if isinstance(exc,HTTPFailure):return exc.code in (408,425,429,500,502,503,504)
    if isinstance(exc,(NetworkFailure,HangupException,socket.timeout,TimeoutError,ConnectionError)):return True
    if isinstance(exc,GitProtocolError):return any(t in str(exc).lower() for t in ("unexpected eof","unexpected end","unexpectedly closed","expected flush","connection reset","hung up"))
    return False
def retry(a,label,operation):
    for attempt in range(1,max(1,a.retry)+1):
        if attempt>1:a.trace=True
        LOG.info("===== %s | 尝试 %d/%d =====",label,attempt,a.retry)
        try:return operation()
        except Exception as exc:
            if not is_retryable(exc) or attempt==a.retry:raise
            delay=max(a.retry_wait,getattr(exc,"retry_after",0));LOG.warning("网络错误，%.1f 秒后重试: %s",delay,exc);time.sleep(delay)
def push_target(repo,a,remote,ref,target,endpoint,auths,cache,done,lease=None):
    """每次尝试都重新读取远端公告引用；若上次响应丢失但引用已更新，按幂等成功处理。"""
    def attempt():
        net=Transport(a,auths,urlsplit(remote).scheme=="https");client=StdlibGitClient(remote,net)
        remote_progress=Progress("remote: ");pack_progress=Progress("PACK: ");observed={}
        try:
            def update(refs):
                old=refs.get(ref) or ZERO_SHA;observed["old"]=old
                if old==target:LOG.info("远端已是目标提交（幂等）: %s",target.decode()[:12]);return {}
                if lease is not None and old!=lease:raise StopPush("force-with-lease 条件不满足，远端已变化")
                if not a.force and lease is None and not ancestor(repo,old,target):raise StopPush("non-fast-forward：请先拉取合并远端历史")
                upload_lfs(net,endpoint,outgoing_lfs(repo,refs,target,a),cache,ref,done)  # LFS 失败则 pack 根本不会发送
                return {ref:target}
            def generate(have,want,**kwargs):
                kwargs["progress"]=pack_progress;return repo.generate_pack_data({s for s in have if s in repo.object_store},want,**kwargs)
            result=client.send_pack(urlsplit(remote).path,update,generate,progress=remote_progress,push_options=[v.encode() for v in a.push_option] or None,atomic=a.atomic)
            statuses=getattr(result,"ref_status",None) or {}
            if any(statuses.values()):raise StopPush("远端拒绝引用更新: "+repr(statuses))
            if observed.get("old")!=target and ref not in statuses:
                current=client.get_refs(urlsplit(remote).path).refs.get(ref) if hasattr(client.get_refs(urlsplit(remote).path),"refs") else None
                if current is not None and current!=target:raise StopPush("服务端未确认目标引用，不报告成功")
            LOG.info("推送成功: %s -> %s",text(ref),target.decode()[:12])
        finally:
            remote_progress.finish();pack_progress.finish();net.close();client.close()
    retry(a,f"推送 {safe_url(remote)} {text(ref)}",attempt)
def parse_identity(value,default_name,default_email):
    value=value.replace("，",",").replace("、",",").strip()
    if not value:return default_name,default_email
    if "," in value:
        name,email=(p.strip() for p in value.split(",",1));return name,email
    parts=value.rsplit(None,1);return (parts[0],parts[1]) if len(parts)==2 and "@" in parts[1] else (value,default_email)
def identity_for(repo,a,user,remote):
    config=repo.get_config_stack();name=text(cfg(config,b"user",b"name"));email=text(cfg(config,b"user",b"email"))
    parts=[p for p in urlsplit(remote).path.strip("/").split("/") if p];default_name=user if user and user!="x-access-token" else (parts[0] if parts else "")
    default_email=f"{default_name}@users.noreply.github.com" if urlsplit(remote).hostname in ("github.com","www.github.com") and default_name else ""
    if a.user is not None:
        name,email=(default_name,default_email) if a.user=="AUTO" else parse_identity(a.user,default_name,default_email)
    else:
        name=os.environ.get("GIT_AUTHOR_NAME",name) or name;email=os.environ.get("GIT_AUTHOR_EMAIL",email) or email
    name=a.name or name;email=a.email or email
    if not name or not email:raise StopPush("缺少提交身份；GitHub 可用 -u，其他服务器请用 --name/--email")
    if any(c in name+email for c in "\n\r\0<>") or "@" not in email:raise StopPush("提交姓名/邮箱格式无效")
    if a.user is not None or a.name or a.email:
        local=repo.get_config();local.set((b"user",),b"name",name.encode());local.set((b"user",),b"email",email.encode());local.write_to_path()
    LOG.info("提交身份: %s <%s>",name,email);return f"{name} <{email}>".encode()
def lfs_settings(repo,config,remote,remote_name,a,auths):
    section=(b"remote",remote_name.encode())
    endpoint=a.lfs_url or text(cfg(config,(b"lfs",),b"pushurl") or cfg(config,section,b"lfspushurl") or cfg(config,(b"lfs",),b"url") or cfg(config,section,b"lfsurl"))
    if not endpoint:
        path=Path(repo.path)/".lfsconfig"
        if path.exists() and not path.is_symlink():
            local=ConfigFile.from_file(io.BytesIO(read_regular(path,1024*1024)));endpoint=text(cfg(local,(b"lfs",),b"pushurl") or cfg(local,(b"lfs",),b"url"))
    base=remote[:-4] if remote.endswith(".git") else remote
    endpoint=endpoint or base+".git/info/lfs"
    clean,user,password=split_credentials(endpoint)
    if urlsplit(clean).query:raise StopPush("LFS endpoint 不能带查询串")
    token=basic(user,password)
    if token:auths[origin(clean)]=token  # 独立 endpoint 的凭据只对该 origin 生效
    return clean.rstrip("/")+"/objects/batch"
def preprocess(argv):
    out=[];i=0
    value_flags={"--repo","--repo-path","--path","-path","-p","--branch","-b","--size","-s","--threshold","--retry","-retry","-r","--retry-wait","--retry-seconds","--verbose","-v","--connect-timeout","--io-timeout","--low-speed-limit","--low-speed-time","--progress-interval","--max-commit-size","--max-pack-size","--max-blob-size","--name","--email","--proxy","--ca-file","--lfs-url","--push-option","--remote"}
    while i<len(argv):
        arg=argv[i]
        if arg in ("-m","--message","--commit-msg","--commit_msg"):
            if i+1>=len(argv):raise StopPush("-m 后缺少提交消息")
            out.extend(["--message"," ".join(argv[i+1:])]);break  # -m 之后全部视为消息
        if arg in ("-u","--user","--auto-user"):
            nxt=argv[i+1] if i+1<len(argv) else None
            if nxt and not nxt.startswith("-") and nxt!="push" and "://" not in nxt and not nxt.startswith("git@"):out.extend([arg,nxt]);i+=2;continue
            out.append(arg);i+=1;continue  # -u 单独使用不会吞掉 push / URL
        if "=" in arg and arg.startswith("--"):out.append(arg);i+=1;continue
        if arg in value_flags:
            if i+1>=len(argv):raise StopPush(f"{arg} 缺少参数")
            out.extend(argv[i:i+2]);i+=2;continue
        if arg.startswith("-"):out.append(arg)
        elif "://" in arg or arg.startswith("git@"):out.extend(["--remote",arg])
        else:out.append(arg)
        i+=1
    return out
def parser():
    p=argparse.ArgumentParser(description="Dulwich 1.2.15 + Python 标准库的 HTTP(S) 自动提交与 push（不运行外部过滤器）")
    p.add_argument("mode",nargs="?",choices=["push"],default="push");p.add_argument("--remote",default="");p.add_argument("--repo","--repo-path","--path","-path","-p",default=".")
    p.add_argument("--branch","-b",default=os.environ.get("BRANCH"));p.add_argument("--user","-u","--auto-user",nargs="?",const="AUTO");p.add_argument("--name");p.add_argument("--email")
    p.add_argument("--message","-m","--commit-msg","--commit_msg",default="");p.add_argument("--no-ask","--noask","-noask","-y","-yes",action="store_true")
    p.add_argument("--size","-s",type=parse_size,default=100*1024**2);p.add_argument("--threshold",type=int,default=0);p.add_argument("--max-blob-size",type=parse_size,default=100*1024**2)
    p.add_argument("--max-commit-size",type=parse_size,default=1900*1024**2);p.add_argument("--max-pack-size",type=parse_size,default=1900*1024**2)
    p.add_argument("--retry","-retry","-r",type=int,default=10);p.add_argument("--retry-wait","--retry-seconds",type=float,default=5);p.add_argument("--verbose","-v",type=int,default=2)
    p.add_argument("--connect-timeout",type=float,default=45);p.add_argument("--io-timeout",type=float,default=300);p.add_argument("--low-speed-limit",type=int,default=10)
    p.add_argument("--low-speed-time",type=float,default=60);p.add_argument("--progress-interval",type=float,default=.5)
    p.add_argument("--proxy");p.add_argument("--no-proxy",action="store_true");p.add_argument("--ca-file");p.add_argument("--lfs-url");p.add_argument("--no-auto-lfs",action="store_true")
    p.add_argument("--renormalize",action="store_true");p.add_argument("--force",action="store_true");p.add_argument("--force-with-lease",nargs="?",const="auto");p.add_argument("--set-upstream",action="store_true")
    p.add_argument("--push-option",action="append",default=[]);p.add_argument("--atomic",action="store_true");p.add_argument("--self-test",action="store_true")
    return p
def arguments(argv=None):
    p=parser();a=p.parse_args(preprocess(list(sys.argv[1:] if argv is None else argv)));a.trace=a.verbose>=3
    if a.threshold>0:a.size=a.threshold
    if not all(math.isfinite(x) for x in (a.connect_timeout,a.io_timeout,a.progress_interval,a.retry_wait,a.low_speed_time)):p.error("时间参数不能是 NaN 或无穷大")
    if min(a.size,a.max_blob_size,a.max_commit_size,a.max_pack_size,a.connect_timeout,a.io_timeout,a.progress_interval)<=0:p.error("大小与时间参数必须为正")
    return a
def remote_for(repo,a):
    config=repo.get_config_stack();name="origin"
    url=a.remote
    if not url:
        url=text(cfg(config,(b"remote",b"origin"),b"pushurl") or cfg(config,(b"remote",b"origin"),b"url"))
    if not url:raise StopPush("未提供远程地址，且仓库没有 origin")
    return url,name
def main(a):
    try:LOG.info("Dulwich 版本: %s | 网络: Python 标准库 http.client/socket/ssl",__import__("importlib.metadata",fromlist=["version"]).version("dulwich"))
    except Exception:LOG.info("Dulwich 版本: 未知")
    try:repo=Repo(str(Path(a.repo).expanduser().resolve()))
    except NotGitRepository as exc:raise StopPush(f"不是 Git 仓库: {a.repo}") from exc
    try:
        LOG.info("仓库路径: %s",repo.path)
        raw,name=remote_for(repo,a);remote,user,password,url_branch=normalize_remote(raw)
        if urlsplit(remote).scheme not in ("http","https"):raise StopPush("只支持 http/https 远程地址")
        config=repo.get_config_stack();auths={}
        token=basic(user,password)
        if token:auths[origin(remote)]=token
        chain,head=repo.refs.follow(b"HEAD");current=chain[-1] if chain and chain[-1]!=b"HEAD" else b"refs/heads/master"
        branch=a.branch or url_branch or os.fsdecode(current).replace("refs/heads/","")
        ref=b"refs/heads/"+branch.encode()
        LOG.info("远程地址: %s | 分支: %s",safe_url(remote),branch)
        LOG.info("LFS 阈值: %s | 最大普通 Blob: %s",human(a.size),human(a.max_blob_size))
        LOG.info("连接超时: %.0fs | 低速: %dB/s 持续 %.0fs | 每 %.2fs 输出",a.connect_timeout,a.low_speed_limit,a.low_speed_time,a.progress_interval)
        identity=identity_for(repo,a,user,remote);cache=LFSCache(repo,config);endpoint=lfs_settings(repo,config,remote,name,a,auths)
        ids,headsha=prepare(repo,a,identity,cache)
        if not headsha:raise StopPush("没有任何提交可推送")
        if ref!=current and a.branch:
            repo.refs[ref]=headsha  # 显式指定分支时同步一份本地引用
        lease=None
        if a.force_with_lease:
            lease=repo.refs.get(b"refs/remotes/"+name.encode()+b"/"+branch.encode()) or ZERO_SHA if a.force_with_lease=="auto" else a.force_with_lease.encode()
        push_target(repo,a,remote,ref,headsha,endpoint,auths,cache,set(),lease)
        if a.set_upstream:
            local=repo.get_config();local.set((b"branch",branch.encode()),b"remote",name.encode());local.set((b"branch",branch.encode()),b"merge",ref);local.write_to_path();LOG.info("已设置上游分支")
        LOG.info("完成：新增提交 %d 个",len(ids))
    finally:repo.close()
def self_test():
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    from unittest.mock import patch
    class Tests(unittest.TestCase):
        def setUp(self):
            self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/"repo";self.root.mkdir();self.repo=Repo.init(str(self.root))
            self.a=arguments(["--no-ask","--remote","https://example.invalid/u/r","-v","1"]);self.a.size=512;self.a.max_blob_size=1024*1024;self.a.progress_interval=.2;self.a.low_speed_time=0;self.a.retry=3;self.a.retry_wait=.01;self.a.connect_timeout=10;self.a.io_timeout=10
            self.identity=b"test <test@example.com>"
            config=self.repo.get_config()
            for section,key,value in (((b"user",),b"name",b"test"),((b"user",),b"email",b"test@example.com"),((b"core",),b"autocrlf",b"false"),((b"core",),b"safecrlf",b"false"),((b"core",),b"attributesfile",os.fsencode(Path(self.temp.name)/"none-attrs")),((b"core",),b"excludesfile",os.fsencode(Path(self.temp.name)/"ignore")),((b"commit",),b"gpgsign",b"false")):config.set(section,key,value)
            config.write_to_path();self.repo.get_config_stack=self.repo.get_config;self.cache=LFSCache(self.repo,config)  # 隔离全局配置与 LFS 存储
        def tearDown(self):
            self.repo.close();self.temp.cleanup()
        def write(self,name,data):
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);return path
        def stage(self):return prepare(self.repo,self.a,self.identity,self.cache)
        def test_regular_reader_stable_and_changed(self):
            p=self.write("x.bin",b"hello");self.assertEqual(read_regular(p),b"hello")  # 之前在 Windows 上因 fstat 无 inode 而误判
            self.assertEqual(config_bytes(self.root/"missing"),b"")
            with self.assertRaises(StopPush):
                with regular_reader(p) as (f,_):
                    f.read();time.sleep(.01);p.write_bytes(b"changed-content")
        def test_ignore_lfs_delete_and_no_process(self):
            self.write("tracked.tmp",b"old");self.stage();self.write("tracked.tmp",b"new")
            self.write(".gitignore",b"*.tmp\n!keep.tmp\nblocked/\nselect/*\n!select/keep.txt\nignored-large.bin\n")
            for name,data in (("drop.tmp",b"drop"),("keep.tmp",b"keep"),("blocked/no.txt",b"no"),("select/keep.txt",b"yes"),("select/no.txt",b"no"),("ignored-large.bin",b"x"*600),("has space.bin",b"a"*600),(".gitattributes",b"*.lfs filter=lfs diff=lfs merge=lfs -text\n"),("small.lfs",b"x"),("nested/.gitignore",b"!stay.tmp\n"),("nested/stay.tmp",b"stay"),("化学[上册].pdf",b"\0"*600)):self.write(name,data)
            config=self.repo.get_config();config.set((b"filter",b"lfs"),b"process",b"must-not-execute");config.set((b"filter",b"lfs"),b"required",b"true");config.write_to_path()
            with patch("subprocess.Popen",side_effect=AssertionError("禁止启动子进程")):self.stage()  # 确认不会调用 git-lfs
            index=self.repo.open_index()
            for name in (b"tracked.tmp",b"keep.tmp",b"select/keep.txt",b"nested/stay.tmp"):self.assertIn(name,index)
            for name in (b"drop.tmp",b"blocked/no.txt",b"select/no.txt",b"ignored-large.bin"):self.assertNotIn(name,index)
            for name in (b"has space.bin",b"small.lfs","化学[上册].pdf".encode()):
                info=pointer_info(self.repo.object_store[index[name].sha].data);self.assertIsNotNone(info,name)
                if name!=b"small.lfs":self.assertEqual(self.cache.path(info[0]).stat().st_size,info[1])
            self.assertEqual(self.stage()[0],[])  # 幂等：第二次没有变化就不产生提交
            (self.root/"tracked.tmp").unlink();self.stage();self.assertNotIn(b"tracked.tmp",self.repo.open_index())
        def test_auto_lfs_writes_attributes(self):
            self.write("big.bin",b"b"*700);self.stage();data=(self.root/".gitattributes").read_bytes()
            self.assertIn(b"filter=lfs",data);self.assertIn(b"/big.bin",data);self.assertIn(b".gitattributes",self.repo.open_index())
            self.stage();self.assertEqual(data.count(b"/big.bin"),(self.root/".gitattributes").read_bytes().count(b"/big.bin"))  # 规则不重复追加
        def test_global_exclude_precedence(self):
            (Path(self.temp.name)/"ignore").write_bytes(b"*.bak\n!special.dat\n");info=Path(self.repo.controldir())/"info";info.mkdir(exist_ok=True);(info/"exclude").write_bytes(b"!keep.bak\nspecial.dat\n")
            self.write("keep.bak",b"y");self.write("drop.bak",b"n");self.write("special.dat",b"n");self.stage();index=self.repo.open_index()
            self.assertIn(b"keep.bak",index);self.assertNotIn(b"drop.bak",index);self.assertNotIn(b"special.dat",index)
        def test_attr_c_quote_and_macro(self):
            self.write(".gitattributes",b"[attr]large filter=lfs -text\n\"/has space.txt\" large\n");self.write("has space.txt",b"a");self.stage()
            self.assertIsNotNone(pointer_info(self.repo.object_store[self.repo.open_index()[b"has space.txt"].sha].data))
            self.assertEqual(attr_words(b'"a\\tb.txt" text')[0],b"a\tb.txt");self.assertEqual(attr_words(b"# comment")[0],None)
            with self.assertRaises(StopPush):attr_words(b'"unterminated text')
        def test_crlf_and_unknown_filter(self):
            self.write(".gitattributes",b"*.txt text\n*.weird filter=magic\n");self.write("a.txt",b"line1\r\nline2\r\n");self.stage()
            self.assertEqual(self.repo.object_store[self.repo.open_index()[b"a.txt"].sha].data,b"line1\nline2\n")  # 入库统一 LF
            self.write("b.weird",b"x")
            with self.assertRaises(StopPush):self.stage()
        def test_symlink_does_not_walk_target(self):
            outside=Path(self.temp.name)/"outside";outside.mkdir();(outside/"private.bin").write_bytes(b"x"*1024)
            try:os.symlink(outside,self.root/"link",target_is_directory=True)
            except (OSError,NotImplementedError):self.skipTest("当前系统不允许创建符号链接")
            self.write(".gitignore",b"link/\n");self.stage();index=self.repo.open_index()
            self.assertEqual(index[b"link"].mode,0o120000);self.assertFalse(any(p.startswith(b"link/") for p in index))
        def test_split_commits_and_local_push(self):
            self.a.max_commit_size=5
            for i in range(3):self.write(f"file{i}",b"abcd")
            commits,head=self.stage();self.assertEqual(len(commits),3);self.assertEqual(head,self.repo.head())
            remote=Repo.init_bare(str(Path(self.temp.name)/"bare"),mkdir=True)
            try:
                result=LocalGitClient().send_pack(remote.path,lambda refs:{b"refs/heads/main":self.repo.head()},self.repo.generate_pack_data)
                self.assertFalse(any((getattr(result,"ref_status",None) or {}).values()));self.assertEqual(remote.refs[b"refs/heads/main"],self.repo.head())
            finally:remote.close()
        def test_history_pointer_and_large_blob(self):
            self.write("large.bin",b"q"*600);self.stage();index=self.repo.open_index();oid,size=pointer_info(self.repo.object_store[index[b"large.bin"].sha].data)
            (self.root/"large.bin").unlink();self.stage();self.assertEqual(outgoing_lfs(self.repo,{},self.repo.head(),self.a)[oid],size)  # 历史里的指针仍要上传
            self.a.no_auto_lfs=True;self.write("oversize",b"z"*700);self.stage();self.a.max_blob_size=400
            with self.assertRaises(StopPush):outgoing_lfs(self.repo,{},self.repo.head(),self.a)
        def test_missing_lfs_cache_and_ancestor(self):
            with self.assertRaises(StopPush):self.cache.require("0"*64,10)
            self.write("a",b"1");c1=self.stage()[1];self.write("a",b"2");c2=self.stage()[1]
            self.assertTrue(ancestor(self.repo,c1,c2));self.assertFalse(ancestor(self.repo,c2,c1));self.assertTrue(ancestor(self.repo,ZERO_SHA,c2))
        def test_git_smart_http_and_idempotent_push(self):
            from dulwich.server import DictBackend
            from dulwich.web import make_wsgi_chain
            from wsgiref.simple_server import make_server,WSGIRequestHandler
            class Quiet(WSGIRequestHandler):
                def log_message(self,*args):pass
            self.write("http-file",b"smart-http");self.stage()
            remote=Repo.init_bare(str(Path(self.temp.name)/"server.git"),mkdir=True)  # MemoryRepo 不支持 add_thin_pack(max_input_size)，必须用磁盘仓库
            app=make_wsgi_chain(DictBackend({"/test.git":remote}));server=make_server("127.0.0.1",0,app,handler_class=Quiet)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();url=f"http://127.0.0.1:{server.server_port}/test.git"
            try:
                with patch("subprocess.Popen",side_effect=AssertionError("禁止启动子进程")):
                    for _ in range(2):push_target(self.repo,self.a,url,b"refs/heads/main",self.repo.head(),url+"/info/lfs/objects/batch",{},self.cache,set())  # 第二次走幂等分支
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
                self.assertEqual(counters["/unauthorized"],1)  # 401 不重试
                self.assertEqual(get("/redirect"),b"")  # 跨 origin（localhost vs 127.0.0.1）不转发 Authorization
                self.write("payload",b"binary"*100);oid,size=pointer_info(self.cache.put(self.root/"payload"));done=set()
                upload_lfs(net,base+"/batch",{oid:size},self.cache,b"refs/heads/main",done)
                self.assertIn((oid,size),done);self.assertEqual(stored[oid],b"binary"*100);self.assertEqual(counters["put-path"],"/upload?signature=kept")  # 签名查询串完整保留
                upload_lfs(net,base+"/batch",{oid:size},self.cache,b"refs/heads/main",done)  # 已完成的对象不再重复上传
            finally:
                net.close();server.shutdown();server.server_close();thread.join(timeout=5)
        def test_low_speed_watchdog(self):
            class Dummy:
                closed=False
                def shutdown(self,how):self.closed=True
            sock=Dummy();self.a.progress_interval=.01;self.a.low_speed_time=.05;meter=TransferMonitor(sock,self.a,"test");deadline=time.monotonic()+3
            while not sock.closed and time.monotonic()<deadline:time.sleep(.01)
            try:
                self.assertTrue(sock.closed);self.assertIsNotNone(meter.failure);self.assertTrue(is_retryable(meter.failure))
            finally:meter.close()
        def test_cli_and_url_and_redaction(self):
            a=arguments(["-v","3","-u","push","https://user:ghp_xxxx@github.com/user/repo","--retry","4","-m","hello","world"])
            self.assertEqual(a.user,"AUTO");self.assertEqual(a.message,"hello world");self.assertEqual(a.retry,4);self.assertEqual(a.mode,"push")
            a=arguments(["--remote=https://github.com/user/repo","--proxy=http://127.0.0.1:8080","push"]);self.assertEqual(a.proxy,"http://127.0.0.1:8080")
            url,user,password,_=normalize_remote("https://me:ghp_xxxx@github.com/me/repo")
            self.assertEqual(url,"https://github.com/me/repo.git");self.assertEqual(password,"ghp_xxxx");self.assertNotIn("ghp_xxxx",redact("fail https://me:ghp_xxxx@github.com/me/repo?q=ghp_xxxx"))
            self.assertEqual(normalize_remote("git@github.com:me/repo.git")[0],"https://github.com/me/repo.git")
            self.assertEqual(normalize_remote("https://github.com/me/repo/tree/dev")[3],"dev")
            self.assertFalse(is_retryable(AttributeError("bug")));self.assertFalse(is_retryable(HTTPFailure(403,url)));self.assertTrue(is_retryable(HTTPFailure(503,url)))
            self.assertEqual(parse_size("2k"),2048);self.assertEqual(parse_identity("Tom, tom@a.com","d","d@a"),("Tom","tom@a.com"))
        def test_pointer_helpers(self):
            data=pointer_bytes("a"*64,123);self.assertEqual(pointer_info(data),("a"*64,123));self.assertIsNone(pointer_info(b"not a pointer"));self.assertIsNone(pointer_info(POINTER_PREFIX+b"oid sha256:zz\nsize 1\n"))
            self.assertIn(b'"/a b.bin"',exact_attr_rule("a b.bin"));self.assertIn(b"/plain.bin filter=lfs",exact_attr_rule("plain.bin"))
        def test_repo_state_guards(self):
            (Path(self.repo.controldir())/"MERGE_HEAD").write_bytes(b"x")
            with self.assertRaises(StopPush):self.stage()
            (Path(self.repo.controldir())/"MERGE_HEAD").unlink()
            config=self.repo.get_config();config.set((b"commit",),b"gpgsign",b"true");config.write_to_path()
            with self.assertRaises(StopPush):self.stage()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests));return 0 if result.wasSuccessful() else 1
if __name__=="__main__":
    try:
        a=arguments();setup_logging(a.verbose)
        if a.self_test:setup_logging(0);sys.exit(self_test())
        main(a)
    except KeyboardInterrupt:LOG.warning("用户中断；已创建的提交与 LFS 快照保留，可续推");sys.exit(130)
    except Exception as exc:
        if not LOG.handlers:setup_logging(2)
        LOG.error("失败: %s",exc,exc_info=LOG.isEnabledFor(logging.DEBUG));sys.exit(1)

r'''

C:\Users\Administrator\Documents\energetic>C:\QGB\anaconda3\python D:\test\github\dulwich_git\L976.py --self-test
test_attr_c_quote_and_macro (__main__.self_test.<locals>.Tests.test_attr_c_quote_and_macro) ... ok
test_auto_lfs_writes_attributes (__main__.self_test.<locals>.Tests.test_auto_lfs_writes_attributes) ... ok
test_cli_and_url_and_redaction (__main__.self_test.<locals>.Tests.test_cli_and_url_and_redaction) ... FAIL
test_crlf_and_unknown_filter (__main__.self_test.<locals>.Tests.test_crlf_and_unknown_filter) ... ok
test_git_smart_http_and_idempotent_push (__main__.self_test.<locals>.Tests.test_git_smart_http_and_idempotent_push) ... ERROR
test_global_exclude_precedence (__main__.self_test.<locals>.Tests.test_global_exclude_precedence) ... ok
test_history_pointer_and_large_blob (__main__.self_test.<locals>.Tests.test_history_pointer_and_large_blob) ... FAIL
test_ignore_lfs_delete_and_no_process (__main__.self_test.<locals>.Tests.test_ignore_lfs_delete_and_no_process) ... ok
test_low_speed_watchdog (__main__.self_test.<locals>.Tests.test_low_speed_watchdog) ... ok
test_missing_lfs_cache_and_ancestor (__main__.self_test.<locals>.Tests.test_missing_lfs_cache_and_ancestor) ... ok
test_network_retry_http_and_lfs (__main__.self_test.<locals>.Tests.test_network_retry_http_and_lfs) ... ok
test_pointer_helpers (__main__.self_test.<locals>.Tests.test_pointer_helpers) ... ok
test_regular_reader_stable_and_changed (__main__.self_test.<locals>.Tests.test_regular_reader_stable_and_changed) ... ok
test_repo_state_guards (__main__.self_test.<locals>.Tests.test_repo_state_guards) ... ok
test_split_commits_and_local_push (__main__.self_test.<locals>.Tests.test_split_commits_and_local_push) ... ok
test_symlink_does_not_walk_target (__main__.self_test.<locals>.Tests.test_symlink_does_not_walk_target) ... ERROR

======================================================================
ERROR: test_git_smart_http_and_idempotent_push (__main__.self_test.<locals>.Tests.test_git_smart_http_and_idempotent_push)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L976.py", line 891, in test_git_smart_http_and_idempotent_push
    for _ in range(2):push_target(self.repo,self.a,url,b"refs/heads/main",self.repo.head(),url+"/info/lfs/objects/batch",{},self.cache,set())  # 第二次走幂等分支
                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L976.py", line 687, in push_target
    retry(a,f"推送 {safe_url(remote)} {text(ref)}",attempt)
  File "D:\test\github\dulwich_git\L976.py", line 659, in retry
    try:return operation()
               ^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L976.py", line 678, in attempt
    result=client.send_pack(urlsplit(remote).path,update,generate,progress=remote_progress,push_options=[v.encode() for v in a.push_option] or None,atomic=a.atomic)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\client.py", line 4851, in send_pack
    self._discover_references(b"git-receive-pack", url)
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\client.py", line 4628, in _discover_references
    resp, read = self._http_request(url, headers)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L976.py", line 416, in _http_request
    detail=w.read(4096).decode("utf-8","replace");delay=retry_delay(w.headers.get("Retry-After"));w.close();raise HTTPFailure(resp.status,url,detail[:600],delay)
                                                                                                            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
HTTPFailure: HTTP 404 http://127.0.0.1:50133/test.git/test.git/info/refs No git repository was found at /test.git/test.git

======================================================================
ERROR: test_symlink_does_not_walk_target (__main__.self_test.<locals>.Tests.test_symlink_does_not_walk_target)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L976.py", line 860, in test_symlink_does_not_walk_target
    self.assertEqual(index[b"link"].mode,0o120000);self.assertFalse(any(p.startswith(b"link/") for p in index))
                     ~~~~~^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\index.py", line 1256, in __getitem__
    return self._byname[self.canonical_path(key)]
           ~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^
KeyError: b'link'

======================================================================
FAIL: test_cli_and_url_and_redaction (__main__.self_test.<locals>.Tests.test_cli_and_url_and_redaction)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L976.py", line 950, in test_cli_and_url_and_redaction
    self.assertEqual(a.user,"AUTO");self.assertEqual(a.message,"hello world");self.assertEqual(a.retry,4);self.assertEqual(a.mode,"push")
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: 'push' != 'AUTO'
- push
+ AUTO


======================================================================
FAIL: test_history_pointer_and_large_blob (__main__.self_test.<locals>.Tests.test_history_pointer_and_large_blob)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L976.py", line 874, in test_history_pointer_and_large_blob
    with self.assertRaises(StopPush):outgoing_lfs(self.repo,{},self.repo.head(),self.a)
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: StopPush not raised

----------------------------------------------------------------------
Ran 16 tests in 4.463s

FAILED (failures=2, errors=2)
'''
        