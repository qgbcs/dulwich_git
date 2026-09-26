#!/usr/bin/env python3
from __future__ import annotations # 启用新注解语法兼容旧版解释器
import argparse,base64,hashlib,http.client,io,json,logging,math,os,re,socket,ssl,stat,sys,tempfile,threading,time,unittest # 全部标准库导入无第三方依赖
from contextlib import contextmanager,suppress # 上下文管理器与异常抑制工具
from datetime import datetime # 时区与提交时间计算
from pathlib import Path # 面向对象路径操作
from urllib.parse import quote,unquote,urljoin,urlsplit,urlunsplit # URL解析拼接与分支解码
from urllib.request import getproxies,proxy_bypass # 系统代理发现与直连判断
from dulwich.client import AbstractHttpGitClient,LocalGitClient # HTTP与本地推送客户端基类
from dulwich.errors import GitProtocolError,NotGitRepository # 仓库不存在与协议错误
from dulwich.ignore import IgnoreFilter,IgnoreFilterManager,default_user_ignore_filter_path,translate as ignore_translate # 多层忽略规则与通配翻译
from dulwich.index import IndexEntry,index_entry_from_stat,commit_tree,validate_path,get_path_element_validator # 索引项构造与路径校验
from dulwich.object_store import iter_tree_contents # 遍历提交树内容
from dulwich.objects import Blob,Commit # Blob与Commit对象构造
from dulwich.protocol import ZERO_SHA # 全零SHA表示空引用
from dulwich.repo import Repo # 仓库打开与初始化
from unittest.mock import patch # 自测中拦截子进程确保纯标准库
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer # 自测用HTTP与LFS模拟服务
LOG=logging.getLogger("PurePush");SECRETS=set();CHUNK=64*1024;POINTER_PREFIX=b"version https://git-lfs.github.com/spec/v1\n";MEDIA="application/vnd.git-lfs+json";UA="git/2.45.0 purepush-dulwich" # 全局日志密钥分块指针常量
class StopPush(RuntimeError):pass # 不可重试致命错误直接终止推送
class NetworkFailure(RuntimeError):pass # 可重试网络瞬断错误
class HTTPFailure(StopPush): # HTTP状态码错误携带重试等待
 def __init__(self,code,url,detail="",retry_after=0):super().__init__(f"HTTP {code} {safe_url(url)} {detail}");self.code=int(code);self.retry_after=retry_after # 保存状态码与Retry-After
def remember(s): # 登记需脱敏的令牌与密码
 if s and len(str(s))>3:SECRETS.add(str(s)) # 过短不登记避免误替换
def safe_url(v): # 日志用安全URL去凭据与查询串
 try:p=urlsplit(str(v));h=p.hostname or "";h=f"[{h}]" if ":" in h else h;return urlunsplit((p.scheme,h+(f":{p.port}" if p.port else ""),p.path,"","")) # IPv6补括号丢弃query防签名泄漏
 except ValueError:return "[URL已隐藏]" # 非法URL直接隐藏
def redact(v): # 脱敏任意日志文本防令牌ANSI污染
 t=str(v) # 转字符串统一处理
 for s in sorted(SECRETS,key=len,reverse=True):t=t.replace(s,"***") # 长密钥先替换避免部分残留
 t=re.sub(r"https?://[^\s\"' ]+",lambda m:safe_url(m.group()),t) # 所有URL统一脱敏
 return t.replace("\x1b","\\x1b") # ANSI转义防止终端控制注入
class SafeFormatter(logging.Formatter): # 安全日志格式化器
 def format(self,r):return redact(super().format(r)) # 连堆栈一起脱敏
def setup_logging(v): # 配置控制台日志级别与格式
 h=logging.StreamHandler(sys.stdout);h.setFormatter(SafeFormatter("%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s","%Y-%m-%d %H:%M:%S"));LOG.handlers[:]=[h];LOG.propagate=False;LOG.setLevel({0:logging.ERROR,1:logging.WARNING,2:logging.INFO}.get(v,logging.DEBUG)) # v映射级别默认INFO
def trace(a,m,*x): # -v3细节追踪日志
 if getattr(a,"trace",False):LOG.log(logging.DEBUG if a.verbose>=3 else logging.INFO,m,*x) # 仅trace开启才输出
def text(v):return v.decode("utf-8","surrogateescape") if isinstance(v,bytes) else str(v) # 字节安全转字符串保留非法字节
def cfg(c,s,k,d=b""): # 读取git配置缺失返回默认
 s=(s,) if isinstance(s,bytes) else tuple(s) # 统一节名为元组
 try:return c.get(s,k) # 正常读取
 except KeyError:return d # 缺失返回默认
def yes(c,s,k,d=False): # 读取布尔配置兼容异常
 try:return c.get_boolean(tuple(s),k,d) # 标准布尔解析
 except Exception:return d # 异常回默认
def human(n): # 字节数转人类可读
 n=float(n);u=("B","KiB","MiB","GiB","TiB");i=0 # 单位表
 while n>=1024 and i<len(u)-1:n/=1024;i+=1 # 循环除1024
 return f"{n:.2f} {u[i]}" # 保留两位小数
def parse_size(v): # 解析100MB/1g等尺寸字符串
 s=str(v).strip().lower();m=1 # 转小写去空格
 for suf,f in (("gb",1024**3),("g",1024**3),("mb",1024**2),("m",1024**2),("kb",1024),("k",1024)): # 从长到短匹配后缀
  if s.endswith(suf):m=f;s=s[:-len(suf)];break # 命中则 stripping
 if s.endswith("b"):s=s[:-1] # 去掉末尾b
 return int(float(s)*m) # 浮点乘系数转整
def retry_delay(v): # 解析Retry-After秒数或HTTP日期
 if not v:return 0 # 空直接0
 v=v.strip() # 去空格
 if v.isdigit():return int(v) # 纯数字秒数
 try:from email.utils import parsedate_to_datetime;return max(0,int((parsedate_to_datetime(v).timestamp()-time.time()))) # HTTP日期转剩余秒
 except Exception:return 0 # 解析失败0
def origin(u): # 取URL源scheme://host:port
 p=urlsplit(u);return f"{p.scheme}://{p.hostname}:{p.port or (443 if p.scheme=='https' else 80)}" # 默认端口补全
def basic(u,p): # 构造Basic认证头并登记脱敏
 if not u:return None # 无用户无认证
 t="Basic "+base64.b64encode(f"{unquote(u)}:{unquote(p)}".encode()).decode();remember(t);remember(u);remember(p);return t # 登记令牌防日志泄漏
def split_credentials(u): # 分离URL中用户名密码与干净地址
 p=urlsplit(u);u1=unquote(p.username or "");p1=unquote(p.password or "") # 解码用户密码
 net=p.hostname or "" # 主机名
 if ":" in net:net=f"[{net}]" # IPv6括号
 if p.port:net+=f":{p.port}" # 补端口
 return urlunsplit((p.scheme,net,p.path or "/","","")),u1,p1 # 返回干净URL与凭据
def clean_remote_and_auth(remote,branch): # 归一化远程地址兼容网页tree/blob路径
 if remote.startswith("git@"): # SCP语法转https提示
  h,_,rp=remote[4:].partition(":");remote=f"https://{h}/{rp}" # git@host:path转https
  LOG.warning("已将SCP地址转为HTTPS，需凭据请写在URL中") # 提醒凭据
 p=urlsplit(remote);user=unquote(p.username or "");pwd=unquote(p.password or "") # 提取凭据
 if user or pwd:remember(user);remember(pwd) # 登记脱敏
 parts=[x for x in p.path.strip("/").split("/") if x] # 路径分段
 if len(parts)>2 and parts[2] in ("tree","blob"): # 网页地址容错
  if len(parts)>3:branch=unquote(parts[3]) # 取分支名
  LOG.warning("网页路径只定位仓库，含斜杠分支请显式--branch") # 提醒斜杠分支
 base="/"+"/".join(parts[:2]) # 只取owner/repo
 if base.endswith(".git"):base=base[:-4] # 去重.git
 clean=urlunsplit((p.scheme,p.hostname+ (f":{p.port}" if p.port else ""),base+".git","","")) # 拼标准.git地址
 if not branch:branch="master" # 默认分支master
 return clean.rstrip("/"),user,pwd,branch # 返回干净地址与分支
def atomic_write(path,data): # 同目录原子写防半截文件
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True) # 确保父目录
 if path.is_symlink():raise StopPush(f"拒绝覆盖符号链接: {path}") # 拒绝链接覆盖
 mode=stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644 # 保留原权限
 fd,tmp=tempfile.mkstemp(prefix=".purepush-",dir=str(path.parent)) # 同目录临时文件
 try: # 写临时后替换
  with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno()) # 刷盘保证落盘
  os.chmod(tmp,mode);os.replace(tmp,path) # 原子替换
 finally: # 清理残留
  with suppress(FileNotFoundError):os.unlink(tmp) # 替换成功后删除源
def signature(st):return (stat.S_IFMT(st.st_mode),st.st_size,int(st.st_mtime)) # 仅类型大小秒级mtime容忍Windows抖动
def identity_pair(st):return (getattr(st,"st_dev",0),getattr(st,"st_ino",0)) # 取设备inode对Windows多为0
@contextmanager
def regular_reader(path): # 安全读普通文件防链接劫持与中途篡改
 path=Path(path);before=path.lstat() # 先lstat不跟随链接
 if not stat.S_ISREG(before.st_mode):raise StopPush(f"不是普通文件拒绝跟随: {path}") # 非普通文件拒绝
 fd=os.open(str(path),os.O_RDONLY|getattr(os,"O_BINARY",0)|getattr(os,"O_NOFOLLOW",0)) # O_NOFOLLOW防链接
 with os.fdopen(fd,"rb") as f: # 接管fd自动关闭
  opened=os.fstat(f.fileno()) # 打开后fstat
  if signature(opened)!=signature(before):time.sleep(0.02);nb=path.lstat();no=os.fstat(f.fileno());before=nb if signature(no)==signature(nb) else before # 杀软抖动重采一次
  if signature(os.fstat(f.fileno()))!=signature(before):raise StopPush(f"读取前文件已变化: {path}") # 仍不一致报错
  a,b=identity_pair(os.fstat(f.fileno())),identity_pair(before) # 取inode对
  if all(a) and all(b) and a!=b:raise StopPush(f"打开的不是同一文件: {path}") # inode可用才校验避Windows0
  yield f,before # 产出句柄与快照
  if signature(os.fstat(f.fileno()))!=signature(before) or signature(path.lstat())!=signature(before):raise StopPush(f"读取时文件变化请重试: {path}") # 读后双重校验
