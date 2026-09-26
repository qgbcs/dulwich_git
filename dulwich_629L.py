#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dulwich_push.py —— dulwich 1.2.15 + 标准库实现 push，细节对齐 git_logic.py；不启动 git / git-lfs 进程。"""
import argparse,base64,hashlib,http.client,json,logging,os,ssl,sys,time,urllib3
from pathlib import Path
from urllib.parse import unquote,urlsplit,urlunsplit
from dulwich import __version__ as DULWICH_VERSION
from dulwich.client import HTTPUnauthorized,get_transport_and_path_from_url
from dulwich.errors import SendPackError
from dulwich.ignore import IgnoreFilterManager,Pattern
from dulwich.index import index_entry_from_stat
from dulwich.objects import Blob,Commit,Tree
from dulwich.protocol import ZERO_SHA
from dulwich.repo import Repo
LOG=logging.getLogger("GitAutoPush")
UA="git/2.45.0"
INLINE_MAX=512*1024*1024
POINTER_HEAD=b"version https://git-lfs.github.com/spec/v1"
NET_KEYS=("timed out","timeout","connection reset","connection aborted","connection refused","failed to connect","unable to access","remote end hung up","network is unreachable","recv failure","unexpected eof","broken pipe","rpc failed","expected flush after ref listing","empty reply from server","http 502","http 503","http 504","closed the connection","nonnumeric port","getaddrinfo","name resolution","would block","incomplete read","temporarily unavailable")
AUTH_KEYS=("authentication failed","permission denied","invalid credentials","http 401","http 403","403 forbidden","support for password authentication","bad credentials","token required")
LARGE_KEYS=("large files detected","exceeds github's file size limit","exceeds the maximum","gh001","too large","object exceeds")
class Flags:
    """跨函数开关容器：http_debug 控制是否打印请求/响应头级别细节。"""
    http_debug=False
class Meter:
    """全局上传计量器：socket 每写出字节就汇入这里，兼做低速超时判定。"""
    sent=0;start=time.monotonic();last=time.monotonic();last_sent=0;label="pack";low_limit=0;low_time=0
    @classmethod
    def reset(cls,label="pack"):cls.sent=0;cls.start=cls.last=time.monotonic();cls.last_sent=0;cls.label=label
    @classmethod
    def add(cls,n):
        if n<=0:return
        cls.sent+=n;now=time.monotonic();elapsed=max(now-cls.start,1e-6)
        if now-cls.last>=.25:
            inst=(cls.sent-cls.last_sent)/max(now-cls.last,1e-6);cls.last=now;cls.last_sent=cls.sent
            LOG.info("[%s] 已发送 %s | 瞬时 %s | 平均 %s | 用时 %.2fs",cls.label,human(cls.sent),rate(inst),rate(cls.sent/elapsed),elapsed)
        if cls.low_limit and cls.low_time and elapsed>=cls.low_time and cls.sent/elapsed<cls.low_limit:raise TimeoutError(f"上传平均速度低于 {cls.low_limit}B/s 已持续 {elapsed:.0f}s，主动断开以重试")
    @classmethod
    def finish(cls):
        elapsed=max(time.monotonic()-cls.start,1e-6)
        if cls.sent:LOG.info("[%s] 传输结束 共 %s | 平均 %s | 用时 %.2fs",cls.label,human(cls.sent),rate(cls.sent/elapsed),elapsed)
def human(n):
    units=("B","KiB","MiB","GiB","TiB");v=float(max(n,0));i=0
    while v>=1024 and i<len(units)-1:v/=1024;i+=1
    return f"{v:.2f} {units[i]}"
def rate(v):return human(v)+"/s"
def stime():
    ft=time.time();return time.strftime('%Y-%m-%d__%H.%M.%S',time.localtime(ft))+'__.'+f"{ft:.3f}".split('.')[1]
def setup_logging(verbosity):
    # 与参考脚本同构：-v 0..3 决定级别；>=3 额外输出 HTTP 请求/响应头与 TLS 细节。
    lv={0:logging.ERROR,1:logging.WARNING,2:logging.INFO}.get(verbosity,logging.DEBUG if verbosity>=3 else logging.ERROR)
    h=logging.StreamHandler(sys.stdout);h.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-7s | %(message)s','%Y-%m-%d %H:%M:%S'));LOG.handlers[:]=[h];LOG.setLevel(lv);Flags.http_debug=verbosity>=3
def redact_url(value):
    # 日志只保留用户名与主机，token 永不打印、永不写盘。
    p=urlsplit(value or "")
    if p.scheme and p.netloc and "@" in p.netloc:
        user=p.netloc.rsplit("@",1)[0].split(":",1)[0];host=p.netloc.rsplit("@",1)[1]
        return urlunsplit((p.scheme,f"{user}:***@{host}",p.path,p.query,p.fragment))
    return value or ""
def safe_url(url):
    try:
        p=urlsplit(url);return urlunsplit((p.scheme,p.hostname or "",p.path or "/","",""))
    except Exception:return "<bad-url>"
def hide_header(k,v):
    return "***" if (k or "").lower() in {"authorization","proxy-authorization","cookie","set-cookie","www-authenticate","x-api-key"} else v
def split_remote(raw):
    # 关键修复：先摘掉 userinfo 再重建 URL，避免 urllib3 把 token 当端口（nonnumeric port）。
    p=urlsplit(raw or "")
    if p.scheme not in ("http","https") or not p.hostname:raise SystemExit("仅支持 http/https 远程地址；SSH 请直接用 git 本体")
    netloc=p.hostname+(f":{p.port}" if p.port else "")
    clean=urlunsplit((p.scheme,netloc,p.path or "/",p.query,p.fragment))
    return clean,(unquote(p.username) if p.username else None),(unquote(p.password) if p.password else None)
