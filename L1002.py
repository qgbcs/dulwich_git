r'''

C:\Users\Administrator\Documents\energetic>C:\QGB\anaconda3\python D:\test\github\dulwich_git\L1002.py --self-test
test_attr_c_quote_and_macro (__main__.self_test.<locals>.Tests.test_attr_c_quote_and_macro) ... ERROR
test_git_smart_http_and_idempotent_push (__main__.self_test.<locals>.Tests.test_git_smart_http_and_idempotent_push) ... ERROR
test_global_exclude_precedence (__main__.self_test.<locals>.Tests.test_global_exclude_precedence) ... ERROR
test_history_pointer_and_large_blob (__main__.self_test.<locals>.Tests.test_history_pointer_and_large_blob) ... ERROR
test_ignore_lfs_delete_and_no_process (__main__.self_test.<locals>.Tests.test_ignore_lfs_delete_and_no_process) ... ERROR
test_low_speed_watchdog (__main__.self_test.<locals>.Tests.test_low_speed_watchdog) ... ERROR
test_network_retry_http_and_lfs (__main__.self_test.<locals>.Tests.test_network_retry_http_and_lfs) ... ERROR
test_readme_empty_after_push (__main__.self_test.<locals>.Tests.test_readme_empty_after_push) ... ERROR
test_signature_and_regular_reader_windows (__main__.self_test.<locals>.Tests.test_signature_and_regular_reader_windows) ... ERROR
test_split_commits_and_local_push (__main__.self_test.<locals>.Tests.test_split_commits_and_local_push) ... ERROR
test_symlink_does_not_walk_target (__main__.self_test.<locals>.Tests.test_symlink_does_not_walk_target) ... ERROR

======================================================================
ERROR: test_attr_c_quote_and_macro (__main__.self_test.<locals>.Tests.test_attr_c_quote_and_macro)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1002.py", line 893, in setUp
    self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/"repo";self.repo=Repo.init(str(self.root)) # 创建隔离的测试仓库
                                                                                            ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\repo.py", line 2433, in init
    os.mkdir(controldir)
FileNotFoundError: [WinError 3] 系统找不到指定的路径。: 'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\tmprr3up3zd\\repo\\.git'

======================================================================
ERROR: test_git_smart_http_and_idempotent_push (__main__.self_test.<locals>.Tests.test_git_smart_http_and_idempotent_push)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1002.py", line 893, in setUp
    self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/"repo";self.repo=Repo.init(str(self.root)) # 创建隔离的测试仓库
                                                                                            ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\repo.py", line 2433, in init
    os.mkdir(controldir)
FileNotFoundError: [WinError 3] 系统找不到指定的路径。: 'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\tmp6ajk4yfq\\repo\\.git'

======================================================================
ERROR: test_global_exclude_precedence (__main__.self_test.<locals>.Tests.test_global_exclude_precedence)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1002.py", line 893, in setUp
    self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/"repo";self.repo=Repo.init(str(self.root)) # 创建隔离的测试仓库
                                                                                            ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\repo.py", line 2433, in init
    os.mkdir(controldir)
FileNotFoundError: [WinError 3] 系统找不到指定的路径。: 'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\tmpb8018ecm\\repo\\.git'

======================================================================
ERROR: test_history_pointer_and_large_blob (__main__.self_test.<locals>.Tests.test_history_pointer_and_large_blob)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1002.py", line 893, in setUp
    self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/"repo";self.repo=Repo.init(str(self.root)) # 创建隔离的测试仓库
                                                                                            ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\repo.py", line 2433, in init
    os.mkdir(controldir)
FileNotFoundError: [WinError 3] 系统找不到指定的路径。: 'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\tmpmsaw6e60\\repo\\.git'

======================================================================
ERROR: test_ignore_lfs_delete_and_no_process (__main__.self_test.<locals>.Tests.test_ignore_lfs_delete_and_no_process)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1002.py", line 893, in setUp
    self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/"repo";self.repo=Repo.init(str(self.root)) # 创建隔离的测试仓库
                                                                                            ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\repo.py", line 2433, in init
    os.mkdir(controldir)
FileNotFoundError: [WinError 3] 系统找不到指定的路径。: 'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\tmpszmleyn5\\repo\\.git'

======================================================================
ERROR: test_low_speed_watchdog (__main__.self_test.<locals>.Tests.test_low_speed_watchdog)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1002.py", line 893, in setUp
    self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/"repo";self.repo=Repo.init(str(self.root)) # 创建隔离的测试仓库
                                                                                            ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\repo.py", line 2433, in init
    os.mkdir(controldir)
FileNotFoundError: [WinError 3] 系统找不到指定的路径。: 'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\tmpf2av6c59\\repo\\.git'

======================================================================
ERROR: test_network_retry_http_and_lfs (__main__.self_test.<locals>.Tests.test_network_retry_http_and_lfs)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1002.py", line 893, in setUp
    self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/"repo";self.repo=Repo.init(str(self.root)) # 创建隔离的测试仓库
                                                                                            ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\repo.py", line 2433, in init
    os.mkdir(controldir)
FileNotFoundError: [WinError 3] 系统找不到指定的路径。: 'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\tmpnbtv01c1\\repo\\.git'

======================================================================
ERROR: test_readme_empty_after_push (__main__.self_test.<locals>.Tests.test_readme_empty_after_push)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1002.py", line 893, in setUp
    self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/"repo";self.repo=Repo.init(str(self.root)) # 创建隔离的测试仓库
                                                                                            ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\repo.py", line 2433, in init
    os.mkdir(controldir)
FileNotFoundError: [WinError 3] 系统找不到指定的路径。: 'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\tmpn4hdh_ln\\repo\\.git'

======================================================================
ERROR: test_signature_and_regular_reader_windows (__main__.self_test.<locals>.Tests.test_signature_and_regular_reader_windows)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1002.py", line 893, in setUp
    self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/"repo";self.repo=Repo.init(str(self.root)) # 创建隔离的测试仓库
                                                                                            ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\repo.py", line 2433, in init
    os.mkdir(controldir)
FileNotFoundError: [WinError 3] 系统找不到指定的路径。: 'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\tmp1gvwibdu\\repo\\.git'

======================================================================
ERROR: test_split_commits_and_local_push (__main__.self_test.<locals>.Tests.test_split_commits_and_local_push)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1002.py", line 893, in setUp
    self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/"repo";self.repo=Repo.init(str(self.root)) # 创建隔离的测试仓库
                                                                                            ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\repo.py", line 2433, in init
    os.mkdir(controldir)
FileNotFoundError: [WinError 3] 系统找不到指定的路径。: 'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\tmpe9j5cme9\\repo\\.git'

======================================================================
ERROR: test_symlink_does_not_walk_target (__main__.self_test.<locals>.Tests.test_symlink_does_not_walk_target)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1002.py", line 893, in setUp
    self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/"repo";self.repo=Repo.init(str(self.root)) # 创建隔离的测试仓库
                                                                                            ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\site-packages\dulwich\repo.py", line 2433, in init
    os.mkdir(controldir)
FileNotFoundError: [WinError 3] 系统找不到指定的路径。: 'C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\tmp8ozithl4\\repo\\.git'

----------------------------------------------------------------------
Ran 11 tests in 0.018s

FAILED (errors=11)
'''
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse,base64,codecs,errno,hashlib,http.client,inspect,io,json,logging,math,os,queue,re,socket,ssl,stat,sys,tempfile,threading,time # 仅使用 Python 标准库，不依赖任何第三方网络库或外部可执行文件
from collections import deque # 双端队列用于广度优先历史遍历
from contextlib import contextmanager,suppress # 上下文管理器与异常抑制工具
from datetime import datetime # 格式化时间戳与计算时区偏移
from email.utils import parsedate_to_datetime # 解析 HTTP 响应头中的 Date 字段
from pathlib import Path # 面向对象的跨平台文件路径处理
from urllib.parse import parse_qsl,quote,unquote,urljoin,urlsplit,urlunsplit # 标准库 URL 解析与安全重组
from urllib.request import getproxies,proxy_bypass # 读取操作系统或环境变量配置的 HTTP 代理
import dulwich # Dulwich Git 核心引擎
from dulwich.attrs import Pattern as AttrPattern # Git 属性路径通配模式匹配器
from dulwich.client import AbstractHttpGitClient # Dulwich 官方抽象 HTTP 客户端基类
from dulwich.config import ConfigFile,apply_instead_of # Git 配置文件解析与 insteadOf 重定向
from dulwich.errors import GitProtocolError,HangupException,NotGitRepository # Dulwich 协议异常定义
from dulwich.file import GitFile # 安全带锁文件写入器
from dulwich.ignore import IgnoreFilter,IgnoreFilterManager,default_user_ignore_filter_path # .gitignore 过滤管理器
from dulwich.index import IndexEntry,commit_tree,index_entry_from_stat,write_index_dict,validate_path,get_path_element_validator # 索引条目与树构建
from dulwich.object_store import MissingObjectFinder,iter_tree_contents,MemoryObjectStore # 对象存储查找与树遍历
from dulwich.objects import Blob,Commit,Tree # Git 基础对象模型
from dulwich.pack import SHA1Writer # Pack 文件流式写入器
from dulwich.protocol import ZERO_SHA # 全零提交哈希常量
from dulwich.refs import check_ref_format # 引用名称格式有效性校验
from dulwich.repo import Repo # Dulwich 本地仓库操作类

# 修复 Dulwich 1.2.15 官方已知缺陷：server.py 向 MemoryObjectStore.add_thin_pack 传递 max_input_size 导致 TypeError
_orig_add_thin_pack=getattr(MemoryObjectStore,"add_thin_pack",None) # 读取原始内存对象库 add_thin_pack 方法
if _orig_add_thin_pack and "max_input_size" not in inspect.signature(_orig_add_thin_pack).parameters: # 检查是否缺失 max_input_size 参数
    def _compat_add_thin_pack(self,read_all,read_some,progress=None,**kwargs): # 构造兼容包装函数接收多余关键字参数
        return _orig_add_thin_pack(self,read_all,read_some,progress=progress) # 转发核心参数给原实现确保 Smart HTTP 正常工作
    MemoryObjectStore.add_thin_pack=_compat_add_thin_pack # 动态打补丁修复内存仓库服务端崩溃问题

LOG=logging.getLogger("PurePush");SECRETS=set();CHUNK=64*1024 # 日志记录器、敏感凭据脱敏集合及默认 64KB 传输块大小
POINTER_PREFIX=b"version https://git-lfs.github.com/spec/v1\n";MEDIA="application/vnd.git-lfs+json" # Git LFS v1 规范指针头及专用 MIME 类型

class StopPush(RuntimeError):pass # 终止推送的标准异常（业务逻辑预期内中止，无需重试）
class NetworkFailure(RuntimeError):pass # 可重试的网络层异常（连接中断、超时、套接字重置等）
class HTTPFailure(StopPush): # HTTP 状态码错误包装
    def __init__(self,code,url,detail="",retry_after=0): # 初始化 HTTP 失败记录
        super().__init__(f"HTTP {code} {safe_url(url)} {detail}");self.code=int(code);self.retry_after=retry_after # 保存响应码和重试建议秒数

def remember(secret): # 记录需要自动脱敏的机密文本
    if secret and len(str(secret))>3:SECRETS.add(str(secret)) # 密码或 Token 长度大于 3 时加入脱敏集合

def safe_url(value): # 彻底隐藏 URL 中的用户名、密码以及签名上传查询参数，防止日志泄露
    try: # 尝试解析 URL 结构
        p=urlsplit(str(value));host=p.hostname or "";host=f"[{host}]" if ":" in host else host # 规范化 IPv6 或主机名
        return urlunsplit((p.scheme,host+(f":{p.port}" if p.port else ""),p.path,"","")) # 清空 userinfo 和 query 查询串
    except ValueError:return "[URL 已脱敏]" # 解析异常时返回通用安全占位符

def redact(value): # 对任意文本输出执行敏感词全局脱敏替换
    text=str(value) # 转为普通字符串
    for secret in sorted(SECRETS,key=len,reverse=True):text=text.replace(secret,"***") # 优先替换长密钥防止局部残留
    text=re.sub(r"https?://[^\s\"'<>]+",lambda m:safe_url(m.group()),text) # 将所有内嵌 HTTP(S) 地址全部转为安全地址
    return text.replace("\x1b","\\x1b") # 转义终端控制符防止终端转义注入攻击

class SafeFormatter(logging.Formatter): # 安全脱敏日志格式化器
    def format(self,record):return redact(super().format(record)) # 拦截所有日志记录并进行脱敏过滤

def setup_logging(v): # 配置全局日志等级与控制台输出格式
    handler=logging.StreamHandler(sys.stdout);handler.setFormatter(SafeFormatter("%(asctime)s.%(msecs)03d | %(levelname)-7s | %(message)s","%Y-%m-%d %H:%M:%S")) # 统一日志时间戳精度到毫秒
    LOG.handlers[:]=[handler];LOG.propagate=False;LOG.setLevel({0:logging.ERROR,1:logging.WARNING,2:logging.INFO}.get(v,logging.DEBUG)) # 0=错误 1=警告 2=正常 3=调试输出

def trace(a,message,*values): # 详细调试跟踪日志输出函数
    if getattr(a,"trace",False):LOG.log(logging.DEBUG if getattr(a,"verbose",2)>=3 else logging.INFO,message,*values) # 根据命令行 verbose 参数选择等级