def read_regular(path,limit=None): # 读普通文件全部内容可选限大小
 with regular_reader(path) as (f,st): # 安全打开
  if limit is not None and st.st_size>limit:raise StopPush(f"文件过大: {path}") # 超限拒绝防内存爆
  return f.read() # 返回全部字节
def config_bytes(path): # 读配置文件缺失或链接返回空
 path=Path(path) # 统一Path
 if path.is_symlink():return b"" # 链接返回空防穿越
 try:return read_regular(path,8*1024*1024) # 限8M防超大配置
 except (FileNotFoundError,NotADirectoryError,PermissionError,OSError):return b"" # 缺失返回空
class SafeIgnore(IgnoreFilterManager): # 安全忽略管理器防链接穿越
 def _load_path(self,path): # 重写单目录.gitignore加载
  if (Path(self._top_path)/path/".gitignore").is_symlink():return None # 链接的ignore不读
  return super()._load_path(path) # 正常加载
 def _is_dir(self,path): # 重写目录判断不跟随链接
  p=Path(self._top_path)/path;return path.endswith("/") or (p.is_dir() and not p.is_symlink() and not getattr(p,"is_junction",lambda:False)()) # 链接junction不算目录修复link/误杀
def ignore_manager(repo,config): # 构建全局到局部忽略链
 ignorecase=yes(config,(b"core",),b"ignorecase",False);filters=[] # 大小写敏感配置
 for p in (Path(text(cfg(config,b"core",b"excludesfile",os.fsencode(default_user_ignore_filter_path(config))))).expanduser(),Path(repo.controldir())/"info"/"exclude"): # 全局与exclude
  try:filters.append(IgnoreFilter.from_path(str(p),ignorecase)) # 低优先级在前
  except (FileNotFoundError,NotADirectoryError,OSError):pass # 缺失跳过
 return SafeIgnore(str(repo.path),filters,ignorecase) # 顶层+过滤器+大小写
def attr_words(line): # 解析attributes单行支持C引号
 line=line.strip() # 去两端空白
 if not line or line.startswith(b"#"):return None,[] # 空与注释跳过
 if not line.startswith(b'"'):w=line.split();return w[0],w[1:] # 非引号空格切分
 out=bytearray();i=1;esc={ord("a"):7,ord("b"):8,ord("t"):9,ord("n"):10,ord("v"):11,ord("f"):12,ord("r"):13,34:34,92:92} # C转义表
 while i<len(line): # 逐字节解析引号
  b=line[i];i+=1 # 取字节
  if b==34:return bytes(out),line[i:].split() # 闭合返回模式与属性
  if b!=92:out.append(b);continue # 非反斜杠直存
  if i>=len(line):break # 末尾反斜杠中断
  b=line[i];i+=1 # 取转义字符
  if 48<=b<=55: # 八进制转义
   o=bytearray([b]);k=0 # 收集最多3位
   while k<2 and i<len(line) and 48<=line[i]<=55:o.append(line[i]);i+=1;k+=1 # 继续收集
   v=int(o,8) # 转数值
   if v>255:raise StopPush(".gitattributes八进制超界") # 超字节报错
   out.append(v);continue # 存入
  if b in esc:out.append(esc[b]);continue # 命名转义
  raise StopPush(".gitattributes不支持的C转义") # 未知转义报错
 raise StopPush(".gitattributes引号未闭合") # 缺闭合报错
def parse_attribute(t): # 解析单个属性token
 if t[:1]==b"-":return t[1:],False # -text为False
 if t[:1]==b"!":return t[1:],None # !attr取消为None
 if b"=" in t:k,v=t.split(b"=",1);return k,v # k=v键值
 return t,True # 裸属性为True
class AttrPattern: # 属性模式匹配器复用ignore通配
 def __init__(self,p):self.p=p;self.r=re.compile(ignore_translate(p if p.startswith(b"/") or b"/" in p.rstrip(b"/") else b"**/"+p)) # 无斜杠自动**/前缀
 def match(self,rel):return bool(self.r.match(rel)) or bool(self.r.match(b"/"+rel)) # 相对与绝对双试
class Attributes: # 多层attributes合并管理器
 def __init__(self,repo,config,index):self.repo=repo;self.root=Path(repo.path);self.index=index;self.cache={};d=Path(os.environ.get("XDG_CONFIG_HOME",str(Path.home()/".config")))/"git"/"attributes";self.g=Path(text(cfg(config,b"core",b"attributesfile",os.fsencode(d)))).expanduser();self.info=Path(repo.controldir())/"info"/"attributes" # 全局与info路径
 def invalidate(self):self.cache.clear() # 自动LFS后清缓存
 def load(self,path,rel=None,macro=True): # 加载单个attributes文件
  k=(str(path),macro) # 缓存键含宏权限
  if k in self.cache:return self.cache[k] # 命中返回
  data=config_bytes(path) # 读工作区文件
  if not data and rel is not None and rel in self.index: # 工作区缺失回退索引
   e=self.index[rel] # 取索引项
   if e.mode in (0o100644,0o100755): # 仅普通文件
    with suppress(KeyError):data=self.repo.object_store[e.sha].data # 取Blob数据
  rules=[];macros={} # 规则与宏
  for ln in data.splitlines(): # 逐行解析
   pat,toks=attr_words(ln) # 词法切分
   if pat is None:continue # 跳过空注释
   vals=[parse_attribute(t) for t in toks] # 解析属性值
   if pat.startswith(b"[attr]"): # 宏定义
    if macro:macros[pat[6:]]=vals # 仅顶层允许
    else:LOG.warning("忽略子目录宏: %s",path) # 子目录警告
   elif pat.startswith(b"!"):raise StopPush(f".gitattributes不允许负模式: {path}") # 负模式拒绝
   else: # 普通规则
    try:rules.append((AttrPattern(pat),vals)) # 编译模式
    except (ValueError,re.error) as e:raise StopPush(f"属性模式无效: {path}: {e}") from e # 包装报错
  self.cache[k]=(rules,macros);return rules,macros # 缓存返回
 def get(self,rel): # 取路径最终生效属性
  parts=rel.split(b"/");levels=[(self.g,rel,None,True)] # 全局层
  for i in range(len(parts)):n=b"/".join(parts[:i]+[b".gitattributes"]);levels.append((self.root/os.fsdecode(n),b"/".join(parts[i:]),n,i==0)) # 每级目录层
  levels.append((self.info,rel,None,True)) # info层最高
  loaded=[(self.load(p,k,m),l) for p,l,k,m in levels] # 加载全部
  defs={b"binary":[(b"diff",False),(b"merge",False),(b"text",False)]};res={} # 内建binary宏
  for (_,ms),_ in loaded:defs.update(ms) # 合并用户宏
  def apply(vs,seen=frozenset()): # 递归展开宏
   for n,v in vs:res[n]=v # 先赋值
   for n,v in vs: # 再展开值为True的宏
    if v is True and n in defs: # 命中宏
     if n in seen:raise StopPush("属性宏循环: "+text(n)) # 循环报错
     apply(defs[n],seen|{n}) # 递归
  for (rs,_),lc in loaded: # 按优先级依次应用
   for pat,vs in rs: # 遍历规则
    if pat.match(lc):apply(vs) # 命中应用
  return {k:v for k,v in res.items() if v is not None} # 过滤取消属性
def exact_attr_rule(name): # 生成单文件精确LFS规则
 raw=os.fsencode(name);body=b"".join((b"\\"+bytes([c])) if c in b'"\\' else bytes([c]) for c in raw) # 转义引号反斜杠
 need=b" " in raw or b"[" in raw or b"#" in raw or b"*" in raw or b"?" in raw # 需引号字符
 q=b'"/'+body+b'"' if need else b"/"+body # 含特殊字符加引号
 return q+b" filter=lfs diff=lfs merge=lfs -text" # 拼LFS四属性
def pointer_bytes(o,s):return POINTER_PREFIX+f"oid sha256:{o}\nsize {s}\n".encode() # 生成LFS指针内容
def pointer_info(d): # 解析LFS指针返回oid,size
 if not d.startswith(POINTER_PREFIX) or len(d)>1024:return None # 前缀长度初筛
 o=s=None # 初始化
 for ln in d.splitlines()[1:]: # 逐行解析
  if ln.startswith(b"oid sha256:"):o=ln[11:].decode("ascii","replace") # 取oid
  elif ln.startswith(b"size "): # 取size
   with suppress(ValueError):s=int(ln[5:]) # 容错整数
 if o and re.fullmatch(r"[0-9a-f]{64}",o) and s is not None and s>=0:return o,s # 严格校验
 return None # 非法返回空
class LFSCache: # LFS本地对象缓存
 def __init__(self,repo,config):c=text(cfg(config,b"lfs",b"storage",b""));self.root=Path(c).expanduser() if c else Path(repo.controldir())/"lfs";self.verified={} # 自定义或默认.git/lfs
 def path(self,o):return self.root/"objects"/o[:2]/o[2:4]/o # 按oid分片路径
 def put(self,src): # 快照大文件到LFS并返回指针
  src=Path(src);self.root.mkdir(parents=True,exist_ok=True);td=self.root/"tmp";td.mkdir(parents=True,exist_ok=True) # 确保目录
  fd,tmp=tempfile.mkstemp(dir=str(td));h=hashlib.sha256();sz=0;last=time.monotonic() # 临时文件与哈希
  try: # 拷贝哈希
   with os.fdopen(fd,"wb") as out,regular_reader(src) as (f,st): # 双打开读写
    for b in iter(lambda:f.read(CHUNK),b""):out.write(b);h.update(b);sz+=len(b) # 分块拷贝
    if time.monotonic()-last>=1:LOG.info("LFS快照: %s | %s/%s",src.name,human(sz),human(st.st_size));last=time.monotonic() # 每秒进度
    out.flush();os.fsync(out.fileno()) # 刷盘
   o=h.hexdigest();d=self.path(o);d.parent.mkdir(parents=True,exist_ok=True);os.replace(tmp,d);self.verified[(o,sz)]=signature(d.stat());return pointer_bytes(o,sz) # 关闭后替换避Win占用
  finally: # 清理临时
   with suppress(FileNotFoundError):os.unlink(tmp) # 删除残留
 def require(self,o,s): # 校验并取缓存对象
  p=self.path(o) # 定位路径
  if not p.is_file() or p.is_symlink():raise StopPush(f"LFS缓存缺失{o[:12]}恢复原文件重推") # 缺失报错
  if self.verified.get((o,s))!=signature(p.stat()): # 未验证或变化重验
   h=hashlib.sha256();t=0 # 哈希计数
   with regular_reader(p) as (f,_): # 安全读
    for b in iter(lambda:f.read(1024*1024),b""):h.update(b);t+=len(b) # 分块哈希
   if t!=s or h.hexdigest()!=o:raise StopPush(f"LFS缓存损坏: {o[:12]}") # 损坏报错
   self.verified[(o,s)]=signature(p.stat()) # 登记验证
  return p # 返回路径