class CountingSocket:
    # 只代理 send/sendall 做写出计量，其他属性透传，保证 http.client/urllib3 行为完全不变。
    def __init__(self,sock):object.__setattr__(self,"_s",sock)
    def send(self,data,*a,**k):
        n=self._s.send(data,*a,**k);Meter.add(n if isinstance(n,int) and n>0 else len(data));return n
    def sendall(self,data,*a,**k):
        # dulwich 可能把整个 pack 一次性交出来：这里自己切 64KB 分块发送，才能给出真正的“实时”速度。
        if not isinstance(data,(bytes,bytearray,memoryview)):self._s.sendall(data,*a,**k);return
        buf=bytes(data) if not isinstance(data,bytes) else data;off=0;total=len(buf)
        while off<total:
            start=off;off=min(off+65536,total);self._s.sendall(buf[start:off]);Meter.add(off-start)
    def makefile(self,mode="r",*a,**k):return self._s.makefile(mode,*a,**k)
    def close(self):return self._s.close()
    def __getattr__(self,name):return getattr(object.__getattribute__(self,"_s"),name)
    def __setattr__(self,name,value):setattr(object.__getattribute__(self,"_s"),name,value)
def log_connection(conn,sock):
    # 连接建立即打印：对端地址、TLS 版本、加密套件、证书 CN、ALPN —— 相当于 curl -v 的开头。
    peer="-";cn="-";cipher="-";alpn="-";comp="-"
    try:peer=repr(sock.getpeername())
    except Exception:pass
    try:
        cert=sock.getpeercert() or {}
        for rdn in cert.get("subject",()) or ():
            for key,val in rdn:
                if key=="commonName":cn=val
    except Exception:pass
    try:
        if hasattr(sock,"cipher") and sock.cipher():cipher=sock.cipher()[0]
        if hasattr(sock,"selected_alpn_protocol"):alpn=str(sock.selected_alpn_protocol())
        if hasattr(sock,"compression"):comp=str(sock.compression() or "-")
    except Exception:pass
    LOG.debug("[CONN] %s:%s -> %s | TLS=%s | 套件=%s | 证书CN=%s | ALPN=%s | 压缩=%s",getattr(conn,"host","-"),getattr(conn,"port","-"),peer,getattr(sock,"version",lambda:"-")(),cipher,cn,alpn,comp)
def make_pool(timeout,insecure=False,cafile=None):
    # 自建 urllib3 连接池：把 Connection 类换成会计量的版本；git 协议仍完全交给 dulwich。
    from urllib3.connection import HTTPConnection,HTTPSConnection
    from urllib3.connectionpool import HTTPConnectionPool,HTTPSConnectionPool
    class MeteredHTTP(HTTPConnection):
        def connect(self):super().connect();log_connection(self,self.sock);self.sock=CountingSocket(self.sock)
    class MeteredHTTPS(HTTPSConnection):
        def connect(self):super().connect();log_connection(self,self.sock);self.sock=CountingSocket(self.sock)
    class PHTTP(HTTPConnectionPool):ConnectionCls=MeteredHTTP
    class PHTTPS(HTTPSConnectionPool):ConnectionCls=MeteredHTTPS
    class Pool(urllib3.PoolManager):
        def __init__(self,*a,**k):super().__init__(*a,**k);self.pool_classes_by_scheme={"http":PHTTP,"https":PHTTPS}
        def request(self,method,url,fields=None,headers=None,**kw):
            body=kw.get("body")
            if str(method).upper()=="POST" and body is not None:
                Meter.reset("pack");LOG.debug("[HTTP] -> POST %s | body=%s",safe_url(url),"stream" if not isinstance(body,(bytes,str)) else f"{len(body)}B")
            else:LOG.debug("[HTTP] -> %s %s",method,safe_url(url))
            for k,v in (headers or {}).items():LOG.debug("[HTTP] > Send header: %s: %s",k,hide_header(k,v))
            t=time.monotonic()
            try:resp=super().request(method,url,fields,headers,**kw)
            except Exception as exc:LOG.debug("[HTTP] !! %s %s -> %r",method,safe_url(url),exc);raise
            LOG.debug("[HTTP] <= Recv header: HTTP/1.1 %s %s (首包 %.2fs)",getattr(resp,"status",""),getattr(resp,"reason",""),time.monotonic()-t)
            for k,v in (getattr(resp,"headers",None) or {}).items():LOG.debug("[HTTP] <= Recv header: %s: %s",k,hide_header(k,v))
            return resp
    kw=dict(num_pools=8,timeout=urllib3.Timeout(connect=timeout,read=max(timeout,120)),retries=False,headers={"User-Agent":UA,"Accept-Encoding":"identity"})
    if insecure:
        import warnings;warnings.filterwarnings("ignore",message=".*Unverified HTTPS request.*")
        kw.update(cert_reqs="CERT_NONE",assert_hostname=False,assert_fingerprint=None)
    if cafile:kw["ca_certs"]=cafile
    return Pool(**kw)
class ProgressWriter:
    # receive-pack 的 side-band 进度用 \r 刷新，这里切行并去重，观感接近 git --progress。
    def __init__(self):self.buf="";self.last=""
    def write(self,data):
        text=data.decode("utf-8","replace") if isinstance(data,(bytes,bytearray)) else str(data)
        parts=(self.buf+text).replace("\r","\n").split("\n");self.buf=parts.pop()
        for p in parts:
            line=p.strip()
            if line and line!=self.last:self.last=line;LOG.info("remote: %s",line)
    def flush(self):
        line=self.buf.strip();self.buf=""
        if line and line!=self.last:LOG.info("remote: %s",line)