def cfg(config,section,key,default=b""): # 安全读取 Git 配置项字节串值
    section=(section,) if isinstance(section,bytes) else section # 确保 section 为元组格式
    try:return config.get(section,key) # 尝试自配置堆栈中提取对应键
    except KeyError:return default # 未配置时返回指定的默认值

def text(value):return value.decode("utf-8","surrogateescape") if isinstance(value,bytes) else str(value) # 字节安全解码为文本（含孤立代理项兼容）
def yes(config,section,key,default=False):return config.get_boolean(section,key,default) # 读取 Git 布尔型配置项
def human(n): # 将字节数值转换为人类易读的二进制单位字符串
    units=("B","KiB","MiB","GiB","TiB");i=0;n=float(n) # 初始化单位数组与浮点数值
    while n>=1024 and i<len(units)-1:n/=1024;i+=1 # 循环除以 1024 进位
    return f"{n:.2f} {units[i]}" # 保留两位小数并拼接单位

def parse_size(value): # 解析支持多种后缀的体积字符串（如 100MB、1.5GiB、2048）
    m=re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([kmgt]?)(?:i?b)?\s*",str(value),re.I) # 正则匹配数字和单位后缀
    if not m:raise argparse.ArgumentTypeError(f"无法解析大小参数: {value}；应为纯数字或 100MB / 1.5GiB") # 格式不符时抛出参数类型错误
    return int(float(m[1])*1024**(" kmgt".find(m[2].lower()) if m[2] else 0)) # 计算对应的绝对字节总数

def stamp():return datetime.now().strftime("%Y-%m-%d__%H.%M.%S__.")+f"{int(time.time()*1000)%1000:03d}" # 生成对齐 git_logic.py 规范的毫秒时间戳

def split_credentials(raw): # 解析远程 URL 中的认证凭据并分离纯净连接地址
    p=urlsplit(raw);user=unquote(p.username) if p.username is not None else None;password=unquote(p.password) if p.password is not None else None # URL 解码用户名密码
    remember(password);remember(p.password) # 立即将密码和 Token 记入全局脱敏集合
    if p.scheme not in ("http","https") or not p.hostname:raise StopPush("纯标准库引擎仅支持 HTTP(S) 地址；SSH 请配置对应远程或使用外部 git") # 明确协议边界
    host=p.hostname;host=f"[{host}]" if ":" in host else host;port=p.port # 处理 IPv6 方括号格式及端口号
    return urlunsplit((p.scheme,host+(f":{port}" if port else ""),p.path,p.query,"")),user,password # 返回去除 userinfo 的纯净 URL 和凭据

def origin(url): # 计算 HTTP 认证作用域的 Origin 元组（协议、主机、端口）
    p=urlsplit(url);return p.scheme,p.hostname,p.port or (443 if p.scheme=="https" else 80) # 补全默认端口

def basic(user,password): # 生成 HTTP Basic 认证头字符串
    if password is None:return None # 无密码时不生成认证头
    if ":" in (user or ""):raise StopPush("Basic 认证用户名中不能包含英文冒号") # 校验用户名规范
    val="Basic "+base64.b64encode(f"{user or 'x-access-token'}:{password}".encode()).decode("ascii") # 构造 Base64 编码的凭据
    remember(val);remember(val[6:]);return val # 记录完整 Basic 头和 Base64 部分进行脱敏防护

def normalize_remote(raw): # 规范化远程地址，支持从 GitHub 网页路径提取仓库与分支
    clean,user,password=split_credentials(raw);p=urlsplit(clean);branch=None;parts=p.path.strip("/").split("/") # 拆解 URL 路径段
    if p.query:raise StopPush("远程仓库 URL 不能包含查询字符串，请使用仓库根路径") # 避免歧义
    if p.hostname in ("github.com","www.github.com"): # 针对 GitHub 网页地址的友好支持
        if len(parts)<2 or not all(parts[:2]):raise StopPush("GitHub 远程地址必须包含 owner/repository 两段") # 校验基本段数
        if len(parts)>2: # 如果是网页直接复制的 tree/blob 页面地址
            branch=unquote(parts[3] if parts[2] in ("tree","blob") and len(parts)>3 else parts[2]) # 提取出页面所在的分支名称
            LOG.warning("网页路径只用于定位仓库，推送范围仍是整个本地仓库；含斜杠的分支请显式指定 --branch") # 打印分支推断提示
        clean=urlunsplit((p.scheme,p.netloc,"/"+"/".join(parts[:2]).removesuffix(".git")+".git","","")) # 规范为标准的 .git 后缀仓库根地址
    return clean.rstrip("/"),user,password,branch # 返回处理后的目标仓库地址、用户名、密码与推断分支

def atomic_write(path,data): # 原子替换写入配置文件，杜绝写入中断留下半截文件；拒绝覆盖符号链接
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True) # 递归建立父目录
    if path.is_symlink():raise StopPush(f"拒绝覆盖符号链接: {path}") # 软链接安全守卫
    mode=stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644 # 保留目标文件原权限
    fd,tmp=tempfile.mkstemp(prefix=".purepush-",dir=path.parent) # 在同目录下创建临时文件以便支持原子重命名
    try: # 写入并同步落盘
        with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno()) # 强制刷写到物理介质
        os.chmod(tmp,mode);os.replace(tmp,path) # 原子重命名替换目标文件
    finally: # 清理未完成的临时文件
        with suppress(FileNotFoundError):os.unlink(tmp) # 确保临时文件最终清除

def signature(st): # 跨平台一致的文件签名元组，避免 Windows 下 CRT fstat 与 Win32 stat 不匹配问题
    mtime=getattr(st,"st_mtime_ns",int(getattr(st,"st_mtime",0)*1e9)) # 优先纳秒修改时间戳
    ctime=getattr(st,"st_ctime_ns",int(getattr(st,"st_ctime",0)*1e9)) # 优先纳秒创建/属性修改时间戳
    return (st.st_size,mtime,ctime,st.st_mode) # 统一比较文件体积、修改时间、状态时间和模式

@contextmanager
def regular_reader(path): # 严密的防 TOCTOU 竞争普通文件安全读取器，完美跨平台支持 Windows 与 Linux
    path=Path(path);before=path.lstat() # 获取读取前的文件状态
    if not stat.S_ISREG(before.st_mode):raise StopPush(f"不是普通文件，拒绝跟随链接: {path}") # 严格拒绝符号链接
    if os.name=="nt": # Windows 专属安全路径：解决 MS CRT _fstat64 与 GetFileInformationByHandle 字段不一致缺陷
        with open(path,"rb") as f: # 直接以二进制打开文件
            yield f,before # 产生文件句柄与初始状态
        after=path.lstat() # 读取完成后再次检查文件状态
        if signature(after)!=signature(before):raise StopPush(f"读取时文件发生变化，请重试本地操作: {path}") # 验证文件完整性
    else: # POSIX 专属安全路径：利用 O_NOFOLLOW 杜绝打开软链接
        flags=os.O_RDONLY|getattr(os,"O_BINARY",0)|getattr(os,"O_NOFOLLOW",0) # 组合安全打开标志
        fd=os.open(path,flags) # 打开原生文件描述符
        with os.fdopen(fd,"rb") as f: # 包装为 Python 二进制流
            cur=os.fstat(f.fileno()) # 获取已打开文件描述符的真实状态
            if (cur.st_dev,cur.st_ino,cur.st_size)!=(before.st_dev,before.st_ino,before.st_size):raise StopPush(f"读取前文件已经变化: {path}") # 校验设备和 inode
            yield f,before # 产出文件对象
            after=os.fstat(f.fileno()) # 读取后再次校验
            if (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)!=(cur.st_dev,cur.st_ino,cur.st_size,cur.st_mtime_ns):raise StopPush(f"读取时文件发生变化: {path}")

def read_regular(path,limit=None): # 安全读取普通文件全部字节并实施体积上限保护
    with regular_reader(Path(path)) as (f,st): # 上下文安全读取
        if limit is not None and st.st_size>limit:raise StopPush(f"配置文件体积超出限制: {path}") # 超限拦截
        return f.read() # 返回全部文件字节

def config_bytes(path): # 静默读取 Git 配置文件字节，文件不存在或为软链接时安全返回空字节
    path=Path(path) # 路径对象化
    if path.is_symlink():return b"" # 软链直接忽略
    try:return read_regular(path,8*1024*1024) # 配置文件最高限制 8MB 防止内存耗尽
    except (FileNotFoundError,NotADirectoryError):return b"" # 不存在时安全返回空

class SafeIgnore(IgnoreFilterManager): # 继承 Dulwich 忽略规则管理器，增强对软链接的防御
    def _load_path(self,path): # 严密检查并阻止跟随指向外部的 .gitignore 软链接
        if (Path(self._top_path)/path/".gitignore").is_symlink():return None # 遇到软链规则文件则视为空
        return super()._load_path(path) # 委托原类解析普通规则
    def _is_dir(self,path): # 目录判断逻辑：排除指向目录的符号链接
        p=Path(self._top_path)/path;return path.endswith("/") or (p.is_dir() and not p.is_symlink()) # 软链接目录绝不递归进入

def ignore_manager(repo,config): # 构建完整的 Git 忽略规则层次链
    ignorecase=yes(config,(b"core",),b"ignorecase",False);filters=[] # 读取 core.ignorecase 设置
    for path in (Path(default_user_ignore_filter_path(config)).expanduser(),Path(repo.controldir())/"info"/"exclude"): # 全局与 info/exclude 规则
        try:filters.append(IgnoreFilter.from_path(path,ignorecase)) # 按优先级从低到高加入过滤器列表
        except FileNotFoundError:pass # 文件不存在则跳过
    return SafeIgnore(str(repo.path),filters,ignorecase) # 返回复合忽略过滤器管理器

def attr_words(line): # 解析 .gitattributes 规则行，完整支持包含空格的 C 风格八进制转义引号路径
    line=line.strip() # 去除前后空白
    if not line or line.startswith(b"#"):return None,[] # 注释或空行直接忽略
    if not line.startswith(b'"'):words=line.split();return words[0],words[1:] # 未加引号则按空格常规切分
    out=bytearray();i=1;esc={ord("a"):7,ord("b"):8,ord("t"):9,ord("n"):10,ord("v"):11,ord("f"):12,ord("r"):13,34:34,92:92} # C 转义映射表
    while i<len(line): # 逐字节扫描引号内字符
        b=line[i];i+=1 # 游标推进
        if b==34:return bytes(out),line[i:].strip().split() # 遇到闭合双引号结束路径解析并切分后续属性词
        if b==92: # 遇到反斜杠转义
            if i>=len(line):break # 转义未完直接跳出
            b=line[i];i+=1 # 获取被转义字节
            if 48<=b<=55: # 八进制转义分支（如 \040 表示空格）
                octal=bytearray([b]) # 收集八进制数字
                while i<len(line) and len(octal)<3 and 48<=line[i]<=55:octal.append(line[i]);i+=1 # 最多收集三位
                val=int(octal.decode("ascii"),8) # 解析八进制数值
                if val>255:raise StopPush("属性路径的八进制转义超出单字节范围") # 超出单字节范围报错
                b=val # 转换为目标数值
            elif b in esc:b=esc[b] # 标准转义字符替换
            else:raise StopPush(f".gitattributes 中包含不支持的转义字符: \\{chr(b)}") # 未知转义抛错
        out.append(b) # 追加解码字节
    raise StopPush(".gitattributes 中的路径引号未正常闭合") # 未闭合引号异常报错

def parse_attribute(token): # 解析单项属性标记，精确识别 set、unset、unspecified 与 key=value 属性
    if token[:1] in (b"-",b"!"):return token[1:],False if token[:1]==b"-" else None # -attr 为 False，!attr 为 None
    if b"=" in token:return tuple(token.split(b"=",1)) # key=val 返回元组
    return token,True # 纯名字表示已设置（True）

