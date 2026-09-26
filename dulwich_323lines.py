#!/usr/bin/env python3
from __future__ import annotations
import argparse,base64,hashlib,http.client,json,logging,os,ssl,sys,time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote,urlsplit,urlunsplit
from urllib.request import Request,urlopen
from dulwich import porcelain
from dulwich.client import HTTPProxyUnauthorized,HTTPUnauthorized,default_urllib3_manager,get_transport_and_path_from_url
from dulwich.objects import Blob
from dulwich.protocol import ZERO_SHA
from dulwich.repo import Repo

LOG=logging.getLogger("DulwichPush")
def setup_log(v):
    # v=3 时打开连接和响应头细节，默认仍保留可读的 INFO 日志。
    level={0:logging.ERROR,1:logging.WARNING,2:logging.INFO}.get(v,logging.DEBUG)
    h=logging.StreamHandler(sys.stdout);h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S"))
    LOG.handlers[:]=[h];LOG.setLevel(level)
def size_bytes(value):
    # 兼容 100MB、100M、1GB、1024B 等写法，默认使用二进制单位。
    s=str(value or "100MB").strip().lower();m=1
    for suffix,mul in (("gb",1024**3),("g",1024**3),("mb",1024**2),("m",1024**2),("kb",1024),("k",1024),("b",1)):
        if s.endswith(suffix):s=s[:-len(suffix)];m=mul;break
    try:return int(float(s)*m)
    except ValueError:raise argparse.ArgumentTypeError("无效大小: "+value)
def split_remote(raw):
    # 先拆出认证，再重建无 userinfo 的 URL；这样 token 不会被错误当作 host/port。
    p=urlsplit(raw)
    if p.scheme not in ("http","https"):return raw,None,None
    if not p.hostname:raise ValueError("远程 URL 缺少主机名")
    user=unquote(p.username or "");password=unquote(p.password or "")
    port=p.port
    host=p.hostname
    netloc=host+(":"+str(port) if port else "")
    clean=urlunsplit((p.scheme,netloc,p.path or "",p.query,p.fragment))
    return clean,user or None,password if p.password is not None else None
def safe_url(url):
    # 日志只显示主机和路径，既保留连接定位信息又不泄露 token 或签名查询参数。
    try:
        p=urlsplit(url);return urlunsplit((p.scheme,p.hostname or "",p.path or "","",""))
    except Exception:return "<hidden-url>"
def redact_header(name,value):
    return "***" if name.lower() in {"authorization","proxy-authorization","cookie","set-cookie"} else value
def fmt_rate(value):
    units=("B/s","KiB/s","MiB/s","GiB/s");n=float(value);i=0
    while n>=1024 and i<len(units)-1:n/=1024;i+=1
    return f"{n:.2f} {units[i]}"
class MeteredBody:
    # 包装 Dulwich 生成的 pack 迭代器，在真正送入 socket 时统计上传速度。
    def __init__(self,source,callback,low_speed_limit=0,low_speed_time=0):
        self.source=source;self.callback=callback;self.iterator=None;self.total=0;self.started=time.monotonic();self.last=self.started;self.last_total=0;self.low_speed_limit=low_speed_limit;self.low_speed_time=low_speed_time;self.finished=False
    def __iter__(self):return self
    def __next__(self):
        if hasattr(self.source,"read"):
            chunk=self.source.read(64*1024)
            if not chunk:
                self.finish();raise StopIteration
        else:
            if self.iterator is None:self.iterator=iter(self.source)
            chunk=next(self.iterator)
        if not chunk:return self.__next__()
        self.total+=len(chunk);now=time.monotonic()
        if self.low_speed_limit and now-self.started>=self.low_speed_time and self.total/max(now-self.started,.001)<self.low_speed_limit:raise TimeoutError(f"上传速度低于 {self.low_speed_limit}B/s，持续超过 {self.low_speed_time}s")
        if now-self.last>=.25:
            elapsed=max(now-self.started,.001);instant=(self.total-self.last_total)/max(now-self.last,.001);self.callback(self.total,instant,self.total/elapsed,elapsed,False);self.last=now;self.last_total=self.total
        return chunk
    def finish(self):
        if not self.finished:
            self.finished=True;elapsed=max(time.monotonic()-self.started,.001);self.callback(self.total,0,self.total/elapsed,elapsed,True)
    def close(self):
        close=getattr(self.source,"close",None)
        if close:close()