def discover_repo(path):
    # 允许在仓库任意子目录执行：优先 dulwich 的 discover，退化为向上找 .git。
    start=Path(path or ".").resolve()
    try:
        found=Repo.discover(str(start))
        if found:return Path(found).resolve()
    except Exception:pass
    for cand in (start,)+tuple(start.parents):
        if (cand/".git").exists() or (cand/"HEAD").is_file():return cand
    raise SystemExit(f"未找到 Git 仓库: {start}")
def head_branch_bytes(repo):
    # 解析 HEAD 文本，兼容 unborn 仓库（刚 git init、还没有任何 commit）。
    try:
        chain,_=repo.refs.follow(b"HEAD")
        for ref in reversed(list(chain)):
            if ref.startswith(b"refs/heads/"):return ref[len(b"refs/heads/"):]
    except Exception:pass
    try:
        txt=(Path(repo.controldir())/"HEAD").read_bytes().decode("utf-8","surrogateescape").strip()
        if txt.startswith("ref: refs/heads/"):return txt[len("ref: refs/heads/"):].encode("utf-8","surrogateescape")
    except Exception:pass
    return b"master"
def cfg_get(repo,section,key):
    for c in (repo.get_config(),repo.get_config_stack()):
        try:
            v=c.get((section.encode(),),key.encode())
            if v:return v.decode("utf-8","replace") if isinstance(v,bytes) else str(v)
        except Exception:continue
    return ""
def cfg_set(repo,section,key,value):
    try:c=repo.get_config();c.set((section.encode(),),key.encode(),value.encode("utf-8"));c.write_to_path()
    except Exception as exc:LOG.debug("写配置 %s.%s 失败: %r",section,key,exc)
def set_remote(repo,url):
    if cfg_get(repo,'remote "origin"',"url")==url:return
    cfg_set(repo,'remote "origin"',"url",url);LOG.info("已绑定远程 origin（去凭证）: %s",safe_url(url))
def apply_git_user_config(repo,user,force):
    # 对应参考脚本 -u：URL 带账号就强制覆盖 user.name/user.email，并用 GitHub noreply 邮箱。
    name,email=cfg_get(repo,"user","name"),cfg_get(repo,"user","email")
    if user:
        name,email=user,f"{user}@users.noreply.github.com"
        cfg_set(repo,"user","name",name);cfg_set(repo,"user","email",email)
        LOG.info("强制应用用户配置 (-u): user.name=[%s], user.email=[%s]",name,email);return name,email
    if not name or not email:
        name=name or os.environ.get("GIT_AUTHOR_NAME") or "dulwich";email=email or os.environ.get("GIT_AUTHOR_EMAIL") or "dulwich@localhost"
        cfg_set(repo,"user","name",name);cfg_set(repo,"user","email",email)
    LOG.info("提交身份: user.name=[%s], user.email=[%s]",name,email);return name,email
def load_lfs_rules(root):
    # 复用 dulwich 的 gitignore 通配引擎解析 .gitattributes 中所有 filter=lfs 的路径模式。
    f=root/".gitattributes";rules=[]
    if f.exists():
        for line in f.read_text("utf-8",errors="replace").splitlines():
            s=line.strip()
            if not s or s.startswith("#") or "filter=lfs" not in s:continue
            pat=s.split(None,1)[0].strip('"')
            try:rules.append(Pattern(pat.encode("utf-8","surrogateescape")))
            except Exception as exc:LOG.warning("忽略无法解析的 .gitattributes 规则 %r: %s",line,exc)
    return rules
def match_rules(rules,rel):
    b=rel.encode("utf-8","surrogateescape")
    return any(p.match(b) for p in rules)
def nested_repo_prefixes(root):
    # 嵌套仓库是独立 worktree，其文件不能进外层仓库（与参考脚本一致）。
    out=set()
    for base,dirnames,_ in os.walk(root,topdown=True,followlinks=False):
        bp=Path(base);keep=[]
        for d in dirnames:
            p=bp/d
            if d==".git":continue
            if (p/".git").exists():out.add(p.relative_to(root).as_posix()+"/")
            else:keep.append(d)
        dirnames[:]=keep
    return out
def update_gitattributes(root,paths):
    # 逐文件写精确规则而不是 *.ext，避免误伤；保留非 LFS 行，去重已有 LFS 行。
    if not paths:return False
    f=root/".gitattributes";other=[];lfs=set()
    if f.exists():
        for raw in f.read_text("utf-8",errors="replace").splitlines():
            s=raw.strip()
            if not s:continue
            lfs.add(s) if "filter=lfs" in s else other.append(s)
    nested=nested_repo_prefixes(root);changed=False
    for rel in sorted(paths):
        if rel in nested or any(rel.startswith(p) for p in nested):continue
        if (root/rel).is_symlink():continue
        rule=(f'"{rel}"' if (" " in rel or "\\" in rel) else rel)+" filter=lfs diff=lfs merge=lfs -text"
        if rule in lfs:continue
        lfs.add(rule);changed=True
    if changed:
        f.write_text("\n".join(other+sorted(lfs))+"\n","utf-8");LOG.info(".gitattributes 更新完成，LFS 追踪总数: %d",len(lfs))
    else:LOG.info(".gitattributes 无需变更，LFS 追踪总数: %d",len(lfs))
    return changed