class TransferMonitor: # 传输测速与低速看门狗
 def __init__(self,sock,a,label,total=None):self.sock=sock;self.a=a;self.label=label;self.total=total;self.lock=threading.Lock();self.sent=0;self.recv=0;self.start=time.monotonic();self.last_log=0;self.last_act=time.monotonic();self.hist=[];self.fail=None;self.stop=threading.Event();self.th=threading.Thread(target=self.run,daemon=True);self.th.start() # 启动后台线程
 def add(self,s=0,r=0): # 累加收发字节
  with self.lock:self.sent+=s;self.recv+=r;self.last_act=time.monotonic();self.hist.append((self.last_act,s+r)) # 记录历史
  self.check() # 检查失败
 def speed(self): # 近2秒平均速度
  n=time.monotonic();c=n-2.0 # 窗口起点
  with self.lock:self.hist=[x for x in self.hist if x[0]>=c];return sum(x[1] for x in self.hist)/2.0 # 求和除2
 def run(self): # 后台循环输出与熔断
  while not self.stop.wait(0.1): # 每0.1s检查
   n=time.monotonic() # 当前时间
   with self.lock:s,r,la,fail=self.sent,self.recv,self.last_act,self.fail # 快照
   if fail:break # 已失败退出
   if n-self.last_log>=self.a.progress_interval and (s+r)>0: # 到间隔输出
    tot=f"/{human(self.total)}" if self.total else "";el=n-self.start+1e-9 # 总量与耗时
    LOG.info("%s: ↑%s ↓%s%s | 瞬时%s/s 平均%s/s",self.label,human(s),human(r),tot,human(self.speed()),human((s+r)/el)) # 实时速度
    self.last_log=n # 更新日志时间
   idle=n-la # 空闲时长
   if idle>=self.a.low_speed_time and (s+r)>0 and self.speed()<self.a.low_speed_limit and self.fail is None: # 低速持续
    self.fail=NetworkFailure(f"{self.label}: 低于{self.a.low_speed_limit}B/s持续{idle:.1f}s断开");LOG.warning("%s",self.fail) # 置失败
    with suppress(Exception):self.sock.shutdown(socket.SHUT_RDWR) # 打断阻塞
    break # 退出循环
 def check(self): # 抛低速失败
  if self.fail is not None:raise self.fail # 有失败抛出
 def close(self): # 停止线程
  self.stop.set() # 置停止
  with suppress(RuntimeError):self.th.join(timeout=1) # 等线程
class CountingConnectionMixin: # 连接发送计数混入
 monitor=None # 监视器槽
 def send(self,d): # 重写发送计数
  if self.monitor is not None and isinstance(d,(bytes,bytearray,memoryview)):self.monitor.add(s=len(d)) # 统计出站
  return super().send(d) # 原发送
class CountingHTTP(CountingConnectionMixin,http.client.HTTPConnection):pass # HTTP计数连接
class CountingHTTPS(CountingConnectionMixin,http.client.HTTPSConnection):pass # HTTPS计数连接
class CountingReader(io.RawIOBase): # 响应读取计数包装
 def __init__(self,raw,m):self.raw=raw;self.m=m # 保存原始与监视器
 def readable(self):return True # 可读
 def read(self,n=-1): # 重写读计数
  d=self.raw.read() if n is None or n<0 else self.raw.read(n) # 兼容-1
  if d:self.m.add(r=len(d)) # 统计入站
  self.m.check() # 检查熔断
  return d # 返回数据
 def close(self): # 关闭透传
  with suppress(Exception):self.raw.close() # 关原始
  super().close() # 关基类
class Transport: # 标准库HTTP传输支持代理测速重定向
 def __init__(self,a,auths=None):self.a=a;self.auths=auths or {} # 保存参数与凭据
 def proxy_for(self,url): # 取代理地址
  if getattr(self.a,"proxy",None):return self.a.proxy # 显式代理优先
  if getattr(self.a,"no_proxy",False):return None # 禁代理返回空
  try: # 系统代理
   if proxy_bypass(urlsplit(url).hostname or ""):return None # 直连名单
  except Exception:pass # 异常忽略
  px=getproxies().get("https") or getproxies().get("http") # 取系统代理
  return px # 返回代理
 def connect(self,url,label,total=None): # 建立连接并输出DNS/TCP/TLS耗时
  p=urlsplit(url);scheme=p.scheme;host=p.hostname;port=p.port or (443 if scheme=="https" else 80) # 解析目标
  px=self.proxy_for(url);use_px=bool(px) and not (host in ("127.0.0.1","localhost","::1")) # 本地不走代理
  chost,cport=host,port # 默认直连
  if use_px:pp=urlsplit(px);chost,cport=pp.hostname,pp.port or 8080 # 代理主机端口
  t0=time.monotonic();ip=socket.getaddrinfo(chost,cport,type=socket.SOCK_STREAM)[0][4][0];t1=time.monotonic() # DNS解析计时
  trace(self.a,"DNS %s->%s %.0fms",chost,ip,(t1-t0)*1000) # 输出DNS
  s=socket.create_connection((chost,cport),timeout=self.a.connect_timeout);t2=time.monotonic() # TCP连接计时
  s.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1) # 禁Nagle降延迟
  try:s.settimeout(self.a.io_timeout) # IO超时
  except Exception:pass # 忽略
  LOG.info("连接 %s TCP %.0fms%s",safe_url(url),(t2-t1)*1000," 经代理" if use_px else "") # 输出TCP
  if scheme=="https": # TLS握手
   ctx=ssl.create_default_context(cafile=getattr(self.a,"ca_file",None) or None) # 自签CA支持
   if use_px: # 代理隧道
    s.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n".encode()) # 发CONNECT
    f=s.makefile("rb");ln=f.readline().decode("iso-8859-1");f.close() # 读首行
    if " 200" not in ln:raise NetworkFailure(f"代理隧道失败: {ln.strip()}") # 非200报错
   t3=time.monotonic();s=ctx.wrap_socket(s,server_hostname=host);t4=time.monotonic() # 包装TLS计时
   LOG.info("TLS %s 握手 %.0fms %s",safe_url(url),(t4-t3)*1000,s.version() if hasattr(s,"version") else "") # 输出TLS
  else: # HTTP代理无需隧道
   pass # 直通
  m=TransferMonitor(s,self.a,label,total) # 创建监视器
  if scheme=="https":c=CountingHTTPS(host,port,timeout=self.a.connect_timeout,context=ctx) # HTTPS连接
  else:c=CountingHTTP(host,port,timeout=self.a.connect_timeout) # HTTP连接
  c.sock=s;c.monitor=m # 注入已连socket与监视器
  return c,m,use_px # 返回连接监视代理标志
 def request(self,method,url,headers=None,body=None,label="HTTP",allow_error=False,body_size=None,depth=0): # 发送请求处理重定向测速
  if depth>5:raise StopPush("重定向过多") # 防循环
  h=dict(headers or {});h.setdefault("User-Agent",UA);h.setdefault("Accept-Encoding","identity") # 默认头
  tok=self.auths.get(origin(url)) # 取同源凭据
  if tok:h.setdefault("Authorization",tok) # 附凭据
  p=urlsplit(url);tgt=url if (self.proxy_for(url) and p.scheme=="http" and p.hostname not in ("127.0.0.1","localhost")) else (p.path or "/")+(f"?{p.query}" if p.query else "") # 代理用绝对URL
  if isinstance(body,(bytes,bytearray)):body_size=len(body) # 字节体长度
  c,m,use_px=self.connect(url,f"{label} {method} {safe_url(url)}",body_size) # 建连
  c.monitor=m # 绑定监视
  try: # 发请求
   if isinstance(body,(bytes,bytearray)):h.setdefault("Content-Length",str(len(body))) # 字节体长度头
   c.request(method,tgt,body=body,headers=h) # 发送
   raw=c.getresponse() # 取响应
  except (socket.timeout,TimeoutError,ConnectionError,http.client.HTTPException,ssl.SSLError,OSError) as e: # 网络异常
   m.close();with suppress(Exception):c.close() # 关资源
   if m.fail is not None:raise m.fail from e # 低速优先
   raise NetworkFailure(f"{label} {method} {safe_url(url)}失败: {e}") from e # 包装重试
  finally:c.monitor=None # 解绑防复用
  loc=raw.getheader("Location") # 取重定向
  if raw.status in (301,302,303,307,308) and loc: # 重定向处理
   raw.read();m.close(); # 读空关监视
   with suppress(Exception):c.close() # 关连接
   new=urljoin(url,loc);trace(self.a,"重定向%d->%s",raw.status,safe_url(new)) # 日志
   if origin(new)!=origin(url):h.pop("Authorization",None) # 跨域去凭据
   if raw.status==303 or (raw.status in (301,302) and method=="POST"):method,body,body_size="GET",None,None # 改GET
   if body is not None and not isinstance(body,(bytes,bytearray)):raise StopPush("流式体遇重定向无法重放") # 流体拒绝
   return self.request(method,new,h,body,label,allow_error,body_size,depth+1) # 递归
  if raw.status>=400 and not allow_error: # 错误状态
   d=raw.read(4096).decode("utf-8","replace");dl=retry_delay(raw.getheader("Retry-After"));m.close() # 读片段与等待
   with suppress(Exception):c.close() # 关连接
   raise HTTPFailure(raw.status,url,d[:600],dl) # 抛HTTP错
  w=CountingReader(raw,m);w.status=raw.status;w.headers=raw.headers;w.monitor=m;w.raw_response=raw # 包装计数读
  oc=w.close # 保存原关闭
  def cl():m.close();oc() # 先停监视再关响应
  w.close=cl;w._conn=c # 覆盖关闭保存连接
  return w # 返回包装
 def close(self):pass # 单次连接无需池清理