class MeterPool:
    # 不改写 Dulwich 协议，只在 urllib3 PoolManager 外面记录请求、响应头和 body。
    def __init__(self,pool,low_speed_limit=0,low_speed_time=0):self.pool=pool;self.low_speed_limit=low_speed_limit;self.low_speed_time=low_speed_time
    @property
    def headers(self):return getattr(self.pool,"headers",{})
    def request(self,method,url,body=None,**kwargs):
        upload=method.upper()=="POST" and body is not None and not isinstance(body,(bytes,bytearray,str))
        if upload:
            LOG.debug("[HTTP] -> %s %s",method,safe_url(url));body=MeteredBody(body,lambda total,instant,average,elapsed,final: self.report(total,instant,average,elapsed,final),self.low_speed_limit,self.low_speed_time)
        else:LOG.debug("[HTTP] -> %s %s",method,safe_url(url))
        started=time.monotonic()
        try:resp=self.pool.request(method,url,body=body,**kwargs)
        except Exception as exc:LOG.debug("[HTTP] !! %s %s: %r",method,safe_url(url),exc);raise
        elapsed=time.monotonic()-started;LOG.debug("[HTTP] <= status=%s elapsed=%.2fs",getattr(resp,"status","?"),elapsed)
        for key,value in getattr(resp,"headers",{}).items():LOG.debug("[HTTP] <= %s: %s",key,redact_header(key,value))
        return resp
    def report(self,total,instant,average,elapsed,final=False):
        LOG.info("[PACK] 已发送 %s | 瞬时 %s | 平均 %s | 用时 %.2fs",human_bytes(total),fmt_rate(instant),fmt_rate(average),elapsed)
    def clear(self):
        close=getattr(self.pool,"clear",None)
        if close:close()
def human_bytes(n):
    units=("B","KiB","MiB","GiB");n=float(n);i=0
    while n>=1024 and i<len(units)-1:n/=1024;i+=1
    return f"{n:.2f} {units[i]}"
def remote_progress(data):
    # side-band channel 2 是 receive-pack 的 remote: 进度，按到达顺序立即输出。
    text=data.decode("utf-8","replace").replace("\r","\n")
    for line in text.splitlines():
        if line.strip():LOG.info("remote: %s",line)
def activity(*args):
    # Dulwich 的 report_activity 在不同小版本中参数名称略有变化，这里故意兼容多种调用。
    if args:LOG.debug("[NET] activity=%s",args)
def repo_root(path):
    # 支持从仓库子目录运行，同时不把嵌套仓库的文件交给外层仓库。
    p=Path(path).resolve()
    for candidate in (p,)+tuple(p.parents):
        if (candidate/".git").exists():return candidate
    raise RuntimeError(f"未找到 Git 仓库: {p}")
def active_branch(repo):
    # follow 能处理多层 symbolic ref；detached HEAD 必须由 --branch 明确指定。
    chain,_=repo.refs.follow(b"HEAD")
    for ref in reversed(chain):
        if ref.startswith(b"refs/heads/"):return ref[len(b"refs/heads/"):].decode("utf-8")
    raise RuntimeError("当前 HEAD 不是分支，请使用 --branch 指定目标分支")
def cfg_value(repo,section,key):
    for config in (repo.get_config(),repo.get_config_stack()):
        try:
            value=config.get((section.encode(),),key.encode())
            if value is not None:return value.decode("utf-8","replace") if isinstance(value,bytes) else str(value)
        except (KeyError,AttributeError):pass
    return ""
def set_origin(repo,url):
    # 只保存清理后的 origin，避免把 token 写入 .git/config；本次认证仍由参数或环境变量提供。
    config=repo.get_config();config.set((b'remote "origin"',),b"url",url.encode());config.write_to_path()
def ignored(manager,rel,is_dir=False):
    # Dulwich 1.2.15 的 is_ignored 返回 False 表示被普通 ignore 规则排除。
    value=manager.is_ignored(rel+"/" if is_dir else rel)
    return value is False
@dataclass
class LfsObject:
    path:str
    oid:str
    size:int