def head_paths(repo):
    # HEAD 里已跟踪的路径集合：随后被 .gitignore 命中的也要保留，行为等同 git add -A。
    out=set()
    try:
        for e in repo.object_store.iter_tree_contents(repo[repo[b"HEAD"]].tree):out.add(e.path.decode("utf-8","surrogateescape"))
    except Exception:pass
    return out
def blob_sha1(data):
    return hashlib.sha1(b"blob %d\0"%len(data)+data).hexdigest().encode("ascii")
def pointer_blob(oid,size):
    return (POINTER_HEAD.decode()+f"\noid sha256:{oid}\nsize {size}\n").encode()
def cache_file(root):return root/".git"/"dulwich-push-cache"
def load_cache(root):
    try:
        p=cache_file(root);return json.loads(p.read_text("utf-8")) if p.exists() else {}
    except Exception:return {}
def save_cache(root,data):
    try:cache_file(root).write_text(json.dumps(data),"utf-8")
    except Exception as exc:LOG.debug("写 stat 缓存失败: %r",exc)
def scan_worktree(repo,threshold,quiet_progress=False):
    """一次遍历完成 gitignore 过滤、LFS 判定与 blob 计算；记录为 rel→(mode,sha,data,st,is_lfs,oid,size)。"""
    root=Path(repo.path);ignore=IgnoreFilterManager.from_repo(repo);rules=load_lfs_rules(root);tracked=head_paths(repo)
    cache=load_cache(root);new_cache={};records={};nf=nd=lfs_n=0;last=time.monotonic()
    for base,dirnames,filenames in os.walk(root,topdown=True,followlinks=False):
        bp=Path(base);keep=[];nd+=1
        for d in sorted(dirnames):
            p=bp/d
            if d==".git" or p.is_symlink() or (p/".git").exists():continue
            rel=p.relative_to(root).as_posix()
            if ignore.is_ignored(rel+"/") is True:continue
            keep.append(d)
        dirnames[:]=keep
        for name in sorted(filenames):
            p=bp/name;rel=p.relative_to(root).as_posix();nf+=1
            try:st=p.lstat()
            except OSError:continue
            if p.is_symlink():
                try:target=os.readlink(p).encode("utf-8","surrogateescape")
                except OSError:continue
                sha=blob_sha1(target);new_cache[rel]=[0,0,"",sha.decode()]
                records[rel]=(0o120000,sha,target,st,False,None,len(target));continue
            if not p.is_file():continue
            if ignore.is_ignored(rel) is True and rel not in tracked:continue
            is_lfs=bool(rules) and match_rules(rules,rel)
            if not is_lfs and st.st_size>=threshold:is_lfs=True
            if not is_lfs and st.st_size>INLINE_MAX:LOG.warning("文件 %s 达 %s 且未纳入 LFS，跳过以免占满内存",rel,human(st.st_size));continue
            hit=cache.get(rel);hit=hit if isinstance(hit,list) and len(hit)==4 else None
            fast=bool(hit and hit[0]==st.st_size and hit[1]==st.st_mtime_ns)
            sha=hit[3].encode() if (fast and hit[3]) else None;oid=hit[2] if (fast and is_lfs and hit[2]) else None
            data=None
            if is_lfs:
                if st.st_size<4096:
                    with p.open("rb") as fh:peek=fh.read(4096)
                    if peek.startswith(POINTER_HEAD):
                        # 工作区里已经是指针（例如未 smudge 的检出）：原样保留且不再上传，避免指针套指针。
                        sha=blob_sha1(peek);records[rel]=(0o100644,sha,peek,st,True,None,len(peek))
                        new_cache[rel]=[st.st_size,st.st_mtime_ns,"",sha.decode()];LOG.debug("%s 已是指针，保持原样",rel);continue
                if oid is None:
                    h=hashlib.sha256()
                    with p.open("rb") as fh:
                        while True:
                            blk=fh.read(1<<20)
                            if not blk:break
                            h.update(blk)
                    oid=h.hexdigest()
                data=pointer_blob(oid,st.st_size);sha=blob_sha1(data);new_cache[rel]=[st.st_size,st.st_mtime_ns,oid,sha.decode()]
            else:
                if sha is None:
                    with p.open("rb") as fh:data=fh.read()
                    sha=blob_sha1(data);new_cache[rel]=[st.st_size,st.st_mtime_ns,"",sha.decode()]
            mode=0o100644 if os.name=="nt" else (0o100755 if st.st_mode & 0o111 else 0o100644)
            records[rel]=(mode,sha,data,st,is_lfs,oid,st.st_size)
            if is_lfs and oid:lfs_n+=1
            now=time.monotonic()
            if now-last>=1:
                if quiet_progress or Flags.http_debug:LOG.debug("扫描文件: %s | 目录: %s | LFS: %d | 当前: %s",f"{nf:,}",f"{nd:,}",lfs_n,rel)
                else:
                    width=os.get_terminal_size((120,24)).columns;txt=f"扫描文件: {nf:,} | 目录: {nd:,} | 当前: {rel}"
                    sys.stdout.write("\r\033[2K"+txt[-(width-1):] if len(txt)>width else "\r\033[2K"+txt);sys.stdout.flush()
                last=now
    if not quiet_progress and not Flags.http_debug:sys.stdout.write("\r\033[2K");sys.stdout.flush()
    merged={k:v for k,v in cache.items() if k in records};merged.update(new_cache);save_cache(root,merged)
    big=sum(1 for v in records.values() if v[4] and v[5])
    LOG.info("扫描到 %d 个本地大文件（工作区文件 %s 个，已跟踪校验 %d 个）",big,f"{nf:,}",len(records))
    return records