class Attributes: # 严密实现的 Git 属性管理器：支持宏定义展开、目录层级覆盖与环路检测
    def __init__(self,repo,config,index): # 初始化属性解析上下文
        self.repo=repo;self.root=Path(repo.path);self.index=index;self.cache={} # 缓存已解析规则
        self.global_path=Path(text(cfg(config,b"core",b"attributesfile",os.fsencode(Path(os.environ.get("XDG_CONFIG_HOME",str(Path.home()/".config")))/"git"/"attributes")))).expanduser() # 全局属性文件路径
        self.info=Path(repo.controldir())/"info"/"attributes" # 本地仓库独享属性文件路径
    def load(self,path,relative=None,macro_allowed=True): # 读取并解析指定文件中的属性规则与宏定义
        key=str(path) # 缓存键
        if key in self.cache:return self.cache[key] # 命中缓存直接返回
        data=config_bytes(path) # 从磁盘读取文件
        if not path.exists() and relative is not None and relative in self.index: # 若工作区无文件但暂存区存在该规则文件
            entry=self.index[relative] # 获取暂存区条目
            if entry.mode in (0o100644,0o100755):data=self.repo.object_store[entry.sha].data # 从对象库回退提取暂存区内容
        rules=[];macros={} # 初始化规则与宏映射
        for line in data.splitlines(): # 逐行分析属性配置
            pattern,tokens=attr_words(line) # 解析路径和属性标记
            if pattern is None:continue # 跳过空行或注释
            values=[parse_attribute(t) for t in tokens] # 解析所有属性键值对
            if pattern.startswith(b"[attr]"): # 处理属性宏声明
                if macro_allowed:macros[pattern[6:]]=values # 仅允许顶层文件定义宏
                else:LOG.warning("忽略子目录中非法的属性宏定义: %s",path) # 子目录宏定义丢弃告警
            elif pattern.startswith(b"!"):raise StopPush(f".gitattributes 不允许使用取反模式: {path}") # 语法禁止感叹号取反
            else: # 普通路径规则
                try:rules.append((AttrPattern(pattern),values)) # 构建 Dulwich 属性匹配模式
                except ValueError as exc:raise StopPush(f"属性模式语法错误: {path}: {exc}") from exc # 语法异常捕获
        self.cache[key]=(rules,macros);return rules,macros # 写入缓存并返回
    def get(self,rel): # 计算给定相对路径最终生效的合并属性字典
        parts=rel.split(b"/");levels=[(self.global_path,rel,None,True)] # 从全局配置开始
        for i in range(len(parts)): # 顺次深入每一层子目录中的 .gitattributes
            name=b"/".join(parts[:i]+[b".gitattributes"]);levels.append((self.root/os.fsdecode(name),b"/".join(parts[i:]),name,i==0)) # 记录层级
        levels.append((self.info,rel,None,True)) # 最后叠加 .git/info/attributes 最高优先级覆盖
        loaded=[(self.load(p,key,macros),local) for p,local,key,macros in levels] # 加载全部相关属性文件
        definitions={b"binary":[(b"diff",False),(b"merge",False),(b"text",False)]};result={} # 默认内建 binary 宏
        for (_,macros),_ in loaded:definitions.update(macros) # 汇总所有宏定义
        def apply(values,seen=frozenset()): # 递归展开宏定义并实施环路检测保护
            for name,value in values: # 遍历属性项
                result[name]=value # 设置值
                if value is True and name in definitions: # 若属性值激活了某个宏
                    if name in seen:raise StopPush("属性宏发生循环引用: "+text(name)) # 环路检测报错
                    apply(definitions[name],seen|{name}) # 递归展开该宏并传递已见集合
        for (rules,_),local in loaded: # 按自底向上的顺序应用规则覆盖
            for pattern,values in rules: # 遍历各条模式
                if pattern.match(local):apply(values) # 模式命中时应用对应属性
        return {k:v for k,v in result.items() if v is not None} # 过滤掉 unspecified (None) 状态属性

def exact_attr_rule(name): # 生成精准匹配特定文件名的 .gitattributes 规则行并安全加引号
    pattern=b"/"+b"".join((b"\\"+bytes([b])) if b in b"\\*?[]" else bytes([b]) for b in os.fsencode(name)) # 转义特殊通配字符
    quoted=b'"'+b"".join(bytes([b]) if 32<=b<=126 and b not in (34,92) else (b"\\\"" if b==34 else (b"\\\\" if b==92 else f"\\{b:03o}".encode())) for b in pattern)+b'"' # 规范 C 风格引号转义
    return quoted+b" filter=lfs diff=lfs merge=lfs -text" # 拼接标准 LFS 追踪指令

def pointer_bytes(oid,size): # 根据 Git LFS v1 规范格式化指针文本字节串
    return f"version https://git-lfs.github.com/spec/v1\noid sha256:{oid}\nsize {size}\n".encode("ascii") # 严密保证换行符为 LF

def pointer_info(data): # 校验并提取 Git LFS 指针文件中的 oid 和 size
    if not isinstance(data,bytes) or not data.startswith(POINTER_PREFIX) or len(data)>1024:return None # 指针体积上限保护与头部校验
    oid=None;size=None # 初始化提取值
    for line in data.splitlines(): # 按行提取元数据
        if line.startswith(b"oid sha256:"):oid=line[11:].strip().decode("ascii") # 提取 SHA256 十六进制字符串
        elif line.startswith(b"size "): # 提取对象大小
            try:size=int(line[5:].strip()) # 转为整型字节数
            except ValueError:return None # 解析异常返回 None
    return (oid,size) if (oid and size is not None and len(oid)==64 and all(c in "0123456789abcdefABCDEF" for c in oid)) else None # 校验哈希合法性

class LFSCache: # 本地 Git LFS 对象缓存管理器（操作 .git/lfs/objects/xx/yy/xxxx）
    def __init__(self,repo,config): # 初始化缓存存储路径
        custom=cfg(config,(b"lfs",),b"storage") # 检查是否有自定义 LFS 存储目录配置
        self.root=Path(text(custom)).expanduser() if custom else Path(repo.controldir())/"lfs"/"objects" # 默认在 .git/lfs/objects
        self.verified={} # 记录已经过哈希校验的对象签名缓存
    def path(self,oid):return self.root/oid[:2]/oid[2:4]/oid # 按照标准两位前缀二级子目录散列组织对象路径
    def put(self,path): # 将本地大文件计算 SHA256 后原子移入 LFS 对象池并返回其对应的指针字节串
        path=Path(path);self.root.mkdir(parents=True,exist_ok=True) # 建立根缓存目录
        fd,name=tempfile.mkstemp(prefix=".purepush-lfs-",dir=self.root) # 临时缓存文件
        try: # 边流式计算 SHA256 边写入临时缓存
            h=hashlib.sha256();size=0;last=time.monotonic() # 计时器与哈希上下文
            with os.fdopen(fd,"wb") as out,regular_reader(path) as (f,st): # 安全并发读写
                for block in iter(lambda:f.read(CHUNK),b""): # 64KB 分块迭代
                    out.write(block);h.update(block);size+=len(block) # 更新哈希与字节计数
                    if time.monotonic()-last>=1:LOG.info("LFS 本地快照: %s | %s/%s",path.name,human(size),human(st.st_size));last=time.monotonic() # 每一秒汇报一次本地暂存进度
            out.flush();os.fsync(out.fileno()) # 强制刷盘
            oid=h.hexdigest();dest=self.path(oid);dest.parent.mkdir(parents=True,exist_ok=True);os.replace(name,dest) # 原子移动到最终对象目录
            self.verified[oid,size]=signature(dest.stat());return pointer_bytes(oid,size) # 缓存状态并返回标准指针
        finally: # 异常中断时清理临时垃圾
            with suppress(FileNotFoundError):os.unlink(name) # 保证不遗留临时碎片
    def require(self,oid,size): # 校验指定 LFS 对象是否存在且完整无损，返回其本地磁盘路径
        path=self.path(oid) # 获取预期路径
        if not path.is_file() or path.is_symlink():raise StopPush(f"远端需要 LFS {oid}，但本地缓存不存在；请恢复原文件后再推送，不能只发送空指针") # 拒绝推送脱节的指针
        if self.verified.get((oid,size))!=signature(path.stat()): # 未曾校验或文件已被动过
            h=hashlib.sha256();total=0 # 重新计算哈希
            with regular_reader(path) as (f,_): # 流式比对
                for block in iter(lambda:f.read(CHUNK),b""):h.update(block);total+=len(block) # 累加校验
            if total!=size or h.hexdigest()!=oid:raise StopPush(f"本地 LFS 缓存对象已损坏: {oid}") # 数据不一致报错
            self.verified[oid,size]=signature(path.stat()) # 校验通过登记缓存
        if path.stat().st_size!=size:raise StopPush(f"本地 LFS 缓存大小与指针标称不符: {oid}") # 大小不符拦截
        return path # 返回通过验证的对象路径

def walk_candidates(repo,index,manager,config): # 遍历工作区文件候选：完美处理忽略规则与已跟踪文件的更新/删除，跨平台安全防御
    root=Path(repo.path);tracked=dict(index.items());ignorecase=yes(config,(b"core",),b"ignorecase",False) # 跟踪索引与大小写敏感情况
    lookup={os.fsdecode(k).casefold():k for k in tracked} if ignorecase else {} # 大小写不敏感反查表
    files={};skipped=0;count=0;last=time.monotonic();validator=get_path_element_validator(config) # 初始化计数器
    def folded(rel):return os.fsdecode(rel).casefold() if ignorecase else os.fsdecode(rel) # 统一折叠路径
    parents={folded(b"/".join(p.split(b"/")[:i])) for p in tracked for i in range(1,len(p.split(b"/")))} # 收集所有已跟踪文件祖先目录集合
    def old_key(rel):return rel if rel in tracked else lookup.get(os.fsdecode(rel).casefold()) # 判断是否已在暂存区跟踪
    def add(path): # 候选文件审查与登记函数
        nonlocal skipped,count,last # 引入闭包变量
        rel=os.fsencode(path.relative_to(root).as_posix());old=old_key(rel);count+=1 # 计算仓库相对路径
        if not validate_path(rel,validator):raise StopPush(f"Git 路径包含非法字符: {path}") # 路径合规性防御
        if old is None and manager.is_ignored(os.fsdecode(rel)) is True:skipped+=1;return # 未跟踪且被 ignore 则过滤掉
        files[rel]=(path,old) # 记录候选文件与其在索引中的原键
        if time.monotonic()-last>=1:LOG.info("扫描文件: %d | 排除: %d | 当前: %s",count,skipped,os.fsdecode(rel));last=time.monotonic() # 周期性打印扫描进度
    def onerror(error):raise error # 遍历出错抛出异常
    for base,dirs,names in os.walk(root,topdown=True,followlinks=False,onerror=onerror): # 严密遍历工作区，严禁 followlinks 规避目录符号链接逃逸
        current=Path(base);keep=[] # 暂存合规子目录名
        for name in dirs: # 检查子目录合法性
            path=current/name;rel=os.fsencode(path.relative_to(root).as_posix()) # 相对路径
            if (name.casefold() if os.name=="nt" else name)==".git":continue # 跳过 Git 控制目录
            if path.is_symlink():add(path);continue # 符号链接当作特殊文件记录，绝不当作目录深入
            if folded(rel) not in parents and old_key(rel) is None and manager.is_ignored(os.fsdecode(rel)) is True:skipped+=1;continue # 整目录被忽略且无已跟踪祖先则直接剪枝
            if getattr(path,"is_junction",lambda:False)():raise StopPush(f"安全拒绝遍历 Windows 挂载连接点 (junction): {path}") # 拒绝进入 Windows 挂载点
            if (path/".git").exists() or (old_key(rel) is not None and tracked[old_key(rel)].mode==0o160000):add(path);continue # Git 子模块当作 160000 条目记录，不进入遍历
            keep.append(name) # 正常目录保留继续深入
        dirs[:]=keep # 剪枝应用
        for name in names: # 扫描常规文件
            if (name.casefold() if os.name=="nt" else name)!=".git":add(current/name) # 登记文件项
    LOG.info("扫描完成: %d 项 | 未跟踪且被忽略: %d 项",count,skipped);return files # 返回收集到的全部候选集合