def scan_large(repo,threshold):
    # 扫描前先套用 Dulwich ignore manager，.gitignore 中的文件不会被转成 LFS 或提交。
    manager=__import__("dulwich.ignore",fromlist=["IgnoreFilterManager"]).IgnoreFilterManager.from_repo(repo);found={};count=0;last=time.monotonic()
    for base,dirs,files in os.walk(repo.path,topdown=True,followlinks=False):
        base_path=Path(base);keep=[]
        for name in dirs:
            p=base_path/name;rel=p.relative_to(repo.path).as_posix()
            if name==".git" or p.is_symlink() or (p/".git").exists() or ignored(manager,rel,True):continue
            keep.append(name)
        dirs[:]=keep
        for name in files:
            p=base_path/name;count+=1
            if p.is_symlink():continue
            rel=p.relative_to(repo.path).as_posix()
            if ignored(manager,rel):continue
            try:size=p.stat().st_size
            except OSError:continue
            if size<threshold:continue
            h=hashlib.sha256()
            try:
                with p.open("rb") as stream:
                    while True:
                        block=stream.read(1024*1024)
                        if not block:break
                        h.update(block)
            except OSError as exc:LOG.warning("无法读取大文件 %s: %s",rel,exc);continue
            found[rel]=LfsObject(rel,h.hexdigest(),size)
            if time.monotonic()-last>=1:LOG.info("扫描文件 %s | 大文件 %d",count,len(found));last=time.monotonic()
    return found
def update_attributes(repo,objects):
    # 每个大文件用精确规则，避免简单扩展名规则误伤其他文件；已有规则不会重复写入。
    if not objects:return False
    path=Path(repo.path)/".gitattributes";lines=path.read_text("utf-8").splitlines() if path.exists() else [];existing={}
    for line in lines:
        words=line.split(None,1)
        if words:existing[words[0].strip('"')]=line
    changed=False
    for rel in sorted(objects):
        if rel in existing and "filter=lfs" in existing[rel]:continue
        safe=rel.replace("\\","\\\\").replace('"','\\"');lines.append(f'"{safe}" filter=lfs diff=lfs merge=lfs -text');changed=True
    if changed:path.write_text("\n".join(lines)+"\n","utf-8")
    return changed
def apply_lfs_pointers(repo,objects):
    # porcelain.add 已按 .gitignore 完成常规暂存，这里只把索引中的大文件 blob 替换为 LFS pointer。
    if not objects:return
    index=repo.open_index();changed=0
    for item in objects.values():
        key=os.fsencode(item.path)
        if key not in index:continue
        pointer=f"version https://git-lfs.github.com/spec/v1\noid sha256:{item.oid}\nsize {item.size}\n".encode()
        blob=Blob.from_string(pointer);repo.object_store.add_object(blob);index[key]=index[key]._replace(sha=blob.id,size=item.size);changed+=1
    if changed:index.write();LOG.info("已将 %d 个索引项转换为 LFS pointer",changed)
def lfs_endpoint(remote):
    p=urlsplit(remote);path=p.path.rstrip("/")
    if not path.endswith(".git"):path+=".git"
    return urlunsplit((p.scheme,p.netloc,path+"/info/lfs/objects/batch","",""))
def auth_header(user,password):
    if user is None or password is None:return {}
    raw=base64.b64encode(f"{user}:{password}".encode()).decode("ascii")
    return {"Authorization":"Basic "+raw}
def lfs_batch(remote,user,password,objects,timeout):
    # batch 请求很小，使用标准库；真正的大文件 PUT 在 upload_lfs 中使用 http.client 流式发送。
    if not objects:return
    payload={"operation":"upload","transfers":["basic"],"objects":[{"oid":x.oid,"size":x.size} for x in objects.values()]}
    headers={"Accept":"application/vnd.git-lfs+json","Content-Type":"application/vnd.git-lfs+json","User-Agent":"dulwich-push/1.0",**auth_header(user,password)}
    request=Request(lfs_endpoint(remote),data=json.dumps(payload).encode(),headers=headers,method="POST")
    LOG.info("LFS batch 上传 %d 个对象 -> %s",len(objects),safe_url(request.full_url))
    try:
        with urlopen(request,timeout=timeout) as response:answer=json.loads(response.read().decode("utf-8"));LOG.debug("[LFS] batch status=%s",response.status)
    except Exception as exc:raise RuntimeError(f"LFS batch 请求失败: {exc}") from exc
    by_oid={x.oid:x for x in objects.values()}
    for item in answer.get("objects",[]):
        obj=by_oid.get(item.get("oid",""))
        if not obj:continue
        if item.get("error"):raise RuntimeError(f"LFS 对象 {obj.path} 被拒绝: {item['error']}")
        action=item.get("actions",{}).get("upload")
        if action:upload_lfs(obj,action,timeout)
        else:LOG.info("LFS 对象已存在: %s",obj.path)