def ensure_object(repo,sha,path,data):
    # 已存在（含 pack 内）就跳过，缺对象才写松散对象；缓存命中时连文件都不读。
    try:
        if sha in repo.object_store:return
    except Exception:pass
    if data is None:
        if not path:raise RuntimeError(f"缺少对象 {sha.decode()} 且无源文件可重建")
        with open(path,"rb") as fh:data=fh.read()
    repo.object_store.add_object(Blob.from_string(data))
def build_tree(repo,paths,depth=0):
    # 由扁平路径列表自底向上构造 tree 对象；同内容目录 sha 自然相同，重复对象被 store 去重。
    t=Tree();dirs={}
    for rel,mode,sha in paths:
        parts=rel.split(b"/")
        if len(parts)==1:t.add(parts[0],mode,sha);continue
        dirs.setdefault(parts[0],[]).append((b"/".join(parts[1:]),mode,sha))
    for name,sub in dirs.items():
        try:t.add(name,0o040000,build_tree(repo,sub,depth+1))
        except Exception as exc:LOG.warning("目录 %s 构建失败，跳过: %s",name,exc)
    repo.object_store.add_object(t);return t.id
def write_tree(repo,records):
    # 先把 blob 落盘再拼 tree；这一步完全绕开 dulwich 的 gitattributes 过滤器机制。
    paths=[]
    for rel,(mode,sha,data,st,is_lfs,oid,size) in records.items():
        rb=rel.encode("utf-8","surrogateescape")
        ensure_object(repo,sha,os.path.join(repo.path,rel.replace("/",os.sep)) if data is None else None,data)
        paths.append((rb,mode,sha))
    return build_tree(repo,sorted(paths)),paths
def commit_tree(repo,tree_id,name,email,message,branch):
    ref=b"refs/heads/"+branch.encode("utf-8","surrogateescape")
    c=Commit();c.tree=tree_id
    old=repo.refs.as_dict().get(ref)
    if old and old!=ZERO_SHA:c.parents=[old]
    ident=f"{name} <{email}>".encode("utf-8","surrogateescape")
    now=int(time.time());c.author=c.committer=ident;c.author_time=c.commit_time=now
    c.author_timezone=c.commit_timezone=-(time.altime if time.daylight else time.timezone)
    c.encoding=b"UTF-8";c.message=message.encode("utf-8","surrogateescape")
    repo.object_store.add_object(c);repo.refs[ref]=c.id
    try:repo.refs.set_symbolic_ref(b"HEAD",ref)
    except Exception:pass
    return c.id
def rebuild_index(repo,records):
    # 回写 .git/index，让外部 git status 与本提交一致；失败仅告警，不影响推送内容。
    try:
        idx=repo.open_index()
        for key in list(idx):
            try:del idx[key]
            except Exception:pass
        for rel,(mode,sha,data,st,is_lfs,oid,size) in records.items():
            try:
                p=Path(repo.path)/rel;stat=p.stat()
                idx[rel.encode("utf-8","surrogateescape")]=index_entry_from_stat(stat,sha.decode(),0,mode=mode)
            except Exception as exc:LOG.debug("index 条目跳过 %s: %r",rel,exc)
        idx.write()
    except Exception as exc:LOG.warning("写入 .git/index 失败（不影响推送）: %r",exc)
def diff_against_head(repo,tree_id):
    # 与 HEAD tree 比较得到 新增/修改/删除 清单，用于日志与“无变更则跳过提交”。
    try:head=repo[repo[b"HEAD"]].tree
    except Exception:return ["<initial-commit>"],1
    old={e.path:e.sha for e in repo.object_store.iter_tree_contents(head)}
    new={e.path:e.sha for e in repo.object_store.iter_tree_contents(tree_id)}
    added=[p for p in new if p not in old];mod=[p for p in new if p in old and new[p]!=old[p]];dele=[p for p in old if p not in new]
    out=[os.fsdecode(p) for p in sorted(added)+sorted(mod)+sorted(dele)]
    return out,len(out)
def lfs_endpoint(remote):
    p=urlsplit(remote);path=p.path or "/"
    if not path.endswith(".git"):path=path.rstrip("/")+".git"
    return urlunsplit((p.scheme,p.netloc,path+"/info/lfs/objects/batch","",""))
def lfs_basic(user,token):
    return "Basic "+base64.b64encode(f"{user or ''}:{token or ''}".encode()).decode("ascii")
def lfs_batch(remote,user,token,objects,pool):
    # batch 只是小 JSON；GitHub 对已存在对象不返回 actions，因此天然是幂等的“补齐上传”。
    if not objects:return {}
    payload={"operation":"upload","transfers":["basic"],"objects":[{"oid":o["oid"],"size":o["size"]} for o in objects]}
    body=json.dumps(payload).encode();url=lfs_endpoint(remote)
    LOG.info("LFS batch 上传 %d 个对象 -> %s",len(objects),url)
    base={"Accept":"application/vnd.git-lfs+json","Content-Type":"application/vnd.git-lfs+json","User-Agent":UA,"Content-Length":str(len(body))}
    for scheme in ("Basic","RemoteAuth"):
        headers=dict(base);headers["Authorization"]=lfs_basic(user,token) if scheme=="Basic" else "RemoteAuth "+base64.b64encode((token or "").encode()).decode("ascii")
        try:
            resp=pool.request("POST",url,headers=headers,body=body,preload_content=False)
            raw=resp.read();resp.close();status=getattr(resp,"status",0)
        except Exception as exc:
            LOG.warning("LFS batch 请求失败（LFS 指针仍会提交）: %s",exc);return {}
        if status in (401,403):
            LOG.info("%s 认证失败，尝试 GitHub %s 方式...",scheme,"RemoteAuth" if scheme=="Basic" else "Basic");continue
        if status>=400:LOG.warning("LFS batch HTTP %s（LFS 指针仍会提交）: %s",status,raw[:180].decode("utf-8","replace"));return {}
        try:answer=json.loads(raw.decode("utf-8"))
        except Exception as exc:LOG.warning("LFS batch 响应解析失败: %r",exc);return {}
        LOG.debug("[LFS] batch 200 | objects=%d | transfer=%s",len(answer.get("objects",[])),answer.get("transfer","basic"))
        plan={}
        for item in answer.get("objects",[]):
            oid=item.get("oid","")
            if item.get("error"):LOG.warning("LFS 对象 %s 被拒绝: %s",oid,item["error"]);continue
            actions=item.get("actions") or {}
            if actions.get("upload"):plan[oid]={"upload":actions["upload"],"verify":actions.get("verify")}
        return plan
    LOG.warning("LFS 认证连续失败，跳过对象上传（LFS 指针仍会提交）");return {}