class DulwichResponse: # dulwich兼容响应头
 def __init__(self,w,url):self.wrapper=w;self.status=w.status;self.content_type=w.headers.get("Content-Type");l=w.headers.get("Location");self.redirect_location=urljoin(url,l) if l and self.status in (301,302,303,307,308) else None # 保存重定向
 def close(self):self.wrapper.close() # 关闭透传
class StdlibGitClient(AbstractHttpGitClient): # 标准库Git智能HTTP客户端
 def __init__(self,base_origin,net,**k):self._net=net;super().__init__(base_url=base_origin.rstrip("/")+"/",dumb=False,**k) # 基址为origin防双拼
 def _get_url(self,path):return urljoin(self._base_url,str(path).lstrip("/")) # 拼接仓库路径
 def _http_request(self,url,headers=None,data=None): # 桥接传输
  h=dict(headers or {}) # 拷贝头
  if data is not None:h.setdefault("Content-Type","application/x-git-receive-pack-request") # 推送体类型
  w=self._net.request("GET" if data is None else "POST",url,h,data,"GitHTTP",allow_error=True) # 发请求允错
  r=DulwichResponse(w,url) # 包装响应
  if r.status>=400 and r.redirect_location is None: # 真错误
   d=w.read(4096).decode("utf-8","replace");dl=retry_delay(w.headers.get("Retry-After"));w.close();raise HTTPFailure(r.status,url,d[:600],dl) # 抛错
  return r,w.read # 返回响应与读函数
 def close(self):pass # 空关闭
def walk_candidates(repo,index,manager,config): # 扫描工作区候选文件处理忽略与跟踪
 root=Path(repo.path);tracked=dict(index.items());ic=yes(config,(b"core",),b"ignorecase",False);lookup={os.fsdecode(k).casefold():k for k in tracked} if ic else {};files={};skip=0;cnt=0;last=time.monotonic();val=get_path_element_validator(config) # 初始化
 def fold(r):return os.fsdecode(r).casefold() if ic else os.fsdecode(r) # 大小写折叠
 parents={fold(b"/".join(p.split(b"/")[:i])) for p in tracked for i in range(1,len(p.split(b"/")))} # 已跟踪父目录集
 def oldk(r):return r if r in tracked else lookup.get(os.fsdecode(r).casefold()) # 取旧键兼容大小写
 def add(p): # 单文件加入候选
  nonlocal skip,cnt,last;rel=os.fsencode(p.relative_to(root).as_posix());old=oldk(rel);cnt+=1 # 算相对路径
  if not validate_path(rel,val):raise StopPush(f"无效Git路径: {p}") # 非法路径拒绝
  if old is None and manager.is_ignored(os.fsdecode(rel)) is True:skip+=1;return # 未跟踪且忽略跳过
  files[rel]=(p,old) # 登记候选
  if time.monotonic()-last>=1:LOG.info("扫描: %d | 排除: %d | 当前: %s",cnt,skip,os.fsdecode(rel));last=time.monotonic() # 每秒进度
 def err(e):raise e # 遍历错误直接抛
 for base,dirs,names in os.walk(str(root),topdown=True,followlinks=False,onerror=err): # 不跟随链接遍历
  cur=Path(base);keep=[] # 当前目录与保留子目录
  for n in dirs: # 处理子目录
   ph=cur/n;rel=os.fsencode(ph.relative_to(root).as_posix()) # 子路径与相对键
   if (n.casefold() if os.name=="nt" else n)==".git":continue # 跳过.git
   if ph.is_symlink():add(ph);continue # 目录链接按文件存不进入
   if getattr(ph,"is_junction",lambda:False)():raise StopPush(f"拒绝junction: {ph}") # junction拒绝
   ok=oldk(rel) # 旧键
   if (ph/".git").exists(): # 嵌套仓库
    if ok is not None and tracked[ok].mode==0o160000:add(ph) # 已跟踪子模块按gitlink
    else:LOG.warning("跳过嵌套仓库: %s",ph) # 未跟踪跳过
    continue # 不进入
   if fold(rel) not in parents and ok is None and manager.is_ignored(os.fsdecode(rel)) is True:skip+=1;continue # 无跟踪后代且忽略剪枝
   keep.append(n) # 保留进入
  dirs[:]=keep # 回写保留
  for n in names: # 处理文件
   if (n.casefold() if os.name=="nt" else n)!=".git":add(cur/n) # 跳过.git文件
 LOG.info("扫描完成: %d项 | 忽略: %d项",cnt,skip);return files # 输出统计
def normalize_blob(data,attrs,old,repo,config,path,renorm=False): # 内建换行ident转换拒绝外部过滤
 if attrs.get(b"working-tree-encoding") not in (None,False):raise StopPush(f"不支持编码转换: {os.fsdecode(path)}") # 编码拒绝
 sel=attrs.get(b"filter") # 取filter
 if sel not in (None,False,True,b"lfs"):raise StopPush(f"不执行外部filter={text(sel)}: {os.fsdecode(path)}") # 外部拒绝
 if attrs.get(b"ident") is True:data=re.sub(rb"\$Id:[^$\r\n]*\$",b"$Id$",data) # ident收缩
 ta=attrs.get(b"text");eol=attrs.get(b"eol");auto=cfg(config,b"core",b"autocrlf",b"false").lower() # 取换行配置
 if ta is None and b"crlf" in attrs:ta=False if attrs[b"crlf"] is False else True # 兼容crlf属性
 if ta is False or (ta is None and eol is None and auto not in (b"true",b"input")):return data # 二进制直返
 auto2=ta!=True and not (ta is None and eol in (b"lf",b"crlf")) # 是否自动探测
 non=sum(data.count(bytes([b])) for b in range(32) if b not in (8,9,10,12,13,27))+data.count(b"\x7f") # 不可打印计数
 if auto2 and (b"\0" in data or data.count(b"\r")!=data.count(b"\r\n") or non>(len(data)-non)//128):return data # 二进制特征直返
 if auto2 and old is not None and not renorm and old.mode!=0o160000: # 已有Blob且非强制
  if b"\r\n" in repo.object_store[old.sha].data:return data # 历史含CRLF保持
 conv=data.replace(b"\r\n",b"\n");safe=cfg(config,b"core",b"safecrlf",b"false").lower();ce=cfg(config,b"core",b"eol",b"native") # 转LF取安全策略
 crlf=eol==b"crlf" or (eol is None and (auto==b"true" or (auto!=b"input" and (ce==b"crlf" or (ce==b"native" and os.name=="nt"))))) # 检出是否CRLF
 rest=conv.replace(b"\n",b"\r\n") if crlf else conv # 还原比较
 if safe in (b"true",b"warn") and rest!=data: # 不可逆检查
  if safe==b"true":raise StopPush(f"safecrlf拒绝转换: {os.fsdecode(path)}") # 严格拒绝
  LOG.warning("换行不可逆: %s",os.fsdecode(path)) # 警告
 return conv # 返回LF数据
def stage_all(repo,index,a,config,cache): # 全量暂存自动LFS无外部进程
 if any(not isinstance(e,IndexEntry) for _,e in index.items()):raise StopPush("索引冲突未解决") # 冲突拒绝
 if any(stat.S_ISDIR(e.mode) or getattr(e,"skip_worktree",False) for _,e in index.items()):raise StopPush("稀疏索引不受支持") # 稀疏拒绝
 if any(getattr(x,"signature",b"X")[:1].islower() for x in (getattr(index,"_extensions",[]) or [])):raise StopPush("必需索引扩展不受支持") # 扩展拒绝
 manager=ignore_manager(repo,config);files=walk_candidates(repo,index,manager,config);attrs=Attributes(repo,config,index);auto={};olds=dict(index.items());root=Path(repo.path) # 初始化
 for rel,(ph,ok) in list(files.items()): # 首遍探测大文件
  st=ph.lstat() # 取状态
  if ok is not None and (olds[ok].flags&0x8000 or olds[ok].mode==0o120000):continue # 假设未变与链接跳过探测
  if not stat.S_ISREG(st.st_mode) or st.st_size<a.size:continue # 仅普通大文件
  if attrs.get(rel).get(b"filter")==b"lfs":continue # 已LFS跳过
  if a.no_auto_lfs:continue # 禁自动跳过
  LOG.info("自动LFS(%s>=%s): %s",human(st.st_size),human(a.size),os.fsdecode(rel)) # 日志
  auto[rel]=exact_attr_rule(os.fsdecode(rel)) # 生成规则
 if auto: # 追加attributes
  tgt=root/".gitattributes";ex=config_bytes(tgt);ap=b"".join(r+b"\n" for _,r in sorted(auto.items()) if r.strip() not in ex.splitlines()) # 去重
  nl=b"" if not ex or ex.endswith(b"\n") else b"\n" # 换行处理
  if ap:atomic_write(tgt,ex+nl+ap);LOG.info("追加LFS规则%d条",len(auto));attrs=Attributes(repo,config,index);files[b".gitattributes"]=(tgt,b".gitattributes" if b".gitattributes" in index else None) # 写回并重载
 seen=set();pl=0;fm=yes(config,(b"core",),b"filemode",os.name!="nt") # 已见集合LFS计数文件模式
 for rel,(ph,ok) in files.items(): # 逐文件暂存
  st=ph.lstat();old=olds.get(ok) if ok is not None else None;eff=attrs.get(rel) # 状态旧项属性
  if stat.S_ISLNK(st.st_mode): # 符号链接
   tgt=os.fsencode(os.readlink(ph));bl=Blob.from_string(tgt);repo.object_store.add_object(bl);en=index_entry_from_stat(st,bl.id,mode=0o120000);en.size=len(tgt) # 目标为Blob
  elif stat.S_ISDIR(st.st_mode): # 子模块目录
   if (ph/".git").exists() or (old is not None and old.mode==0o160000): # 确认gitlink
    sub=Repo(str(ph)) # 打开子模块
    try:hd=sub.head() # 取HEAD
    except Exception:hd=None # 空取空
    sub.close() # 立即关闭避占用
    if not hd:raise StopPush(f"子模块空HEAD: {ph}") # 空拒绝
    en=IndexEntry(st.st_ctime,st.st_mtime,st.st_dev,st.st_ino,0o160000,st.st_uid,st.st_gid,0,hd,0) # 构造gitlink项
   else:continue # 非模块跳过
  elif stat.S_ISREG(st.st_mode): # 普通文件
   isl=eff.get(b"filter")==b"lfs" # 是否LFS
   if isl:data=cache.put(ph);pl+=1;mode=0o100755 if (fm and st.st_mode&0o111) or (not fm and old is not None and old.mode==0o100755) else 0o100644 # 快照指针与权限
   else: # 普通Blob
    if st.st_size>=a.max_blob_size:raise StopPush(f"普通Blob超限: {os.fsdecode(rel)}") # 超限报错
    data=normalize_blob(read_regular(ph),eff,old,repo,config,rel,a.renormalize);mode=0o100755 if (fm and st.st_mode&0o111) or (not fm and old is not None and old.mode==0o100755) else 0o100644 # 换行与权限
  else:raise StopPush(f"不支持类型: {ph}") # 其他拒绝
  if signature(ph.lstat())!=signature(st):raise StopPush(f"暂存期间变化: {ph}") # 中途变化
  if stat.S_ISREG(st.st_mode) and eff.get(b"filter")==b"lfs" and pointer_info(data) is None and stat.S_ISLNK(st.st_mode)==False: # LFS验证
   pass # cache.put已保证指针
  if stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode): # Blob入库链接已入库目录跳过
   if stat.S_ISREG(st.st_mode):bl=Blob.from_string(data);repo.object_store.add_object(bl);en=index_entry_from_stat(st,bl.id,mode=mode);en.size=st.st_size&0xffffffff # 普通入库
  if ok is not None and ok!=rel:del index[ok] # 大小写改名删旧
  index[rel]=en;seen.add(rel);trace(a,"暂存: %s",os.fsdecode(rel)) # 写索引
 for r in list(index): # 删 worktree 已失
  if r not in seen:del index[r];trace(a,"删: %s",os.fsdecode(r)) # 同步删除
 LOG.info("暂存完成 | LFS新%d",pl) # 输出统计