def upload_lfs(obj,action,timeout):
    # 不把整个文件读入内存；PUT 阶段逐块显示连接、已发送字节和实时速度。
    p=urlsplit(action["href"]);port=p.port or (443 if p.scheme=="https" else 80);target=(p.path or "/")+("?"+p.query if p.query else "")
    context=ssl.create_default_context();conn=(http.client.HTTPSConnection if p.scheme=="https" else http.client.HTTPConnection)(p.hostname,port,timeout=timeout,context=context) if p.scheme=="https" else http.client.HTTPConnection(p.hostname,port,timeout=timeout)
    LOG.debug("[LFS HTTP] -> PUT %s:%s%s",p.hostname,port,p.path or "/");conn.connect()
    conn.putrequest("PUT",target)
    sent_headers={k.lower() for k in action.get("header",{})};
    for key,value in action.get("header",{}).items():conn.putheader(key,value)
    if "content-length" not in sent_headers:conn.putheader("Content-Length",str(obj.size))
    if "content-type" not in sent_headers:conn.putheader("Content-Type","application/octet-stream")
    conn.endheaders();started=time.monotonic();last=started;last_bytes=0;sent=0
    try:
        with (Path.cwd()/obj.path).open("rb") as stream:
            while True:
                block=stream.read(1024*1024)
                if not block:break
                conn.send(block);sent+=len(block);now=time.monotonic()
                if now-last>=.25:
                    instant=(sent-last_bytes)/max(now-last,.001);average=sent/max(now-started,.001);LOG.info("[LFS] %s | 已发送 %s/%s | 瞬时 %s | 平均 %s",obj.path,human_bytes(sent),human_bytes(obj.size),fmt_rate(instant),fmt_rate(average));last=now;last_bytes=sent
        response=conn.getresponse();body=response.read(4096)
        for key,value in response.getheaders():LOG.debug("[LFS HTTP] <= %s: %s",key,redact_header(key,value))
        if response.status<200 or response.status>=300:raise RuntimeError(f"LFS PUT HTTP {response.status}: {body.decode('utf-8','replace')[:300]}")
        LOG.info("LFS 上传完成: %s | %s | %.2fs",obj.path,human_bytes(sent),time.monotonic()-started)
    finally:conn.close()
def is_ancestor(repo,old,new):
    # 非 force 推送前本地检查快进关系，避免先生成大 pack 再收到 non-fast-forward。
    if old in (None,ZERO_SHA):return True
    todo=[new];seen=set()
    while todo:
        oid=todo.pop()
        if oid==old:return True
        if oid in seen or oid in (None,ZERO_SHA):continue
        seen.add(oid)
        try:parents=repo[oid].parents
        except (KeyError,AttributeError):continue
        todo.extend(parents)
    return False
def remote_refs(result):
    return getattr(result,"refs",result)
def push_once(repo,remote,branch,user,password,args):
    pool=MeterPool(default_urllib3_manager(timeout=args.connect_timeout,base_url=remote),args.low_speed_limit,args.low_speed_time)
    try:
        client,path=get_transport_and_path_from_url(remote,operation="push",username=user,password=password,report_activity=activity,pool_manager=pool)
        ref=b"refs/heads/"+branch.encode("utf-8");new=repo.refs[ref]
        if not new:raise RuntimeError(f"本地分支没有提交: {branch}")
        refs=remote_refs(client.get_refs(path));old=refs.get(ref,ZERO_SHA)
        if old is None:old=ZERO_SHA
        if not args.force and not is_ancestor(repo,old,new):raise RuntimeError(f"远端 {branch} 不是本地提交的祖先，拒绝非快进推送；需要 --force")
        def update(remote_refs):
            # send_pack 会用这个映射生成 receive-pack 命令和需要发送的对象集合。
            return {ref:new}
        result=client.send_pack(path,update,repo.generate_pack_data,progress=remote_progress)
        status=getattr(result,"ref_status",None) or {}
        failed={k:v for k,v in status.items() if v}
        if failed:raise RuntimeError("远端拒绝 ref: "+repr(failed))
        LOG.info("推送完成: %s -> %s",branch,new.decode() if isinstance(new,bytes) else new);return result
    finally:pool.clear()
def push(repo,remote,branch,args,user,password,lfs_objects):
    # 先扫描和改写索引，再提交；每次网络重试都会重新建立 Dulwich HTTP client。
    if lfs_objects:
        lfs_batch(remote,user,password,lfs_objects,args.connect_timeout)
    last=None
    for attempt in range(1,args.retry+1):
        LOG.info("===== 推送 %s %s (尝试 %d/%d，间隔 %ss) =====",safe_url(remote),branch,attempt,args.retry,args.retry_wait)
        try:return push_once(repo,remote,branch,user,password,args)
        except (HTTPUnauthorized,HTTPProxyUnauthorized) as exc:raise RuntimeError("认证失败，请检查 URL token 或 GITHUB_TOKEN") from exc
        except Exception as exc:
            last=exc;text=str(exc).lower();network=any(x in text for x in ("timed out","timeout","connection reset","connection aborted","connection refused","temporarily unavailable","remote end hung up","network is unreachable","protocol error","http 502","http 503","http 504"))
            if not network or attempt>=args.retry:raise
            LOG.warning("网络错误，%s 秒后重试: %s",args.retry_wait,exc);time.sleep(args.retry_wait)
    raise last