def lfs_local_path(root,oid):return Path(root)/".git"/"lfs"/"objects"/oid[:2]/oid[2:4]/oid
def lfs_local_store(root,src,oid,size):
    # 上传成功后写入标准 LFS 缓存目录，之后 git-lfs 可直接复用，也避免重复推送。
    dst=lfs_local_path(root,oid)
    if dst.is_file():return
    try:
        dst.parent.mkdir(parents=True,exist_ok=True);tmp=dst.with_name(dst.name+".incomplete")
        with src.open("rb") as fi,tmp.open("wb") as fo:
            while True:
                blk=fi.read(1<<20)
                if not blk:break
                fo.write(blk)
        if tmp.stat().st_size==size:os.replace(tmp,dst)
        else:tmp.unlink(missing_ok=True)
    except Exception as exc:LOG.debug("写 LFS 缓存失败: %r",exc)
def lfs_put(root,rel,oid,size,action,timeout,verify,insecure):
    # 用 http.client 流式 PUT：自己分块发送以精确计量速度，并打印连接与响应头细节。
    p=urlsplit(action["href"]);port=p.port or (443 if p.scheme=="https" else 80)
    target=(p.path or "/")+(f"?{p.query}" if p.query else "")
    ctx=ssl.create_default_context()
    if insecure:ctx.check_hostname=False;ctx.verify_mode=ssl.CERT_NONE
    conn=http.client.HTTPSConnection(p.hostname,port,timeout=timeout,context=ctx) if p.scheme=="https" else http.client.HTTPConnection(p.hostname,port,timeout=timeout)
    LOG.debug("[LFS HTTP] -> PUT %s://%s:%s%s",p.scheme,p.hostname,port,target)
    try:
        conn.connect();log_connection(conn,conn.sock)
        extra={k:v for k,v in (action.get("header") or {}).items() if k.lower() not in ("content-length","host","content-type","accept-encoding")}
        conn.putrequest("PUT",target,skip_accept_encoding=True)
        conn.putheader("Content-Length",str(size));conn.putheader("Content-Type","application/octet-stream");conn.putheader("Accept","*/*");conn.putheader("User-Agent",UA)
        for k,v in extra.items():conn.putheader(k,v);LOG.debug("[LFS HTTP] > Send header: %s: %s",k,hide_header(k,v))
        conn.endheaders();Meter.reset("LFS");fp=Path(root)/rel;sent=0
        with fp.open("rb") as fh:
            while True:
                blk=fh.read(1<<20)
                if not blk:break
                conn.send(blk);sent+=len(blk)
        Meter.finish()
        resp=conn.getresponse();resp.read();LOG.debug("[LFS HTTP] <= %s %s",resp.status,resp.reason)
        for k,v in resp.getheaders():LOG.debug("[LFS HTTP] <= Recv header: %s: %s",k,hide_header(k,v))
        if not 200<=resp.status<300:raise RuntimeError(f"LFS PUT HTTP {resp.status}")
        lfs_local_store(root,fp,oid,size)
        if verify:
            vbody=json.dumps({"oid":oid,"size":size}).encode();vp=urlsplit(verify["href"]);vport=vp.port or (443 if vp.scheme=="https" else 80)
            vc=http.client.HTTPSConnection(vp.hostname,vport,timeout=timeout,context=ctx) if vp.scheme=="https" else http.client.HTTPConnection(vp.hostname,vport,timeout=timeout)
            vc.putrequest("POST",vp.path or "/",skip_host=True,skip_accept_encoding=True)
            vc.putheader("Host",vp.hostname);vc.putheader("Content-Length",str(len(vbody)));vc.putheader("Content-Type","application/vnd.git-lfs+json")
            for k,v in (verify.get("header") or {}).items():
                if k.lower() not in ("content-length","host","content-type"):vc.putheader(k,v)
            vc.endheaders();vc.send(vbody);vr=vc.getresponse();vr.read();LOG.debug("[LFS] verify %s -> %s",oid[:12],vr.status);vc.close()
    finally:
        try:conn.close()
        except Exception:pass
def upload_lfs(root,remote,user,token,items,pool,args):
    # 本地已有对象直接跳过；单个对象失败按 --retry 重试；整体失败只告警（与参考脚本一致的容错）。
    todo=[i for i in items if not lfs_local_path(root,i["oid"]).is_file()]
    if not todo:LOG.info("LFS 对象全部命中本地缓存，跳过上传");return
    plan=lfs_batch(remote,user,token,todo,pool)
    by_oid={i["oid"]:i for i in todo}
    for oid,act in plan.items():
        item=by_oid.get(oid)
        if not item:continue
        for attempt in range(1,args.retry+1):
            try:
                lfs_put(root,item["rel"],oid,item["size"],act["upload"],args.connect_timeout,act.get("verify"),args.insecure);break
            except Exception as exc:
                if attempt>=args.retry:LOG.warning("LFS 对象上传失败（LFS 指针仍会提交）: %s | %s",item["rel"],exc);break
                LOG.warning("⚠️ LFS %s 第 %d 次失败: %s，%ds 后重试",item["rel"],attempt,exc,args.retry_wait);time.sleep(args.retry_wait)