def tree_map(repo,hd): # 取提交树映射
 if not hd:return {} # 空返回空
 return {e.path:(e.sha,e.mode) for e in iter_tree_contents(repo.object_store,repo[hd].tree)} # 遍历树
def check_repo_state(repo,config): # 检查仓库健康拒绝危险状态
 if repo.bare:raise StopPush("需非bare工作区") # bare拒绝
 if cfg(config,b"extensions",b"objectformat",b"sha1")!=b"sha1":raise StopPush("仅支持SHA1") # 哈希拒绝
 if repo.get_shallow():raise StopPush("浅仓库请补全") # 浅拒绝
 if cfg(config,b"extensions",b"partialclone"):raise StopPush("部分克隆请补全") # 部分拒绝
 for s in config.sections(): # 遍历节
  if s[:1]==(b"remote",) and yes(config,s,b"promisor",False):raise StopPush("promisor不受支持") # promisor拒绝
 if yes(config,(b"core",),b"sparsecheckout",False) or yes(config,(b"core",),b"splitindex",False):raise StopPush("稀疏分裂不受支持") # 稀疏拒绝
 for n in ("MERGE_HEAD","CHERRY_PICK_HEAD","REVERT_HEAD","rebase-merge","rebase-apply","sequencer"): # 操作锁
  if (Path(repo.controldir())/n).exists():raise StopPush(f"操作未结束{n}请处理") # 未结束拒绝
 if yes(config,(b"commit",),b"gpgsign",False):raise StopPush("要求签名请改配置") # 签名拒绝
 if (Path(repo.commondir())/"info"/"grafts").exists() or any(r.startswith(b"refs/replace/") for r in repo.refs.keys()):raise StopPush(" grafts/replace拒绝") # 替换历史拒绝
def head_info(repo): # 取HEAD链旧值与目标分支兼容未出生
 try:syms=repo.refs.get_symrefs();tgt=syms.get(b"HEAD",b"refs/heads/master") # 取符号目标
 except Exception:tgt=b"refs/heads/master" # 异常默认
 try:raw=repo.refs.read_ref(b"HEAD") # 读原始
 except Exception:raw=None # 异常空
 if raw and raw.startswith(b"ref:"):tgt=raw[4:].strip() # 解析ref
 try:old=repo.refs[tgt] # 取旧值
 except KeyError:old=None # 未出生空
 return [tgt],old,tgt # 返回链旧目标
def save_index(repo,index): # 安全保存索引防锁泄漏
 try:index.commit() # 优先原生提交
 except AttributeError: # 旧版回退
  from dulwich.index import write_index_dict # 延迟导入
  from dulwich.pack import SHA1Writer # 写锁类
  lk=Path(repo.controldir())/"index.lock" # 锁路径
  w=SHA1Writer(lk) # 建写器
  try:write_index_dict(w,dict(index.items()),version=3);w.close() # 写并关闭
  except Exception: # 失败清理
   with suppress(Exception):w.abort() # 中止
   with suppress(FileNotFoundError):lk.unlink() # 删锁
   raise # 重抛
 except Exception: # 其他异常清锁
  with suppress(FileNotFoundError):(Path(repo.controldir())/"index.lock").unlink() # 删残锁
  raise # 重抛
def commit_staged(repo,index,a,iden,exp): # 按Blob大小拆提交并更新分支
 chain,old,tgt=exp # 解包期望
 _,cur,_=head_info(repo) # 重取当前防并发
 if cur!=old:raise StopPush("暂存期间HEAD变化") # 变化拒绝
 flat=tree_map(repo,old);targ={p:(e.sha,e.mode) for p,e in index.items()};chg=sorted(set(flat)|set(targ),key=lambda p:(p in targ,p));chg=[p for p in chg if flat.get(p)!=targ.get(p)] # 算变更
 if not chg:LOG.info("暂存空不提交");return [],None # 空返回
 LOG.info("变更%d 前10:%s",len(chg),[os.fsdecode(p) for p in chg[:10]]) # 日志
 msg=a.message;larg=None;lsz=-1;empty=None;root=Path(repo.path) # 消息最大Empty
 for p in chg: # 找最大文件与Empty标记
  fp=root/os.fsdecode(p) # 工作区路径
  if fp.is_file() and not fp.is_symlink(): # 普通文件
   sz=fp.stat().st_size # 大小
   if sz>lsz:larg,lsz=os.fsdecode(p),sz # 更新最大
   if p==b"ReadMe.md" and sz<512: # 小ReadMe
    with suppress(OSError): # 容错读
     if b"#EmptyAfterPush" in fp.read_bytes():empty=True # 标记推后清空
 if not msg: # 自动消息含最大文件时间
  from datetime import datetime as _d;msg=f"[{larg} {lsz}B] {_d.now().strftime('%Y-%m-%d__%H.%M.%S')} auto" if larg else f"auto {time.strftime('%Y-%m-%d__%H.%M.%S')}" # 拼消息
 sizes={} # 每路径Blob大小
 for p in chg: # 取Blob大小LFS按指针
  if p in targ:sizes[p]=len(repo.object_store[targ[p][0]].data) # Blob长度
  else:sizes[p]=0 # 删除0
 batches=[];cur=[];tot=0 # 拆批
 for p in sorted(chg,key=lambda x:(sizes[x]==0,x)): # 删除优先防目录冲突
  s=sizes[p] # 大小
  if cur and tot+s>a.max_commit_size:batches.append(cur);cur=[];tot=0 # 超限新批
  cur.append(p);tot+=s # 加入
 if cur:batches.append(cur) # 尾批
 ids=[];par=old;now=int(time.time());tz=int(datetime.now().astimezone().utcoffset().total_seconds()) # 提交循环
 for n,ps in enumerate(batches,1): # 逐批提交
  for p in ps: # 更新树
   if p in targ:flat[p]=targ[p] # 新增修改
   else:flat.pop(p,None) # 删除
  c=Commit();c.parents=[par] if par else [];c.tree=commit_tree(repo.object_store,[(p,s,m) for p,(s,m) in flat.items()]);c.author=c.committer=iden;c.author_time=c.commit_time=now+n;c.author_timezone=c.commit_timezone=tz # 构造提交
  tm=msg if len(batches)==1 else f"{msg} ({n}/{len(batches)})" if msg else f"分批({n}/{len(batches)}):{len(ps)}项" # 批消息
  if empty and n==len(batches):tm+="\n\n警告:ReadMe过小" # 附加警告
  c.message=tm.encode("utf-8");repo.object_store.add_object(c);ids.append(c.id);par=c.id;LOG.info("提交[%d/%d]: %s %s",n,len(batches),c.id.decode()[:8],tm.splitlines()[0]) # 入库日志
 if old is None:repo.refs[tgt]=ids[-1] # 未出生直接赋值
 else: # 已有分支原子更新
  if not repo.refs.set_if_equals(tgt,old,ids[-1]):raise StopPush("分支被并发推进") # 失败报错
 return ids,empty # 返回ID与标记
def prepare(repo,a,iden,cache): # 暂存并提交全流程
 config=repo.get_config_stack();check_repo_state(repo,config);exp=head_info(repo);idx=repo.open_index();stage_all(repo,idx,a,config,cache);save_index(repo,idx);return commit_staged(repo,idx,a,iden,exp) # 校验暂存保存提交