def build_parser():
    # 参数保留原脚本常用的 -v 3 -u push URL 调用方式，同时补充纯 Dulwich 必需的网络选项。
    p=argparse.ArgumentParser(description="Dulwich 1.2.15 pure-Python push")
    p.add_argument("-v","--verbose",type=int,default=2);p.add_argument("-u","--auto-user",action="store_true",help="从 URL 或环境变量自动设置身份")
    p.add_argument("mode",choices=("push",));p.add_argument("remote",nargs="?");p.add_argument("--repo",default=".");p.add_argument("--branch");p.add_argument("-m","--message");p.add_argument("--name");p.add_argument("--email")
    p.add_argument("--force",action="store_true");p.add_argument("--no-lfs",action="store_true");p.add_argument("--size",default="100MB");p.add_argument("--connect-timeout",type=float,default=45);p.add_argument("--low-speed-limit",type=int,default=10);p.add_argument("--low-speed-time",type=int,default=60);p.add_argument("--retry",type=int,default=10);p.add_argument("--retry-wait",type=int,default=5)
    return p
def main():
    args=build_parser().parse_args();setup_log(args.verbose);root=repo_root(args.repo);repo=Repo(str(root));LOG.info("仓库路径: %s",root);LOG.info("Git 引擎: dulwich 纯 Python 实现（无需外部 git）");LOG.info("文件限制: %s (%d 字节)",human_bytes(size_bytes(args.size)),size_bytes(args.size))
    raw=args.remote or cfg_value(repo,'remote "origin"',"url")
    if not raw:raise SystemExit("缺少远程 URL；请传入 URL 或配置 remote.origin.url")
    remote,user,password=split_remote(raw);env_token=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if password is None and env_token:password=env_token
    if user is None:
        parts=[x for x in urlsplit(remote).path.strip("/").split("/") if x];user=(parts[0] if parts else None)
    LOG.info("远程地址: %s",safe_url(remote));branch=args.branch or active_branch(repo);LOG.info("分支: %s",branch);LOG.info("连接超时: %ss | 低速阈值: %sB/s | 低速超时: %ss",args.connect_timeout,args.low_speed_limit,args.low_speed_time)
    if args.remote:set_origin(repo,remote)
    name=args.name or os.environ.get("GIT_AUTHOR_NAME") or cfg_value(repo,"user","name");email=args.email or os.environ.get("GIT_AUTHOR_EMAIL") or cfg_value(repo,"user","email")
    if args.auto_user:
        name=user or name or "dulwich-user";email=f"{user}@users.noreply.github.com" if user else (email or f"{name}@users.noreply.github.com");LOG.info("自动身份: %s <%s>",name,email)
    if not name or not email:raise SystemExit("缺少提交身份，请使用 -u、--name/--email 或配置 user.name/user.email")
    threshold=size_bytes(args.size);large={} if args.no_lfs else scan_large(repo,threshold);LOG.info("扫描到 %d 个非忽略大文件",len(large))
    if large and update_attributes(repo,large):LOG.info(".gitattributes 更新完成，LFS 追踪总数: %d",len(large))
    os.chdir(root);added,ignored_paths=porcelain.add(repo);apply_lfs_pointers(repo,large)
    if ignored_paths:LOG.info("按 gitignore 排除 %d 个路径",len(ignored_paths))
    status=porcelain.status(repo);staged=getattr(status,"staged",status[0] if isinstance(status,tuple) else [])
    staged=list(staged or [])
    if staged:
        message=args.message or f"auto push {time.strftime('%Y-%m-%d__%H.%M.%S')}"
        commit=porcelain.commit(repo,message,author=f"{name} <{email}>",committer=f"{name} <{email}>");LOG.info("提交完成: %s | 暂存文件 %d",commit.decode() if isinstance(commit,bytes) else commit,len(staged))
    else:LOG.info("工作区没有需要提交的变更")
    push(repo,remote,branch,args,user,password,large);LOG.info("操作结束！")
if __name__=="__main__":
    try:main()
    except KeyboardInterrupt:LOG.warning("用户中断");sys.exit(130)
    except Exception as exc:LOG.error("失败: %s",exc);sys.exit(1)