def is_fast_forward(repo,old,new):
    # 本地先判快进，避免白生成大 pack 再被服务端拒绝；无法判定时返回 None 交给服务端。
    if not old or old in (ZERO_SHA,b"0"*40):return True
    if old==new:return True
    seen=set();todo=[new];steps=0
    try:
        while todo and steps<50000:
            oid=todo.pop();steps+=1
            if oid==old:return True
            if oid in seen or not oid:continue
            seen.add(oid)
            try:todo.extend(repo[oid].parents)
            except Exception:continue
    except Exception:return None
    return False
def push_once(repo,remote,branch,user,token,pool,args):
    client,path=get_transport_and_path_from_url(remote,operation="push",username=user,password=token,pool_manager=pool)
    pw=ProgressWriter()
    try:
        result=client.get_refs(path)
        remote_refs=dict(getattr(result,"refs",result) or {})
    except Exception as exc:
        if classify(str(exc))=="net":raise
        LOG.debug("读取远端 refs 失败，按空仓库处理: %r",exc);remote_refs={}
    ref=b"refs/heads/"+branch.encode("utf-8","surrogateescape")
    local=repo.refs.as_dict().get(ref)
    if not local:raise SystemExit(f"本地分支 {branch} 没有提交，无法推送")
    old=remote_refs.get(ref) or ZERO_SHA
    if old==local:LOG.info("远端 %s 已一致，无需推送",branch);return "up-to-date"
    if not args.force and is_fast_forward(repo,old,local) is False:
        raise SystemExit(f"非快进推送已被本地拦截（{old[:7].decode()} -> {local[:7].decode()}）；确认覆盖请加 --force")
    LOG.info("打包并上传 %s: %s -> %s",branch,old[:7].decode() or "-",local[:7].decode())
    try:
        gpd=getattr(repo,"generate_pack_data",None) or getattr(repo.object_store,"generate_pack_data",None)
        res=client.send_pack(path,lambda refs:{ref:local},gpd,progress=pw.write)
    except SendPackError as exc:raise RuntimeError(f"服务端拒绝 pack: {exc}") from exc
    finally:pw.flush();Meter.finish()
    bad={k.decode("utf-8","replace"):v for k,v in (dict(getattr(res,"ref_status",None) or {})).items() if v}
    if bad:raise RuntimeError("远端 ref 更新失败: "+json.dumps(bad,ensure_ascii=False))
    LOG.info("✅ 推送成功 %s",stime());return "pushed"
def classify(text):
    t=(text or "").lower()
    if any(k in t for k in LARGE_KEYS):return "large"
    if any(k in t for k in AUTH_KEYS):return "auth"
    if any(k in t for k in NET_KEYS):return "net"
    return "unknown"
def push_with_retry(repo,remote,branch,user,token,pool,args):
    # 网络类错误重试；认证/历史大文件立即退出；重试时自动升级日志详细度（对应 GIT_CURL_VERBOSE）。
    for attempt in range(1,args.retry+1):
        LOG.info("===== 推送 %s %s (尝试 %d/%d) 间隔 %ds =====",redact_url(remote),branch,attempt,args.retry,args.retry_wait)
        if attempt>1 and not Flags.http_debug:Flags.http_debug=True;LOG.setLevel(logging.DEBUG);LOG.info("🔍 启用详细连接日志")
        try:return push_once(repo,remote,branch,user,token,pool,args)
        except SystemExit:raise
        except HTTPUnauthorized:LOG.critical("❌ 认证失败(401)：fine-grained token 需要 Contents: write");sys.exit(1)
        except KeyboardInterrupt:raise
        except Exception as exc:
            kind=classify(str(exc))
            if kind=="large":LOG.error("❌ 服务端因历史大文件拒绝：仅新增 .gitattributes 不会清除旧 blob，需改写历史后 --force 推送。");sys.exit(1)
            if kind=="auth":LOG.critical("❌ 认证/权限错误，不重试: %s",exc);sys.exit(1)
            if attempt>=args.retry:LOG.critical("❌ 推送失败（%d 次重试后放弃）: %s",args.retry,exc);sys.exit(1)
            LOG.warning("⚠️ 网络错误，稍后重试 (%s)",exc);time.sleep(args.retry_wait)
def parse_size(val):
    s=str(val or "100MB").strip().lower();mul=1
    for suf,m in (("gb",1024**3),("g",1024**3),("mb",1024**2),("m",1024**2),("kb",1024),("k",1024),("b",1)):
        if s.endswith(suf):s=s[: -len(suf)].strip();mul=m;break
    try:return max(int(float(s)*mul),1)
    except Exception:raise SystemExit(f"无法解析大小: {val}")
