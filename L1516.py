#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pure_push.py —— 只用 dulwich(1.2.15) + Python 标准库实现的“全功能 git push”。
能力：自动 add -A（正确处理 .gitignore / info/exclude / core.excludesFile / core.ignorecase / 已跟踪文件绕过忽略）、
.gitattributes（filter=lfs、text/eol/autocrlf/ident、binary 宏、C 引号路径、全局<根<子目录<info/attributes 优先级）、
Git LFS（本地缓存、指针识别、历史增量扫描、batch API、上传、verify、签名地址凭据隔离）、
按大小自动拆分提交、纯 http.client/socket/ssl 的 Smart HTTP 传输（代理、重定向、凭据脱敏、指数退避重试、Retry-After）、
上传时实时显示连接详情（TLS 版本/加密套件/本地与对端地址/代理）与实时速度（瞬时、平均、百分比、ETA），
低速看门狗自动掐断卡死连接；--self-test 是完全离线的详细自测。
用法：python pure_push.py -v 3 -u push https://user:token@github.com/user/repo
"""
from __future__ import annotations
import argparse,base64,errno,hashlib,http.client,inspect,io,json,logging,os,re,shutil,socket,ssl,stat,sys,tempfile,threading,time,unittest
from collections import deque
from contextlib import contextmanager,suppress
from datetime import datetime
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from importlib.metadata import version as pkg_version
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote,urljoin,urlsplit,urlunsplit
from urllib.request import getproxies,proxy_bypass
from dulwich.client import AbstractHttpGitClient
from dulwich.config import ConfigFile,apply_instead_of
from dulwich.errors import NotGitRepository
from dulwich.file import GitFile
from dulwich.ignore import IgnoreFilter,IgnoreFilterManager,default_user_ignore_filter_path
from dulwich.index import IndexEntry,commit_tree,index_entry_from_stat,write_index_dict
from dulwich.object_store import iter_tree_contents
from dulwich.objects import Blob,Commit
from dulwich.pack import SHA1Writer
from dulwich.repo import Repo
try:from dulwich.protocol import ZERO_SHA
except Exception:ZERO_SHA=b"0"*40
try:from dulwich.index import validate_path,get_path_element_validator
except Exception:
    def get_path_element_validator(config=None):return None  # 老版本 dulwich 没有路径校验器，用内置规则兜底
    def validate_path(path,validator=None):
        if not path or b"\0" in path or path.startswith(b"/") or path.endswith(b"/"):return False
        return all(e and e not in (b".",b"..") for e in path.split(b"/"))
try:from dulwich.refs import check_ref_format
except Exception:check_ref_format=lambda r:bool(re.fullmatch(rb"[A-Za-z0-9._/\-]+",r)) and not (r.endswith(b".lock") or b".." in r or r.startswith(b"/"))
LOG=logging.getLogger("PurePush");SECRETS=set();CHUNK=64*1024
try:AGENT="git/2.45 (pure-push; dulwich+%s)"%pkg_version("dulwich")
except Exception:AGENT="git/2.45 (pure-push; dulwich+unknown)"
POINTER_PREFIX=b"version https://git-lfs.github.com/spec/v1\n";MEDIA="application/vnd.git-lfs+json"
class StopPush(RuntimeError):pass  # 明确失败，重试也没用（必须先由用户处理）
class NetworkFailure(RuntimeError):pass  # 网络层失败，可重试
class HTTPFailure(StopPush):
    def __init__(self,code,url,detail="",retry_after=0.0):
        super().__init__("HTTP %s %s %s"%(code,safe_url(url),(detail or "").strip()[:400]));self.code=int(code);self.retry_after=float(retry_after or 0)
    @property
    def retryable(self):return self.code in (408,425,429) or self.code>=500  # 401/403/404/422 是配置问题，重试只是浪费时间
def remember(secret):
    if secret and len(str(secret))>3:SECRETS.add(str(secret))  # 记录令牌/密码，日志统一打码
def safe_url(value):
    try:  # 日志里的 URL 一律去掉 user:password 与 query（LFS 签名上传地址含临时令牌）
        p=urlsplit(str(value));host=p.hostname or "";host="[%s]"%host if ":" in host else host
        return urlunsplit((p.scheme,host+((":%d"%p.port) if p.port else ""),p.path,"",""))
    except ValueError:return "[URL 已隐藏]"
def redact(value):
    t=str(value)
    for s in sorted(SECRETS,key=len,reverse=True):t=t.replace(s,"***")
    return re.sub(r"(https?|ssh|git|ftp)://[^\s\"'<>]+",lambda m:safe_url(m.group()),t).replace("\x1b","\\x1b")
class SafeFormatter(logging.Formatter):
    def format(self,record):return redact(super().format(record))  # 连 traceback 一起脱敏；绝不使用 http.client 的 debuglevel
def setup_logging(v):
    h=logging.StreamHandler(sys.stdout);h.setFormatter(SafeFormatter("%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s","%Y-%m-%d %H:%M:%S"))
    LOG.handlers[:]=[h];LOG.propagate=False;LOG.setLevel({0:logging.ERROR,1:logging.WARNING,2:logging.INFO}.get(v,logging.DEBUG))
def trace(a,msg,*args):
    if getattr(a,"trace",False):LOG.log(logging.DEBUG if getattr(a,"verbose",0)>=3 else logging.INFO,msg,*args)
def text(v):return v.decode("utf-8","surrogateescape") if isinstance(v,(bytes,bytearray)) else str(v)
def human(n):
    units=("B","KiB","MiB","GiB","TiB");n=float(n);i=0
    while n>=1024 and i<len(units)-1:n/=1024.0;i+=1
    return ("%d B"%int(n)) if i==0 else ("%.2f %s"%(n,units[i]))
def elapsed(sec):
    sec=max(0,int(sec));h,m=divmod(sec,3600);m,s=divmod(m,60)
    return ("%dh%02dm%02ds"%(h,m,s)) if h else (("%dm%02ds"%(m,s)) if m else ("%ds"%s))
def cfg(config,section,key,default=b""):
    section=(section,) if isinstance(section,bytes) else tuple(section)
    try:return config.get(section,key)
    except Exception:return default  # dulwich 对缺失项抛 KeyError，对类型问题抛别的异常，统一兜底
def yes(config,section,key,default=False):
    try:return config.get_boolean(tuple(section) if not isinstance(section,tuple) else section,key,default)
    except Exception:return default
def stable(st):return (st.st_size,st.st_mtime_ns)  # 只比大小与修改时间：Windows 上“按路径 lstat”和“按句柄 fstat”的 dev/ino/mode/ctime 本来就可能不同，比它们会误报“文件已变化”
def signature(st):return stable(st)  # 兼容旧名字
def atomic_write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)  # 临时文件与目标同目录，失败不留半写文件，也不覆盖符号链接
    if path.is_symlink():raise StopPush("拒绝覆盖符号链接: %s"%path)
    mode=stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd,tmp=tempfile.mkstemp(prefix=".purepush-",dir=str(path.parent))
    try:
        with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,mode);os.replace(tmp,str(path))
    finally:
        with suppress(OSError):os.unlink(tmp)
@contextmanager
def regular_reader(path,limit=None):
    """安全读取普通文件。关键修复：一致性判断只用“同一句柄”的 fstat 前后快照，
    不再把 lstat(路径) 与 fstat(句柄) 直接比较——那是 L988 在 Windows 上必然误报“读取前文件已经变化”的根因。"""
    path=Path(path)
    try:before=path.lstat()
    except OSError as e:raise StopPush("无法访问文件: %s (%s)"%(path,e.strerror or e)) from e
    if stat.S_ISLNK(before.st_mode):raise StopPush("拒绝跟随符号链接读取: %s"%path)
    if not stat.S_ISREG(before.st_mode):raise StopPush("不是普通文件: %s"%path)
    fd=os.open(str(path),os.O_RDONLY|getattr(os,"O_BINARY",0)|getattr(os,"O_NOFOLLOW",0))  # Windows 无 O_BINARY/O_NOFOLLOW 时取 0
    try:f=os.fdopen(fd,"rb")
    except Exception:os.close(fd);raise
    with f:
        opened=os.fstat(f.fileno())  # 打开后立即取句柄快照，作为本次读取的唯一基准
        if not stat.S_ISREG(opened.st_mode):raise StopPush("打开后不是普通文件: %s"%path)
        if limit is not None and opened.st_size>limit:raise StopPush("文件超过允许大小 %s: %s"%(human(limit),path))
        yield f,opened
        if stable(os.fstat(f.fileno()))!=stable(opened):raise StopPush("读取期间文件发生变化，请重试本地操作: %s"%path)
def read_regular(path,limit=None):
    with regular_reader(path,limit) as (f,st):return f.read(),st
def config_bytes(path):
    path=Path(path)
    if path.is_symlink():return b""  # 配置文件是符号链接时按空处理，避免被链接内容左右
    try:data,_=read_regular(path,8*1024*1024);return data
    except (OSError,StopPush):return b""
class SafeIgnore(IgnoreFilterManager):
    """dulwich 1.2.15 忽略管理器：True=忽略，False=! 重新包含，None=无匹配。这里加固符号链接语义。"""
    def _load_path(self,path):
        if (Path(self._top_path)/path/".gitignore").is_symlink():return None  # 被链接的 .gitignore 不可信，视为不存在
        return super()._load_path(path)
    def _is_dir(self,path):
        p=Path(self._top_path)/path
        return path.endswith("/") or (p.is_dir() and not p.is_symlink())  # 符号链接目录按“文件”处理，dir/ 规则不匹配它
def ignore_manager(repo,config):
    ignorecase=yes(config,(b"core",),b"ignorecase",os.name=="nt");filters=[]
    default=os.fsencode(str(Path(os.environ.get("XDG_CONFIG_HOME",str(Path.home()/".config")))/"git"/"ignore"))
    try:global_path=Path(text(default_user_ignore_filter_path(config))).expanduser()
    except Exception:global_path=Path(text(default)).expanduser()
    for p in (global_path,Path(repo.controldir())/"info"/"exclude"):
        try:filters.append(IgnoreFilter.from_path(p,ignorecase))  # 顺序即优先级：全局最低，info/exclude 次之，工作区各级 .gitignore 最高
        except Exception:pass
    return SafeIgnore(str(repo.path),filters,ignorecase)
def c_unquote(line):
    """解析 .gitattributes 的 C 风格引号路径（dulwich 的简单 split 不识别含空格的引号路径）。返回 (pattern, tokens)。"""
    line=line.strip()
    if not line or line.startswith(b"#"):return None,[]
    if not line.startswith(b'"'):
        words=line.split();return (words[0],words[1:]) if words else (None,[])
    out=bytearray();i=1;esc={ord("a"):7,ord("b"):8,ord("t"):9,ord("n"):10,ord("v"):11,ord("f"):12,ord("r"):13,34:34,92:92}
    while i<len(line):
        b=line[i];i+=1
        if b==34:return bytes(out),line[i:].split()  # 引号闭合，其后按空白切分成属性 token
        if b!=92:out.append(b);continue
        if i>=len(line):break
        b=line[i];i+=1
        if 48<=b<=55:
            digits=bytes([b])
            while i<len(line) and 48<=line[i]<=55 and len(digits)<3:digits+=bytes([line[i]]);i+=1
            v=int(digits,8)
            if v>255:raise StopPush("属性路径的八进制转义超出字节范围")
            out.append(v)
        elif b in esc:out.append(esc[b])
        else:raise StopPush(".gitattributes 中存在不支持的 C 转义: \\%s"%chr(b))
    raise StopPush(".gitattributes 的路径引号没有闭合")
def parse_attribute(token):
    if token[:1]==b"-":return token[1:],False  # -text：显式取消
    if token[:1]==b"!":return token[1:],None  # !attr：视为未指定，从结果里剔除
    if b"=" in token:k,v=token.split(b"=",1);return k,v
    return token,True
def wildmatch(pattern):
    """把 git 通配符翻译成 bytes 正则：* 不跨 /，? 匹配单字符，** 跨目录，[...] 字符类。"""
    out=[b"(?s)"];i=0;n=len(pattern)
    while i<n:
        c=pattern[i:i+1]
        if c==b"*":
            if pattern[i:i+3]==b"**/":out.append(b"(?:.*/)?");i+=3
            elif pattern[i:i+2]==b"**":out.append(b".*");i+=2
            else:out.append(b"[^/]*");i+=1
        elif c==b"?":out.append(b"[^/]");i+=1
        elif c==b"[":
            j=i+1;buf=b"";neg=False
            if j<n and pattern[j:j+1] in (b"!",b"^"):neg=True;j+=1
            while j<n and pattern[j:j+1]!=b"]":buf+=pattern[j:j+1];j+=1
            if j>=n:out.append(re.escape(b"["));i+=1;continue
            i=j+1
            out.append((b"[^]" if neg and not buf else b"[")+(b"^" if neg else b"")+buf.replace(b"\\",b"\\\\")+b"]")
        else:out.append(re.escape(c));i+=1
    out.append(b"$")
    return re.compile(b"".join(out))
class Attributes:
    """自实现的 .gitattributes 合并：全局 < 根 < 逐级子目录 < info/attributes；支持 [attr] 宏、取消属性、C 引号路径。
    不依赖 dulwich.attrs，避免各版本 Pattern 行为差异。"""
    MACROS={b"binary":[(b"diff",False),(b"merge",False),(b"text",False)]}
    def __init__(self,repo,config,index):
        self.repo=repo;self.root=Path(repo.path);self.index=index;self.cache={}
        default=os.fsencode(str(Path(os.environ.get("XDG_CONFIG_HOME",str(Path.home()/".config")))/"git"/"attributes"))
        self.global_path=Path(text(cfg(config,(b"core",),b"attributesfile",default))).expanduser()
        self.info=Path(repo.controldir())/"info"/"attributes"
    def load(self,path,relative=None,macro_allowed=True):
        key=str(path)
        if key in self.cache:return self.cache[key]
        data=config_bytes(path)
        if not data and relative is not None and relative in self.index:  # 工作区里被删但索引仍在：用已提交内容
            entry=self.index[relative]
            if entry.mode in (0o100644,0o100755):
                with suppress(Exception):data=self.repo.object_store[entry.sha].data
        rules=[];macros={}
        for line in data.splitlines():
            try:pattern,tokens=c_unquote(line)
            except StopPush as e:LOG.warning("%s（%s）",e,path);continue
            if pattern is None:continue
            values=[parse_attribute(t) for t in tokens]
            if pattern.startswith(b"[attr]"):
                if macro_allowed:macros[pattern[6:]]=values
                else:LOG.warning("忽略子目录中不允许定义的属性宏: %s",path)
            elif pattern.startswith(b"!"):raise StopPush(".gitattributes 不允许负模式: %s"%text(pattern))
            else:rules.append((pattern,values))
        self.cache[key]=(rules,macros);return rules,macros
    @staticmethod
    def match(pattern,rel):
        body=pattern[1:] if pattern.startswith(b"/") else pattern  # 前导 / 表示锚定到该属性文件所在目录
        if body.endswith(b"/"):body=body[:-1]  # 尾随 / 只对目录有意义，匹配文件时去掉
        if b"/" in body:return bool(wildmatch(body).match(rel))  # 含斜杠：按相对路径锚定匹配
        return bool(wildmatch(body).match(rel.rsplit(b"/",1)[-1]))  # 不含斜杠：匹配 basename
    def get(self,rel):
        parts=rel.split(b"/");levels=[(self.global_path,rel,None,True)]
        for i in range(len(parts)):
            name=b"/".join(parts[:i]+[b".gitattributes"]);levels.append((self.root/os.fsdecode(name),b"/".join(parts[i:]),name,i==0))
        levels.append((self.info,rel,None,True))
        loaded=[(self.load(p,key,macros),local) for p,local,key,macros in levels]
        definitions=dict(self.MACROS)
        for (_,macros),_ in loaded:definitions.update(macros)  # 越靠近路径/info 的宏定义覆盖越外层的
        result={}
        def apply(values,seen=frozenset()):
            for name,value in values:
                result[name]=value
                if value is True and name in definitions:
                    if name in seen:raise StopPush("属性宏循环引用: %s"%text(name))
                    apply(definitions[name],seen|{name})
        for (rules,_),local in loaded:
            for pattern,values in rules:
                if self.match(pattern,local):apply(values)
        return {k:v for k,v in result.items() if v is not None}  # !attr 得到 None，必须剔除
def pointer_bytes(oid,size):return POINTER_PREFIX+b"oid sha256:"+oid.encode()+b"\nsize %d\n"%size
def pointer_info(data):
    """识别 LFS 指针；返回 (oid,size) 或 None。指针必然很短，长文件直接排除，避免无谓解析。"""
    if not data.startswith(POINTER_PREFIX) or len(data)>200 or b"\n\n" in data:return None
    oid=None;size=None
    for line in data.splitlines()[1:]:
        if line.startswith(b"oid sha256:"):
            v=text(line[11:].strip());oid=v if re.fullmatch(r"[0-9a-f]{64}",v) else None
        elif line.startswith(b"size "):
            v=line[5:].strip()
            if v.isdigit():size=int(v)
    return (oid,size) if oid and size is not None and size>=0 else None
class LfsCache:
    """Git LFS 本地缓存：<lfsdir>/objects/<oid[:2]>/<oid[2:4]>/<oid>；同目录临时文件 + os.replace 落盘。"""
    def __init__(self,repo,a):
        d=text(cfg(repo.get_config(),(b"lfs",),b"storage",b"lfs"))
        self.dir=Path(d) if Path(d).is_absolute() else Path(repo.controldir())/d
        self.objects=self.dir/"objects";self.tmp=self.dir/"tmp";self.a=a;self.verified={}
    def path(self,oid):return self.objects/oid[:2]/oid[2:4]/oid
    def put(self,path,expected_oid=None):
        """把工作区文件搬进 LFS 缓存并返回指针内容；边写边算 sha256，不二次读盘。"""
        path=Path(path);h=hashlib.sha256();total=0;last=time.monotonic()
        self.tmp.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix="lfs-",dir=str(self.tmp))
        try:
            with os.fdopen(fd,"wb") as out,regular_reader(path) as (f,st):
                while True:
                    block=f.read(CHUNK)
                    if not block:break
                    out.write(block);h.update(block);total+=len(block)
                    if time.monotonic()-last>=1.0:LOG.info("LFS 本地快照: %s | %s/%s",path.name,human(total),human(st.st_size));last=time.monotonic()
                out.flush();os.fsync(out.fileno())
                expected_size=st.st_size
            oid=h.hexdigest()
            if expected_oid and oid!=expected_oid:raise StopPush("LFS 内容校验失败: 期望 %s 实得 %s"%(expected_oid,oid))
            if total!=expected_size:raise StopPush("LFS 快照期间文件被修改: %s"%path)
            dest=self.path(oid);dest.parent.mkdir(parents=True,exist_ok=True)
            with suppress(OSError):os.chmod(name,0o444)  # LFS 对象按 git 习惯置为只读
            try:os.replace(name,str(dest))
            except OSError:  # Windows 上覆盖只读目标会 PermissionError，先去掉只读位再替换
                with suppress(OSError):os.chmod(str(dest),0o644)
                os.replace(name,str(dest))
            self.verified[oid,total]=stable(dest.stat());return pointer_bytes(oid,total)
        finally:
            with suppress(OSError):os.unlink(name)
    def require(self,oid,size):
        """推送前确认缓存里真有该对象；只发指针不发内容会造成远端永久缺数据，必须硬失败。"""
        p=self.path(oid)
        if not p.is_file() or p.is_symlink():raise StopPush("远端需要 LFS 对象 %s，但本地缓存不存在；请恢复原文件或缓存后再推送"%oid[:12])
        if self.verified.get((oid,size))!=stable(p.stat()):
            h=hashlib.sha256();total=0
            with regular_reader(p) as (f,_):
                for block in iter(lambda:f.read(1024*1024),b""):h.update(block);total+=len(block)
            if total!=size or h.hexdigest()!=oid:raise StopPush("LFS 缓存损坏或大小不符: %s"%oid[:12])
            self.verified[oid,size]=stable(p.stat())
        return p
def parse_url(value,branch=None):
    """把各种写法归一为 (https://host/owner/repo.git, user, password, branch)：支持 scp 式、GitHub 网页 URL、带凭据 URL。"""
    raw=str(value or "").strip()
    if not raw:raise StopPush("必须提供远程地址（-u）")
    user=password=None
    m=re.fullmatch(r"(?:ssh://)?(?:([^@/]+)@)?([\w.\-]+):(?!//)(.+?)/?",raw)
    if m and "://" not in raw:  # git@github.com:user/repo.git 这类 scp 语法
        user=m.group(1) or "git";raw="https://%s/%s"%(m.group(2),m.group(3).strip("/"));LOG.warning("已把 scp 风格地址转换为 HTTPS: %s",raw)
    if "://" not in raw:raw="https://"+raw.lstrip("/")
    p=urlsplit(raw)
    if p.scheme not in ("http","https"):raise StopPush("本实现只支持 http/https 远程，不支持 %s（那需要 SSH 库）"%p.scheme)
    if p.username:user=unquote(p.username)
    if p.password:password=unquote(p.password)
    parts=[x for x in p.path.split("/") if x]
    if not parts:raise StopPush("远程地址缺少仓库路径: %s"%safe_url(raw))
    if parts[0] in ("tree","blob","commits","blame","raw"):raise StopPush("URL 结构异常，缺少 owner: %s"%safe_url(raw))
    if len(parts)>2 and parts[1] in ("tree","blob","commits","blame"):  # https://github.com/owner/repo/tree/branch/...
        seg=parts[3] if parts[1] in ("tree","blob") and len(parts)>3 else parts[2]
        if branch is None:branch=unquote(seg);LOG.warning("从网页路径推断分支 %s；含斜杠的分支请用 --branch 显式指定",branch)
    owner_repo="/".join(parts[:2])
    if user:remember(user)
    if password:remember(password)
    clean=urlunsplit((p.scheme,"%s%s"%(p.hostname or "",(":%d"%p.port) if p.port else ""),"/"+owner_repo.removesuffix(".git")+".git","",""))
    return clean,user,password,(branch or "master")
def origin(url):
    p=urlsplit(str(url));return urlunsplit((p.scheme,"%s%s"%(p.hostname or "",(":%d"%p.port) if p.port else ""),"","",""))  # 同源判断用于凭据隔离
def retry_delay(value):
    if not value:return 0.0
    try:return max(0.0,min(120.0,float(value)))
    except ValueError:pass
    try:return max(0.0,min(120.0,(parsedate_to_datetime(value)-datetime.now().astimezone()).total_seconds()))
    except Exception:return 0.0
def describe_socket(sock,proxy_text=None):
    """连接详情：本地/对端地址、TLS 版本与加密套件、代理。这就是“实时显示连接详情”的内容来源。"""
    try:local=sock.getsockname();peer=sock.getpeername()
    except Exception:return "连接详情不可用"
    tls=""
    with suppress(Exception):
        raw=getattr(sock,"_sslobj",None) or (sock if isinstance(sock,ssl.SSLSocket) else None)
        if raw is not None:
            cipher=raw.cipher() or ()
            tls=" | %s %s"%(raw.version() or "?",cipher[0] if cipher else "?")
    return "%s:%s → %s:%s%s%s"%(local[0],local[1],peer[0],peer[1],tls,(" | 代理 %s"%proxy_text) if proxy_text else "")
class TransferMonitor:
    """实时速度 + 连接详情 + 低速看门狗。pack 上传与 LFS 上传共用。"""
    def __init__(self,sock,a,label,total=None,tty=None):
        self.sock=sock;self.a=a;self.label=label;self.total=total;self.sent=0;self.recv=0
        self.start=time.monotonic();self.window=deque();self.lock=threading.Lock()
        self.stalled=False;self.closed=False;self.last_report=0.0
        self.tty=(bool(sys.stdout.isatty()) if tty is None else bool(tty))
        self.conn_text=describe_socket(sock,getattr(a,"proxy_text",None))
        self.thread=threading.Thread(target=self._loop,name="monitor-%s"%label,daemon=True);self.thread.start()
    def add(self,n,direction=1):
        if not n:return
        now=time.monotonic()
        with self.lock:
            if direction>0:self.sent+=n
            else:self.recv+=n
            self.window.append((now,n))
            while self.window and now-self.window[0][0]>self.a.speed_window:self.window.popleft()
    def rate(self):
        now=time.monotonic()
        with self.lock:
            w=[(t,n) for t,n in self.window if now-t<=self.a.speed_window]
            span=now-(w[0][0] if w else now)
            return (sum(n for _,n in w)/span) if span>0.05 else 0.0
    def average(self):
        d=time.monotonic()-self.start;return (self.sent+self.recv)/d if d>0 else 0.0
    def line(self):
        done=self.sent+self.recv;rate=self.rate();extra=""
        if self.total:
            extra=" (%.1f%%)"%(100.0*min(done,self.total)/self.total)
            if rate>1 and done<self.total:extra+=" | 剩余 %s"%elapsed((self.total-done)/rate)
        return "%s | %s/%s%s | 实时 %.2f/s | 平均 %.2f/s | 已用 %s"%(self.label,human(done),human(self.total) if self.total else "?",extra,rate,self.average(),elapsed(time.monotonic()-self.start))
    def _loop(self):
        low_since=None
        while not self.closed:
            time.sleep(min(0.05,max(0.005,self.a.progress_interval/4.0)))
            now=time.monotonic()
            if not self.closed and now-self.last_report>=self.a.progress_interval:self.last_report=now;self.report()
            if self.a.low_speed_time>0:
                if self.rate()<self.a.low_speed_limit:
                    if low_since is None:low_since=now
                    elif now-low_since>=self.a.low_speed_time:
                        self.stalled=True
                        LOG.error("速度低于 %s/s 已持续 %ds，主动断开: %s",human(self.a.low_speed_limit),self.a.low_speed_time,self.label)
                        with suppress(Exception):self.sock.shutdown(socket.SHUT_RDWR)
                        with suppress(Exception):self.sock.close()
                        self.closed=True;return
                else:low_since=None
    def report(self):
        if self.tty:sys.stdout.write("\r\x1b[K%s | %s"%(self.line(),self.conn_text));sys.stdout.flush()
        else:LOG.info("%s | %s",self.line(),self.conn_text)
    def stop(self,final=True):
        if self.closed and not final:return
        self.closed=True
        with suppress(Exception):self.thread.join(timeout=1.0)
        if self.tty:sys.stdout.write("\r\x1b[K");sys.stdout.flush()
        if final:LOG.info("%s | 完成 %s | 平均 %.2f/s | 用时 %s | %s",self.label,human(self.sent+self.recv),self.average(),elapsed(time.monotonic()-self.start),self.conn_text)
class Response:
    def __init__(self,raw,url):
        self.raw=raw;self.url=url;self.status=int(raw.status);self.code=self.status;self.reason=raw.reason
        self.headers=raw.msg;self.msg=raw.msg;self.will_close=bool(getattr(raw,"will_close",False))
        self.had_auth=False;self.monitor=None;self._body=None;self._closed=False
    def getheader(self,name,default=None):return self.raw.getheader(name,default)
    def getheaders(self):return self.raw.getheaders()
    def info(self):return self.headers
    def geturl(self):return self.url
    def _read_all(self):
        if self._body is None:
            chunks=[]
            while True:
                block=self.raw.read(CHUNK)
                if not block:break
                chunks.append(block)
                if self.monitor is not None:self.monitor.add(len(block),-1)  # 下载方向单独计数
            self._body=b"".join(chunks)
        return self._body
    def read(self,n=-1):
        body=self._read_all()
        if n is None or n<0:return body
        self._body=body[n:];return body[:n]
    def close(self):
        if self._closed:return
        self._closed=True
        if self.monitor is not None:self.monitor.stop();self.monitor=None
        with suppress(Exception):self.raw.close()
class Transport:
    """纯标准库 HTTP(S) 客户端：http.client + socket + ssl。支持代理、重定向（跨源丢弃凭据）、连接复用与失效重连、实时测速。"""
    def __init__(self,a,creds=None):
        self.a=a;self.creds=dict(creds or {});self.conns={};self.lock=threading.Lock();self.requests=0;self.bytes_sent=0;self.bytes_recv=0;self._monitor=None
    def close(self):
        with self.lock:
            for c in self.conns.values():
                with suppress(Exception):c.close()
            self.conns.clear()
    def __enter__(self):return self
    def __exit__(self,*exc):self.close()
    @staticmethod
    def ssl_context():
        ctx=ssl.create_default_context()  # 校验证书与主机名，禁止降级
        with suppress(Exception):ctx.minimum_version=ssl.TLSVersion.TLSv1_2
        ctx.options|=ssl.OP_NO_COMPRESSION
        return ctx
    def _proxy_for(self,p):
        if self.a.no_proxy:return None
        if p.hostname and proxy_bypass(p.hostname):return None
        return getproxies().get(p.scheme)
    def _connect(self,p,proxy):
        key=(p.scheme,p.hostname,p.port,proxy)
        with self.lock:
            conn=self.conns.get(key)
            if conn is not None and getattr(conn,"sock",None) is not None:return conn,False
        timeout=self.a.timeout;ctx=self.ssl_context()
        if proxy:
            pp=urlsplit(proxy if "://" in proxy else "http://"+proxy)
            conn=http.client.HTTPSConnection(pp.hostname,pp.port or 80,timeout=timeout,context=ctx) if p.scheme=="https" else http.client.HTTPConnection(pp.hostname,pp.port or 80,timeout=timeout)
            if p.scheme=="https":
                if isinstance(conn,http.client.HTTPSConnection):conn.set_tunnel(p.hostname,p.port or 443)  # CONNECT 隧道
                else:conn=http.client.HTTPSConnection(pp.hostname,pp.port or 80,timeout=timeout,context=ctx);conn.set_tunnel(p.hostname,p.port or 443)
            self.a.proxy_text="%s:%s"%(pp.hostname,pp.port or 80)
        elif p.scheme=="https":
            conn=http.client.HTTPSConnection(p.hostname,p.port or 443,timeout=timeout,context=ctx);self.a.proxy_text=None
        else:
            conn=http.client.HTTPConnection(p.hostname,p.port or 80,timeout=timeout);self.a.proxy_text=None
        conn.connect()  # 立即建连，这样监控线程一开始就能拿到 socket 与 TLS 详情
        LOG.info("已连接 %s | %s",safe_url(urlunsplit((p.scheme,"%s%s"%(p.hostname,(":%d"%p.port) if p.port else ""),"","","")),describe_socket(conn.sock,self.a.proxy_text))
        with self.lock:self.conns[key]=conn
        return conn,True
    def _drop(self,p,proxy):
        with self.lock:
            key=(p.scheme,p.hostname,p.port,proxy);conn=self.conns.pop(key,None)
        if conn is not None:
            with suppress(Exception):conn.close()
    def request(self,method,url,headers=None,body=None,label="HTTP",allow_error=False,total=None):
        """body 可为 bytes / 可迭代对象 / (文件对象, 大小)。返回 Response（响应体已读入内存并计数）。"""
        redirects=0;current=url;auth_retried=False
        while True:
            resp=self._once(method,current,headers,body,label,total)
            if resp.status in (301,302,303,307,308) and resp.getheader("Location"):
                redirects+=1
                if redirects>self.a.max_redirects:raise HTTPFailure(resp.status,current,"重定向次数过多")
                target=urljoin(current,resp.getheader("Location"))
                if origin(target)!=origin(current):  # 跨源重定向：绝不把 Authorization 带过去
                    headers={k:v for k,v in (headers or {}).items() if k.lower()!="authorization"}
                    self.creds.pop(origin(target),None)
                if resp.status==303 or (resp.status in (301,302) and method!="GET"):method="GET";body=None;total=None
                LOG.info("重定向 %d: %s → %s",redirects,safe_url(current),safe_url(target));resp.close();current=target;continue
            if resp.status==401 and not auth_retried and not resp.had_auth and self.creds.get(origin(current)):
                auth_retried=True;headers=dict(headers or {});headers["Authorization"]=self.creds[origin(current)]
                LOG.info("服务端要求认证，补充凭据后重试: %s",safe_url(current));resp.close();continue
            if resp.status>=400 and not allow_error:
                detail=resp.read().decode("utf-8","replace")
                delay=retry_delay(resp.getheader("Retry-After"));resp.close()
                raise HTTPFailure(resp.status,current,detail,delay)
            return resp
    def _once(self,method,url,headers,body,label,total):
        p=urlsplit(url);proxy=self._proxy_for(p)
        hdrs={"User-Agent":AGENT,"Accept":"*/*","Accept-Encoding":"identity","Connection":"keep-alive","Pragma":"no-cache"}
        for k,v in (headers or {}).items():hdrs[k]=v
        token=self.creds.get(origin(url))
        had_auth=any(k.lower()=="authorization" for k in hdrs)
        if token and not had_auth:hdrs["Authorization"]=token;had_auth=True
        if isinstance(body,(bytes,bytearray)):total=len(body)
        elif isinstance(body,tuple):total=body[1]
        if total is not None:hdrs["Content-Length"]=str(total)
        elif body is not None:hdrs["Transfer-Encoding"]="chunked"  # 只有长度未知时才用分块（HTTP/1.0 服务器不支持分块，所以我们优先给出长度）
        target=urlunsplit(("","",p.path or "/",p.query,""))
        if proxy:target=url  # 走代理时必须使用绝对 URI
        fh=body[0] if isinstance(body,tuple) else None
        last=None
        for attempt in (0,1):  # 复用的 keep-alive 连接可能已被服务端关闭，透明重连一次
            mon=None;fresh=True
            try:
                conn,fresh=self._connect(p,proxy)
                payload=None
                if fh is not None:
                    fh.seek(0);payload=self._counting(iter(lambda:fh.read(CHUNK),b""))
                elif isinstance(body,(bytes,bytearray)):payload=self._counting(iter([bytes(body)]))
                elif body is not None:payload=self._counting(body)
                if total:mon=TransferMonitor(conn.sock,self.a,"%s %s"%(label,method.upper()),total=total,tty=self.a.tty)  # 只有已知长度的上传才开监控线程，避免小请求刷屏
                self._monitor=mon
                self.requests+=1;trace(self.a,"%s %s (%s) body=%s",method,safe_url(url),label,human(total) if total else "0 B")
                conn.request(method,target,body=payload,headers=hdrs)
                raw=conn.getresponse()
                resp=Response(raw,url);resp.had_auth=had_auth;resp.monitor=mon
                data=resp._read_all()
                if mon is not None:mon.stop();resp.monitor=None
                self.bytes_sent+=total or 0;self.bytes_recv+=len(data)
                if resp.will_close or raw.version<11:self._drop(p,proxy)  # HTTP/1.0 服务器（如 wsgiref）不复用连接
                if len(data)>=1024*1024:LOG.info("%s 响应 %s | %s",label,human(len(data)),describe_socket(conn.sock,self.a.proxy_text) if getattr(conn,"sock",None) is not None else "")
                return resp
            except (socket.timeout,TimeoutError) as e:
                if mon is not None:mon.stop(final=False)  # 失败也要收回监控线程，否则线程泄漏
                self._drop(p,proxy);raise NetworkFailure("超时(%gs) %s: %s"%(self.a.timeout,safe_url(url),e)) from e
            except (OSError,http.client.HTTPException,ssl.SSLError) as e:
                stalled=bool(mon is not None and mon.stalled)
                if mon is not None:mon.stop(final=False)
                self._drop(p,proxy)
                if stalled:raise NetworkFailure("低速看门狗掐断连接（%s）: %s"%(label,safe_url(url))) from e
                last=e
                if attempt==0 and not fresh:continue  # 只在“复用连接”失败时静默重连，新连接失败直接报
                raise NetworkFailure("HTTP 传输失败 %s: %s"%(safe_url(url),e)) from e
            finally:
                self._monitor=None
        raise NetworkFailure("HTTP 传输失败 %s: %s"%(safe_url(url),last))
    def _counting(self,it):
        mon=getattr(self,"_monitor",None)
        for chunk in it:
            if mon is not None:mon.add(len(chunk))
            yield chunk
class PurePushClient(AbstractHttpGitClient):
    """把 dulwich 的 Smart HTTP 客户端接到我们自己的标准库 Transport 上，从而获得实时测速、代理与重试能力。"""
    def __init__(self,a,remote,net):
        self.a=a;self.remote=remote;self.net=net;self.base=remote if remote.endswith("/") else remote+"/"
        params=inspect.signature(AbstractHttpGitClient.__init__).parameters;kw={}
        if "config" in params:kw["config"]=None
        if "dumb" in params:kw["dumb"]=False
        if "user_agent" in params:kw["user_agent"]=AGENT
        try:super().__init__(**kw)
        except TypeError:AbstractHttpGitClient.__init__(self)  # 各版本构造参数不同，逐级退化
    def _absolute(self,url):
        url=str(url)
        if re.match(r"^[A-Za-z][\w+.\-]*://",url):return url
        return urljoin(self.base,url)  # dulwich 可能给 /owner/repo.git/xxx（绝对路径）或 info/refs（相对路径），两种都能拼对
    def _http_request(self,url,headers,data,read_body=False,raise_for_status=True,**kw):
        url=self._absolute(url);hdrs=dict(headers or {});spool=None;fh=None
        label="引用发现" if "info/refs" in url else ("推送" if "git-receive-pack" in url else "Git HTTP")
        body=None;total=None
        if data is not None:
            spool=self._spool(data);total=os.path.getsize(spool)  # 先把 pack 落到临时文件：可给出准确 Content-Length（兼容 HTTP/1.0 服务器）、准确百分比进度，且重试不必重新生成
            fh=open(spool,"rb");body=(fh,total)
            LOG.info("待上传 pack: %s | 临时文件 %s",human(total),spool)
        try:
            resp=self.net.request("GET" if data is None else "POST",url,hdrs,body,label,allow_error=not raise_for_status,total=total)
        finally:
            if fh is not None:
                with suppress(OSError):fh.close()
            if spool is not None:
                with suppress(OSError):os.unlink(spool)
        return resp,resp.read  # dulwich 1.2.x 的约定：返回 (response, read_callable)
    def _spool(self,data):
        fd,name=tempfile.mkstemp(prefix="purepush-pack-",suffix=".pack",dir=self.a.temp_dir);n=0
        with os.fdopen(fd,"wb") as f:
            if isinstance(data,(bytes,bytearray)):f.write(data);n=len(data)
            else:
                for chunk in data:
                    if not chunk:continue
                    f.write(chunk);n+=len(chunk)
        trace(self.a,"pack 已缓存: %s (%s)",name,human(n));return name
def remote_progress(msg):
    m=text(msg).rstrip() if isinstance(msg,(bytes,bytearray)) else str(msg).rstrip()
    if m:LOG.info("远端: %s",m)  # 服务端 side-band 进度实时透传
def pkt_lines(data):
    """解析 pkt-line 流：0000=flush，0001=delim，其余为长度前缀行。"""
    i=0;n=len(data)
    while i+4<=n:
        head=data[i:i+4]
        if not re.fullmatch(rb"[0-9a-fA-F]{4}",head):break
        length=int(head,16)
        if length==0:i+=4;continue
        if length==1:i+=4;continue
        if length<4 or i+length>n:break
        yield data[i+4:i+length];i+=length
def remote_refs(net,url,a):
    """GET info/refs?service=git-receive-pack，解析引用广告。用于 LFS 增量扫描与推送前的状态报告。"""
    target=(url if url.endswith("/") else url+"/")+"info/refs?service=git-receive-pack"
    try:resp=retry(a,"引用发现",lambda:net.request("GET",target,{"Accept":"*/*"},None,"引用发现",allow_error=True))
    except (StopPush,NetworkFailure) as e:
        LOG.warning("引用发现失败，LFS 将按全量历史扫描: %s",redact(e));return {}
    body=resp.read();ctype=resp.getheader("content-type") or "";code=resp.status;resp.close()
    if code!=200 or "x-git-receive-pack-advertisement" not in ctype:
        LOG.warning("远端不是 Smart HTTP（HTTP %s, Content-Type: %s），拒绝按 dumb 协议推送",code,ctype);return {}
    refs={}
    for line in pkt_lines(body):
        if line.startswith(b"#"):continue
        line=line.rstrip(b"\n").split(b"\0")[0]  # 第一行带能力列表，用 NUL 分隔
        parts=line.split(b" ",1)
        if len(parts)!=2 or not re.fullmatch(rb"[0-9a-fA-F]{40}",parts[0]):continue
        if parts[0]==ZERO_SHA or parts[1].endswith(b"^{}"):continue  # 空仓库的能力广告行 0000…0 capabilities^{} 不是真引用
        refs[parts[1]]=parts[0]
    LOG.info("远端现有引用 %d 个%s",len(refs),(" | %s"%{text(k):text(v)[:10] for k,v in list(refs.items())[:5]}) if refs else "")
    return refs
def is_ancestor(store,old,new):
    """判断 old 是否为 new 的祖先（快进检查）。返回 True/False，缺对象时返回 None。"""
    if not old or old==ZERO_SHA:return True
    if old==new:return True
    seen=set();stack=[new]
    while stack:
        sha=stack.pop()
        if not sha or sha==ZERO_SHA or sha in seen:continue
        seen.add(sha)
        if sha==old:return True
        try:obj=store[sha]
        except KeyError:return None  # 本地缺对象，无法判断
        if isinstance(obj,Commit):stack.extend(obj.parents)
    return False
def outgoing_lfs(repo,have,want,a):
    """收集本次推送新增历史里的全部 LFS 指针（含后来被删除的文件），返回 {oid: size}。"""
    store=repo.object_store;out={};seen_commits=set();seen_trees=set();havens={h for h in have if h and h!=ZERO_SHA}
    stack=list(want);scanned=0
    while stack:
        sha=stack.pop()
        if not sha or sha==ZERO_SHA or sha in seen_commits or sha in havens:continue
        seen_commits.add(sha)
        try:obj=store[sha]
        except KeyError:
            LOG.warning("本地缺少对象 %s，LFS 历史扫描可能不完整",text(sha)[:12]);continue
        if not isinstance(obj,Commit):continue
        stack.extend(obj.parents)
        if obj.tree in seen_trees:continue
        seen_trees.add(obj.tree)
        for entry in iter_tree_contents(store,obj.tree):
            if entry.sha in out or not stat.S_ISREG(entry.mode):continue
            scanned+=1
            if scanned>a.lfs_scan_limit:
                LOG.warning("LFS 历史扫描超过 %d 个 blob 已停止，请用 --lfs-scan-limit 调整",a.lfs_scan_limit);return out
            try:blob=store[entry.sha]
            except KeyError:continue
            if isinstance(blob,Blob) and len(blob.data)<=200:
                info=pointer_info(blob.data)
                if info:out[info[0]]=info[1]
    LOG.info("待推送 LFS 对象: %d 个 | 扫描 blob: %d | 提交: %d",len(out),scanned,len(seen_commits));return out
def upload_lfs(net,batch_url,objects,cache,ref,done,a):
    """调用 LFS batch API 并上传；只向原始 origin 发送凭据，签名上传地址只带服务端给的 header。"""
    items=[{"oid":o,"size":s} for o,s in objects.items() if (o,s) not in done]
    if not items:LOG.info("LFS 对象均已在远端，无需上传");return done
    base_origin=origin(batch_url);hdrs={"Accept":MEDIA,"Content-Type":MEDIA,"User-Agent":"git-lfs/3.5.1"}
    for i in range(0,len(items),100):
        chunk=items[i:i+100];req={"operation":"upload","transfers":["basic"],"objects":chunk}
        if ref:req["ref"]={"name":text(ref)}
        resp=retry(a,"LFS batch",lambda r=req:net.request("POST",batch_url,dict(hdrs),json.dumps(r).encode(),"LFS batch"))
        try:payload=json.loads(resp.read().decode("utf-8","replace"))
        except ValueError as e:raise StopPush("LFS batch 响应不是 JSON: %s"%e) from e
        finally:resp.close()
        for obj in (payload.get("objects") or []):
            oid=obj.get("oid");size=int(obj.get("size") or 0)
            if obj.get("error"):
                err=obj["error"];code=err.get("code");msg=err.get("message","")
                if code in (408,429) or (isinstance(code,int) and code>=500):raise NetworkFailure("LFS 对象 %s 临时错误: %s %s"%(oid[:12],code,msg))
                raise StopPush("LFS 对象 %s 被拒绝: %s %s"%(oid[:12],code,msg))
            actions=obj.get("actions") or {}
            if not actions:
                done.add((oid,size));trace(a,"LFS 已存在于远端: %s",oid[:12]);continue
            up=actions.get("upload") or {}
            if up.get("href"):
                path=cache.require(oid,size)
                uh={"User-Agent":"git-lfs/3.5.1","Content-Type":"application/octet-stream"}
                uh.update(up.get("header") or {})
                if origin(up["href"])==base_origin and net.creds.get(base_origin):uh["Authorization"]=net.creds[base_origin]  # 只有回到同一 origin 才带令牌（S3 签名地址绝不能带）
                verb=(up.get("verb") or "PUT").upper()
                with open(str(path),"rb") as f:
                    def put(u=up["href"],h=uh,fo=f,s=size,v=verb):
                        r=net.request(v,u,h,(fo,s),"LFS 上传 %s"%oid[:12],total=s);r.close();return r
                    retry(a,"LFS 上传 %s"%oid[:12],put)
            vf=actions.get("verify") or {}
            if vf.get("href"):
                vh={"Accept":MEDIA,"Content-Type":MEDIA,"User-Agent":"git-lfs/3.5.1"};vh.update(vf.get("header") or {})
                if origin(vf["href"])==base_origin and net.creds.get(base_origin):vh["Authorization"]=net.creds[base_origin]
                retry(a,"LFS verify",lambda u=vf["href"],h=vh,o=oid,s=size:net.request("POST",u,h,json.dumps({"oid":o,"size":s}).encode(),"LFS verify").close())
            done.add((oid,size));LOG.info("LFS 完成: %s (%s)",oid[:12],human(size))
    return done
def lfs_endpoint(a,repo,config,remote,name):
    if a.lfs_url:return a.lfs_url.rstrip("/")+"/objects/batch"
    lfscfg=Path(repo.path)/".lfsconfig"
    if lfscfg.is_file():
        try:
            lf=ConfigFile.from_path(str(lfscfg));v=cfg(lf,(b"lfs",),b"url")
            if v:return text(v).rstrip("/")+"/objects/batch"
        except Exception as e:LOG.warning("解析 .lfsconfig 失败: %s",e)
    v=cfg(config,(b"remote",os.fsencode(name)),b"lfsurl") or cfg(config,(b"lfs",),b"url")
    if v:return text(v).rstrip("/")+"/objects/batch"
    return remote.rstrip("/")+"/info/lfs/objects/batch"
def normalize_blob(data,attrs,old,repo,config,path,renormalize=False):
    """只做 git 内建的 text/eol/autocrlf/ident 转换；未知过滤器或编码转换一律报错，绝不静默改变内容。"""
    if attrs.get(b"working-tree-encoding") not in (None,False):raise StopPush("暂不支持 working-tree-encoding，拒绝静默改变文件内容: %s"%text(path))
    selected=attrs.get(b"filter")
    if selected not in (None,False,b"lfs"):raise StopPush("不执行外部 filter=%s: %s"%(text(selected),text(path)))
    if attrs.get(b"ident") is True:data=re.sub(rb"\$Id:[^$\r\n]*\$",b"$Id$",data)
    text_attr=attrs.get(b"text");eol=attrs.get(b"eol");auto=cfg(config,(b"core",),b"autocrlf",b"false").lower()
    if text_attr is None and b"crlf" in attrs:text_attr=False if attrs[b"crlf"] is False else True  # 兼容旧的 crlf 属性写法
    if text_attr is False or (text_attr is None and eol is None and auto not in (b"true",b"input")):return data
    automatic=text_attr is not True and not (text_attr is None and eol in (b"lf",b"crlf"))
    nonprint=sum(data.count(bytes([b])) for b in range(32) if b not in (8,9,10,12,13,27))+data.count(b"\x7f")
    if automatic and (b"\0" in data or data.count(b"\r")!=data.count(b"\r\n") or nonprint>(len(data)-nonprint)//128):return data  # git 的二进制启发式判定
    if automatic and old is not None and not renormalize and old.mode!=0o160000:
        with suppress(KeyError):
            if b"\r\n" in repo.object_store[old.sha].data:return data  # 仓库里本来就带 CRLF，说明不是自动转换的产物
    converted=data.replace(b"\r\n",b"\n")
    safe=cfg(config,(b"core",),b"safecrlf",b"false").lower();core_eol=cfg(config,(b"core",),b"eol",b"native")
    checkout_crlf=eol==b"crlf" or (eol is None and (auto==b"true" or (auto!=b"input" and (core_eol==b"crlf" or (core_eol==b"native" and os.name=="nt")))))
    restored=converted.replace(b"\n",b"\r\n") if checkout_crlf else converted
    if safe in (b"true",b"warn") and restored!=data:
        if safe==b"true":raise StopPush("core.safecrlf 拒绝不可逆的换行转换: %s"%text(path))
        LOG.warning("换行转换不可逆: %s",text(path))
    return converted
def walk_candidates(repo,index,manager,config):
    """扫描工作区。已跟踪路径绕过忽略规则（父目录被忽略也不能漏掉其中的修改/删除）；符号链接与 junction 一律不进入。"""
    root=Path(repo.path);tracked=dict(index.items())
    ignorecase=yes(config,(b"core",),b"ignorecase",os.name=="nt")
    lookup={os.fsdecode(k).casefold():k for k in tracked} if ignorecase else {}
    def folded(rel):return os.fsdecode(rel).casefold() if ignorecase else os.fsdecode(rel)
    def old_key(rel):return rel if rel in tracked else lookup.get(folded(rel))
    parents={folded(b"/".join(p.split(b"/")[:i])) for p in tracked for i in range(1,len(p.split(b"/")))}  # 有已跟踪后代的目录必须继续扫描
    files={};skipped=0;count=0;last=time.monotonic();validator=get_path_element_validator(config)
    def add(path):
        nonlocal skipped,count,last
        rel=os.fsencode(Path(path).relative_to(root).as_posix());count+=1
        if not validate_path(rel,validator):raise StopPush("无效 Git 路径（含 . / .. / NUL / 绝对路径）: %s"%path)
        old=old_key(rel)
        if old is None and manager.is_ignored(os.fsdecode(rel)) is True:skipped+=1;return  # 只忽略“未跟踪”的文件
        files[rel]=(Path(path),old)
        if time.monotonic()-last>=1.0:LOG.info("扫描文件: %d | 排除: %d | 当前: %s",count,skipped,os.fsdecode(rel));last=time.monotonic()
    def onerror(e):raise StopPush("扫描目录失败: %s"%e)
    for base,dirs,names in os.walk(str(root),topdown=True,followlinks=False,onerror=onerror):
        current=Path(base);keep=[]
        for name in dirs:
            path=current/name;rel=os.fsencode(path.relative_to(root).as_posix())
            if (name.casefold() if os.name=="nt" else name)==".git":continue  # 任何层级的 .git 都不扫描
            if path.is_symlink():add(path);continue  # 符号链接目录只登记链接本身，绝不跟随
            if getattr(path,"is_junction",lambda:False)():raise StopPush("拒绝遍历 Windows junction: %s"%path)
            if folded(rel) not in parents and old_key(rel) is None and manager.is_ignored(os.fsdecode(rel)+"/") is True and manager.is_ignored(os.fsdecode(rel)) is True:
                skipped+=1;continue  # 整个目录被忽略且无已跟踪后代 → 剪枝；判断目录本身而不是 dir/ 的内容，select/* + !select/keep 才不会被提前剪掉
            if (path/".git").exists() or (old_key(rel) is not None and tracked[old_key(rel)].mode==0o160000):add(path);continue  # 子仓库 / gitlink
            keep.append(name)
        dirs[:]=keep
        for name in names:
            if (name.casefold() if os.name=="nt" else name)==".git":continue
            add(current/name)
    LOG.info("扫描完成: %d 项 | 未跟踪且被忽略: %d 项",count,skipped);return files
def stage_all(repo,index,a,config,cache):
    """替代 porcelain.add：直接写 Blob 与索引项，因此永远不会触发 filter.lfs.process 等外部过滤器子进程。"""
    if any(not isinstance(e,IndexEntry) for _,e in index.items()):raise StopPush("索引存在未解决冲突，拒绝自动提交")
    if any(stat.S_ISDIR(e.mode) or e.skip_worktree for _,e in index.items()):raise StopPush("稀疏索引或 skip-worktree 不受支持，请先展开工作区")
    if any(getattr(ext,"signature",b"X")[:1].islower() for ext in (getattr(index,"_extensions",[]) or [])):raise StopPush("存在不支持的必需索引扩展（如分裂/稀疏索引），拒绝丢弃其数据")
    manager=ignore_manager(repo,config);files=walk_candidates(repo,index,manager,config)
    attrs=Attributes(repo,config,index);old_entries=dict(index.items());root=Path(repo.path)
    filemode=yes(config,(b"core",),b"filemode",os.name!="nt");seen=set();payloads=0;plan=[]
    for rel in sorted(files):
        path,oldkey=files[rel];old=old_entries.get(oldkey) if oldkey is not None else None
        try:st=path.lstat()
        except OSError:continue  # 扫描后被删除，交给末尾的“索引清理”按删除处理
        if old is not None and getattr(old,"flags",0)&0x8000:seen.add(rel);continue  # assume-unchanged 的条目原样保留
        if stat.S_ISLNK(st.st_mode):
            data=os.fsencode(os.readlink(str(path)));mode=0o120000  # 符号链接：blob 内容就是目标路径
        elif stat.S_ISDIR(st.st_mode):
            if old is not None and old.mode==0o160000:
                LOG.warning("跳过子模块 %s（不解析其 HEAD，保留原 gitlink）",os.fsdecode(rel));seen.add(rel);continue
            raise StopPush("意外的目录项: %s"%path)
        elif stat.S_ISREG(st.st_mode):
            effective=attrs.get(rel)
            want_lfs=effective.get(b"filter")==b"lfs" or (a.auto_lfs and st.st_size>=a.lfs_threshold)
            if st.st_size>a.max_blob_size and not want_lfs:raise StopPush("文件 %s (%s) 超过 --max-blob-size(%s) 且未启用 LFS"%(os.fsdecode(rel),human(st.st_size),human(a.max_blob_size)))
            if want_lfs:
                data=pointer_bytes("0"*64,st.st_size) if a.dry_run else cache.put(path)
                if not a.dry_run:payloads+=1
                mode=0o100644  # LFS 指针一律按普通文件提交
            else:
                raw,_=read_regular(path)
                data=normalize_blob(raw,effective,old,repo,config,rel,a.renormalize);mode=0o100644
                if filemode and st.st_mode&0o111:mode=0o100755
                elif not filemode and old is not None and old.mode==0o100755:mode=0o100755  # core.filemode=false 时沿用索引里的可执行位
            if len(data)>a.max_blob_size and pointer_info(data) is None:raise StopPush("普通 Blob 超过允许大小: %s（LFS 规则可能被 .git/info/attributes 覆盖）"%os.fsdecode(rel))
            if stable(path.lstat())!=stable(st):raise StopPush("暂存期间文件被修改，请重试: %s"%path)
        else:raise StopPush("不支持的文件类型（socket/fifo/设备）: %s"%path)
        if a.dry_run:
            plan.append((os.fsdecode(rel),st.st_size,"LFS" if pointer_info(data) else "blob"));seen.add(rel);continue
        blob=Blob.from_string(data);repo.object_store.add_object(blob)
        entry=index_entry_from_stat(st,blob.id,mode=mode)
        with suppress(Exception):entry.size=st.st_size&0xFFFFFFFF  # 索引 size 字段参与 racily-clean 判断
        if mode in (0o100644,0o100755) and attrs.get(rel).get(b"filter")==b"lfs" and pointer_info(data) is None:raise StopPush("LFS 暂存验证失败（内容不是指针）: %s"%path)
        if oldkey is not None and oldkey!=rel:del index[oldkey]  # core.ignorecase 下大小写改名必须删旧键
        index[rel]=entry;seen.add(rel);trace(a,"暂存: %s",os.fsdecode(rel))
    if a.dry_run:
        LOG.info("[dry-run] 将暂存 %d 项 | LFS %d 项 | 前 20: %s",len(plan),sum(1 for x in plan if x[2]=="LFS"),plan[:20]);return payloads
    for rel in list(index):
        if rel not in seen:del index[rel];trace(a,"暂存删除: %s",os.fsdecode(rel))  # 工作区已消失的跟踪文件 → 删除
    LOG.info("索引暂存完成 | LFS 新快照: %d | 未调用任何外部过滤器",payloads);return payloads
def tree_map(repo,head):
    if not head or head==ZERO_SHA:return {}
    return {e.path:(e.sha,e.mode) for e in iter_tree_contents(repo.object_store,repo[head].tree)}
def check_repo_state(repo,config):
    """合并/变基/浅克隆/部分克隆/替换历史等状态必须先由用户处理，绝不静默变成普通提交。"""
    if getattr(repo,"bare",False):raise StopPush("自动暂存 push 需要非 bare 工作区")
    if cfg(config,(b"extensions",),b"objectformat",b"sha1")!=b"sha1":raise StopPush("此版本只处理 SHA-1 仓库（LFS 内容仍是 SHA-256）")
    shallow=False
    with suppress(Exception):shallow=bool(repo.get_shallow())  # 注意：不能把 raise 放进 suppress 里，StopPush 也是 Exception 会被吞掉
    if shallow:raise StopPush("浅仓库尚未支持，请先补全历史，以免错误判断快进关系")
    if cfg(config,(b"extensions",),b"partialclone"):raise StopPush("部分克隆尚未支持，请先补全对象；不启动隐式下载")
    for section in config.sections():
        if tuple(section)[:1]==(b"remote",) and yes(config,section,b"promisor",False):raise StopPush("promisor 部分克隆尚未支持")
    if yes(config,(b"core",),b"sparsecheckout",False) or yes(config,(b"core",),b"splitindex",False):raise StopPush("不自动修改稀疏检出或分裂索引仓库")
    for name in ("MERGE_HEAD","CHERRY_PICK_HEAD","REVERT_HEAD","BISECT_LOG","rebase-merge","rebase-apply","sequencer"):
        if (Path(repo.controldir())/name).exists():raise StopPush("仓库操作尚未结束: %s，请先用 git 处理"%name)
    if yes(config,(b"commit",),b"gpgsign",False):raise StopPush("配置要求签名提交，但纯标准库版本不调用签名程序")
    if (Path(repo.commondir())/"info"/"grafts").exists() or any(r.startswith(b"refs/replace/") for r in repo.refs.keys()):raise StopPush("存在 grafts/replace refs，拒绝按替换历史自动提交")
def identity_of(a,repo,config,url_user):
    name=cfg(config,(b"user",),b"name");mail=cfg(config,(b"user",),b"email")
    if a.author:
        m=re.match(r"\s*(.*?)\s*(?:<([^>]*)>)?\s*$",a.author)
        if m and m.group(1):name=os.fsencode(m.group(1))
        if m and m.group(2):mail=os.fsencode(m.group(2))
    if not name:name=os.fsencode(url_user or os.environ.get("GIT_AUTHOR_NAME") or os.environ.get("USERNAME") or os.environ.get("USER") or "pure-push")
    if not mail:
        u=text(name).strip().replace(" ","-")
        mail=os.fsencode(os.environ.get("GIT_AUTHOR_EMAIL") or ("%s@users.noreply.github.com"%u if url_user else "%s@%s"%(u,socket.gethostname())))
    return b"%s <%s>"%(name,mail)
def commit_staged(repo,index,a,identity,expected):
    """按最终 Blob 大小分组提交：删除先于新增、ReadMe.md 优先、超过 --max-commit-size 自动拆分；全部树建好后才更新 HEAD。"""
    chain,head=expected
    if repo.refs.follow(b"HEAD")!=expected:raise StopPush("暂存期间本地 HEAD 已变化，拒绝把旧工作区提交到新分支")
    flat=tree_map(repo,head);target={p:(e.sha,e.mode) for p,e in index.items()}
    changed=sorted(set(flat)|set(target),key=lambda p:(p in target,p));changed=[p for p in changed if flat.get(p)!=target.get(p)]
    if not changed:LOG.info("暂存区为空，不创建空提交");return [],None
    LOG.info("变更文件: %d 个 | 前 10 项: %s",len(changed),[os.fsdecode(p) for p in changed[:10]])  # 删除项排在前面，文件与目录互换时不会构造冲突的中间树
    sizes={};largest=None;largest_size=-1
    for p in changed:
        size=0
        if p in target:
            with suppress(Exception):
                obj=repo.object_store[target[p][0]]
                size=len(obj.data) if isinstance(obj,Blob) else 130  # LFS 只按指针大小计
        sizes[p]=size
        if size>largest_size:largest,largest_size=os.fsdecode(p),size
    LOG.info("最大变更: %s (%s) | 单提交上限: %s",largest,human(largest_size),human(a.max_commit_size))
    first=[p for p in changed if p in (b"ReadMe.md",b"README.md")];rest=[p for p in changed if p not in first]
    batches=[];current=list(first);total=sum(sizes[p] for p in current)
    for p in rest:
        if total+sizes[p]>a.max_commit_size and current:batches.append(current);current=[];total=0
        current.append(p);total+=sizes[p]
    if current:batches.append(current)
    if len(batches)>1:LOG.info("按 %s 拆分为 %d 个提交",human(a.max_commit_size),len(batches))
    ids=[];parent=head;now=int(time.time());tz=int(datetime.now().astimezone().utcoffset().total_seconds() or 0)
    for number,paths in enumerate(batches,1):
        for p in paths:
            if p in target:flat[p]=target[p]
            else:flat.pop(p,None)
        commit=Commit();commit.tree=commit_tree(repo.object_store,[(p,m,s) for p,(s,m) in sorted(flat.items())])
        commit.parents=[parent] if parent else []
        commit.author=commit.committer=identity
        commit.author_time=commit.commit_time=now+number-1  # 保证时间单调递增，避免同秒提交顺序混乱
        commit.author_timezone=commit.commit_timezone=tz
        base=text(a.message) if a.message else ("更新 %d 个文件"%len(paths))
        commit.message=("%s（第 %d/%d 批）"%(base,number,len(batches)) if len(batches)>1 else base).encode("utf-8")
        repo.object_store.add_object(commit);ids.append(commit.id);parent=commit.id
        LOG.info("已创建提交 %d/%d: %s | tree %s | %d 个路径",number,len(batches),text(commit.id)[:10],text(commit.tree)[:10],len(flat))
    ref_name=chain[-1] if chain else b"HEAD"
    if a.dry_run:LOG.info("[dry-run] 不更新 %s",text(ref_name));return ids,None
    try:
        if not repo.refs.set_if_equals(ref_name,head,ids[-1]):raise StopPush("HEAD 在提交期间被其他进程修改，已放弃更新引用")
    except TypeError:repo.refs[ref_name]=ids[-1]  # 某些 dulwich 版本没有 set_if_equals
    LOG.info("本地引用 %s → %s",text(ref_name),text(ids[-1])[:10]);return ids,ids[-1]
def prepare(repo,a,identity,cache):
    config=repo.get_config();check_repo_state(repo,config)
    expected=repo.refs.follow(b"HEAD")
    if a.dry_run:
        stage_all(repo,repo.open_index(),a,config,cache);return [],None
    with GitFile(str(Path(repo.controldir())/"index.lock")) as lock:  # 用 dulwich 的锁文件避免与真正的 git 并发写索引
        index=repo.open_index();stage_all(repo,index,a,config,cache)
        writer=SHA1Writer(lock);write_index_dict(writer,dict(index.items()),version=3);writer.close()  # 直接重写 index，绕开可能不被支持的扩展
    return commit_staged(repo,index,a,identity,expected)
def push_target(repo,a,remote,ref,new_oid,net,cache):
    """执行一次 Smart HTTP 推送；带重试与快进校验；重复推送同一状态必须是幂等的空操作。"""
    client=PurePushClient(a,remote,net);store=repo.object_store
    def update(refs):
        old=refs.get(ref,ZERO_SHA)
        if a.delete or new_oid is None:
            LOG.info("请求删除远端 %s（当前 %s）",text(ref),text(old)[:10]);return {ref:ZERO_SHA}
        if old==new_oid:
            LOG.info("远端 %s 已是 %s，无需推送",text(ref),text(old)[:10]);return {}
        anc=is_ancestor(store,old,new_oid)
        if anc is False and not a.force:raise StopPush("非快进推送被拒绝：%s 远端 %s 不是本地 %s 的祖先；确需覆盖请加 --force"%(text(ref),text(old)[:10],text(new_oid)[:10]))
        if anc is None and not a.force:raise StopPush("无法确认快进关系（本地缺少远端对象 %s），请加 --force 或先补全历史"%text(old)[:10])
        LOG.info("更新 %s: %s → %s%s",text(ref),text(old)[:10],text(new_oid)[:10],"（强制）" if a.force else "")
        return {ref:new_oid}
    params=inspect.signature(client.send_pack).parameters;kw={}
    if "progress" in params:kw["progress"]=remote_progress
    if "push_options" in params and a.push_option:kw["push_options"]=[v.encode() if isinstance(v,str) else v for v in a.push_option]
    if "atomic" in params and a.atomic:kw["atomic"]=True
    def generate(have,want,ofs_delta=True,progress=None):
        for holder in (repo.object_store,repo):  # 不同 dulwich 版本把 generate_pack_data 挂在不同对象上
            fn=getattr(holder,"generate_pack_data",None)
            if fn is None:continue
            gp=set(inspect.signature(fn).parameters)
            for extra in ({"ofs_delta":ofs_delta,"progress":progress},{"ofs_delta":ofs_delta},{}):
                if not set(extra)<=gp:continue
                try:return fn(have,want,**extra)
                except TypeError:continue
        raise StopPush("当前 dulwich 无法生成 pack 数据（缺少 generate_pack_data）")
    def attempt():
        result=client.send_pack(urlsplit(remote).path,update,generate,**kw)  # 与 dulwich 1.2.15 一致：传路径，_http_request 里再拼回绝对 URL
        statuses={}
        if isinstance(result,dict):statuses=dict(result)
        else:
            for attr in ("ref_status","refs","statuses"):
                v=getattr(result,attr,None)
                if isinstance(v,dict) and v:statuses=v;break
        bad=[(text(r),text(s)) for r,s in statuses.items() if s and not text(s).startswith("ok")]
        if bad:raise StopPush("服务端拒绝更新: %s"%bad)
        LOG.info("服务端确认: %s",{text(k):text(v) for k,v in statuses.items()} if statuses else "无引用变化（已是最新）")
        return result
    return retry(a,"推送 %s %s"%(safe_url(remote),text(ref)),attempt)
def classify(exc):
    """判断异常是否值得重试。"""
    if isinstance(exc,HTTPFailure):return exc.retryable
    if isinstance(exc,NetworkFailure):return True
    if isinstance(exc,(socket.timeout,TimeoutError,ConnectionError,ssl.SSLError,http.client.HTTPException)):return True
    if isinstance(exc,OSError):return getattr(exc,"errno",None) in (errno.ECONNRESET,errno.ECONNABORTED,errno.EPIPE,errno.ETIMEDOUT,errno.ECONNREFUSED,errno.EHOSTUNREACH,errno.ENETUNREACH,errno.ENETRESET)
    return False
def retry(a,label,operation):
    attempt=0
    while True:
        attempt+=1
        try:return operation()
        except Exception as exc:
            if attempt>a.retries or not classify(exc):raise
            delay=getattr(exc,"retry_after",0) or min(a.retry_max_delay,a.retry_delay*(2**(attempt-1)))
            delay=max(0.2,delay)+0.1*attempt
            LOG.warning("%s 第 %d/%d 次失败（%s），%.1fs 后重试",label,attempt,a.retries,redact(exc),delay)
            time.sleep(delay)
def build_parser():
    p=argparse.ArgumentParser(prog="pure_push.py",description="dulwich + Python 标准库实现的全功能 push")
    p.add_argument("-v","--verbose",action="count",default=2,help="日志级别，可重复；-v 3 输出调试与堆栈")
    p.add_argument("-u","--url",nargs="+",help="远程地址；可写 '-u push <url>' 或 '-u <url>'")
    p.add_argument("--repo",default=".",help="本地仓库或工作区路径（默认当前目录）")
    p.add_argument("--remote",default="origin",help="远程名，用于读取 remote.<name>.* 配置")
    p.add_argument("--branch",help="要推送的分支，默认取 HEAD 指向的分支")
    p.add_argument("-m","--message",help="提交信息；缺省自动生成")
    p.add_argument("--author",help="提交身份 'Name <mail>'，覆盖仓库配置")
    p.add_argument("--force",action="store_true",help="允许非快进推送")
    p.add_argument("--atomic",action="store_true",help="要求服务端原子更新")
    p.add_argument("--push-option",action="append",default=[],help="push option，可重复")
    p.add_argument("--delete",action="store_true",help="删除远端分支（配合 --branch）")
    p.add_argument("--dry-run",action="store_true",help="只扫描与报告，不写索引/引用/不联网")
    p.add_argument("--no-commit",action="store_true",help="只推送已有提交，不自动暂存提交")
    p.add_argument("--lfs-threshold",type=float,default=100.0,help="自动转 LFS 的阈值（MiB）")
    p.add_argument("--max-blob-size",type=float,default=100.0,help="普通 Blob 上限（MiB）")
    p.add_argument("--max-commit-size",type=float,default=40.0,help="单提交内容上限（MiB），超出自动拆分")
    p.add_argument("--no-auto-lfs",action="store_true",help="只按 .gitattributes 决定 LFS，不按大小自动转")
    p.add_argument("--renormalize",action="store_true",help="重新应用换行规范化（相当于 git add --renormalize）")
    p.add_argument("--lfs-url",help="覆盖 LFS batch 端点")
    p.add_argument("--lfs-scan-limit",type=int,default=200000,help="LFS 历史扫描 blob 上限")
    p.add_argument("--timeout",type=float,default=45.0,help="连接/读写超时（秒）")
    p.add_argument("--low-speed-limit",type=float,default=10.0,help="低速阈值（B/s）")
    p.add_argument("--low-speed-time",type=float,default=60.0,help="低速持续多少秒后主动断开")
    p.add_argument("--progress-interval",type=float,default=0.5,help="速度输出间隔（秒）")
    p.add_argument("--speed-window",type=float,default=3.0,help="瞬时速度统计窗口（秒）")
    p.add_argument("--retries",type=int,default=3,help="网络重试次数")
    p.add_argument("--retry-delay",type=float,default=1.0,help="重试基础间隔（秒），指数退避")
    p.add_argument("--retry-max-delay",type=float,default=30.0,help="重试最大间隔（秒）")
    p.add_argument("--max-redirects",type=int,default=5,help="最大重定向次数")
    p.add_argument("--no-proxy",action="store_true",help="忽略环境变量里的代理")
    p.add_argument("--token",help="访问令牌（等价于 URL 里的密码）")
    p.add_argument("--user",help="用户名")
    p.add_argument("--password",help="密码")
    p.add_argument("--trace",action="store_true",help="输出关键内部动作")
    p.add_argument("--temp-dir",help="pack/缓存临时目录（默认系统临时目录，Windows 下会 realpath 展开 8.3 短名）")
    p.add_argument("--tty",type=int,choices=[0,1],default=None,help="强制开/关单行刷新的进度显示")
    p.add_argument("--self-test",action="store_true",help="运行内置自测（完全离线）")
    return p
def finalize(a):
    a.lfs_threshold=int(a.lfs_threshold*1024*1024);a.max_blob_size=int(a.max_blob_size*1024*1024);a.max_commit_size=int(max(1.0,a.max_commit_size)*1024*1024)
    a.auto_lfs=not a.no_auto_lfs;a.tty=bool(sys.stdout.isatty()) if a.tty is None else bool(a.tty)
    a.temp_dir=os.path.realpath(a.temp_dir or tempfile.gettempdir());os.makedirs(a.temp_dir,exist_ok=True)
    a.proxy_text=None;a.retries=max(0,int(a.retries))
    if isinstance(a.url,list):  # 兼容 '-u push <url>' 的写法
        vals=[v for v in a.url if v.lower() not in ("push","pull","fetch","origin")]
        a.url=vals[0] if vals else (a.url[-1] if a.url else None)
    return a
def local_head(repo):
    try:return repo.head()
    except (KeyError,NotGitRepository):return None  # unborn 分支还没有提交
def main(a):
    a=finalize(a);setup_logging(a.verbose);t0=time.monotonic()
    LOG.info("Dulwich 版本: %s | 网络: Python 标准库 http.client/socket/ssl",AGENT.split("dulwich+")[-1].rstrip(")"))
    repo_path=os.path.realpath(str(Path(a.repo).expanduser()))
    try:repo=Repo(repo_path)
    except NotGitRepository as e:raise StopPush("%s 不是 Git 仓库（缺少 .git）: %s"%(repo_path,e)) from e
    except Exception as e:raise StopPush("打开仓库失败 %s: %s"%(repo_path,e)) from e
    with repo:
        config=repo.get_config()
        remote=a.url or text(cfg(config,(b"remote",os.fsencode(a.remote)),b"pushurl")) or text(cfg(config,(b"remote",os.fsencode(a.remote)),b"url"))
        if not remote:raise StopPush("未指定远程地址：请用 -u 或配置 remote.%s.url"%a.remote)
        try:remote=apply_instead_of(config,remote) or remote  # 注意：apply_instead_of 返回的是 URL 字符串，不是 config
        except Exception:pass
        url,user,password,branch=parse_url(remote,a.branch)
        if a.user:user=a.user
        if a.token:password=a.token
        if a.password:password=a.password
        if user:remember(user)
        if password:remember(password)
        head_ref=repo.refs.read_ref(b"HEAD") or b""
        if not a.branch and head_ref.startswith(b"ref: "):branch=text(head_ref[5:].split(b"/")[-1])
        elif not a.branch:branch=text(cfg(config,(b"init",),b"defaultbranch",b"master"))
        ref=("refs/heads/%s"%branch).encode()
        if not check_ref_format(ref):raise StopPush("非法引用名: %s"%text(ref))
        LOG.info("仓库路径: %s",repo_path);LOG.info("远程地址: %s | 分支: %s",url,branch)
        LOG.info("LFS 阈值: %s | 最大普通 Blob: %s | 单提交上限: %s",human(a.lfs_threshold),human(a.max_blob_size),human(a.max_commit_size))
        LOG.info("连接超时: %gs | 低速: %gB/s 持续 %gs | 每 %.2fs 输出 | 重试 %d 次",a.timeout,a.low_speed_limit,a.low_speed_time,a.progress_interval,a.retries)
        creds={}
        if user or password:creds[origin(url)]="Basic "+base64.b64encode(("%s:%s"%(user or "",password or "")).encode()).decode()
        identity=identity_of(a,repo,config,user);LOG.info("提交身份: %s",text(identity))
        cache=LfsCache(repo,a);ids=[];new=None
        if not a.no_commit:ids,new=prepare(repo,a,identity,cache)
        want=None if a.delete else (new or local_head(repo))
        if want is None and not a.delete:
            try:want=repo.refs[ref]
            except KeyError:want=None
        if want is None and not a.delete:raise StopPush("本地还没有任何提交，无法推送")
        if a.dry_run:
            LOG.info("[dry-run] 结束，未联网；将推送 %s → %s",text(ref),(text(want)[:10] if want else "(删除)"));return 0
        net=Transport(a,creds)
        try:
            have=remote_refs(net,url,a)  # 先做引用发现：既能报告远端状态，又能把 LFS 扫描限制在增量历史上
            if not a.delete:
                objs=outgoing_lfs(repo,[s for s in have.values() if s and s!=ZERO_SHA],[want],a)
                if objs:
                    batch=lfs_endpoint(a,repo,config,url,a.remote)
                    LOG.info("LFS batch 端点: %s | 对象 %d 个 | 合计 %s",safe_url(batch),len(objs),human(sum(objs.values())))
                    upload_lfs(net,batch,objs,cache,ref,set(),a)
                else:LOG.info("本次推送不含 LFS 对象")
            push_target(repo,a,url,ref,want,net,cache)
        finally:net.close()
        LOG.info("全部完成 | 用时 %s | 新提交 %d 个 | HTTP 请求 %d 次 | 上行 %s | 下行 %s",elapsed(time.monotonic()-t0),len(ids),net.requests,human(net.bytes_sent),human(net.bytes_recv))
    return 0
def rmtree_force(path):
    """Windows 上 dulwich/git 会把对象文件设为只读，rmtree 需要 chmod 兜底，否则清理失败。"""
    def onerr(func,p,info):
        with suppress(OSError):os.chmod(p,stat.S_IWRITE)
        try:func(p)
        except OSError:pass
    shutil.rmtree(str(path),onerror=onerr)
def make_temp_repo(prefix="purepush-test-"):
    """Windows 临时目录注意事项：mkdtemp 可能返回 8.3 短名（C:\\Users\\ADMINI~1\\...），必须 realpath 展开，
    否则后续路径比较、.gitignore 相对路径判断、符号链接目标都会出错。"""
    d=os.path.realpath(tempfile.mkdtemp(prefix=prefix));os.makedirs(d,exist_ok=True);return d
def init_worktree(path):
    path=str(path);os.makedirs(path,exist_ok=True)  # Repo.init 不保证建目录，先建好再 init，避免 Windows 上 FileNotFoundError
    for kw in ({"mkdir":True},{}):
        try:return Repo.init(path,**kw)
        except TypeError:continue
    return Repo.init(path)
def init_bare(path):
    path=str(path);os.makedirs(path,exist_ok=True);errs=[]
    for call in (lambda:Repo.init_bare(path=path,mkdir=True),lambda:Repo.init_bare(path),lambda:Repo.init_bare(path=path),lambda:Repo.init_bare(objects=[],path=path),lambda:Repo.init_bare([],path)):
        try:return call()
        except TypeError as e:errs.append(str(e))
        except Exception as e:errs.append("%s: %s"%(type(e).__name__,e))
    raise StopPush("无法初始化 bare 仓库 %s：%s"%(path,errs[:3]))  # 兼容不同 dulwich 版本的 init_bare 签名
def patch_add_thin_pack(repo):
    """dulwich 1.2.15 的服务端会向 add_thin_pack 传 max_input_size，而 MemoryObjectStore 等实现不接受该参数（导致服务端 500）。
    这里做签名探测并包装，使自测在任何 object_store 实现上都能跑通。"""
    store=repo.object_store;fn=getattr(store,"add_thin_pack",None)
    if fn is None:return
    try:
        if "max_input_size" in inspect.signature(fn).parameters:return
    except (TypeError,ValueError):return
    def wrapper(*args,**kw):
        kw.pop("max_input_size",None);return fn(*args,**kw)
    try:store.add_thin_pack=wrapper
    except Exception:
        with suppress(Exception):setattr(type(store),"add_thin_pack",wrapper)
def self_test():
    """内置自测（完全离线）：Windows 临时目录与 Repo.init、读取竞态修复、忽略规则优先级、属性宏与引号、
    LFS 全流程、拆分提交、Smart HTTP 推送（真实 dulwich 服务端 + 磁盘 bare 仓库）、网络重试/重定向/认证、
    低速看门狗、CLI 与 dry-run、日志脱敏。"""
    class Base(unittest.TestCase):
        def setUp(self):
            self.temp=make_temp_repo();self.addCleanup(rmtree_force,self.temp)
            self.root=Path(self.temp)/"repo";self.root.mkdir(parents=True,exist_ok=True)
            self.repo=init_worktree(self.root);self.addCleanup(self.repo.close)
            cf=self.repo.get_config()
            cf.set((b"core",),b"repositoryformatversion",b"0")
            cf.set((b"core",),b"ignorecase",b"true" if os.name=="nt" else b"false")
            cf.set((b"core",),b"excludesfile",os.fsencode(str(Path(self.temp)/"global-ignore")))  # 显式指定，避免被开发者机器上的全局配置影响
            cf.set((b"core",),b"attributesfile",os.fsencode(str(Path(self.temp)/"global-attributes")))
            cf.set((b"user",),b"name",b"Tester");cf.set((b"user",),b"email",b"tester@example.com")
            cf.write_to_path()
            self.a=finalize(build_parser().parse_args(["--repo",str(self.root),"--progress-interval","5","--speed-window","0.2","--low-speed-time","0","--lfs-threshold","0.0005","--max-blob-size","0.001","--max-commit-size","0.0009","--retries","2","--retry-delay","0.01","--temp-dir",str(Path(self.temp)/"pack-tmp")]))
            self.a.verbose=1;self.identity=b"Tester <tester@example.com>";self.cache=LfsCache(self.repo,self.a)
        def write(self,name,data):
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True)
            if isinstance(data,str):data=data.encode()
            with open(str(p),"wb") as f:f.write(data)
            return p
        def stage(self):return prepare(self.repo,self.a,self.identity,self.cache)
        def head_tree(self):return tree_map(self.repo,self.repo.head())
        def blob(self,path):return self.repo.object_store[self.head_tree()[path][0]].data
    class Tests(Base):
        def test_windows_temp_dir_and_repo_init(self):
            """Windows 临时目录 + Repo.init 的正确姿势：realpath 展开短名、目录先建、unborn HEAD 是符号引用、只读对象可清理。"""
            self.assertEqual(self.temp,os.path.realpath(self.temp));self.assertTrue(os.path.isabs(self.temp))
            self.assertTrue((self.root/".git").is_dir(),".git 目录必须存在: %s"%self.root)
            raw=self.repo.refs.read_ref(b"HEAD");self.assertIsNotNone(raw);self.assertIn(b"ref: refs/heads/",raw)  # 新仓库是 unborn，不能直接取 refs[b'HEAD']
            sym=self.repo.refs.get_symrefs();self.assertIn(b"HEAD",sym)
            with self.assertRaises(KeyError):self.repo.refs[sym[b"HEAD"]]  # 分支尚不存在
            self.assertFalse(self.repo.bare)
            self.write("hello.txt","Hello, Dulwich!");ids,new=self.stage()
            self.assertEqual(len(ids),1);self.assertEqual(self.repo.head(),new);self.assertEqual(ids[-1],new)
            self.assertEqual(self.blob(b"hello.txt"),b"Hello, Dulwich!")
            obj=Path(self.repo.controldir())/"objects"/text(new)[:2]/text(new)[2:]
            if obj.exists():os.chmod(str(obj),0o444)  # 制造只读对象文件，验证 rmtree_force 能清理
            second=make_temp_repo();self.addCleanup(rmtree_force,second);self.assertTrue(os.path.isdir(second))
            bare=init_bare(Path(self.temp)/"bare.git");self.addCleanup(bare.close)
            self.assertTrue(bare.bare);patch_add_thin_pack(bare)  # bare 仓库必须能建出来且被 dulwich 认作 bare
            self.assertTrue((Path(self.temp)/"bare.git"/"objects").is_dir());self.assertTrue((Path(self.temp)/"bare.git"/"refs").is_dir())
            nested=Path(self.temp)/"deep"/"nested.git";repo2=init_bare(nested);self.addCleanup(repo2.close)  # init_bare 必须自己把多级目录建出来
            self.assertTrue(repo2.bare);self.assertFalse((nested/"index").exists())
        def test_regular_reader_no_false_race(self):
            """回归 L988 的致命 bug：刚写完的文件必须能读；只拒绝目录/符号链接/超限，并能发现“读取期间被改”。"""
            p=self.write("fresh.bin",b"x"*4096)
            data,st=read_regular(p)  # 之前这里在 Windows 上必报“读取前文件已经变化”
            self.assertEqual(data,b"x"*4096);self.assertEqual(st.st_size,4096)
            self.assertEqual(read_regular(p,limit=8192)[0],data)
            with self.assertRaises(StopPush):read_regular(p,limit=10)
            with self.assertRaises(StopPush):read_regular(self.root)  # 目录
            with self.assertRaises(StopPush):read_regular(self.root/"nope.bin")  # 不存在
            self.assertEqual(config_bytes(self.root/"nope.bin"),b"")
            self.assertEqual(config_bytes(self.write("cfg.txt",b"abc")),b"abc")
            for i in range(5):  # 连续写完立刻读：模拟真实 push 的时序
                q=self.write("loop%d.bin"%i,b"y"*(100+i));self.assertEqual(read_regular(q)[0],b"y"*(100+i))
            link=self.root/"alink";linked=False
            try:os.symlink(str(p),str(link));linked=True
            except (OSError,NotImplementedError,AttributeError):linked=False  # Windows 无符号链接权限时不 skip，只跳过这一小段
            if linked:
                with self.assertRaises(StopPush):read_regular(link)  # 拒绝跟随链接读取
                self.assertEqual(config_bytes(link),b"")
            with self.assertRaises(StopPush):  # 读取期间被追加 → 退出上下文时必须检测到
                with regular_reader(p) as (f,_):
                    f.read(1)
                    with open(str(p),"ab") as g:g.write(b"zzz")
            self.assertEqual(read_regular(p)[0],b"x"*4096+b"zzz")
        def test_attributes_macros_quotes_precedence(self):
            self.write(".gitattributes",b"*.lfs filter=lfs diff=lfs merge=lfs -text\n[attr]mymacro text eol=lf\n\"with space.bin\" filter=lfs\n/root-only.txt text\nsub/** text\n")
            self.write("sub/.gitattributes",b"*.txt !text filter=lfs\n")
            self.write("nested/deep/.gitattributes",b"[attr]bad x=y\n")
            index=self.repo.open_index();attrs=Attributes(self.repo,self.repo.get_config(),index)
            self.assertEqual(attrs.get(b"a.lfs").get(b"filter"),b"lfs");self.assertIs(attrs.get(b"a.lfs").get(b"text"),False)  # -text 生效
            self.assertEqual(attrs.get(b"with space.bin").get(b"filter"),b"lfs")  # C 引号路径必须解析
            self.assertIs(attrs.get(b"root-only.txt").get(b"text"),True)
            self.assertIsNone(attrs.get(b"deep/root-only.txt").get(b"text"))  # 前导 / 锚定到根
            self.assertIs(attrs.get(b"sub/x/y.txt").get(b"text"),True)  # ** 跨目录
            self.assertIsNone(attrs.get(b"sub/a.txt").get(b"text"));self.assertEqual(attrs.get(b"sub/a.txt").get(b"filter"),b"lfs")  # 子目录 !text 覆盖根目录
            (Path(self.repo.controldir())/"info").mkdir(parents=True,exist_ok=True)
            with open(str(Path(self.repo.controldir())/"info"/"attributes"),"wb") as f:f.write(b"*.txt filter=lfs\n")
            a2=Attributes(self.repo,self.repo.get_config(),index)
            self.assertEqual(a2.get(b"top.txt").get(b"filter"),b"lfs")  # info/attributes 优先级最高
            with open(str(Path(self.temp)/"global-attributes"),"wb") as f:f.write(b"*.glob binary\n*.lfs text\n")
            a3=Attributes(self.repo,self.repo.get_config(),index)
            self.assertIs(a3.get(b"x.glob").get(b"text"),False);self.assertIs(a3.get(b"x.glob").get(b"diff"),False);self.assertIs(a3.get(b"x.glob").get(b"merge"),False)  # binary 宏展开
            self.assertEqual(a3.get(b"g.lfs").get(b"filter"),b"lfs");self.assertIs(a3.get(b"g.lfs").get(b"text"),False)  # 根目录 .gitattributes 覆盖全局
            self.assertEqual(parse_attribute(b"-text"),(b"text",False));self.assertEqual(parse_attribute(b"!text"),(b"text",None))
            self.assertEqual(parse_attribute(b"eol=lf"),(b"eol",b"lf"));self.assertEqual(parse_attribute(b"text"),(b"text",True))
            self.assertEqual(c_unquote(b'"a\\tb" text'),(b"a\tb",[b"text"]))
            self.assertEqual(c_unquote(b'"\\346\\226\\207.bin" filter=lfs'),("文".encode(),[b"filter=lfs"]))  # 八进制转义的中文路径
            self.assertEqual(c_unquote(b"# comment"),(None,[]))
            with self.assertRaises(StopPush):c_unquote(b'"unclosed text')
            with self.assertRaises(StopPush):c_unquote(b'"bad\\q" text')
            self.write("neg/.gitattributes",b"!bad text\n")
            with self.assertRaises(StopPush):Attributes(self.repo,self.repo.get_config(),index).load(Path(self.root)/"neg"/".gitattributes")  # 属性文件里的负模式非法
            self.assertTrue(Attributes.match(b"*.lfs",b"dir/x.lfs"));self.assertFalse(Attributes.match(b"*.lfs",b"dir/x/lfs.txt"))
            self.assertTrue(Attributes.match(b"sub/**",b"sub/a/b.txt"));self.assertFalse(Attributes.match(b"sub/*",b"sub/a/b.txt"))
            self.assertTrue(Attributes.match(b"a?c",b"abc"));self.assertFalse(Attributes.match(b"a?c",b"a/c"))
            self.assertTrue(Attributes.match(b"/a.txt",b"a.txt"));self.assertFalse(Attributes.match(b"/a.txt",b"d/a.txt"))
        def test_ignore_precedence_and_tracked(self):
            self.write("drop.tmp",b"v1");ids,_=self.stage()  # 先让 drop.tmp 成为已跟踪文件
            self.assertIn(b"drop.tmp",self.head_tree())
            self.write(".gitignore",b"*.tmp\n!keep.tmp\nblocked/\nselect/*\n!select/keep.txt\nignored-large.bin\n")
            self.write("nested/.gitignore",b"!stay.tmp\n")
            for n in ("keep.tmp","blocked/no.txt","select/keep.txt","select/no.txt","nested/stay.tmp","nested/gone.tmp","has space.bin","ignored-large.bin","global-only.txt","excluded.txt"):self.write(n,b"data")
            with open(str(Path(self.temp)/"global-ignore"),"wb") as f:f.write(b"global-only.txt\n")
            with open(str(Path(self.repo.controldir())/"info"/"exclude"),"wb") as f:f.write(b"excluded.txt\n")
            manager=ignore_manager(self.repo,self.repo.get_config())
            self.assertIs(manager.is_ignored("drop.tmp"),True);self.assertIs(manager.is_ignored("keep.tmp"),False)  # ! 重新包含
            self.assertIs(manager.is_ignored("blocked/no.txt"),True);self.assertIs(manager.is_ignored("select/no.txt"),True)
            self.assertIs(manager.is_ignored("select/keep.txt"),False);self.assertIs(manager.is_ignored("nested/stay.tmp"),False)  # 嵌套 .gitignore 优先
            self.assertIs(manager.is_ignored("nested/gone.tmp"),True);self.assertIs(manager.is_ignored("global-only.txt"),True)
            self.assertIs(manager.is_ignored("excluded.txt"),True);self.assertIs(manager.is_ignored("has space.bin"),False)
            self.assertIs(manager.is_ignored("normal.txt"),None)  # 无匹配返回 None，而不是 False
            files=walk_candidates(self.repo,self.repo.open_index(),manager,self.repo.get_config())
            self.assertIn(b"drop.tmp",files,"已跟踪文件必须绕过忽略规则")
            self.assertNotIn(b"select/no.txt",files);self.assertNotIn(b"blocked/no.txt",files);self.assertNotIn(b"global-only.txt",files)
            self.assertIn(b"keep.tmp",files);self.assertIn(b"has space.bin",files);self.assertIn(b"select/keep.txt",files)
            self.write("drop.tmp",b"v2");ids2,_=self.stage()
            self.assertTrue(ids2);self.assertEqual(self.blob(b"drop.tmp"),b"v2")  # 已跟踪且被忽略的文件修改仍要提交
            self.write("select/no.txt",b"new");self.stage()
            self.assertNotIn(b"select/no.txt",self.head_tree())
            (self.root/"drop.tmp").unlink();ids3,_=self.stage();self.assertTrue(ids3)
            self.assertNotIn(b"drop.tmp",self.head_tree())  # 删除也要被暂存
        def test_symlink_not_walked(self):
            self.write("target-dir/inner.txt",b"secret")
            try:os.symlink("target-dir",str(self.root/"dirlink"),target_is_directory=True)
            except (OSError,NotImplementedError,AttributeError,TypeError):self.skipTest("无符号链接权限（Windows 需开发者模式）")
            manager=ignore_manager(self.repo,self.repo.get_config())
            files=walk_candidates(self.repo,self.repo.open_index(),manager,self.repo.get_config())
            self.assertIn(b"dirlink",files);self.assertNotIn(b"dirlink/inner.txt",files)  # 只登记链接本身，绝不进入目标
            self.assertIn(b"target-dir/inner.txt",files)
            ids,_=self.stage();self.assertTrue(ids)
            sha,mode=self.head_tree()[b"dirlink"]
            if os.name!="nt":self.assertEqual(mode,0o120000);self.assertEqual(self.repo.object_store[sha].data,b"target-dir")
        def test_lfs_stage_history_and_oversize(self):
            self.write(".gitattributes",b"*.lfs filter=lfs diff=lfs merge=lfs -text\n")
            self.write("small.lfs",b"x");self.write("auto.bin",b"q"*600);self.write("normal.txt",b"hello")
            ids,_=self.stage();self.assertEqual(len(ids),1)
            info=pointer_info(self.blob(b"auto.bin"));self.assertIsNotNone(info,"超过阈值的文件应自动转 LFS")  # 阈值 0.0005MiB≈524B
            self.assertTrue(self.cache.path(info[0]).is_file());self.assertEqual(info[1],600)
            self.assertEqual(self.cache.path(info[0]).stat().st_size,600)
            self.assertIsNotNone(pointer_info(self.blob(b"small.lfs")))  # 属性 filter=lfs 的小文件也进 LFS
            self.assertEqual(self.blob(b"normal.txt"),b"hello")
            oid,size=info
            self.assertEqual(outgoing_lfs(self.repo,[],[self.repo.head()],self.a)[oid],size)
            (self.root/"auto.bin").unlink();ids2,_=self.stage();self.assertTrue(ids2)
            self.assertNotIn(b"auto.bin",self.head_tree())
            self.assertEqual(outgoing_lfs(self.repo,[],[self.repo.head()],self.a)[oid],size,"删除文件后历史里的指针仍必须上传")
            self.assertEqual(outgoing_lfs(self.repo,[self.repo.head()],[self.repo.head()],self.a),{},"have 已覆盖时不应有增量")
            self.a.auto_lfs=False;self.a.no_auto_lfs=True;self.write("oversize",b"z"*900);self.stage()
            self.a.max_blob_size=400
            with self.assertRaises(StopPush):self.stage()  # 关闭自动 LFS 后超限必须硬失败
            self.a.auto_lfs=True;self.a.no_auto_lfs=False;self.a.max_blob_size=2000
            os.chmod(str(self.cache.path(oid)),0o644);self.cache.path(oid).unlink();self.cache.verified.clear()
            with self.assertRaises(StopPush):self.cache.require(oid,size)  # 缓存缺失时禁止只发指针
            self.write("payload",b"binary"*100);info2=pointer_info(self.cache.put(self.root/"payload"))
            self.assertEqual(info2[1],600);self.assertEqual(self.cache.require(*info2).stat().st_size,600)
        def test_normalize_blob_crlf_ident_binary(self):
            config=self.repo.get_config();old=None
            self.assertEqual(normalize_blob(b"a\r\nb",{},old,self.repo,config,b"x"),b"a\r\nb")  # 默认不做任何转换
            self.assertEqual(normalize_blob(b"a\r\nb",{b"text":True},old,self.repo,config,b"x"),b"a\nb")
            self.assertEqual(normalize_blob(b"a\r\nb",{b"filter":b"lfs",b"text":False},old,self.repo,config,b"x"),b"a\r\nb")
            self.assertEqual(normalize_blob(b"$Id: whatever 123 $",{b"ident":True},old,self.repo,config,b"x"),b"$Id$")
            self.assertEqual(normalize_blob(b"\0\1\2bin",{b"text":True},old,self.repo,config,b"x"),b"\0\1\2bin")  # 含 NUL → 二进制，不转换
            with self.assertRaises(StopPush):normalize_blob(b"x",{b"filter":b"indent"},old,self.repo,config,b"x")  # 未知过滤器拒绝
            with self.assertRaises(StopPush):normalize_blob(b"x",{b"working-tree-encoding":b"GBK"},old,self.repo,config,b"x")
            config.set((b"core",),b"autocrlf",b"true");config.set((b"core",),b"safecrlf",b"true")
            self.assertEqual(normalize_blob(b"a\r\nb",{},old,self.repo,config,b"x"),b"a\nb")
            with self.assertRaises(StopPush):normalize_blob(b"a\rb",{},old,self.repo,config,b"x")  # 裸 CR 不可逆
            config.set((b"core",),b"safecrlf",b"warn");self.assertEqual(normalize_blob(b"a\rb",{},old,self.repo,config,b"x"),b"a\rb")
            config.set((b"core",),b"safecrlf",b"false");config.set((b"core",),b"autocrlf",b"input")
            self.assertEqual(normalize_blob(b"a\r\nb",{},old,self.repo,config,b"x"),b"a\nb")
            self.assertEqual(normalize_blob(b"a\r\nb",{b"eol":b"crlf"},old,self.repo,config,b"x"),b"a\nb")
        def test_split_commits_deletions_and_readme(self):
            self.write("ReadMe.md",b"# doc")
            for i in range(8):self.write("file%d"%i,b"x"*300)  # 合计 2407B，单提交上限 0.0009MiB≈943B → 必然拆成 3 个提交
            ids,_=self.stage();self.assertEqual(len(ids),3,"按 --max-commit-size 应拆成 3 个提交")
            self.assertIn(b"ReadMe.md",[e.path for e in iter_tree_contents(self.repo.object_store,self.repo[ids[0]].tree)])  # ReadMe 优先
            for i in range(1,len(ids)):self.assertEqual(self.repo[ids[i]].parents,[ids[i-1]])  # 链式父子关系
            self.write("file0",b"y"*10);(self.root/"file1").unlink();self.write("zzz-new",b"new")
            ids2,_=self.stage();self.assertTrue(ids2)
            tree=self.head_tree();self.assertNotIn(b"file1",tree);self.assertIn(b"zzz-new",tree)
            self.assertEqual(self.repo[ids2[0]].parents,[ids[-1]]);self.assertEqual(self.repo.head(),ids2[-1])
            self.assertEqual(len(self.repo.open_index().items()),len(tree))
            self.assertEqual(self.blob(b"file0"),b"y"*10)
        def test_repo_state_and_atomic_write(self):
            config=self.repo.get_config();check_repo_state(self.repo,config)
            (Path(self.repo.controldir())/"MERGE_HEAD").write_bytes(b"0"*40+b"\n")
            with self.assertRaises(StopPush):check_repo_state(self.repo,config)
            (Path(self.repo.controldir())/"MERGE_HEAD").unlink()
            config.set((b"commit",),b"gpgsign",b"true")
            with self.assertRaises(StopPush):check_repo_state(self.repo,config)
            config.set((b"commit",),b"gpgsign",b"false")
            config.set((b"core",),b"splitindex",b"true")
            with self.assertRaises(StopPush):check_repo_state(self.repo,config)
            config.set((b"core",),b"splitindex",b"false")
            p=self.root/"cfg.txt";atomic_write(p,b"one");self.assertEqual(p.read_bytes(),b"one")
            atomic_write(p,b"two");self.assertEqual(p.read_bytes(),b"two")
            self.assertFalse(list(p.parent.glob(".purepush-*")),"临时文件必须被清理")
            link=self.root/"cfglink";linked=False
            try:os.symlink(str(p),str(link));linked=True
            except (OSError,NotImplementedError,AttributeError):linked=False  # Windows 无符号链接权限时不影响本用例其余断言
            if linked:
                with self.assertRaises(StopPush):atomic_write(link,b"nope")  # 绝不覆盖符号链接
                self.assertEqual(p.read_bytes(),b"two")
        def test_url_parsing_redaction_and_retry(self):
            url,user,pw,br=parse_url("https://qgbcs:ghp_secret@github.com/qgbcs/_")
            self.assertEqual(url,"https://github.com/qgbcs/_.git");self.assertEqual(user,"qgbcs");self.assertEqual(pw,"ghp_secret");self.assertEqual(br,"master")
            self.assertEqual(parse_url("https://github.com/qgbcs/_/tree/dev/x")[3],"dev")
            self.assertEqual(parse_url("https://github.com/qgbcs/_.git")[0],"https://github.com/qgbcs/_.git")
            self.assertEqual(parse_url("git@github.com:qgbcs/_.git")[0],"https://github.com/qgbcs/_.git")
            self.assertEqual(parse_url("github.com/qgbcs/_")[0],"https://github.com/qgbcs/_.git")
            self.assertEqual(parse_url("https://github.com/qgbcs/_","dev")[3],"dev")
            with self.assertRaises(StopPush):parse_url("ssh://git@github.com/qgbcs/_.git")
            with self.assertRaises(StopPush):parse_url("")
            with self.assertRaises(StopPush):parse_url("https://github.com")
            self.assertIn("***",redact("token ghp_secret leaked"))
            self.assertNotIn("ghp_secret",safe_url("https://u:ghp_secret@github.com/o/r?sig=abc"))
            self.assertNotIn("sig=abc",safe_url("https://h/o/r?sig=abc"))
            self.assertTrue(classify(NetworkFailure("x")));self.assertTrue(classify(HTTPFailure(503,"u")));self.assertTrue(classify(HTTPFailure(429,"u")))
            self.assertFalse(classify(HTTPFailure(403,"u")));self.assertFalse(classify(StopPush("x")));self.assertTrue(classify(socket.timeout()))
            self.assertTrue(classify(ConnectionResetError()));self.assertFalse(classify(ValueError()))
            self.assertEqual(retry_delay("2"),2.0);self.assertEqual(retry_delay(None),0.0);self.assertEqual(retry_delay("abc"),0.0)
            a=finalize(build_parser().parse_args(["-u","push","https://x/y","--retries","1","--retry-delay","0.01","--low-speed-time","0"]))
            self.assertEqual(a.url,"https://x/y");calls=[]
            def op():
                calls.append(1)
                if len(calls)<2:raise NetworkFailure("flaky")
                return "ok"
            self.assertEqual(retry(a,"t",op),"ok");self.assertEqual(len(calls),2)
            def always():raise HTTPFailure(403,"u")
            with self.assertRaises(HTTPFailure):retry(a,"t",always)
            self.assertEqual(len(calls),2,"不可重试的错误不应再调用")
            self.assertEqual(pkt_lines(b"0009abcd\n0000"),[b"abcd\n"])  # pkt-line 解析
        def test_smart_http_push_idempotent_force_and_delete(self):
            """用真实 dulwich 服务端 + 磁盘 bare 仓库，避开 MemoryObjectStore.add_thin_pack 的 dulwich 自身 bug。"""
            from dulwich.server import DictBackend
            from dulwich.web import make_wsgi_chain
            from wsgiref.simple_server import make_server,WSGIRequestHandler
            class Quiet(WSGIRequestHandler):
                def log_message(self,*a):pass
            self.write(".gitattributes",b"*.lfs filter=lfs diff=lfs merge=lfs -text\n")
            self.write("http-file",b"smart-http");self.write("big.lfs",b"L"*700);self.write("ReadMe.md",b"doc")
            ids,new=self.stage();self.assertTrue(ids)
            bare=init_bare(Path(self.temp)/"remote.git");self.addCleanup(bare.close);patch_add_thin_pack(bare)
            app=make_wsgi_chain(DictBackend({"/test.git":bare}))
            server=make_server("127.0.0.1",0,app,handler_class=Quiet)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            url="http://127.0.0.1:%d/test.git"%server.server_port
            net=Transport(self.a,{});self.addCleanup(net.close)
            try:
                with patch("subprocess.Popen",side_effect=AssertionError("禁止启动任何子进程")):
                    self.assertEqual(remote_refs(net,url,self.a),{},"空仓库没有引用")
                    push_target(self.repo,self.a,url,b"refs/heads/main",new,net,self.cache)
                    self.assertEqual(bare.refs[b"refs/heads/main"],new)
                    self.assertEqual(bare[new].tree,self.repo[new].tree)  # 对象真的进了远端
                    self.assertEqual(self.blob(b"http-file"),b"smart-http")
                    self.assertIn("refs/heads/main",remote_refs(net,url,self.a))
                    push_target(self.repo,self.a,url,b"refs/heads/main",new,net,self.cache)  # 幂等：第二次必须是空操作且不报错
                    self.assertEqual(bare.refs[b"refs/heads/main"],new)
                    objs=outgoing_lfs(self.repo,[],[new],self.a);self.assertTrue(objs,"应发现 big.lfs 的指针")
                    self.write("after",b"more");ids2,new2=self.stage()
                    side=Commit();side.tree=self.repo[new2].tree;side.parents=[];side.author=side.committer=self.identity
                    side.author_time=side.commit_time=1;side.author_timezone=side.commit_timezone=0;side.message=b"side"
                    self.repo.object_store.add_object(side);bare.refs[b"refs/heads/main"]=side.id  # 制造非快进
                    self.assertIs(is_ancestor(self.repo.object_store,side.id,new2),False)
                    with self.assertRaises(StopPush):push_target(self.repo,self.a,url,b"refs/heads/main",new2,net,self.cache)
                    self.assertNotEqual(bare.refs[b"refs/heads/main"],new2,"被拒绝时远端不应改变")
                    self.a.force=True;push_target(self.repo,self.a,url,b"refs/heads/main",new2,net,self.cache)
                    self.assertEqual(bare.refs[b"refs/heads/main"],new2)
                    self.a.delete=True;push_target(self.repo,self.a,url,b"refs/heads/main",None,net,self.cache)
                    self.assertNotIn(b"refs/heads/main",bare.refs.as_dict())
            finally:
                server.shutdown();server.server_close();thread.join(timeout=3)
        def test_network_retry_redirect_auth_and_lfs_upload(self):
            counters={};stored={};test=self
            class Handler(BaseHTTPRequestHandler):
                protocol_version="HTTP/1.1"
                def log_message(self,*a):pass
                def reply(self,code,body,headers=None):
                    self.send_response(code)
                    for k,v in (headers or {}).items():self.send_header(k,v)
                    self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
                def do_GET(self):
                    counters[self.path]=counters.get(self.path,0)+1
                    if self.path=="/flaky" and counters[self.path]==1:self.reply(503,b"retry",{"Retry-After":"0"});return
                    if self.path=="/denied":self.reply(401,b"denied",{"WWW-Authenticate":'Basic realm="t"'});return
                    if self.path=="/auth-check":self.reply(200,(self.headers.get("Authorization") or "").encode());return
                    if self.path=="/redirect":self.reply(302,b"",{"Location":"http://localhost:%d/auth-check"%self.server.server_port});return
                    self.reply(200,b"ok")
                def do_PUT(self):
                    data=self.rfile.read(int(self.headers["Content-Length"]));stored[hashlib.sha256(data).hexdigest()]=data
                    counters["put-path"]=self.path;counters["put-auth"]=self.headers.get("Authorization");counters["put-ctype"]=self.headers.get("Content-Type")
                    self.reply(200,b"")
                def do_POST(self):
                    body=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    if self.path=="/verify":
                        test.assertEqual(len(stored[body["oid"]]),body["size"]);counters["verify"]=counters.get("verify",0)+1;self.reply(200,b"{}");return
                    objects=[]
                    for item in body["objects"]:
                        item=dict(item)
                        if item["oid"] not in stored:
                            item["actions"]={"upload":{"href":"http://127.0.0.1:%d/upload?signature=kept"%self.server.server_port,"header":{"X-Custom":"1"}},"verify":{"href":"http://127.0.0.1:%d/verify"%self.server.server_port}}
                        objects.append(item)
                    counters["batch-ref"]=body.get("ref",{}).get("name");counters["batch-op"]=body.get("operation")
                    self.reply(200,json.dumps({"objects":objects}).encode(),{"Content-Type":MEDIA})
            server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base="http://127.0.0.1:%d"%server.server_port
            net=Transport(self.a,{origin(base):"Basic unit-test-secret"})
            def get(path,client=None):
                r=(client or net).request("GET",base+path);b=r.read();r.close();return b
            try:
                self.assertEqual(retry(self.a,"重试",lambda:get("/flaky")),b"ok");self.assertEqual(counters["/flaky"],2)
                with self.assertRaises(HTTPFailure):retry(self.a,"认证",lambda:get("/denied"))
                self.assertEqual(counters["/denied"],1,"已带凭据仍 401 时不应重试")
                self.assertEqual(get("/auth-check"),b"Basic unit-test-secret","同源请求自动注入凭据")
                self.assertEqual(get("/redirect"),b"","跨源重定向必须丢弃 Authorization")
                self.assertEqual(counters["/auth-check"],2)
                anon=Transport(self.a,{})
                with self.assertRaises(HTTPFailure):get("/denied",anon)  # 无凭据时 401 直接失败
                anon.close()
                p=self.write("payload",b"binary"*100);info=pointer_info(self.cache.put(p));self.assertIsNotNone(info)
                oid,size=info;done=set()
                upload_lfs(net,base+"/batch",{oid:size},self.cache,b"refs/heads/main",done,self.a)
                self.assertIn((oid,size),done);self.assertEqual(stored[oid],b"binary"*100)
                self.assertEqual(counters["put-path"],"/upload?signature=kept");self.assertEqual(counters["put-ctype"],"application/octet-stream")
                self.assertEqual(counters["put-auth"],"Basic unit-test-secret");self.assertEqual(counters["batch-ref"],"refs/heads/main")
                self.assertEqual(counters["batch-op"],"upload");self.assertEqual(counters.get("verify"),1)
                upload_lfs(net,base+"/batch",{oid:size},self.cache,b"refs/heads/main",done,self.a)  # 已完成的对象不再上传
                self.assertEqual(counters.get("verify"),1)
                self.assertEqual(upload_lfs(net,base+"/batch",{},self.cache,b"refs/heads/main",done,self.a),done)
                self.assertEqual(lfs_endpoint(self.a,self.repo,self.repo.get_config(),base+"/r.git","origin"),base+"/r.git/info/lfs/objects/batch")
                self.a.lfs_url=base+"/custom";self.assertEqual(lfs_endpoint(self.a,self.repo,self.repo.get_config(),base+"/r.git","origin"),base+"/custom/objects/batch")
                self.a.lfs_url=None
                self.write(".lfsconfig",b"[lfs]\n\turl = %s/cfg-lfs\n"%base.encode())
                self.assertEqual(lfs_endpoint(self.a,self.repo,self.repo.get_config(),base+"/r.git","origin"),base+"/cfg-lfs/objects/batch")
            finally:
                net.close();server.shutdown();server.server_close();thread.join(timeout=3)
        def test_low_speed_watchdog_and_monitor(self):
            class Dummy:
                closed=False
                def shutdown(self,how):self.closed=True
                def close(self):self.closed=True
                def getsockname(self):return ("127.0.0.1",1)
                def getpeername(self):return ("127.0.0.1",2)
            sock=Dummy();self.a.progress_interval=0.01;self.a.low_speed_time=0.05;self.a.low_speed_limit=1000
            mon=TransferMonitor(sock,self.a,"测试",total=1000,tty=False)
            deadline=time.monotonic()+3
            while not sock.closed and time.monotonic()<deadline:time.sleep(0.01)
            mon.stop(final=False);self.assertTrue(sock.closed,"低速看门狗必须主动断开");self.assertTrue(mon.stalled)
            sock2=Dummy();self.a.low_speed_time=0;mon2=TransferMonitor(sock2,self.a,"测试2",total=1000,tty=False)
            for _ in range(50):mon2.add(10)
            self.assertEqual(mon2.sent,500);self.assertIn("测试2",mon2.line());self.assertIn("50.0%",mon2.line())
            self.assertFalse(sock2.closed,"关闭看门狗后不应断开");self.assertTrue(mon2.average()>=0)
            mon2.add(20,-1);self.assertEqual(mon2.recv,20)
            mon2.report();mon2.stop(final=False)
            self.assertIn("→",describe_socket(sock2))
        def test_cli_dry_run_and_no_subprocess(self):
            self.write("a.txt",b"1");self.write("b.bin",b"y"*700)
            self.a.dry_run=True
            with patch("subprocess.Popen",side_effect=AssertionError("dry-run 不得启动子进程")):
                ids,new=self.stage();self.assertEqual((ids,new),([],None))
            self.assertIsNone(local_head(self.repo))  # dry-run 不产生任何提交（unborn HEAD 仍然是 unborn）
            idx=Path(self.repo.controldir())/"index"
            self.assertTrue(not idx.exists() or len(self.repo.open_index().items())==0,"dry-run 不得写入索引条目")
            self.assertIs(self.repo.refs.read_ref(b"refs/heads/master"),None)
            self.a.dry_run=False;ids,new=self.stage();self.assertTrue(ids)
            self.a.dry_run=True;ids2,new2=self.stage();self.assertEqual((ids2,new2),([],None))  # 无变化时也不创建空提交
            self.a.dry_run=False
            with self.assertRaises(SystemExit):build_parser().parse_args(["--nope"])
            a=finalize(build_parser().parse_args(["-v","-v","-v","-u","push","https://u:t@github.com/o/r","--branch","dev","--force","--atomic","--push-option","ci.skip","--trace","--tty","0","--delete","--renormalize"]))
            self.assertEqual(a.verbose,3);self.assertEqual(a.url,"https://u:t@github.com/o/r");self.assertTrue(a.force);self.assertTrue(a.atomic)
            self.assertEqual(a.push_option,["ci.skip"]);self.assertEqual(a.lfs_threshold,100*1024*1024);self.assertFalse(a.tty)
            self.assertTrue(a.delete);self.assertTrue(a.renormalize);self.assertEqual(a.branch,"dev")
            self.assertEqual(identity_of(finalize(build_parser().parse_args([])),self.repo,self.repo.get_config(),"qgb"),b"Tester <tester@example.com>")  # 仓库配置优先
            cfgx=ConfigFile();a2=finalize(build_parser().parse_args(["--author","Q GB <q@e.com>"]))
            self.assertEqual(identity_of(a2,self.repo,cfgx,None),b"Q GB <q@e.com>")
            a3=finalize(build_parser().parse_args([]))
            self.assertEqual(identity_of(a3,self.repo,cfgx,"qgbcs"),b"qgbcs <qgbcs@users.noreply.github.com>")  # 无配置时用 URL 用户名推导
        def test_secrets_and_logging(self):
            setup_logging(1);remember("SUPERSECRET123")
            self.assertEqual(redact("https://user:SUPERSECRET123@h/p?x=1"),"https://h/p")
            self.assertIn("***",redact("value SUPERSECRET123 here"))
            rec=logging.LogRecord("t",logging.INFO,__file__,1,"msg %s","SUPERSECRET123",None)
            self.assertIn("***",SafeFormatter("%(message)s").format(rec))
            self.assertEqual(human(0),"0 B");self.assertEqual(human(1024),"1.00 KiB");self.assertEqual(human(5*1024*1024),"5.00 MiB")
            self.assertEqual(elapsed(3661),"1h01m01s");self.assertEqual(elapsed(61),"1m01s");self.assertEqual(elapsed(5),"5s")
            self.assertEqual(origin("https://u:p@h.com:443/a/b?c=1"),"https://h.com:443")
            self.assertEqual(text(b"abc"),"abc");self.assertEqual(text("abc"),"abc")
    suite=unittest.TestLoader().loadTestsFromTestCase(Tests)
    result=unittest.TextTestRunner(verbosity=2,stream=sys.stdout).run(suite)
    return 0 if result.wasSuccessful() else 1
def run(argv=None):
    a=build_parser().parse_args(argv)
    if a.self_test:return self_test()
    setup_logging(a.verbose)
    try:return main(a)
    except StopPush as e:
        LOG.error("失败: %s",redact(e))
        if a.verbose>=3:import traceback;traceback.print_exc()
        return 1
    except NetworkFailure as e:
        LOG.error("网络失败（重试已耗尽）: %s",redact(e))
        if a.verbose>=3:import traceback;traceback.print_exc()
        return 2
    except KeyboardInterrupt:
        LOG.error("已被用户中断");return 130
    except Exception as e:
        LOG.error("未预期错误: %s: %s",type(e).__name__,redact(e));import traceback;traceback.print_exc()
        return 3
if __name__=="__main__":sys.exit(run())
'''

'''