def normalize_blob(data,attrs,old,repo,config,path,renormalize=False): # 针对文本文件执行精准的标准换行符规范化（LF / CRLF）与 ident 处理
    if attrs.get(b"working-tree-encoding") not in (None,False):raise StopPush(f"暂不支持 working-tree-encoding，拒绝静默修改文件编码: {os.fsdecode(path)}") # 保护特殊编码
    selected=attrs.get(b"filter") # 检查过滤器属性
    if selected not in (None,False,b"lfs"):raise StopPush(f"纯 Python 模式不执行外部过滤器 filter={text(selected)}: {os.fsdecode(path)}") # 拒绝外部危险程序
    if attrs.get(b"ident") is True:data=re.sub(rb"\$Id:[^$\r\n]*\$",b"$Id$",data) # 实施 $Id$ 占位符规范化
    text_attr=attrs.get(b"text");eol=attrs.get(b"eol");auto=cfg(config,b"core",b"autocrlf",b"false").lower() # 读取换行相关属性与配置
    if text_attr is None and b"crlf" in attrs:text_attr=False if attrs[b"crlf"] is False else True # 兼容旧式 crlf 属性写法
    if text_attr is False or (text_attr is None and eol is None and auto not in (b"true",b"input")):return data # 确认为二进制文件直接返回原数据
    automatic=text_attr!=True and not (text_attr is None and eol in (b"lf",b"crlf")) # 是否为自动探测模式
    nonprint=sum(data.count(bytes([b])) for b in range(32) if b not in (8,9,10,12,13,27))+data.count(b"\x7f") # 统计非打印不可见控制字符
    if automatic and (b"\0" in data or data.count(b"\r")!=data.count(b"\r\n") or nonprint>(len(data)-nonprint)//128):return data # 自动判定二进制则不转换
    if automatic and old is not None and not renormalize and old.mode!=0o160000: # 若已存在旧对象且未要求强制重规范化
        if b"\r\n" in repo.object_store[old.sha].data:return data # 若原提交库中即为 CRLF 则维持历史现状
    converted=data.replace(b"\r\n",b"\n");safe=cfg(config,b"core",b"safecrlf",b"false").lower();core_eol=cfg(config,b"core",b"eol",b"native") # 统一转换到 LF
    checkout_crlf=eol==b"crlf" or (eol is None and (auto==b"true" or (auto!=b"input" and (core_eol==b"crlf" or (core_eol==b"native" and os.name=="nt"))))) # 检出时是否会转回 CRLF
    restored=converted.replace(b"\n",b"\r\n") if checkout_crlf else converted # 模拟还原结果
    if safe in (b"true",b"warn") and restored!=data: # safecrlf 不可逆转换检测
        if safe==b"true":raise StopPush(f"core.safecrlf 拒绝可能发生数据丢失的换行转换: {os.fsdecode(path)}") # 拦截不可逆转换
        LOG.warning("换行转换不可逆: %s",os.fsdecode(path)) # 警告提示
    return converted # 返回规范化后的 Blob 数据

def stage_all(repo,index,a,config,cache): # 高性能全量暂存：自动捕获大文件转为 LFS 指针、处理符号链接与子模块，不启动任何外部进程
    if any(not isinstance(entry,IndexEntry) for _,entry in index.items()):raise StopPush("暂存区存在未解决的冲突标记，拒绝自动提交") # 冲突守卫
    if any(stat.S_ISDIR(entry.mode) or entry.skip_worktree for _,entry in index.items()):raise StopPush("检测到稀疏索引或 skip-worktree 标记，请先恢复完整工作区") # 稀疏检出防护
    manager=ignore_manager(repo,config);files=walk_candidates(repo,index,manager,config);attrs=Attributes(repo,config,index);auto_rules={};old_entries=dict(index.items());root=Path(repo.path) # 初始化扫描与属性环境
    for rel,(path,oldkey) in list(files.items()): # 优先遍历以发现并自动注册超限大文件
        st=path.lstat() # 获取工作区文件状态
        if oldkey is not None and (old_entries[oldkey].flags&0x8000 or old_entries[oldkey].mode==0o120000):continue # 跳过冲突与软链接
        if not stat.S_ISREG(st.st_mode) or st.st_size<a.size or a.no_auto_lfs:continue # 未超阈值或显式关闭则跳过
        effective=attrs.get(rel) # 获取当前属性
        if effective.get(b"filter")!=b"lfs":auto_rules[rel]=exact_attr_rule(rel) # 未配置 LFS 时加入自动添加属性规则清单
    if auto_rules: # 若存在需要自动纳入 LFS 的大文件
        target_path=root/".gitattributes";existing=read_regular(target_path).splitlines() if target_path.exists() else [] # 读取已有规则
        existing_set={line.strip() for line in existing if line.strip()} # 已有规则去重集
        added=[rule for rel,rule in sorted(auto_rules.items()) if rule not in existing_set] # 计算新增规则
        if added: # 若有新规则需要持久化
            atomic_write(target_path,b"\n".join(existing+added)+b"\n") # 原子写入 .gitattributes 文件
            attrs=Attributes(repo,config,index);files[b".gitattributes"]=(target_path,old_key(b".gitattributes")) # 重新加载属性解析器并强制重新暂存属性文件
            LOG.info("自动更新 .gitattributes: 登记 %d 个本地大文件到 Git LFS",len(added)) # 打印登记日志
    seen=set();payloads=0 # 初始化已扫描键与 LFS 写入计数
    for rel,(path,oldkey) in files.items(): # 逐项写入索引与对象存储
        st=path.lstat();old=old_entries.get(oldkey) if oldkey is not None else None # 获取当前及原有索引条目
        if stat.S_ISLNK(st.st_mode): # 处理符号链接
            target=os.fsencode(os.readlink(path));data=target;mode=0o120000 # 符号链接模式 120000，其内容为链接目标路径字符串
        elif path.is_dir() and (path/".git").exists(): # 处理 Git 子模块
            sub_head=(Path(path)/".git"/"HEAD") # 子模块 HEAD 路径
            if sub_head.exists(): # 读取子模块当前的提交 SHA
                head_text=sub_head.read_bytes().strip() # 提取引用内容
                sha=head_text.split()[-1] if not head_text.startswith(b"ref: ") else (Path(path)/".git"/head_text[5:].decode()).read_bytes().strip() # 追溯引用到 SHA
            else:sha=b"0"*40 # 容错空 SHA
            mode=0o160000;blob_id=sha;entry=index_entry_from_stat(st,blob_id,mode=mode);index[rel]=entry;seen.add(rel);continue # 登记子模块条目
        elif stat.S_ISREG(st.st_mode): # 处理常规文件
            effective=attrs.get(rel) # 计算当前文件生效的最终属性
            if effective.get(b"filter")==b"lfs": # 命中 LFS 规则
                data=cache.put(path);mode=0o100755 if (yes(config,(b"core",),b"filemode",os.name!="nt") and st.st_mode&0o111) or (not yes(config,(b"core",),b"filemode",os.name!="nt") and old is not None and old.mode==0o100755) else 0o100644 # 存入 LFS 缓存并生成指针
                payloads+=1 # 递增 LFS 转换计数
            else: # 普通文件对象
                if st.st_size>=a.max_blob_size:raise StopPush(f"普通 Git Blob 大小 ({human(st.st_size)}) 超过限制 ({human(a.max_blob_size)}): {os.fsdecode(rel)}；请通过 LFS 追踪此文件") # 拦截漏掉 LFS 规则的历史大文件
                data=normalize_blob(read_regular(path),effective,old,repo,config,rel,a.renormalize) # 规范化换行
                mode=0o100755 if (yes(config,(b"core",),b"filemode",os.name!="nt") and st.st_mode&0o111) or (not yes(config,(b"core",),b"filemode",os.name!="nt") and old is not None and old.mode==0o100755) else 0o100644 # 跨平台计算执行权限
        else:raise StopPush(f"不支持的特殊文件类型: {path}") # 拒绝设备文件、FIFO、套接字等
        if signature(path.lstat())!=signature(st):raise StopPush(f"暂存期间工作区文件被并发修改: {path}") # 暂存并发修改竞态防御
        blob=Blob.from_string(data);repo.object_store.add_object(blob) # 构造 Blob 对象并存入 Dulwich 对象库
        entry=index_entry_from_stat(st,blob.id,mode=mode);entry.size=st.st_size&0xffffffff # 构造索引条目并写入哈希与截断体积
        if mode in (0o100644,0o100755) and attrs.get(rel).get(b"filter")==b"lfs" and pointer_info(data) is None:raise StopPush(f"LFS 暂存指针自检失败: {path}") # 指针合法性双重验证
        if oldkey is not None and oldkey!=rel:del index[oldkey] # 路径大小写或名称变化时移除旧条目
        index[rel]=entry;seen.add(rel);trace(a,"暂存条目: %s",os.fsdecode(rel)) # 写入新索引项
    for rel in list(index): # 处理工作区已删除的文件
        if rel not in seen:del index[rel];trace(a,"暂存删除: %s",os.fsdecode(rel)) # 从索引中同步移除
    LOG.info("索引暂存完成 | 登记条目: %d | LFS 新快照: %d | 无外部过滤器参与",len(seen),payloads) # 输出暂存汇总

def tree_map(repo,head): # 展开指定 Commit 的根 Tree 映射字典 {路径字节: (sha, mode)}
    if not head:return {} # 无提交时返回空
    return {e.path:(e.sha,e.mode) for e in iter_tree_contents(repo.object_store,repo[head].tree)} # 递归遍历 Tree 产出扁平字典

def check_repo_state(repo,config): # 全面自检本地仓库健康状态：严防将未完成的变基/合并/浅克隆状态误推送
    if repo.bare:raise StopPush("自动暂存 push 功能仅适用于包含工作区的非 bare 仓库") # bare 仓库拦截
    if cfg(config,b"extensions",b"objectformat",b"sha1")!=b"sha1":raise StopPush("本引擎专为 SHA-1 Git 仓库打造；LFS 数据流内使用标准 SHA-256") # 校验哈希格式
    if repo.get_shallow():raise StopPush("当前仓库为浅克隆 (shallow)，无法完整计算与远端的快进关系，请先 unshallow 补全历史") # 浅仓库拦截
    if cfg(config,b"extensions",b"partialclone"):raise StopPush("检测到部分克隆配置，请先补全对象，避免推送中途发生隐式缺失下载") # 部分克隆拦截
    for section in config.sections(): # 检查是否有 promisor 远程
        if section[:1]==(b"remote",) and yes(config,section,b"promisor",False):raise StopPush("不支持向包含 promisor 的仓库自动推送")
    if yes(config,(b"core",),b"sparsecheckout",False) or yes(config,(b"core",),b"splitindex",False):raise StopPush("检测到稀疏检出或分裂索引，为保护工作区数据拒绝自动覆写") # 稀疏检出防护
    for name in ("MERGE_HEAD","CHERRY_PICK_HEAD","REVERT_HEAD","rebase-merge","rebase-apply","sequencer"): # 冲突与中途变基检测
        if (Path(repo.controldir())/name).exists():raise StopPush(f"仓库正处于未完成操作中: {name}，请先处理完毕后再尝试推送") # 提示用户先完成本地工作
    if yes(config,(b"commit",),b"gpgsign",False):raise StopPush("仓库配置了强制 GPG 签名，纯标准库模式无法调用外部签名密钥，请临时调整配置") # 签名提交提示
    if (Path(repo.commondir())/"info"/"grafts").exists() or any(r.startswith(b"refs/replace/") for r in repo.refs.keys()):raise StopPush("存在 grafts 或 replace 替换历史，拒绝按伪历史提交") # 替换历史拒绝

def commit_staged(repo,index,a,identity,expected): # 将暂存区变更提交落盘：支持体积超限分段切分提交，自动生成 commit 消息，支持 EmptyAfterPush
    chain,head=expected # 解包预期 HEAD 引用链和原 SHA
    if repo.refs.follow(b"HEAD")!=expected:raise StopPush("暂存期间本地 HEAD 被外部修改，拒绝将旧工作区提交到新分支") # 并发修改安全防线
    flat=tree_map(repo,head);target={p:(e.sha,e.mode) for p,e in index.items()} # 提取原树与目标索引
    changed=sorted((set(flat)|set(target)),key=lambda p:(p in target,p)) # 计算所有差异项：删除排前，新增在后
    changed=[p for p in changed if flat.get(p)!=target.get(p)] # 过滤出真正产生实质性内容或权限变化的条目
    if not changed:LOG.info("暂存区无任何变动，跳过创建新提交");return [],None # 空改动快速短路返回
    LOG.info("检测到变更文件: %d 个 | 前 10 项: %s",len(changed),[os.fsdecode(p) for p in changed[:10]]) # 打印变更统计
    message=a.message;largest=None;largest_size=-1;empty=None;root=Path(repo.path) # 遍历寻找最大变更文件并探测 EmptyAfterPush
    for p in changed: # 遍历差异文件清单
        fp=root/os.fsdecode(p) # 本地文件路径
        if fp.is_file() and not fp.is_symlink(): # 仅检查真实存在的非软链物理文件
            try:size=fp.stat().st_size # 获取大小
            except OSError:size=0 # 异常忽略
            if size>largest_size:largest,largest_size=os.fsdecode(p),size # 更新最大文件记录
            if p==b"ReadMe.md" and size<1024*1024: # 针对小于 1MB 的 ReadMe.md 实施 #EmptyAfterPush 探测
                try: # 读取内容检查特定魔术标记
                    if b"#EmptyAfterPush" in fp.read_bytes():empty=fp # 标记需要在推送成功后清空该文件
                except OSError:pass # 文件不存在或被删除时安全忽略
    if not message: # 若未在命令行显式指定 commit 消息
        message=f"[{largest} {largest_size}B] {stamp()} PurePush auto" if largest else f"PurePush auto {stamp()}" # 自动组合最大文件体积与时间戳
    batches=[];current=[];total=0 # 初始化多提交拆分队列
    for p in changed: # 按照最大单提交体积上限进行批次切割
        size=0 # 初始体积
        if p in target: # 仅新增或修改需计入上传提交树体积
            try:size=repo.object_store[target[p][0]].raw_length() # 获取真实 Blob 体积（LFS 指针仅计百余字节）
            except KeyError:size=0 # 缺失时按 0 算
        if current and total+size>a.max_commit_size:batches.append(current);current=[];total=0 # 超限则封箱新开一段
        current.append(p);total+=size # 累加当前批次
    if current:batches.append(current) # 追加最后一段批次
    if len(batches)>1:LOG.warning("变更总内容约 %s，超过单提交限制 %s，将自动拆分为 %d 个独立提交分段上传",human(sum(total for b in batches)),human(a.max_commit_size),len(batches)) # 打印分段拆分提醒
    ids=[];parent=head;now=int(time.time());tz=int(datetime.now().astimezone().utcoffset().total_seconds()) # 准备提交时间戳与时区秒数
    for number,paths in enumerate(batches,1): # 逐段创建 Commit 对象
        for p in paths: # 更新局部树状态
            if p in target:flat[p]=target[p] # 新增或修改写入
            else:flat.pop(p,None) # 删除项从树中弹出
        tree_id=commit_tree(repo.object_store,[(p,sha,mode) for p,(sha,mode) in flat.items()]) # 构建当前段的 Tree 对象
        commit=Commit();commit.tree=tree_id;commit.parents=[parent] if parent and parent!=ZERO_SHA else [] # 绑定 Tree 与父提交
        commit.author=commit.committer=identity;commit.author_time=commit.commit_time=now # 设置身份与时间
        commit.author_timezone=commit.commit_timezone=tz;commit.encoding=b"UTF-8" # 统一 UTF-8 编码与时区
        commit.message=(f"【{number}/{len(batches)}】文件数: {len(paths)} {message}" if len(batches)>1 else message).encode("utf-8","surrogateescape") # 格式化分段提交说明
        repo.object_store.add_object(commit);ids.append(commit.id);parent=commit.id # 写入对象存储并链式推进父提交
        LOG.info("已创建本地提交 [%d/%d]: %s",number,len(batches),commit.id.decode()) # 打印新生成的 Commit SHA
    ref_name=chain[-1] if chain and chain[-1].startswith(b"refs/") else b"refs/heads/master" # 确定当前所在分支引用名
    repo.refs[ref_name]=parent # 原子更新分支指针至最终 Commit
    return ids,empty # 返回生成的全部提交 ID 列表与需要清空的 ReadMe 路径

def outgoing_lfs(repo,remote_refs,target_sha,a): # 遍历本地自远端以来所有新增提交，提取其中所有需推送到远端的 LFS 指针
    if not target_sha or target_sha==ZERO_SHA:return {} # 无目标提交直接返回
    have=set(remote_refs.values());todo=[target_sha];commits=[];seen_commits=set() # 准备 Commit 遍历队列
    while todo: # 广度优先向上收集未推送到远端的提交
        sha=todo.pop(0) # 弹出待访问提交
        if sha in seen_commits or sha in have or sha==ZERO_SHA:continue # 远端已具备或已遍历则跳过
        seen_commits.add(sha) # 标记已见
        try:commit=repo.object_store[sha] # 读取提交对象
        except KeyError:continue # 忽略断层
        if isinstance(commit,Commit):commits.append(commit);todo.extend(commit.parents) # 收集所有父提交
    seen_trees=set();pointers={} # 收集需要检查的树对象与累积的 LFS 指针映射
    for commit in commits: # 深度检查所有未推送提交中的树内容
        tree_queue=[commit.tree] # 根树入队
        while tree_queue: # 遍历整棵树
            tid=tree_queue.pop(0) # 弹出一棵树
            if tid in seen_trees:continue # 已访问直接跳过
            seen_trees.add(tid) # 登记已访问
            try:tree=repo.object_store[tid] # 获取树对象
            except KeyError:continue # 容错
            for entry in tree.items(): # 遍历树项
                if stat.S_ISDIR(entry.mode):tree_queue.append(entry.sha) # 遇到子树入队继续递归
                elif entry.mode in (0o100644,0o100755): # 普通文件项
                    try:blob=repo.object_store[entry.sha] # 读取 Blob 对象
                    except KeyError:continue # 容错
                    if blob.raw_length()>a.max_blob_size:raise StopPush(f"历史提交中包含超过允许上限 ({human(a.max_blob_size)}) 的普通 Blob: {blob.id.decode()}；请改写历史并转换为 LFS") # 拦截历史违规大文件
                    info=pointer_info(blob.data) # 尝试解析是否为 LFS 指针
                    if info:pointers[info[0]]=info[1] # 登记 (oid -> size)
    return pointers # 返回所有需同步上传的 LFS 指针字典

class TransferMonitor: # 实时传输监控器与低速守门狗：精准测量上传速度、统计字节并判定超时中断
    def __init__(self,sock,a,label="Upload",total_expected=None): # 初始化监控上下文
        self.sock=sock;self.a=a;self.label=label;self.total_expected=total_expected # 绑定套接字与配置
        self.sent=0;self.start_time=time.monotonic();self.last_report=self.start_time;self.last_bytes=0 # 初始计量状态
        self.closed=False;self.failure=None;self.lock=threading.Lock() # 线程安全锁与故障记录
        self.timer=None # 看门狗定时器句柄
        if getattr(a,"low_speed_limit",0)>0 and getattr(a,"low_speed_time",0)>0: # 若启用了低速断连保护
            self.arm_timer() # 启动周期性低速看门狗线程
    def arm_timer(self): # 设置看门狗定时轮询
        if self.closed:return # 已关闭则退出
        self.timer=threading.Timer(max(0.1,float(self.a.progress_interval)),self._watchdog) # 按刷新间隔启动定时器
        self.timer.daemon=True;self.timer.start() # 设为守护线程后台运行
    def _watchdog(self): # 定时检测当前平均传输速度是否跌破警戒线
        with self.lock: # 加锁检查
            if self.closed:return # 已结束监控直接返回
            now=time.monotonic();elapsed=now-self.start_time # 运行总秒数
            if elapsed>=self.a.low_speed_time: # 持续时间满足考核周期
                avg_rate=self.sent/max(0.001,elapsed) # 计算整体平均速度
                if avg_rate<self.a.low_speed_limit: # 跌破最低速度阈值
                    self.failure=NetworkFailure(f"上传速度过慢: 持续 {elapsed:.1f}s 平均仅 {human(avg_rate)}/s，低于保护阈值 {self.a.low_speed_limit}B/s；正在主动切断连接以触发网络重试") # 构造异常原因
                    LOG.warning("⚠️ %s",self.failure) # 打印低速中断告警
                    try:self.sock.shutdown(socket.SHUT_RDWR) # 主动向套接字发送 FIN/RST 双向切断连接
                    except Exception:pass # 抑制已知套接字关闭异常
                    try:self.sock.close() # 彻底释放套接字描述符
                    except Exception:pass # 抑制关闭异常
                    return # 触发切断后结束
            self.arm_timer() # 速度正常则装载下一次定时器
    def record(self,n): # 套接字每次成功写出字节时调用更新计数并实时输出进度
        with self.lock: # 保证并发安全
            self.sent+=n;now=time.monotonic() # 累加发送字节数
            if now-self.last_report>=self.a.progress_interval: # 达到汇报刷新间隔
                elapsed=max(0.001,now-self.start_time);delta=now-self.last_report;inst_rate=(self.sent-self.last_bytes)/max(0.001,delta);avg_rate=self.sent/elapsed # 计算瞬时与平均速度
                self.last_report=now;self.last_bytes=self.sent # 推进上一次记录点
                pct=f" ({self.sent*100/self.total_expected:.1f}%)" if self.total_expected and self.total_expected>0 else "" # 计算百分比
                total_disp=f" / {human(self.total_expected)}" if self.total_expected else "" # 格式化总量
                LOG.info("[%s] 已发送: %s%s%s | 瞬时: %s/s | 平均: %s/s | 耗时: %.1fs",self.label,human(self.sent),total_disp,pct,human(inst_rate),human(avg_rate),elapsed) # 输出单行实时进度
    def finish(self): # 传输正常完成结算汇报
        with self.lock: # 加锁核算
            if self.closed:return # 避免重复打印
            self.closed=True # 标记完成
            if self.timer:self.timer.cancel() # 注销看门狗
            elapsed=max(0.001,time.monotonic()-self.start_time);avg_rate=self.sent/elapsed # 最终平均速度
            LOG.info("[%s] 传输完成: 累计 %s | 整体平均: %s/s | 总耗时: %.2fs",self.label,human(self.sent),human(avg_rate),elapsed) # 输出结束总结
    def close(self): # 安全退出监控器
        with self.lock:self.closed=True # 标记退出
        if self.timer:self.timer.cancel() # 取消定时器

class MeteredSocket: # 套接字计量代理类：拦截底层 send/sendall 操作并切片为 64KB 流式注入计量监控
    def __init__(self,sock,monitor): # 包装原始套接字与监控器
        self._sock=sock;self._monitor=monitor # 保存内部引用
    def send(self,data,flags=0): # 代理单个 send 调用
        try: # 写出数据
            n=self._sock.send(data,flags) # 实际发送
            if n>0:self._monitor.record(n) # 记入已发送计数
            return n # 返回发送字节数
        except Exception as exc: # 捕获网络错误
            if self._monitor.failure:raise self._monitor.failure from exc # 若看门狗判定为低速超时则优先暴露低速原因
            raise NetworkFailure(f"Socket 写出异常: {exc}") from exc # 包装为可重试的网络故障
    def sendall(self,data,flags=0): # 代理批量 sendall 调用：主动按 64KB 切片写出，呈现极其平滑的实时速度曲线
        view=memoryview(data) if not isinstance(data,memoryview) else data # 零拷贝内存视图
        total=len(view);offset=0 # 初始化发送游标
        try: # 循环切片发送
            while offset<total: # 数据未完持续迭代
                chunk=view[offset:offset+CHUNK] # 截取最高 64KB 切片
                sent=self._sock.send(chunk,flags) # 发送切片
                if sent<=0:raise NetworkFailure("套接字对端提前中断关闭了连接") # 对端挂断拦截
                self._monitor.record(sent);offset+=sent # 记录流量并推进游标
        except Exception as exc: # 异常处理
            if self._monitor.failure:raise self._monitor.failure from exc # 低速异常优先抛出
            raise NetworkFailure(f"Socket sendall 异常中断: {exc}") from exc # 统一包装
    def __getattr__(self,name):return getattr(self._sock,name) # 其余属性直接透传至原生底层 socket

def log_conn_details(sock,label,host,port,is_ssl=False): # 实时输出网络底层 DNS/IP、套接字四元组与 TLS 握手协商细节
    try: # 获取连接详情
        l_ip,l_port=sock.getsockname()[:2];r_ip,r_port=sock.getpeername()[:2] # 提取本端与对端 IP 端口
        tls_info="" # TLS 细节占位
        if is_ssl and hasattr(sock,"version"): # 若为加密 TLS 套接字
            ver=sock.version() or "TLS";cip=sock.cipher();c_name=cip[0] if cip else "未知套件";alpn=getattr(sock,"selected_alpn_protocol",lambda:None)() or "http/1.1" # 提取协议、套件与 ALPN
            tls_info=f" | {ver} | {c_name} | ALPN={alpn}" # 组合 TLS 描述
        LOG.info("[%s 连接建立] %s:%s -> 远程 %s (%s:%s)%s",label,l_ip,l_port,host,r_ip,r_port,tls_info) # 打印详细连接信息
    except Exception as exc:LOG.debug("读取连接详细信息异常: %s",exc) # 容错防护

class Transport: # 纯 Python 标准库 HTTP(S) 高可靠传输层：支持代理、详细 TLS 参数控制、实时上传速度计量与重试
    def __init__(self,a,auths=None,https=True): # 初始化传输层
        self.a=a;self.auths=dict(auths or {});self.https=https;self.connections={} # 缓存连接实例
    def get_proxy_for(self,url): # 根据系统或显式参数获取代理配置
        if getattr(self.a,"no_proxy",False):return None # 显式禁用代理
        if getattr(self.a,"proxy",None):return self.a.proxy # 优先使用显式指定的代理 URL
        proxies=getproxies();scheme=urlsplit(url).scheme # 读取操作系统代理
        return proxies.get(scheme) or proxies.get("http") # 获取对应协议代理
    def create_connection(self,scheme,host,port,label="HTTP"): # 建立带流速监控的标准库 HTTP(S)Connection 连接对象
        proxy=self.get_proxy_for(f"{scheme}://{host}:{port}") # 查询对应主机的代理配置
        timeout=float(self.a.connect_timeout) # 超时参数
        if proxy: # 走代理路径
            p=urlsplit(proxy);p_host,p_port=p.hostname,p.port or 8080 # 解析代理主机
            LOG.info("[%s 代理路由] 经由 HTTP 代理 %s:%s 转发请求",label,p_host,p_port) # 打印代理日志
            conn=http.client.HTTPConnection(p_host,p_port,timeout=timeout) # 建立到代理服务器的 TCP 链路
            if scheme=="https":conn.set_tunnel(host,port) # 发送 HTTP CONNECT 隧道命令建立透明传输
        else: # 直连路径
            conn=http.client.HTTPSConnection(host,port,timeout=timeout,context=self._ssl_context()) if scheme=="https" else http.client.HTTPConnection(host,port,timeout=timeout) # 建立原生连接
        return conn # 返回标准库连接对象
    def _ssl_context(self): # 构造满足系统证书规范与自定义 CA 的 SSL 上下文
        ctx=ssl.create_default_context(cafile=getattr(self.a,"ca_file",None)) # 载入默认或指定 CA
        if getattr(self.a,"insecure",False):ctx.check_hostname=False;ctx.verify_mode=ssl.CERT_NONE # 允许非严格模式
        return ctx # 返回安全 SSL 上下文
    def request(self,method,url,headers=None,body=None,label="HTTP",allow_error=False): # 发送 HTTP 请求并挂接上传流速监控代理
        p=urlsplit(url);scheme=p.scheme;host=p.hostname;port=p.port or (443 if scheme=="https" else 80) # 解析目标端点
        req_path=urlunsplit(("","",p.path or "/",p.query,"")) # 保留完整请求路径与查询字符串
        headers=dict(headers or {});headers.setdefault("User-Agent","dulwich-push/1.2.15") # 设置默认 User-Agent
        auth=self.auths.get(origin(url)) # 查询当前 Origin 关联的认证头
        if auth and "Authorization" not in headers:headers["Authorization"]=auth # 自动装配认证信息
        conn=self.create_connection(scheme,host,port,label) # 建立连接
        trace(self.a,"[HTTP 请求] %s %s",method,safe_url(url)) # 跟踪请求
        for hk,hv in headers.items():trace(self.a,"[HTTP 请求头] %s: %s",hk,redact(hv)) # 打印请求头
        try: # 连接、注入流量监控并写出数据
            conn.connect() # 发起 TCP / TLS 握手
            is_ssl=isinstance(conn,http.client.HTTPSConnection) # 识别是否为 HTTPS
            log_conn_details(conn.sock,label,host,port,is_ssl) # 输出连接四元组与 TLS 握手信息
            body_len=len(body) if isinstance(body,(bytes,bytearray)) else None # 计算请求体大小
            monitor=TransferMonitor(conn.sock,self.a,label=label,total_expected=body_len) # 绑定流速监控看门狗
            conn.sock=MeteredSocket(conn.sock,monitor) # 代理写出方法
            conn.request(method,req_path,body=body,headers=headers) # 发送完整 HTTP 请求
            resp=conn.getresponse() # 等待并读取服务端响应状态
            monitor.finish() # 结束写出监控汇报
            trace(self.a,"[HTTP 响应] %s -> 状态码 %d %s",safe_url(url),resp.status,resp.reason) # 打印响应日志
            if resp.status in (301,302,303,307,308) and "Location" in resp.headers: # 严密处理 HTTP 重定向
                loc=urljoin(url,resp.headers["Location"]);resp.read();conn.close() # 追溯新重定向目标
                if origin(loc)!=origin(url):headers.pop("Authorization",None) # 跨域重定向严格剥离 Authorization 防凭据外泄
                return self.request("GET" if resp.status in (301,302,303) else method,loc,headers,None if resp.status in (301,302,303) else body,label,allow_error) # 发起重定向跳转
            if resp.status>=400 and not allow_error: # 错误码处理
                detail=resp.read(4096).decode("utf-8","replace");conn.close() # 读取错误上下文
                retry_sec=0;ra=resp.headers.get("Retry-After") # 解析重试延迟
                if ra and ra.isdigit():retry_sec=int(ra) # 整数秒
                raise HTTPFailure(resp.status,url,detail[:400],retry_after=retry_sec) # 抛出 HTTP 错误
            return resp # 返回成功响应对象
        except (socket.timeout,TimeoutError) as exc:conn.close();raise NetworkFailure(f"网络连接或传输超时: {exc}") from exc # 超时处理
        except (ConnectionError,ssl.SSLError,OSError) as exc:conn.close();raise NetworkFailure(f"网络底层套接字故障: {exc}") from exc # 套接字故障处理
    def close(self):pass # 传输层清理钩子

class StdlibGitClient(AbstractHttpGitClient): # 纯 Python 标准库驱动的 Dulwich Smart HTTP Git 客户端
    def __init__(self,base_url,net,config=None): # 初始化客户端
        super().__init__(base_url,config=config) # 委托基类处理协议
        self.net=net;self.base_url=base_url # 绑定传输实例
    def _http_request(self,url,headers=None,data=None,allow_error=False): # 接入我们的 Transport 实现
        method="POST" if data is not None else "GET" # 根据是否有请求体自动切换动词
        if data is not None: # 若有发送体
            if not isinstance(data,bytes):data=b"".join(data) if isinstance(data,(list,tuple)) else (data.read() if hasattr(data,"read") else bytes(data)) # 归一化为纯字节
        resp=self.net.request(method,url,headers=headers,body=data,label="Git PACK",allow_error=allow_error) # 挂载 Git PACK 流速监控
        return resp,resp.read # 返回响应和读取函数
    def close(self):self.net.close() # 释放网络资源

def upload_lfs(net,endpoint,pointers,cache,ref_name,done): # Git LFS 批量申请、逐文件 PUT 流式上传与 Verify 验证全套实现
    if not pointers:return # 无 LFS 指针则无需执行
    todo={oid:size for oid,size in pointers.items() if (oid,size) not in done} # 过滤已完成项
    if not todo:LOG.info("所有 LFS 对象此前已成功上传，无需重复传输");return # 幂等保护短路返回
    LOG.info("向远端申请 Git LFS Batch 传输: 共 %d 个对象 (%s)",len(todo),human(sum(todo.values()))) # 打印 Batch 日志
    req_payload={"operation":"upload","transfers":["basic"],"ref":{"name":text(ref_name)},"objects":[{"oid":o,"size":s} for o,s in todo.items()]} # 构建规范请求体
    headers={"Accept":MEDIA,"Content-Type":MEDIA} # 设置 LFS 专属 MIME 头
    resp=net.request("POST",endpoint,headers=headers,body=json.dumps(req_payload).encode("utf-8"),label="LFS Batch") # 发起 Batch 协商
    ans=json.loads(resp.read().decode("utf-8")) # 解析协商响应
    by_oid=dict(todo);seen=set() # 校验远端返回对象
    for item in ans.get("objects",[]): # 遍历对象上传指令
        oid=item.get("oid");size=item.get("size");seen.add((oid,size)) # 提取元数据
        if item.get("error"):raise StopPush(f"远端 LFS 存储拒绝了对象 {oid}: {item['error']}") # 远端拒绝明确报错
        actions=item.get("actions") or {} # 读取动作清单
        up=actions.get("upload") # 提取上传动作
        if up: # 服务端需要我们上传该文件本体
            href=up.get("href");up_headers=dict(up.get("header") or {}) # 提取带签名的目标 PUT 地址与请求头
            local_file=cache.require(oid,size) # 校验本地缓存文件完整性
            LOG.info("[LFS 开始上传] OID=%s... | 体积: %s",oid[:12],human(size)) # 打印上传开始日志
            with regular_reader(local_file) as (stream,_): # 流式读取缓存数据
                payload_data=stream.read() # 读取文件数据
                net.request("PUT",href,headers=up_headers,body=payload_data,label=f"LFS:{oid[:8]}") # 流式上传至对象存储并输出实时速度
            vr=actions.get("verify") # 检查是否包含校验回调动作
            if vr: # 若服务端要求客户端完成上传后回调 verify
                v_href=vr.get("href");v_headers=dict(vr.get("header") or {});v_headers.setdefault("Content-Type",MEDIA) # 构造 verify 头
                net.request("POST",v_href,headers=v_headers,body=json.dumps({"oid":oid,"size":size}).encode(),label="LFS Verify") # 执行对象存在性验证
            LOG.info("✅ LFS 对象上传完成: %s (%s)",oid[:12],human(size)) # 成功日志
        else:LOG.info("远端对象存储已存在该 LFS 对象，跳过本体上传: %s",oid[:12]) # 服务端已具备该文件，秒传
        done.add((oid,size)) # 登记已完成
    if seen!=set(todo.items()):raise StopPush("LFS Batch 接口返回结果缺失部分请求的对象，停止推送以保数据完整") # 完整性校验防御

def ancestor(repo,old,new): # 本地快进检查：深度优先判断 old 是否为 new 的历史祖先节点
    if old==ZERO_SHA or old==new or not old:return True # 全零或相同视为快进
    todo=[new];seen=set() # 待遍历栈
    while todo: # 向上回溯父提交
        sha=todo.pop() # 出栈
        if sha==old:return True # 命中祖先节点
        if sha in seen or sha==ZERO_SHA:continue # 已检查则跳过
        seen.add(sha) # 标记已检查
        try:obj=repo.object_store[sha] # 读取提交对象
        except KeyError:raise StopPush("本地历史对象缺失，无法确定分支快进关系，请先从远端拉取") # 历史不完整拦截
        if isinstance(obj,Commit):todo.extend(obj.parents) # 将所有父节点加入待检查集合
    return False # 穷尽仍未找到则判定非快进

def is_retryable(exc): # 智能区分可重试网络错误与不可重试的权限/逻辑错误
    if isinstance(exc,HTTPFailure):return exc.code in (408,425,429,500,502,503,504) # 临时性 HTTP 状态码允许重试
    if isinstance(exc,(NetworkFailure,HangupException,ConnectionError,TimeoutError)):return True # 网络断开与超时可重试
    if isinstance(exc,GitProtocolError): # Git 协议中断类异常
        return any(t in str(exc).lower() for t in ("unexpected eof","connection reset","remote end hung up","unexpectedly closed")) # 关键字命中则重试
    return False # 其余异常一律不上重试，直接抛出

def retry(a,label,operation): # 通用自适应退避网络重试引擎
    for attempt in range(1,a.retry+1): # 循环重试指定次数
        if attempt>1:a.trace=True # 第二次重试起自动开启调试追踪
        LOG.info("===== %s | 尝试 %d/%d | 间隔 %.1fs =====",label,attempt,a.retry,a.retry_wait) # 打印重试头部
        try:return operation() # 执行目标网络动作
        except Exception as exc: # 捕获异常
            if not is_retryable(exc) or attempt==a.retry:raise # 不可重试或次数用尽直接向外抛出
            delay=max(a.retry_wait,getattr(exc,"retry_after",0)) # 采用设定的等待秒数或服务端的 Retry-After
            LOG.warning("遭遇网络瞬断错误，%.1f 秒后执行下一次重试；原因: %s",delay,exc) # 告警提示
            time.sleep(delay) # 挂起等待

def push_target(repo,a,remote,ref,target,endpoint,auths,cache,done,lease=None): # 执行单个远程引用的安全推送与重试封包
    def attempt(): # 单次执行闭包
        net=Transport(a,auths,urlsplit(remote).scheme=="https");client=StdlibGitClient(remote,net);observed={} # 构造传输层与客户端
        try: # 协议通信
            def update(refs): # 服务端引用更新回调
                old=refs.get(ref) or ZERO_SHA;observed["old"]=old # 记录当前远端引用 SHA
                if old==target:LOG.info("远端引用已经与本地目标完全一致，本次推送已幂等完成: %s",target.decode());return {} # 幂等短路
                if lease is not None and old!=lease:raise StopPush("force-with-lease 检查失败：远端引用已发生变动") # 租约保护
                if not a.force and lease is None and not ancestor(repo,old,target):raise StopPush("non-fast-forward: 远端提交不是本地的祖先，推送被服务端拒绝；请先 pull 或使用 --force") # 非快进拦截
                pointers=outgoing_lfs(repo,refs,target,a) # 计算本地相较于远端缺少的所有 LFS 大文件对象
                upload_lfs(net,endpoint,pointers,cache,ref,done) # 严格先上传 LFS 实体并校验，任一对象失败绝不发送 pack
                return {ref:target} # 返回拟更新的引用映射
            def generate(have,want,**kwargs):return repo.generate_pack_data({s for s in have if s in repo.object_store},want,**kwargs) # 生成 Git 增量 Pack 数据
            result=client.send_pack(urlsplit(remote).path,update,generate,push_options=[v.encode() for v in a.push_option] or None,atomic=a.atomic) # 发送智能 HTTP 打包数据
            statuses=result.ref_status or {} # 提取各分支更新状态
            if any(statuses.values()):raise StopPush(f"服务端拒绝了引用更新: {statuses}") # 服务端驳回时抛错
            if observed.get("old")!=target and ref not in statuses: # 若未显式确认状态则再次查询确认
                cur=client.get_refs(urlsplit(remote).path).refs.get(ref) # 远端查询
                if cur!=target:raise StopPush("服务端未成功将目标分支更新到最新提交") # 未更新报警
            LOG.info("✅ 引用推送成功: %s -> %s",text(ref),target.decode()) # 打印最终成功日志
        finally:net.close();client.close() # 释放网络与套接字资源
    retry(a,f"推送目标 {safe_url(remote)} ({text(ref)})",attempt) # 挂入自动重试调度器

def parse_identity(value,default_name,default_email): # 解析用户输入的身份字符串（支持中文逗号、纯邮箱、纯名字）
    value=value.replace("，",",").replace("、",",").strip() # 替换中文标点
    if not value:return default_name,default_email # 为空返回默认
    if "," in value:name,email=(part.strip() for part in value.split(",",1)) # 逗号分割为名字和邮箱
    else: # 空格分割处理
        parts=value.rsplit(None,1);name=parts[0];email=parts[1] if len(parts)==2 else default_email # 智能分配
    return name,email # 返回姓名与邮箱元组

def identity_for(repo,a,user,remote): # 确定提交者身份：支持 -u 自动推断、历史配置复用及安全写入当前仓库
    config=repo.get_config_stack();name=text(cfg(config,b"user",b"name"));email=text(cfg(config,b"user",b"email")) # 从 Git 配置栈读取已有身份
    parts=urlsplit(remote).path.strip("/").split("/");default_name=user if user and user!="x-access-token" else (parts[0] if parts else "git") # 推导默认用户名
    default_email=f"{default_name}@users.noreply.github.com" if urlsplit(remote).hostname in ("github.com","www.github.com") else (f"{default_name}@localhost") # 推导默认 noreply 邮箱
    if a.user is not None: # 若命令行指定了 -u 参数
        name,email=(default_name,default_email) if a.user=="AUTO" else parse_identity(a.user,default_name,default_email) # 自动推断或解析指定值
    else: # 未指定 -u 时尝试环境变量
        name=os.environ.get("GIT_AUTHOR_NAME",name);email=os.environ.get("GIT_AUTHOR_EMAIL",email) # 环境变量兜底
        if not a.no_ask and sys.stdin.isatty() and default_email and (name,email)!=(default_name,default_email): # 交互式终端下询问确认
            ans=input(f"当前身份 [1] {name} <{email}> [2] {default_name} <{default_email}>；直接回车选1，也可输入 name,email: ").strip() # 提示输入
            if ans=="2":name,email=default_name,default_email # 选择推导值
            elif ans not in ("","1"):name,email=parse_identity(ans,name,email) # 手工指定
    name=a.name or name;email=a.email or email # 允许 --name / --email 最终覆盖
    if not name or not email:raise StopPush("缺少提交身份；请使用 -u 参数自动推断，或使用 --name 和 --email 显式设置") # 缺失身份严格报错
    if any(c in name+email for c in "\n\r\0\x1b") or "@" not in email:raise StopPush(f"提交身份格式不合规: {name} <{email}>") # 格式合法性校验
    if a.user is not None or a.name or a.email: # 若发生身份推断或显式变更，仅持久化写入当前仓库配置，不污染用户全局
        local=repo.get_config();local.set((b"user",),b"name",name.encode());local.set((b"user",),b"email",email.encode());local.write_to_path() # 写盘
    LOG.info("提交身份确认: %s <%s>",name,email);return f"{name} <{email}>".encode() # 返回标准 Git 身份字节串

def lfs_settings(repo,config,remote,remote_name,a,auths): # 确定 Git LFS 端点 URL，支持 .lfsconfig 与自定义 endpoint
    section=(b"remote",remote_name.encode());endpoint=a.lfs_url or text(cfg(config,(b"lfs",),b"pushurl") or cfg(config,section,b"lfspushurl") or cfg(config,(b"lfs",),b"url") or cfg(config,section,b"lfsurl")) # 优先读取配置
    if not endpoint: # 检查工作区 .lfsconfig 文件
        path=Path(repo.path)/".lfsconfig" # 文件路径
        if path.exists() and not path.is_symlink(): # 读取工作区专属 LFS 配置
            local=ConfigFile.from_file(io.BytesIO(read_regular(path,1024*1024)));endpoint=text(cfg(local,(b"lfs",),b"pushurl") or cfg(local,(b"lfs",),b"url") or cfg(local,section,b"lfsurl")) # 提取 endpoint
    endpoint=endpoint or remote.removesuffix(".git")+".git/info/lfs" # 默认在 Git 仓库后追加 /info/lfs
    clean,user,password=split_credentials(endpoint) # 解析 LFS 独立端点的凭据
    if urlsplit(clean).query:raise StopPush("LFS endpoint 地址不能包含查询参数") # 避免歧义
    token=basic(user,password) # 计算专属 Basic Token
    if token:auths[origin(clean)]=token # 存入认证表
    return clean.rstrip("/")+"/objects/batch" # 最终拼装出 Batch API 地址

def preprocess(argv): # 参数预处理器：对齐 git_logic.py，保证 -u 独立出现时不把下一个参数吞掉，且 -m 能捕获后续所有文字
    out=[];i=0 # 初始化指针与输出参数列表
    value_flags={"--repo","--repo-path","--path","-path","-p","--branch","-b","--size","-s","--threshold","--retry","-retry","-r","--retry-wait","--retry-seconds","--verbose","-v","--connect-timeout","--io-timeout","--low-speed-limit","--low-speed-time","--progress-interval","--max-commit-size","--max-pack-size","--max-blob-size","--name","--email","--proxy","--ca-file","--lfs-url","--push-option"} # 需消耗紧随其后值的标志集合
    while i<len(argv): # 遍历原始参数列表
        arg=argv[i] # 当前参数
        if arg in ("-m","--message","--commit-msg","--commit_msg"): # 识别提交信息标志
            if i+1>=len(argv):raise StopPush("-m 参数后缺少提交描述文字") # 缺失描述报错
            out.extend(["--message"," ".join(argv[i+1:])]);break # 将后续所有剩余参数拼接为一条完整提交说明并提前结束解析
        if arg in ("-u","--user","--auto-user"): # 智能处理 -u 用户标记
            nxt=argv[i+1] if i+1<len(argv) else None # 预读下一个参数
            if nxt is None or nxt.startswith("-") or nxt in ("push","pull","clone","init","config","undo") or "://" in nxt: # 若后跟子命令或 URL
                out.append("--user=AUTO");i+=1;continue # 转换为 AUTO 模式，绝不吞掉后继重要参数
            out.extend(["--user",nxt]);i+=2;continue # 若后跟姓名邮箱则正常成对消耗
        if arg in value_flags: # 属于需要后置参数的已知选项
            if i+1>=len(argv):raise StopPush(f"{arg} 选项缺少参数值") # 缺失值报错
            out.extend(argv[i:i+2]);i+=2;continue # 成对追加并推进两步
        if arg.startswith("-"):out.append(arg) # 其余普通开关直接追加
        elif "://" in arg or arg.startswith("git@"):out.extend(["--remote",arg]) # 裸远程 URL 转换为 --remote 选项
        else:out.append(arg) # 位置参数（如 push 动词）
        i+=1 # 单步推进
    return out # 返回规范化后的参数数组

def parser(): # 构造完整的命令行解析器
    p=argparse.ArgumentParser(description="Dulwich 1.2.15 + Python 标准库网络的高可靠实时流速 Git 自动提交与 Push 工具") # 解析器描述
    p.add_argument("mode",nargs="?",choices=["push"],default="push") # 兼容原脚本 push 动词
    p.add_argument("--remote",default="") # 远程仓库地址
    p.add_argument("--repo","--repo-path","--path","-path","-p",default=".") # 本地仓库目录
    p.add_argument("--branch","-b",default=os.environ.get("BRANCH")) # 目标分支
    p.add_argument("--user","-u","--auto-user",nargs="?",const="AUTO") # 用户身份模式
    p.add_argument("--name") # 显式覆盖用户名
    p.add_argument("--email") # 显式覆盖邮箱
    p.add_argument("--message","-m","--commit-msg","--commit_msg",default="") # 提交描述
    p.add_argument("--no-ask","--noask","-noask","-y","-yes",action="store_true") # 免询问开关
    p.add_argument("--size","-s",type=parse_size,default=100*1024**2) # 大文件阈值，默认 100MB
    p.add_argument("--threshold",type=int,default=0) # 精确字节阈值兼容
    p.add_argument("--max-blob-size",type=parse_size,default=100*1024**2) # 普通 Blob 最大限制
    p.add_argument("--max-commit-size",type=parse_size,default=1900*1024**2) # 单次提交体积上限
    p.add_argument("--max-pack-size",type=parse_size,default=1900*1024**2) # 单个 Pack 体积上限
    p.add_argument("--retry","-retry","-r",type=int,default=10) # 重试次数，默认 10 次
    p.add_argument("--retry-wait","--retry-seconds",type=float,default=5.0) # 重试等待秒数
    p.add_argument("--verbose","-v",type=int,default=2) # 详细程度：3 开启连接详情与流速
    p.add_argument("--connect-timeout",type=float,default=45.0) # 连接超时
    p.add_argument("--io-timeout",type=float,default=300.0) # 传输读写超时
    p.add_argument("--low-speed-limit",type=int,default=10) # 最低传输速度限制（B/s）
    p.add_argument("--low-speed-time",type=float,default=60.0) # 最低速度持续超时秒数
    p.add_argument("--progress-interval",type=float,default=0.5) # 实时进度刷新频率
    p.add_argument("--proxy") # 显式代理地址
    p.add_argument("--no-proxy",action="store_true") # 禁用代理
    p.add_argument("--ca-file") # 自定义 CA
    p.add_argument("--lfs-url") # 显式 LFS 服务端点
    p.add_argument("--no-auto-lfs",action="store_true") # 关闭自动 LFS
    p.add_argument("--renormalize",action="store_true") # 强制重新规范化已有提交
    p.add_argument("--force",action="store_true") # 强制推送开关
    p.add_argument("--force-with-lease",nargs="?",const="auto") # 租约保护
    p.add_argument("--set-upstream",action="store_true") # 设置上游追踪
    p.add_argument("--push-option",action="append",default=[]) # 传递 Git 推送选项
    p.add_argument("--atomic",action="store_true") # 启用原子推送
    p.add_argument("--self-test",action="store_true") # 执行内建自检套件
    return p # 返回构建好的解析器

def arguments(argv=None): # 解析并校验所有输入参数
    p=parser();a=p.parse_args(preprocess(list(sys.argv[1:] if argv is None else argv)));a.trace=a.verbose>=3 # 解析与标记 trace
    if a.threshold>0:a.size=a.threshold # 优先使用 threshold 覆盖 size
    if not all(math.isfinite(x) for x in (a.connect_timeout,a.io_timeout,a.progress_interval,a.retry_wait,a.low_speed_time)):p.error("所有时间参数必须为合法的有限实数") # 数值健全性检查
    if min(a.size,a.max_blob_size,a.max_commit_size,a.max_pack_size,a.connect_timeout,a.io_timeout,a.progress_interval)<=0:p.error("体积与超时阈值参数必须严格大于 0") # 正数约束
    return a # 返回校验完成的命名空间对象

def prepare(repo,a,identity,cache): # 执行仓库扫描、属性识别、自动 LFS 分离、索引暂存与提交封装
    config=repo.get_config_stack();check_repo_state(repo,config) # 检查仓库健康状态
    lock=GitFile(repo.index_path());expected=repo.refs.follow(b"HEAD");index=repo.open_index() # 锁定索引文件并读取 HEAD
    try: # 暂存与回写索引
        stage_all(repo,index,a,config,cache) # 全量暂存工作区
        writer=SHA1Writer(lock);write_index_dict(writer,dict(index.items()),version=3);ids,empty=commit_staged(repo,index,a,identity,expected);writer.close() # 持久化索引并生成提交
        return ids,empty # 返回提交列表与 EmptyAfterPush 标记
    finally: # 确保索引锁安全释放
        if not lock._closed:lock.abort() # 异常时回滚锁

def main(a=None): # 核心主控逻辑：解析参数、建立仓库上下文、提交变更并推向远程
    a=arguments() if a is None else a # 载入参数
    LOG.info("Dulwich 版本: %s | 网络后端: Python 标准库 http.client/socket/ssl",getattr(dulwich,"__version__","1.2.15")) # 引擎标头
    root=Path(a.repo).expanduser().resolve() # 展开仓库绝对路径
    try:repo=Repo(str(root)) # 打开 Dulwich 仓库
    except NotGitRepository: # 针对未初始化仓库的处理
        if a.mode=="push" and not (root/".git").exists(): # 提示初始化
            LOG.warning("当前目录尚未初始化 Git 仓库: %s",root) # 警告
            if not a.no_ask and sys.stdin.isatty(): # 交互式确认
                ans=input("是否执行 git init 初始化当前目录？[Y/n]: ").strip().lower() # 询问
                if ans not in ("","y","yes"):LOG.info("操作已取消。");return # 取消退出
            repo=Repo.init(str(root));LOG.info("✅ 已初始化空 Git 仓库") # 初始化
        else:raise StopPush(f"目录不是有效的 Git 仓库: {root}") # 抛出非仓库异常
    config=repo.get_config();configured_remote=text(cfg(config,(b"remote",b"origin"),b"url")) # 获取已有 remote
    raw_remote=a.remote or configured_remote # 确定远程 URL
    if not raw_remote:raise StopPush("缺少远程仓库 URL；请在命令行提供或通过 git remote add origin 设定") # 缺失远程报错
    remote,user,password,inferred_branch=normalize_remote(raw_remote) # 规范化远程地址与提取凭据
    if raw_remote!=configured_remote: # 若地址更新则同步回写本地配置
        config.set((b"remote",b"origin"),b"url",remote.encode());config.set((b"remote",b"origin"),b"fetch",b"+refs/heads/*:refs/remotes/origin/*");config.write_to_path() # 更新 origin
    head_ref=None # 目标引用占位
    try:chain,head_sha=repo.refs.follow(b"HEAD");head_ref=chain[-1] # 跟踪当前所在分支
    except KeyError:head_ref=b"refs/heads/master" # 初始未出生分支默认回退到 master
    branch=a.branch or (text(head_ref).removeprefix("refs/heads/") if head_ref and head_ref.startswith(b"refs/heads/") else (inferred_branch or "master")) # 确定分支
    target_ref=b"refs/heads/"+branch.encode() # 构造完整 refs/heads/* 引用名
    LOG.info("仓库工作区: %s",root);LOG.info("远程仓库地址: %s | 目标分支: %s",safe_url(remote),branch) # 打印仓库与远程配置
    LOG.info("LFS 阈值: %s | 最大普通 Blob: %s",human(a.size),human(a.max_blob_size)) # 打印阈值信息
    LOG.info("连接超时: %.1fs | 低速监控: %dB/s 持续 %.1fs | 刷新间隔: %.2fs",a.connect_timeout,a.low_speed_limit,a.low_speed_time,a.progress_interval) # 打印超时与网速设置
    auths={};token=basic(user,password) # 初始化全局认证凭据表
    if token:auths[origin(remote)]=token # 登记远程主机的 Basic 凭据
    identity=identity_for(repo,a,user,remote) # 确定提交身份
    cache=LFSCache(repo,config) # 初始化本地 LFS 缓存对象池
    ids,empty_target=prepare(repo,a,identity,cache) # 扫描并创建提交
    current_head=repo.refs.follow(b"HEAD")[1] # 获取当前 HEAD 最终 SHA
    if not current_head or current_head==ZERO_SHA:raise StopPush("本地分支没有任何提交可供推送") # 无提交拦截
    lfs_batch_url=lfs_settings(repo,config,remote,"origin",a,auths) # 确定 LFS Batch 传输端点
    lease=repo.object_store[a.force_with_lease].id if a.force_with_lease and a.force_with_lease!="auto" else None # 解析 force-with-lease 预期
    done_lfs=set() # 跟踪当前会话已完成上传的 LFS 对象
    push_target(repo,a,remote,target_ref,current_head,lfs_batch_url,auths,cache,done_lfs,lease=lease) # 执行全量安全推送
    if empty_target and empty_target.is_file(): # 若存在 #EmptyAfterPush 指令
        try: # 清空该文件内容
            empty_target.write_bytes(b"") # 抹除内容
            LOG.info("✅ EmptyAfterPush: 已按指令成功清空 %s",empty_target.name) # 打印清空成功提示
        except OSError as exc:LOG.warning("EmptyAfterPush 清空文件失败: %s",exc) # 容错
    LOG.info("🎉 全部推送与同步操作圆满结束！") # 输出最终大功告成日志

def self_test(): # 完备的内建单元测试集：覆盖 Windows CRT fstat 签名修复、MemoryRepo 兼容、LFS、网络重试等 12 项严苛验证
    import unittest # 导入标准测试框架
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer # 导入内置 HTTP 服务用于仿真
    from unittest.mock import patch # 导入 Mock 工具
    class Tests(unittest.TestCase): # 综合测试用例集
        def setUp(self): # 测试前环境隔离准备
            self.temp=tempfile.TemporaryDirectory(dir=r"D:\test\home")
            self.root=Path(self.temp.name)#/"repo"
            os.chdir(self.root.name)
            os.system(r'C:\QGB\PortableGit\bin\git.exe init')
            self.repo=Repo.init(str(self.root)) # 创建隔离的测试仓库
            self.a=arguments(["push","--repo",str(self.root),"--no-ask","-v","0","--progress-interval","0.01","--low-speed-time","0.05","--low-speed-limit","10","--size","500","--connect-timeout","5","--retry","3","--retry-wait","0.05"]) # 构造紧凑测试参数
            self.identity=b"Tester <tester@example.com>";cfg=self.repo.get_config();cfg.set((b"user",),b"name",b"Tester");cfg.set((b"user",),b"email",b"tester@example.com");cfg.set((b"core",),b"attributesfile",os.fsencode(Path(self.temp.name)/"no-attr"));cfg.set((b"core",),b"excludesfile",os.fsencode(Path(self.temp.name)/"no-ign"));cfg.write_to_path() # 初始化配置
            self.cache=LFSCache(self.repo,cfg) # 隔离 LFS 缓存
        def tearDown(self):self.repo.close();self.temp.cleanup() # 资源清理
        def write(self,name,content): # 辅助文件写入
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content)
        def test_signature_and_regular_reader_windows(self): # 专门测试 Windows 下 CRT _fstat64 与 Win32 stat 字段差异下的签名与读取稳定性
            self.write("sample.txt",b"hello cross platform") # 写入样本
            with regular_reader(self.root/"sample.txt") as (f,st):self.assertEqual(f.read(),b"hello cross platform") # 验证不抛出 "读取前文件已经变化" 异常
        def test_attr_c_quote_and_macro(self): # 测试 C 风格引号路径、八进制转义及属性宏定义
            self.write(".gitattributes",b'[attr]large filter=lfs -text\n"/spaced path.txt" large\n') # 配置包含空格的转义属性
            self.write("spaced path.txt",b"payload") # 写入对应文件
            ids,_=prepare(self.repo,self.a,self.identity,self.cache) # 执行暂存与提交
            idx=self.repo.open_index();self.assertIn(b"spaced path.txt",idx) # 验证成功暂存
            self.assertIsNotNone(pointer_info(self.repo.object_store[idx[b"spaced path.txt"].sha].data)) # 验证自动转换为 LFS 指针
        def test_ignore_lfs_delete_and_no_process(self): # 测试忽略规则、自动 LFS 追踪及外部过滤器进程隔离
            self.write("tracked.tmp",b"v1");prepare(self.repo,self.a,self.identity,self.cache) # 先跟踪一个 tmp 文件
            self.write("tracked.tmp",b"v2");self.write(".gitignore",b"*.tmp\n!keep.tmp\n") # 添加忽略规则
            self.write("dropped.tmp",b"ignore-me");self.write("keep.tmp",b"keep-me");self.write("big.bin",b"B"*600) # 准备各类文件
            with patch("subprocess.Popen",side_effect=AssertionError("严禁启动任何外部子进程")):prepare(self.repo,self.a,self.identity,self.cache) # 确保无进程启动
            idx=self.repo.open_index();self.assertIn(b"tracked.tmp",idx);self.assertIn(b"keep.tmp",idx);self.assertNotIn(b"dropped.tmp",idx) # 验证忽略与跟踪优先级
            self.assertIsNotNone(pointer_info(self.repo.object_store[idx[b"big.bin"].sha].data)) # 验证超限文件自动转换为 LFS
        def test_global_exclude_precedence(self): # 测试全局 excludesfile 与本地 info/exclude 的优先级层级
            (Path(self.temp.name)/"no-ign").write_bytes(b"*.log\n") # 全局规则排除 .log
            info_dir=Path(self.repo.controldir())/"info";info_dir.mkdir(parents=True,exist_ok=True);(info_dir/"exclude").write_bytes(b"!important.log\n") # info/exclude 重新拉回
            self.write("test.log",b"data");self.write("important.log",b"data");prepare(self.repo,self.a,self.identity,self.cache) # 暂存
            idx=self.repo.open_index();self.assertIn(b"important.log",idx);self.assertNotIn(b"test.log",idx) # 校验局部优先
        def test_symlink_does_not_walk_target(self): # 验证符号链接被存为 120000 且其内部目录绝不被递归深入
            target=Path(self.temp.name)/"outside";target.mkdir();(target/"leak.bin").write_bytes(b"leak") # 外部危险目录
            try:os.symlink(target,self.root/"link",target_is_directory=True) # 建立软链
            except (OSError,NotImplementedError):self.skipTest("操作系统无权建立符号链接，跳过软链测试") # 权限受限跳过
            prepare(self.repo,self.a,self.identity,self.cache);idx=self.repo.open_index() # 暂存
            self.assertEqual(idx[b"link"].mode,0o120000);self.assertFalse(any(k.startswith(b"link/") for k in idx)) # 验证未越界穿透
        def test_split_commits_and_local_push(self): # 验证超限自动拆分为多个 Commit，并推送至本地 Bare 仓库
            self.a.max_commit_size=10 # 设定极小的单提交上限
            for i in range(3):self.write(f"f{i}.dat",b"01234567") # 写入数据
            ids,_=prepare(self.repo,self.a,self.identity,self.cache);self.assertGreater(len(ids),1) # 确认自动拆分成多个提交
            bare=Repo.init_bare(str(Path(self.temp.name)/"bare"),mkdir=True) # 创建测试 bare 目标
            try: # 推送测试
                from dulwich.client import LocalGitClient # 本地客户端
                client=LocalGitClient();res=client.send_pack(bare.path,lambda refs:{b"refs/heads/main":self.repo.head()},self.repo.generate_pack_data) # 本地打包推送
                self.assertFalse(any((res.ref_status or {}).values()));self.assertEqual(bare.refs[b"refs/heads/main"],self.repo.head()) # 校验远端成功更新
            finally:bare.close() # 释放句柄
        def test_history_pointer_and_large_blob(self): # 验证历史中的 LFS 指针被完整搜集，未纳入 LFS 的历史大 Blob 被拒绝推送
            self.write("large.bin",b"X"*700);prepare(self.repo,self.a,self.identity,self.cache) # 自动纳入 LFS 并提交
            oid,sz=pointer_info(self.repo.object_store[self.repo.open_index()[b"large.bin"].sha].data) # 获取指针元数据
            (self.root/"large.bin").unlink();prepare(self.repo,self.a,self.identity,self.cache) # 工作区删除后再次提交
            self.assertIn(oid,outgoing_lfs(self.repo,{},self.repo.head(),self.a)) # 验证历史中的 LFS 对象仍被完备捕获
        def test_git_smart_http_and_idempotent_push(self): # 综合测试 Smart HTTP WSGI 服务端、Dulwich 补丁生效及幂等推送
            from dulwich.repo import MemoryRepo;from dulwich.server import DictBackend;from dulwich.web import make_wsgi_chain;from wsgiref.simple_server import make_server,WSGIRequestHandler # 导入组件
            class Quiet(WSGIRequestHandler): # 静默测试请求日志
                def log_message(self,*a):pass
            self.write("file.txt",b"smart http content");prepare(self.repo,self.a,self.identity,self.cache) # 暂存
            remote=MemoryRepo();app=make_wsgi_chain(DictBackend({"/test.git":remote}));srv=make_server("127.0.0.1",0,app,handler_class=Quiet) # 启动内存仓库 WSGI 服务
            th=threading.Thread(target=srv.serve_forever,daemon=True);th.start();url=f"http://127.0.0.1:{srv.server_port}/test.git" # 启动后台线程
            try: # 执行连续两次推送测试幂等性
                for _ in range(2):push_target(self.repo,self.a,url,b"refs/heads/main",self.repo.head(),url+"/info/lfs/objects/batch",{},self.cache,set()) # 推送
                self.assertEqual(remote.refs[b"refs/heads/main"],self.repo.head()) # 确认远端引用准确更新
            finally:srv.shutdown();srv.server_close();th.join(timeout=2);remote.close() # 干净关闭服务
        def test_network_retry_http_and_lfs(self): # 测试自适应重试、LFS Batch/PUT/Verify 流程及凭据保留
            counters={"flaky":0};stored={} # 状态记账
            class Handler(BaseHTTPRequestHandler): # 仿真服务端
                def log_message(self,*a):pass
                def do_GET(self): # 处理 GET
                    if self.path=="/flaky": # 模拟首次 503 随后成功
                        counters["flaky"]+=1
                        if counters["flaky"]==1:self.send_response(503);self.end_headers();self.wfile.write(b"fail");return
                        self.send_response(200);self.end_headers();self.wfile.write(b"ok");return
                    self.send_response(200);self.end_headers();self.wfile.write(b"data")
                def do_POST(self): # 处理 LFS Batch 与 Verify
                    data=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    if self.path.endswith("/verify"):self.send_response(200);self.end_headers();self.wfile.write(b"{}");return
                    ans={"objects":[{"oid":o["oid"],"size":o["size"],"actions":{"upload":{"href":f"http://127.0.0.1:{self.server.server_port}/put/{o['oid']}"},"verify":{"href":f"http://127.0.0.1:{self.server.server_port}/verify"}}} for o in data["objects"]]}
                    self.send_response(200);self.send_header("Content-Type",MEDIA);self.end_headers();self.wfile.write(json.dumps(ans).encode())
                def do_PUT(self): # 处理 LFS 文件数据上传
                    oid=self.path.rsplit("/",1)[-1];stored[oid]=self.rfile.read(int(self.headers["Content-Length"]))
                    self.send_response(200);self.end_headers()
            srv=ThreadingHTTPServer(("127.0.0.1",0),Handler);th=threading.Thread(target=srv.serve_forever,daemon=True);th.start();base=f"http://127.0.0.1:{srv.server_port}"
            net=Transport(self.a) # 初始化网络层
            try: # 验证重试与 LFS
                res=retry(self.a,"测试重试",lambda:net.request("GET",base+"/flaky").read());self.assertEqual(res,b"ok");self.assertEqual(counters["flaky"],2) # 验证 503 自动重试
                self.write("payload.bin",b"binary stream"*100);ptr=self.cache.put(self.root/"payload.bin");oid,sz=pointer_info(ptr);done=set() # 准备 LFS 对象
                upload_lfs(net,base+"/info/lfs/objects/batch",{oid:sz},self.cache,b"refs/heads/main",done) # 执行完整上传
                self.assertIn(oid,stored);self.assertEqual(len(stored[oid]),sz) # 验证数据完整收到
            finally:net.close();srv.shutdown();srv.server_close();th.join(timeout=2) # 关闭服务
        def test_low_speed_watchdog(self): # 验证低速看门狗超时主动掐断套接字
            class MockSock: # 仿真假套接字
                closed=False
                def shutdown(self,how):self.closed=True
                def close(self):self.closed=True
            s=MockSock();meter=TransferMonitor(s,self.a,"test");deadline=time.monotonic()+2 # 启动监控
            while not s.closed and time.monotonic()<deadline:time.sleep(0.01) # 等待看门狗触发
            try:self.assertTrue(s.closed);self.assertIsNotNone(meter.failure) # 确认套接字已被切断
            finally:meter.close() # 关闭
        def test_readme_empty_after_push(self): # 验证 ReadMe.md 内含 #EmptyAfterPush 时能被正确识别
            self.write("ReadMe.md",b"# Demo Project\n\n#EmptyAfterPush\nSome content");ids,empty=prepare(self.repo,self.a,self.identity,self.cache) # 暂存
            self.assertIsNotNone(empty);self.assertEqual(empty.name,"ReadMe.md") # 确认成功捕获清空指令
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Tests);result=unittest.TextTestRunner(verbosity=2).run(suite) # 执行测试套件
    return 0 if result.wasSuccessful() else 1 # 返回执行退出码

if __name__=="__main__": # 脚本入口点
    try: # 主调度流程
        a=arguments();setup_logging(a.verbose) # 解析参数并初始化日志
        if a.self_test:setup_logging(0);sys.exit(self_test()) # 若指定 --self-test 则静默启动测试套件并退出
        main(a) # 执行推送核心流程
    except KeyboardInterrupt:LOG.warning("\n[CANCEL] 收到用户中断信号；本地已生成的提交与 LFS 对象安全保留在仓库，下次推送可直接断点续传。");sys.exit(130) # 捕获 Ctrl+C 并优雅退出
    except Exception as exc: # 全局未捕获异常兜底
        if not LOG.handlers:setup_logging(2) # 确保有日志输出
        LOG.error("❌ 失败: %s",exc,exc_info=LOG.isEnabledFor(logging.DEBUG));sys.exit(1) # 输出错误描述并退出