def build_parser():
    p=argparse.ArgumentParser(description="dulwich 纯 Python push（细节对齐 git_logic.py，不依赖 git/git-lfs）")
    p.add_argument("-v","--verbose",type=int,default=2,help="0 静默 1 警告 2 信息 3 连接细节+实时速度")
    p.add_argument("-u","--update-user",action="store_true",help="用 URL 中的账号强制写入 user.name/user.email")
    p.add_argument("-m","--message",default=None,help="提交说明，缺省用 [最大文件 字节] 时间戳 自动生成")
    p.add_argument("--no-ask","-y",dest="no_ask",action="store_true",help="无交互模式（本脚本默认即无交互）")
    p.add_argument("mode",nargs="?",default="push",choices=("push",))
    p.add_argument("url",nargs="?",default=None,help="远程地址，可含 user:token@")
    p.add_argument("--repo",default=".",help="仓库目录（默认自动向上发现）")
    p.add_argument("--branch",default=None,help="目标分支，默认当前分支")
    p.add_argument("--token",default=None,help="不用 URL 内嵌 token 时用此参数或 GITHUB_TOKEN/GH_TOKEN")
    p.add_argument("--size",default="100MB",help="大文件阈值，超过则转 LFS 指针")
    p.add_argument("--retry",type=int,default=10,help="网络错误重试次数")
    p.add_argument("--retry-wait",type=int,default=5,help="重试间隔秒")
    p.add_argument("--connect-timeout",type=float,default=45.0,help="连接/读取超时秒")
    p.add_argument("--low-speed-limit",type=int,default=10,help="平均速度低于此值触发低速中断")
    p.add_argument("--low-speed-time",type=int,default=60,help="低速持续多少秒后中断重试")
    p.add_argument("--force",action="store_true",help="允许非快进推送")
    p.add_argument("--no-lfs",action="store_true",help="关闭 LFS 处理（超阈值大文件将被跳过而非入仓）")
    p.add_argument("--insecure",action="store_true",help="跳过 TLS 校验，等价 GIT_SSL_NO_VERIFY")
    p.add_argument("--ca",default=None,help="自定义 CA bundle")
    p.add_argument("--version",action="version",version=f"dulwich_push.py (dulwich {DULWICH_VERSION})")
    return p
def main():
    args=build_parser().parse_args();setup_logging(args.verbose)
    Meter.low_limit=args.low_speed_limit;Meter.low_time=args.low_speed_time
    root=discover_repo(args.repo);repo=Repo(str(root))
    LOG.info("仓库路径: %s",root)
    LOG.info("Git引擎: dulwich %s 纯 Python 实现（无需外部 git，不启动 git-lfs 过滤器进程）",DULWICH_VERSION)
    threshold=1<<62 if args.no_lfs else parse_size(args.size)
    LOG.info("文件限制: %.2f MB (%d 字节)",threshold/1024/1024,threshold)
    remote_raw=args.url or cfg_get(repo,'remote "origin"',"url")
    if not remote_raw:raise SystemExit("缺少远程地址：把 URL 作为参数传入，或先配置 remote.origin.url")
    remote,user,token=split_remote(remote_raw)
    token=token or args.token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not user:
        seg=[s for s in (urlsplit(remote).path or "").strip("/").split("/") if s];user=seg[0] if seg else "git"
    LOG.info("远程地址: %s",redact_url(remote_raw))
    branch=args.branch or head_branch_bytes(repo).decode("utf-8","surrogateescape")
    LOG.info("分支: %s",branch)
    LOG.info("连接超时: %ss | 低速阈值: %dB/s | 低速超时: %ss",args.connect_timeout,args.low_speed_limit,args.low_speed_time)
    if args.url:set_remote(repo,remote)
    name,email=apply_git_user_config(repo,user if args.update_user else None,args.update_user)
    LOG.info("当前工作目录: %s",Path.cwd())
    records=scan_worktree(repo,threshold)
    large={r for r,v in records.items() if v[4] and v[5]}
    if large:
        LOG.info("LFS 追踪规则: 纯 Python 生成指针（等价 git lfs install + renormalize）...")
        if update_gitattributes(root,large):records=scan_worktree(repo,threshold,True)
    tree_id,_=write_tree(repo,records)
    changed,count=diff_against_head(repo,tree_id)
    if count:
        LOG.info("变更文件: %d 个 (显示前10: %s)",count,changed[:10])
        sized=sorted(((v[6],r) for r,v in records.items() if v[4] and v[5]),reverse=True)
        top=f"[{sized[0][1]} {sized[0][0]}B] " if sized else ""
        msg=args.message or f"{top}{stime()} {Path(__file__).name[-20:]} auto"
        sha=commit_tree(repo,tree_id,name,email,msg,branch);rebuild_index(repo,records)
        LOG.info("提交完成: %s (%s)",sha.decode()[:9],branch)
    else:LOG.info("无变更，跳过提交（仍将校验远端 ref）")
    items=[{"rel":r,"oid":v[5],"size":v[6]} for r,v in records.items() if v[4] and v[5]]
    pool=make_pool(args.connect_timeout,args.insecure,args.ca)
    if items:upload_lfs(root,remote,user,token,items,pool,args)
    push_with_retry(repo,remote,branch,user,token,pool,args)
    readme=root/"ReadMe.md"
    if readme.is_file() and b"#EmptyAfterPush" in readme.read_bytes():
        readme.write_bytes(b"");LOG.info("EmptyAfterPush 成功 %s",stime())
    LOG.info("✅ 操作结束！%s",stime())
if __name__=="__main__":
    try:main()
    except KeyboardInterrupt:LOG.warning("\n[CANCEL] 收到中断信号，已终止（工作区与仓库保持一致）。");sys.exit(130)
    except BrokenPipeError:sys.exit(1)
    except Exception as exc:
        kind=classify(str(exc))
        LOG.error("⚠️ 网络类错误（已用尽重试）: %s",exc) if kind=="net" else (LOG.error("❌ 认证错误: %s",exc) if kind=="auth" else LOG.error("❌ 失败: %r",exc))
        sys.exit(1)