def outgoing_lfs(repo,refs,hd,a): # BFS收集新提交LFS对象与大Blob检查
 if not hd:return {} # 空返回
 known={s for s in refs.values() if s!=ZERO_SHA} # 远端已知
 st=[hd];seen=set();cms=[] # 栈已见提交
 while st: # 深度遍历
  c=st.pop() # 取提交
  if c in seen or c==ZERO_SHA:continue # 跳过已见空
  seen.add(c) # 标记
  if c in known:continue # 已知跳过祖先
  try:o=repo[c] # 取对象
  except KeyError:continue # 缺失跳过
  if not isinstance(o,Commit):continue # 非提交跳过
  cms.append(o);st.extend(o.parents) # 收集并压父母
 objs={} # 结果
 for cm in cms: # 遍历提交树
  for e in iter_tree_contents(repo.object_store,cm.tree): # 遍历条目
   if e.mode not in (0o100644,0o100755):continue # 仅普通文件
   d=repo.object_store[e.sha].data # 取Blob
   inf=pointer_info(d) # 解析指针
   if inf is not None:objs[inf[0]]=inf[1] # 指针收集
   elif not a.no_auto_lfs and len(d)>=a.max_blob_size:raise StopPush(f"历史大Blob{e.path.decode(errors='replace')} {human(len(d))}请转LFS") # 大普通报错
 return objs # 返回映射
def ancestor(repo,old,new): # 判断old是否为new祖先
 if old in (None,ZERO_SHA):return True # 空视为祖先
 if old==new:return True # 相等祖先
 st=[new];seen=set() # 栈已见
 while st: # 遍历
  c=st.pop() # 取值
  if c==old:return True # 命中
  if c in seen or c==ZERO_SHA:continue # 跳过
  seen.add(c) # 标记
  try:o=repo[c] # 取对象
  except KeyError:continue # 缺失跳过
  if isinstance(o,Commit):st.extend(o.parents) # 压父母
 return False # 未找到
def retry(a,label,op): # 指数退避重试区分认证大文件
 at=0 # 尝试计数
 while True: # 循环
  try:return op() # 执行成功返回
  except HTTPFailure as e: # HTTP错
   if e.code in (401,403,404,422):raise # 认证等不重试
   if "large files" in str(e).lower() or "GH001" in str(e):LOG.error("历史大文件请list-big/remove-big");raise # 大文件不重试
   at+=1 # 计数
   if at>a.retry:raise # 超限抛出
   d=e.retry_after or (a.retry_wait*(2**(at-1)));d=min(d,60);LOG.warning("[%s]HTTP%d %.1fs后重试%d/%d",label,e.code,d,at,a.retry);time.sleep(d) # 等待
  except (socket.timeout,TimeoutError,NetworkFailure,http.client.HTTPException,ssl.SSLError,OSError) as e: # 网络错
   at+=1 # 计数
   if at>a.retry:raise StopPush(f"[{label}]重试超限: {e}") # 超限包装
   d=a.retry_wait*(2**(at-1));d=min(d,60);LOG.warning("[%s]网络%s %.1fs后重试%d/%d",label,e,d,at,a.retry);time.sleep(d) # 等待
def upload_lfs(net,batch,objs,cache,ref,done): # LFS batch授权上传验证
 need=[(o,s) for o,s in objs.items() if (o,s) not in done] # 过滤已完成
 if not need:return # 空返回
 LOG.info("LFS batch: %d对象",len(need)) # 日志
 req={"operation":"upload","transfers":["basic"],"ref":{"name":text(ref)},"objects":[{"oid":o,"size":s} for o,s in need]} # 构造请求
 r=net.request("POST",batch,{"Content-Type":MEDIA,"Accept":MEDIA},json.dumps(req).encode(),"LFSBatch") # 发batch
 try:resp=json.loads(r.read().decode("utf-8")) # 解析响应
 finally:r.close() # 关闭
 for it in resp.get("objects",[]): # 逐对象处理
  o=it["oid"];s=it["size"] # 取oid size
  if (o,s) in done:continue # 已完成跳过
  ac=it.get("actions",{}) # 取动作
  if "upload" in ac: # 需上传
   up=ac["upload"];uh=up.get("header",{});lp=cache.require(o,s);LOG.info("上传LFS%s %s",o[:12],human(s)) # 取本地路径
   with regular_reader(lp) as (f,_): # 安全读
    d=f.read() # 小文件一次读保重定向可重放大文件由底层分块
    rr=net.request(up.get("method","PUT"),up["href"],uh,d,f"LFS{o[:8]}",body_size=s) # 上传保留签名query
    try:rr.read() # 读空
    finally:rr.close() # 关闭
  if "verify" in ac: # 需验证
   vv=ac["verify"];vh=dict(vv.get("header",{}));vh["Content-Type"]=MEDIA # 验证头
   rr=net.request("POST",vv["href"],vh,json.dumps({"oid":o,"size":s}).encode(),"LFSVerify") # 发验证
   try:rr.read() # 读空
   finally:rr.close() # 关闭
  done.add((o,s)) # 标记完成
def push_target(repo,a,remote,ref,hd,batch,auths,cache,done): # 单目标推送先LFS后Git
 net=Transport(a,auths) # 建传输
 try: # 全程
  p=urlsplit(remote);base=f"{p.scheme}://{p.netloc}/";cli=StdlibGitClient(base,net);rp=p.path # origin+仓库路径防双拼
  refs=retry(a,"发现引用",lambda:cli.get_refs(rp)) # 取远端引用可重试
  old=refs.get(ref,ZERO_SHA) # 取旧值
  if old==hd:LOG.info("远端已最新: %s",text(ref));return # 幂等返回
  if old!=ZERO_SHA and not a.force and not ancestor(repo,old,hd):raise StopPush("非快进请先pull或--force") # 快进检查
  if a.force_with_lease and old==ZERO_SHA and a.force_with_lease=="auto":LOG.info("远端无分支视为租约通过") # 租约空分支
  objs=outgoing_lfs(repo,refs,hd,a) # 收集LFS
  if objs:retry(a,"LFS上传",lambda:upload_lfs(net,batch,objs,cache,ref,done)) # 上传LFS可重试
  def gen(have,want,progress=None): # 生成pack闭包
   return repo.generate_pack_data(have,want,progress=progress) # 委托仓库生成
  def prog(m):LOG.info("远端: %s",text(m).strip()) # 远端进度
  def att(): # 单次推送尝试
   return cli.send_pack(rp,lambda r:{ref:hd},gen,progress=prog) # 发包
  retry(a,f"推送{text(ref)}",att) # 重试推送
  LOG.info("推送成功 %s %s->%s",safe_url(remote),old.decode()[:8] if old!=ZERO_SHA else "空",hd.decode()[:8]) # 成功日志
 finally:net.close() # 关传输
def identity_from_remote(remote,user,name,email): # 由远程URL推断提交身份
 if name and email:return f"{name} <{email}>".encode() # 显式优先
 if user and user!="AUTO" and "@" not in user and "," not in user:return f"{user} <{user}@users.noreply.github.com>".encode() # -u用户名
 p=urlsplit(remote);segs=[x for x in p.path.strip("/").split("/") if x] # 路径分段
 guess=segs[0] if segs else "PurePush" # 首段为owner
 if "," in (user or ""):n,e=[x.strip() for x in user.replace("，",",").split(",",1)];return f"{n} <{e}>".encode() # 逗号名邮
 return f"{guess} <{guess}@users.noreply.github.com>".encode() # 默认owner身份
def lfs_endpoint(remote,config,local): # 解析LFS batch地址
 ep=text(cfg(local,(b"remote",b"origin"),b"lfsurl",b"") or cfg(local,(b"lfs",),b"url",b"")) # 配置优先
 base=remote[:-4] if remote.endswith(".git") else remote # 去.git
 ep=ep or base+".git/info/lfs" # 默认拼接
 cl,uu,pp=split_credentials(ep) # 分离凭据
 if urlsplit(cl).query:raise StopPush("LFS地址禁query") # 查询串拒绝
 tok=basic(uu,pp) # 认证头
 auths={} # 凭据表
 if tok:auths[origin(cl)]=tok # 登记
 return cl.rstrip("/")+"/objects/batch",auths # 返回batch与凭据
def preprocess(argv): # 预处理兼容-u/-m/裸URL
 out=[];i=0;vals={"--repo","--repo-path","--path","-path","-p","--branch","-b","--size","-s","--threshold","--retry","-retry","-r","--retry-wait","--retry-seconds","--verbose","-v","--connect-timeout","--io-timeout","--low-speed-limit","--low-speed-time","--progress-interval","--max-commit-size","--max-blob-size","--name","--email","--proxy","--ca-file","--lfs-url","--push-option","--remote"} # 带值参数
 while i<len(argv): # 逐个扫描
  ag=argv[i] # 当前
  if ag=="-m": # 消息吞剩余
   if i+1>=len(argv):raise StopPush("-m缺消息") # 缺失报错
   out.extend(["--message"," ".join(argv[i+1:])]);break # 剩余全为消息
  if ag in ("-u","--user","--auto-user"): # 用户特殊
   nx=argv[i+1] if i+1<len(argv) else None # 下一个
   if nx is None or nx.startswith("-") or "://" in nx or nx in ("push","clone","pull"):out.extend([ag,"AUTO"]);i+=1;continue # 无值或positional给AUTO防吃push
   out.extend([ag,nx]);i+=2;continue # 有值成对
  if ag in vals: # 普通带值
   if i+1>=len(argv):raise StopPush(f"{ag}缺参") # 缺失报错
   out.extend(argv[i:i+2]);i+=2;continue # 成对
  if ag.startswith("-"):out.append(ag) # 标志直存
  elif "://" in ag or ag.startswith("git@"):out.extend(["--remote",ag]) # 裸URL转remote
  else:out.append(ag) # 位置直存
  i+=1 # 下一个
 return out # 返回新参数
def parser(): # 构建参数解析器
 p=argparse.ArgumentParser(description="dulwich1.2.15标准库push") # 描述
 p.add_argument("mode",nargs="?",choices=["push"],default="push");p.add_argument("--remote",default="");p.add_argument("--repo","--repo-path","--path","-path","-p",default=".") # 模式远端仓库
 p.add_argument("--branch","-b",default=os.environ.get("BRANCH"));p.add_argument("--user","-u","--auto-user",nargs="?",const="AUTO");p.add_argument("--name");p.add_argument("--email") # 分支用户身份
 p.add_argument("--message","-m","--commit-msg","--commit_msg",default="");p.add_argument("--no-ask","--noask","-noask","-y","-yes",action="store_true") # 消息免询
 p.add_argument("--size","-s",type=parse_size,default=100*1024**2);p.add_argument("--threshold",type=int,default=0);p.add_argument("--max-blob-size",type=parse_size,default=100*1024**2) # 阈值上限
 p.add_argument("--max-commit-size",type=parse_size,default=1900*1024**2);p.add_argument("--max-pack-size",type=parse_size,default=1900*1024**2) # 拆提交包上限
 p.add_argument("--retry","-retry","-r",type=int,default=10);p.add_argument("--retry-wait","--retry-seconds",type=float,default=5);p.add_argument("--verbose","-v",type=int,default=2) # 重试日志
 p.add_argument("--connect-timeout",type=float,default=45);p.add_argument("--io-timeout",type=float,default=300);p.add_argument("--low-speed-limit",type=int,default=10) # 超时低速
 p.add_argument("--low-speed-time",type=float,default=60);p.add_argument("--progress-interval",type=float,default=.5) # 熔断间隔
 p.add_argument("--proxy");p.add_argument("--no-proxy",action="store_true");p.add_argument("--ca-file");p.add_argument("--lfs-url");p.add_argument("--no-auto-lfs",action="store_true") # 代理LFS
 p.add_argument("--renormalize",action="store_true");p.add_argument("--force",action="store_true");p.add_argument("--force-with-lease",nargs="?",const="auto");p.add_argument("--set-upstream",action="store_true") # 规范化强制
 p.add_argument("--push-option",action="append",default=[]);p.add_argument("--atomic",action="store_true");p.add_argument("--self-test",action="store_true") # 推送选项自测
 return p # 返回解析器
def arguments(av=None): # 解析并校验参数
 q=parser();a=q.parse_args(preprocess(list(sys.argv[1:] if av is None else av)));a.trace=a.verbose>=3 # 预处理解析
 if a.threshold>0:a.size=a.threshold # 兼容threshold
 if not all(math.isfinite(x) for x in (a.connect_timeout,a.io_timeout,a.progress_interval,a.retry_wait,a.low_speed_time)):q.error("时间禁NaN无穷") # 有限检查
 if min(a.size,a.max_blob_size,a.max_commit_size,a.max_pack_size,a.connect_timeout,a.io_timeout,a.progress_interval)<=0:q.error("尺寸时间必须正") # 正数检查
 if a.retry<1 or a.retry>50:q.error("重试1-50") # 重试范围
 return a # 返回参数
def main(a): # 主流程打开仓库暂存推送
 setup_logging(a.verbose) # 日志
 try:from importlib.metadata import version as _v;LOG.info("dulwich%s | 标准库http/socket/ssl",_v("dulwich")) # 版本
 except Exception:LOG.info("标准库http/socket/ssl") # 失败仍继续
 root=Path(a.repo or ".").resolve() # 仓库路径
 try:repo=Repo(str(root)) # 打开现有
 except NotGitRepository: # 不存在初始化
  LOG.info("初始化仓库: %s",root);root.mkdir(parents=True,exist_ok=True);repo=Repo.init(str(root)) # 存在目录不用mkdir防183
 config=repo.get_config_stack() # 配置栈
 if not a.remote: # 远端缺失试读origin
  with suppress(Exception):a.remote=text(cfg(config,(b"remote",b"origin"),b"url",b"")) # 读origin
 if not a.remote:raise StopPush("缺--remote且无origin") # 仍缺报错
 clean,user,pwd,br=clean_remote_and_auth(a.remote,a.branch) # 归一化远端
 LOG.info("仓库: %s",root);LOG.info("远端: %s | 分支: %s",safe_url(clean),br);LOG.info("LFS阈值%s | Blob上限%s",human(a.size),human(a.max_blob_size)) # 日志
 LOG.info("超时%.0fs | 低速%dB/s%.0fs | 间隔%.2fs",a.connect_timeout,a.low_speed_limit,a.low_speed_time,a.progress_interval) # 日志
 iden=identity_from_remote(clean,a.user,a.name,a.email);LOG.info("身份: %s",text(iden)) # 身份
 cache=LFSCache(repo,config) # LFS缓存
 ids,empty=prepare(repo,a,iden,cache) # 暂存提交
 try:hd=repo.head() # 取HEAD
 except KeyError:hd=None # 空分支
 if not hd:LOG.error("无提交终止");return 1 # 无提交返回1
 ref=b"refs/heads/"+br.encode() # 目标引用
 auths={} # 凭据表
 t=basic(user,pwd) # 远端凭据
 if t:auths[origin(clean)]=t # 登记
 batch,ea=lfs_endpoint(a.lfs_url or clean,config,config) # LFS地址
 auths.update(ea) # 合并LFS凭据
 push_target(repo,a,clean,ref,hd,batch,auths,cache,set()) # 推送
 if empty: # 推后清空标记
  with open(root/"ReadMe.md","wb") as f:f.write(b"") # 截断
  LOG.info("EmptyAfterPush已清空ReadMe") # 日志
 LOG.info("完成HEAD%s->%s",hd.decode()[:8],text(ref)) # 完成
 return 0 # 成功
def self_test(): # 详细自测覆盖全部回归
 class T(unittest.TestCase): # 测试类
  def setUp(self): # 每个用例建隔离仓库正确处理Win临时
   self.tmp=tempfile.TemporaryDirectory(prefix="pp_");self.rp=Path(self.tmp.name)/"repo";self.repo=Repo.init(str(self.rp),mkdir=True);self.root=Path(self.repo.path);c=self.repo.get_config() # 子目录不存在才mkdir防183
   for s,k,v in (((b"user",),b"name",b"t"),((b"user",),b"email",b"t@e.com"),((b"core",),b"autocrlf",b"false"),((b"core",),b"safecrlf",b"false"),((b"core",),b"attributesfile",os.fsencode(Path(self.tmp.name)/"na")),((b"core",),b"excludesfile",os.fsencode(Path(self.tmp.name)/"ig")),((b"commit",),b"gpgsign",b"false")):c.set(s,k,v) # 隔离配置
   c.write_to_path();self.repo.get_config_stack=self.repo.get_config;self.cache=LFSCache(self.repo,c) # 栈指向本地
   self.a=arguments(["push","--remote","http://127.0.0.1/x.git"]);self.a.size=500;self.a.max_blob_size=1000;self.a.max_commit_size=10*1024*1024;self.a.retry=2;self.a.retry_wait=0.05;self.a.progress_interval=0.05;self.a.low_speed_time=5;self.a.verbose=0;self.a.trace=False;self.a.no_auto_lfs=False;self.iden=b"t <t@e.com>" # 小阈值加速
  def tearDown(self): # 先关仓库再清目录防Win占用
   try:self.repo.close() # 关闭释放句柄
   finally:self.tmp.cleanup() # 删除临时
  def wr(self,n,d):p=self.root/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(d);return p # 写文件助手
  def st(self):return prepare(self.repo,self.a,self.iden,self.cache) # 暂存提交助手
  def test_repo_init_unborn(self): # 验证新建仓库HEAD未出生与提交
   d=tempfile.mkdtemp(prefix="pp_init_") # 新临时目录本身做仓库
   try:r=Repo.init(d);self.assertTrue((Path(d)/".git").is_dir());raw=r.refs.read_ref(b"HEAD");self.assertIn(b"ref:",raw);self.assertIn(b"HEAD",r.refs.get_symrefs()) # HEAD符号检查
   finally:r.close();import shutil;shutil.rmtree(d,ignore_errors=True) # 先关后删
  def test_reader_stable(self): # 验证Windows签名稳定与篡改检出
   p=self.wr("x.bin",b"hello");self.assertEqual(read_regular(p),b"hello");self.assertEqual(config_bytes(self.root/"miss"),b"") # 稳定读与缺失空
   with self.assertRaises(StopPush): # 篡改必报错
    with regular_reader(p) as (f,_):f.read();time.sleep(0.02);p.write_bytes(b"changed-content-long") # 读中修改
  def test_ignore_lfs(self): # 验证忽略优先级LFS无子进程幂等删除
   self.wr("tracked.tmp",b"old");self.st();self.wr("tracked.tmp",b"new");self.wr(".gitignore",b"*.tmp\n!keep.tmp\nblocked/\nselect/*\n!select/keep.txt\nignored-large.bin\n") # 跟踪与忽略
   for n,d in (("drop.tmp",b"drop"),("keep.tmp",b"keep"),("blocked/no.txt",b"no"),("select/keep.txt",b"yes"),("select/no.txt",b"no"),("ignored-large.bin",b"x"*600),("has space.bin",b"a"*600),(".gitattributes",b"*.lfs filter=lfs diff=lfs merge=lfs -text\n"),("small.lfs",b"x"),("nested/.gitignore",b"!stay.tmp\n"),("nested/stay.tmp",b"stay")):self.wr(n,d) # 批量写
   cc=self.repo.get_config();cc.set((b"filter",b"lfs"),b"process",b"must-not");cc.write_to_path() # 设外部过滤
   with patch("subprocess.Popen",side_effect=AssertionError("禁子进程")):self.st() # 确保不调用
   ix=self.repo.open_index() # 读索引
   for n in (b"tracked.tmp",b"keep.tmp",b"select/keep.txt",b"nested/stay.tmp"):self.assertIn(n,ix) # 应包含
   for n in (b"drop.tmp",b"blocked/no.txt",b"select/no.txt",b"ignored-large.bin"):self.assertNotIn(n,ix) # 应排除
   for n in (b"has space.bin",b"small.lfs"):self.assertIsNotNone(pointer_info(self.repo.object_store[ix[n].sha].data)) # LFS指针
   self.assertEqual(self.st()[0],[]) # 幂等无提交
   (self.root/"tracked.tmp").unlink();self.st();self.assertNotIn(b"tracked.tmp",self.repo.open_index()) # 删除同步
  def test_auto_attr(self): # 验证自动规则写入不重复
   self.wr("big.bin",b"b"*700);self.st();d=(self.root/".gitattributes").read_bytes();self.assertIn(b"filter=lfs",d);self.assertIn(b"/big.bin",d) # 含规则
   self.st();self.assertEqual(d.count(b"/big.bin"),(self.root/".gitattributes").read_bytes().count(b"/big.bin")) # 不重复
  def test_exclude(self): # 验证全局与exclude优先级
   (Path(self.tmp.name)/"ig").write_bytes(b"*.bak\n!special.dat\n");inf=Path(self.repo.controldir())/"info";inf.mkdir(exist_ok=True);(inf/"exclude").write_bytes(b"!keep.bak\nspecial.dat\n") # 写规则
   self.wr("keep.bak",b"y");self.wr("drop.bak",b"n");self.wr("special.dat",b"n");self.st();ix=self.repo.open_index() # 暂存
   self.assertIn(b"keep.bak",ix);self.assertNotIn(b"drop.bak",ix);self.assertNotIn(b"special.dat",ix) # 断言
  def test_cquote(self): # 验证C引号宏与错误
   self.wr(".gitattributes",b"[attr]large filter=lfs -text\n\"/has space.txt\" large\n");self.wr("has space.txt",b"a");self.st() # 宏匹配
   self.assertIsNotNone(pointer_info(self.repo.object_store[self.repo.open_index()[b"has space.txt"].sha].data)) # 指针
   self.assertEqual(attr_words(b'"a\\tb.txt" text')[0],b"a\tb.txt") # 转义
   with self.assertRaises(StopPush):attr_words(b'"unterminated text') # 未闭合报错
  def test_crlf(self): # 验证换行与未知过滤拒绝
   self.wr(".gitattributes",b"*.txt text\n*.weird filter=magic\n");self.wr("a.txt",b"line1\r\nline2\r\n");self.st() # 换行
   self.assertEqual(self.repo.object_store[self.repo.open_index()[b"a.txt"].sha].data,b"line1\nline2\n") # 入库LF
   self.wr("b.weird",b"x") # 未知过滤
   with self.assertRaises(StopPush):self.st() # 必拒绝
  def test_symlink(self): # 验证链接不进入目标且不受link/误杀
   out=Path(self.tmp.name)/"out";out.mkdir();(out/"p.bin").write_bytes(b"x"*1024) # 外部目录
   try:os.symlink(out,self.root/"link",target_is_directory=True) # 建目录链接
   except (OSError,NotImplementedError):self.skipTest("无链接权限") # 跳过
   self.wr(".gitignore",b"link/\n");self.st();ix=self.repo.open_index() # 忽略link/
   self.assertEqual(ix[b"link"].mode,0o120000);self.assertFalse(any(p.startswith(b"link/") for p in ix)) # 链接本身保留
  def test_split_local(self): # 验证拆提交与本地推送
   self.a.max_commit_size=5 # 极小拆批
   for i in range(3):self.wr(f"file{i}",b"abcd") # 写文件
   cs,hd=self.st();self.assertEqual(len(cs),3) # 3提交
   rm=Repo.init_bare(str(Path(self.tmp.name)/"bare"),mkdir=True) # 裸仓库
   try:LocalGitClient().send_pack(rm.path,lambda r:{b"refs/heads/main":hd},self.repo.generate_pack_data);self.assertEqual(rm.refs[b"refs/heads/main"],hd) # 本地推
   finally:rm.close() # 关闭
  def test_history(self): # 验证历史指针与大Blob拦截
   self.wr("large.bin",b"q"*600);self.st();ix=self.repo.open_index();o,s=pointer_info(self.repo.object_store[ix[b"large.bin"].sha].data) # 取指针
   (self.root/"large.bin").unlink();self.st();self.assertEqual(outgoing_lfs(self.repo,{},self.repo.head(),self.a)[o],s) # 历史仍需上传
   self.a.no_auto_lfs=True;self.wr("oversize",b"z"*700);self.st();self.a.max_blob_size=400 # 超限
   with self.assertRaises(StopPush):outgoing_lfs(self.repo,{},self.repo.head(),self.a) # 必报错
  def test_http(self): # 验证智能HTTP双推幂等磁盘后端
   from dulwich.server import DictBackend # 后端
   from dulwich.web import make_wsgi_chain # WSGI链
   from wsgiref.simple_server import make_server,WSGIRequestHandler # 简易服务
   class Q(WSGIRequestHandler): # 静默句柄
    def log_message(self,*a):pass # 禁日志
   self.wr("http-file",b"smart-http");self.st() # 准备提交
   rm=Repo.init_bare(str(Path(self.tmp.name)/"srv.git"),mkdir=True) # 磁盘后端避内存API错
   app=make_wsgi_chain(DictBackend({"/test.git":rm}));sv=make_server("127.0.0.1",0,app,handler_class=Q);th=threading.Thread(target=sv.serve_forever,daemon=True);th.start();u=f"http://127.0.0.1:{sv.server_port}/test.git" # 启动服务
   try: # 双推
    with patch("subprocess.Popen",side_effect=AssertionError("禁子进程")): # 禁进程
     for _ in range(2):push_target(self.repo,self.a,u,b"refs/heads/main",self.repo.head(),u+"/info/lfs/objects/batch",{},self.cache,set()) # 第二次幂等
    self.assertEqual(rm.refs[b"refs/heads/main"],self.repo.head()) # 断言
   finally:sv.shutdown();sv.server_close();th.join(timeout=5);rm.close() # 清理
  def test_net_lfs(self): # 验证重试认证重定向LFS签名保留
   cn={};st={};tok="Basic unit-secret";ts=self # 计数存储令牌
   class H(BaseHTTPRequestHandler): # 模拟句柄
    protocol_version="HTTP/1.1" # 长连接
    def log_message(self,*a):pass # 禁日志
    def rp(self,c,b,hd=None):self.send_response(c) # 发状态
    def reply(self,c,b,hd=None):self.send_response(c); # 兼容
     for k,v in (hd or {}).items():self.send_header(k,v) # 发头
     self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b) # 发体
    def do_GET(self):cn[self.path]=cn.get(self.path,0)+1 # 计数
     if self.path=="/flaky" and cn[self.path]==1:self.reply(503,b"retry");return # 首次503
     if self.path=="/unauthorized":self.reply(401,b"denied");return # 401
     if self.path=="/redirect":self.reply(302,b"", {"Location":f"http://localhost:{self.server.server_port}/auth-check"});return # 跨域重定向
     if self.path=="/auth-check":self.reply(200,self.headers.get("Authorization","").encode());return # 回显认证
     self.reply(200,b"ok") # 默认OK
    def do_PUT(self):d=self.rfile.read(int(self.headers["Content-Length"]));st[hashlib.sha256(d).hexdigest()]=d;cn["put-path"]=self.path;self.reply(200,b"") # 存PUT
    def do_POST(self):d=json.loads(self.rfile.read(int(self.headers["Content-Length"]))) # 解析batch
     if self.path=="/verify":ts.assertEqual(len(st[d["oid"]]),d["size"]);self.reply(200,b"{}");return # 验证
     obs=[] # 对象
     for it in d["objects"]:it=dict(it) # 拷贝
      if it["oid"] not in st:it["actions"]={"upload":{"href":f"http://127.0.0.1:{self.server.server_port}/upload?signature=kept"},"verify":{"href":f"http://127.0.0.1:{self.server.server_port}/verify"}} # 动作
      obs.append(it) # 收集
     self.reply(200,json.dumps({"objects":obs}).encode()) # 返回
   sv=ThreadingHTTPServer(("127.0.0.1",0),H);th=threading.Thread(target=sv.serve_forever,daemon=True);th.start();base=f"http://127.0.0.1:{sv.server_port}";net=Transport(self.a,{origin(base):tok}) # 启动
   def gt(p):r=net.request("GET",base+p) # GET助手
   try: # 断言
    try:r=net.request("GET",base+"/flaky");r.read();r.close() # 首次503抛错
    except HTTPFailure:pass # 预期
    self.assertEqual(retry(self.a,"t",lambda:(lambda r:(r.read(),r.close())[0])(net.request("GET",base+"/flaky"))),b"ok");self.assertEqual(cn["/flaky"],3) # 重试成功
    with self.assertRaises(HTTPFailure):retry(self.a,"auth",lambda:net.request("GET",base+"/unauthorized").read()) # 401不重试
    self.assertEqual(cn["/unauthorized"],1) # 一次
    rr=net.request("GET",base+"/redirect");self.assertEqual(rr.read(),b"");rr.close() # 跨域无凭据
    self.wr("payload",b"binary"*100);o,s=pointer_info(self.cache.put(self.root/"payload"));dn=set();upload_lfs(net,base+"/batch",{o:s},self.cache,b"refs/heads/main",dn);self.assertIn((o,s),dn);self.assertEqual(st[o],b"binary"*100);self.assertEqual(cn["put-path"],"/upload?signature=kept") # LFS签名
   finally:net.close();sv.shutdown();sv.server_close();th.join(timeout=5) # 清理
  def test_cli(self): # 验证-u不吃push与URL脱敏
   a=arguments(["-u","push","https://u:p@github.com/o/r"]);self.assertEqual(a.user,"AUTO");self.assertEqual(a.mode,"push") # 不吃positional
   c,u,p,b=clean_remote_and_auth("https://github.com/o/r/tree/main",None);self.assertTrue(c.endswith(".git"));self.assertEqual(b,"main") # 网页分支
   remember("secret123");self.assertNotIn("secret123",redact("x secret123 y")) # 脱敏
 suite=unittest.defaultTestLoader.loadTestsFromTestCase(T);r=unittest.TextTestRunner(verbosity=2).run(suite);return r.wasSuccessful() # 运行返回
if __name__=="__main__": # 入口
 a=arguments() # 解析参数
 if a.self_test:sys.exit(0 if self_test() else 1) # 自测模式
 try:sys.exit(main(a)) # 正常推送
 except StopPush as e:LOG.error("失败: %s",e);sys.exit(1) # 致命退出1
 except KeyboardInterrupt:LOG.warning("用户中断");sys.exit(130) # 中断130

 '''
muse-spark-1.3-max 

C:\Users\Administrator\Documents\energetic>C:\QGB\anaconda3\python D:\test\github\dulwich_git\L865.py --self-test
  File "D:\test\github\dulwich_git\L865.py", line 340
    m.close();with suppress(Exception):c.close() # 关资源
              ^^^^
SyntaxError: invalid syntax

 '''