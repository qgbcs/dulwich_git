#!/usr/bin/env python3
import argparse, fnmatch, hashlib, io, logging, os, platform, shutil, socket, stat, subprocess, sys, tempfile, time, urllib.request # 导入标准库模块
from pathlib import Path # 导入面向对象路径库
from urllib.parse import urlparse, urlunparse # 导入URL解析与组装工具
import dulwich, dulwich.client, dulwich.config, dulwich.diff_tree, dulwich.index, dulwich.objects, dulwich.pack, dulwich.porcelain, dulwich.refs, dulwich.repo # 导入dulwich全套核心模块
from dulwich.objects import Blob, Commit, Tag, Tree, parse_timezone # 导入Git四类核心对象及方法
from dulwich.repo import Repo # 导入Dulwich仓库类
logger = logging.getLogger("GitAutoLFS") # 创建全局日志记录器
LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1\n" # 定义Git LFS指针文件标准魔数前缀
RETRY_NET_KEYWORDS = ["could not read from remote repository", "ssh: connect to host", "connection timed out", "the remote end hung up unexpectedly", "fatal: unable to access", "failed to connect to", "network is unreachable", "remote: fatal:", "dial tcp", "connectex", "a connection attempt failed", "connected party did not properly respond", "connected host has failed to respond", "curl 28", "rpc failed", "expected flush after ref listing", "connection was reset", "empty reply from server", "timed out", "broken pipe", "connection reset", "eof occurred"] # 定义可重试的网络异常关键字列表
RETRY_AUTH_KEYWORDS = ["http 401", "http 403", "error: 401", "error: 403", "401 unauthorized", "403 forbidden", "fatal: authentication failed", "permission to ", "permission denied (publickey)", "unauthorized"] # 定义不可重试的认证失败关键字列表
RETRY_LARGE_FILE_KEYWORDS = ["gh001: large files detected", "exceeds github's file size limit", "exceeds github's file size limit of 100.00 mb"] # 定义GitHub拒绝历史大文件的关键字列表
def setup_logging(verbosity: int): # 初始化日志输出格式与级别
    levels = {0: logging.ERROR, 1: logging.WARNING, 2: logging.INFO, 3: logging.DEBUG} # 映射整数级别到logging常量
    level = levels.get(verbosity, logging.DEBUG if verbosity > 3 else logging.ERROR) # 处理超出范围的日志级别参数
    formatter = logging.Formatter(fmt='%(asctime)s | %(levelname)-7s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S') # 设置与原版一致的时间戳和对齐格式
    handler = logging.StreamHandler(sys.stdout) # 输出日志到标准输出流
    handler.setFormatter(formatter) # 绑定格式化器到处理器
    logger.setLevel(level) # 设置记录器日志等级
    if not logger.handlers: logger.addHandler(handler) # 避免重复添加日志处理器
def stime() -> str: # 生成带毫秒的格式化当前时间字符串
    ft = time.time() # 获取当前浮点型Unix时间戳
    return time.strftime('%Y-%m-%d__%H.%M.%S', time.localtime(ft)) + '__.' + f"{ft:.3f}".split('.')[1] # 拼接年月日时分秒与三位毫秒
def kill_process_tree(pid: int, proc: subprocess.Popen = None): # 强制清理子进程树（用于辅助命令中断）
    if sys.platform == "win32": # Windows平台使用taskkill命令终止进程树
        try: subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) # 静默强杀PID及其子进程
        except Exception: pass # 忽略进程已退出导致的异常
    elif proc: # 非Windows平台直接调用Popen对象的kill方法
        try: proc.kill() # 发送SIGKILL信号终止进程
        except Exception: pass # 忽略终止异常
def looks_like_url(s: str) -> bool: # 判断字符串是否为Git远程URL格式
    return s.startswith("https://") or s.startswith("git@") or "://" in s # 支持HTTPS、SSH git@及带协议头的URL
def redact_url(value: str) -> str: # 对URL中的密码或Token敏感信息进行脱敏
    parsed = urlparse(value) # 解析URL各组成部分
    if parsed.scheme and parsed.netloc and "@" in parsed.netloc: # 若包含认证信息段
        userinfo, host = parsed.netloc.rsplit("@", 1) # 拆分凭据部分与主机名部分
        username = userinfo.split(":", 1)[0] # 提取冒号前的用户名
        return urlunparse(parsed._replace(netloc=f"{username}:***@{host}")) # 将密码替换为三个星号后重组URL
    return value # 不含敏感凭据则原样返回
def parse_size_str(val: str) -> int: # 解析带单位的文件大小字符串为字节整数
    if not val: return 104857600 # 为空时默认返回100MiB（104857600字节）
    s, multiplier = str(val).strip().lower(), 1 # 转为小写并初始化倍率为1
    if s.endswith("gb") or s.endswith("g"): multiplier, s = 1024 ** 3, s.rstrip("gb").rstrip("g") # 处理GB/G单位
    elif s.endswith("mb") or s.endswith("m"): multiplier, s = 1024 ** 2, s.rstrip("mb").rstrip("m") # 处理MB/M单位
    elif s.endswith("kb") or s.endswith("k"): multiplier, s = 1024, s.rstrip("kb").rstrip("k") # 处理KB/K单位
    elif s.endswith("b"): s = s.rstrip("b") # 处理B字节单位
    try: return int(float(s) * multiplier) # 计算对应字节整数
    except ValueError: return 104857600 # 解析失败时回退至默认100MiB
def preprocess_args() -> list[str]: # 预处理命令行参数以支持简写、裸URL与智能默认值
    valid_modes = {"push", "pull", "clone", "config", "init", "list-big", "listbig", "remove-big", "undo"} # 定义所有合法子命令模式
    no_ask_aliases = {"--noask", "-noask", "--no-ask", "-y", "-yes"} # 定义非交互模式的所有别名参数
    raw = sys.argv[1:] # 获取除脚本名外的原始参数列表
    url_indices = {i for i, arg in enumerate(raw) if looks_like_url(arg)} # 预先标记所有形如URL的参数索引
    new, need_auto_user, missing_value, i = [], False, False, 0 # 初始化重写列表与状态标志位
    while i < len(raw): # 逐个扫描原始参数
        arg = raw[i] # 取出当前参数
        if arg == "--remote": # 遇到显式--remote参数时原样保留其值
            new.append(arg) # 添加--remote标志
            if i + 1 < len(raw): new.append(raw[i + 1]); i += 2 # 若后方有值则一并添加并跳过两项
            else: i += 1 # 否则仅前进一项
            continue # 继续下一轮循环
        if arg in ("-m", "--commit-msg", "--commit_msg"): # 遇到提交消息参数时吞并后续所有词作为完整消息
            msg_parts = raw[i + 1:] # 获取其后所有参数片段
            if msg_parts: new.extend(["--commit-msg", " ".join(msg_parts)]) # 存在内容时拼接为单个字符串参数
            else: new.append(arg); missing_value = True # 缺失内容时保留原标志并标记missing_value供argparse报错
            i = len(raw); continue # 直接跳到参数末尾
        if arg in ("-u", "--user"): # 遇到用户配置参数时进行上下文消歧
            if i + 1 < len(raw): # 若后面还有参数
                nxt = raw[i + 1] # 查看紧邻的下一个参数
                if (i + 1) in url_indices: new.extend(["--user", "--remote", nxt]); i += 2; continue # 下一个是URL则拆分为自动用户+远程地址
                elif nxt in no_ask_aliases: new.extend(["--user", "--no-ask"]); i += 2; continue # 下一个是免询问参数则拆分转换
                elif nxt in valid_modes or nxt.startswith("-"): need_auto_user = True; i += 1; continue # 下一个是子命令或选项则延迟追加自动用户
                else: new.extend([arg, nxt]); i += 2; continue # 否则将下一个参数作为显式指定的用户名或邮箱
            else: need_auto_user = True; i += 1; continue # 位于末尾时标记需要自动用户配置
        if looks_like_url(arg): new.extend(["--remote", arg]); i += 1; continue # 将裸URL自动转换为--remote键值对
        new.append(arg); i += 1 # 普通参数直接保留
    if need_auto_user: new.append("--user") # 在末尾追加无参--user触发const="AUTO"
    if not missing_value and not any(a in valid_modes for a in new): new.append("push") # 未指定模式且无缺值错误时默认执行push
    return [sys.argv[0]] + new # 返回重写后的完整sys.argv
def open_repo(repo_root: Path = None) -> Repo: # 使用Dulwich打开指定路径的Git仓库
    target = str((repo_root or Path.cwd()).resolve()) # 解析目标目录绝对路径
    return Repo(target) # 返回Dulwich Repo实例
def is_git_repository(repo_root: Path) -> bool: # 使用Dulwich检测目录是否为有效Git仓库
    try: # 尝试打开Git仓库目录
        if not (repo_root / ".git").exists(): return False # 确保当前目录下存在.git目录或gitfile
        r = open_repo(repo_root); r.close(); return True # 能成功构造Repo对象即为有效仓库
    except Exception: return False # 打开失败说明未初始化
def get_origin_url(repo_root: Path = None) -> str: # 使用Dulwich读取remote.origin.url配置
    try: # 尝试读取仓库配置文件
        r = open_repo(repo_root) # 打开目标仓库
        cfg = r.get_config() # 获取仓库级ConfigFile对象
        val = cfg.get((b"remote", b"origin"), b"url") # 查找[remote "origin"]下的url键
        r.close() # 关闭仓库句柄
        return val.decode("utf-8", errors="replace").strip() if val else "" # 解码并返回URL字符串
    except Exception: return "" # 不存在配置时返回空字符串
def get_current_branch(repo_root: Path = None) -> str: # 使用Dulwich读取HEAD指向的当前分支名（含未出生分支）
    try: # 尝试读取HEAD符号引用
        r = open_repo(repo_root) # 打开目标仓库
        ref = r.refs.read_ref(b"HEAD") # 直接读取HEAD原始引用内容（支持unborn branch）
        r.close() # 关闭仓库句柄
        if ref and ref.startswith(b"ref: refs/heads/"): return ref[len(b"ref: refs/heads/"):].decode("utf-8", errors="replace").strip() # 提取refs/heads/后的分支短名
        elif ref and ref.startswith(b"refs/heads/"): return ref[len(b"refs/heads/"):].decode("utf-8", errors="replace").strip() # 兼容不带ref:前缀的返回格式
    except Exception: pass # 读取失败时忽略异常
    return "" # 处于分离头指针或异常状态时返回空字符串
def get_branch_tracking_url(branch: str, repo_root: Path = None) -> str: # 使用Dulwich获取指定分支追踪的远程仓库URL
    if not branch: return "" # 分支名为空时直接返回
    try: # 尝试从仓库配置读取分支追踪远端
        r = open_repo(repo_root) # 打开目标仓库
        cfg = r.get_config() # 读取仓库配置
        remote_bytes = cfg.get((b"branch", branch.encode("utf-8")), b"remote") # 获取branch..remote配置项
        if not remote_bytes: r.close(); return "" # 未配置追踪远端则返回空
        remote_name = remote_bytes.decode("utf-8", errors="replace").strip() # 解码远端名称
        try: # 尝试将该远端名解析为对应的remote..url
            url_bytes = cfg.get((b"remote", remote_name.encode("utf-8")), b"url") # 读取对应remote的url配置
            r.close() # 关闭仓库句柄
            if url_bytes: return url_bytes.decode("utf-8", errors="replace").strip() # 返回远端URL
        except KeyError: r.close() # 未找到remote段时关闭仓库
        if looks_like_url(remote_name): return remote_name # 若remote直接填写了URL则原样返回
    except Exception: pass # 忽略配置读取异常
    return "" # 默认返回空字符串
def set_remote(remote_url: str, repo_root: Path = None): # 使用Dulwich添加或更新origin远程地址配置
    if not remote_url: return # URL为空时不作处理
    r = open_repo(repo_root) # 打开目标仓库
    cfg = r.get_config() # 获取本地.git/config配置对象
    url_bytes = remote_url.encode("utf-8") # 编码目标URL为字节串
    try: # 检查是否已存在origin配置
        old_url = cfg.get((b"remote", b"origin"), b"url") # 读取现有origin的url
        if old_url and old_url.strip() == url_bytes: r.close(); return # 地址未变化则直接返回
        logger.info("更新远程 origin 地址...") # 记录更新日志
    except KeyError: logger.info("添加远程 origin 地址...") # 原先无origin时记录添加日志
    cfg.set((b"remote", b"origin"), b"url", url_bytes) # 设置remote.origin.url键值
    try: cfg.get((b"remote", b"origin"), b"fetch") # 检查是否存在fetch引用映射配置
    except KeyError: cfg.set((b"remote", b"origin"), b"fetch", b"+refs/heads/*:refs/remotes/origin/*") # 补充标准fetch映射规则
    cfg.write_to_path() # 将修改持久化写回.git/config文件
    r.close() # 关闭仓库句柄
def remove_stale_index_lock(repo_root: Path) -> bool: # 检查并安全清理遗留的.git/index.lock锁文件
    try: r = open_repo(repo_root); lock_path = Path(r.controldir()) / "index.lock"; r.close() # 通过Dulwich定位.git控制目录下的index.lock
    except Exception: lock_path = (repo_root or Path.cwd()) / ".git" / "index.lock" # 回退至标准路径拼接
    if not lock_path.exists(): return True # 锁文件不存在则直接通过
    fuser, lsof = shutil.which("fuser"), shutil.which("lsof") # 查找系统文件占用检测工具
    if fuser: holder = subprocess.run([fuser, "-s", str(lock_path)], capture_output=True) # 使用fuser检测是否有进程持有锁
    elif lsof: holder = subprocess.run([lsof, "-t", "--", str(lock_path)], capture_output=True) # 使用lsof检测是否有进程持有锁
    else: logger.error("无法确认 Git 索引锁是否被占用，请先手动检查并清理: " + str(lock_path)); return False # 无检测工具时拒绝盲目删除以保护数据安全
    if holder.returncode == 0: logger.error(f"Git 索引锁正在被其他进程使用: {lock_path}"); return False # 返回码为0表示仍有活跃进程占用
    try: lock_path.unlink(); logger.warning(f"已清理中断后遗留的 Git 索引锁: {lock_path}"); return True # 删除孤立锁文件并记录告警
    except OSError as exc: logger.error(f"无法清理 Git 索引锁 {lock_path}: {exc}"); return False # 删除失败时报错返回False
def check_lfs_available() -> bool: # 检查环境中是否可用git-lfs或内置Dulwich LFS支持
    git_bin = shutil.which("git") # 查找系统git路径以检测外部git-lfs插件
    if git_bin: # 若存在git命令则检查lfs子命令版本
        res = subprocess.run([git_bin, "lfs", "version"], capture_output=True, text=True) # 调用git lfs version
        if res.returncode == 0: return True # 外部git-lfs可用时返回True
    return hasattr(dulwich, "lfs") or True # Dulwich内置LFS指针与本地对象存储始终可用
def install_lfs() -> bool: # 尝试在Linux或macOS下自动安装git-lfs软件包
    system = platform.system() # 获取当前操作系统类型
    logger.info("检测到大文件，但未找到 Git LFS，尝试自动安装...") # 输出自动安装提示
    if system == "Linux": # Linux平台遍历主流包管理器
        for cmd in [["sudo", "apt-get", "install", "-y", "git-lfs"], ["sudo", "yum", "install", "-y", "git-lfs"], ["sudo", "dnf", "install", "-y", "git-lfs"], ["sudo", "zypper", "install", "-y", "git-lfs"]]: # 依次尝试apt/yum/dnf/zypper
            if shutil.which(cmd[0]): # 检查命令是否存在
                try: subprocess.run(cmd, check=True); return True # 安装成功立即返回True
                except subprocess.CalledProcessError: pass # 当前包管理器失败则尝试下一个
        return False # 所有包管理器均失败返回False
    elif system == "Darwin" and shutil.which("brew"): # macOS平台使用Homebrew安装
        try: subprocess.run(["brew", "install", "git-lfs"], check=True); return True # 执行brew install git-lfs
        except subprocess.CalledProcessError: return False # 安装失败返回False
    return False # 其他平台返回False
def init_lfs(repo_root: Path = None) -> bool: # 使用Dulwich在仓库配置中写入LFS过滤器并初始化本地LFS目录
    logger.info("执行 git lfs install 初始化仓库过滤器...") # 输出初始化日志
    try: # 使用Dulwich配置filter.lfs过滤器参数
        r = open_repo(repo_root) # 打开目标仓库
        cfg = r.get_config() # 获取仓库配置对象
        cfg.set((b"filter", b"lfs"), b"clean", b"git-lfs clean -- %f") # 配置clean过滤器命令
        cfg.set((b"filter", b"lfs"), b"smudge", b"git-lfs smudge -- %f") # 配置smudge过滤器命令
        cfg.set((b"filter", b"lfs"), b"process", b"git-lfs filter-process") # 配置filter-process批处理命令
        cfg.set((b"filter", b"lfs"), b"required", b"true") # 配置required为true
        cfg.write_to_path() # 写回.git/config配置文件
        lfs_dir = Path(r.controldir()) / "lfs" / "objects" # 构造.git/lfs/objects存储路径
        lfs_dir.mkdir(parents=True, exist_ok=True) # 创建本地LFS对象缓存目录
        r.close(); return True # 关闭仓库并返回成功
    except Exception as exc: logger.error(f"Git LFS 初始化失败: {exc}"); return False # 异常时记录错误并返回False
def _load_lfs_attribute_patterns(repo_root: Path) -> list[str]: # 从.gitattributes中解析所有绑定了filter=lfs的文件匹配模式
    attr_path = repo_root / ".gitattributes" # 定位工作区.gitattributes文件
    patterns = [] # 初始化匹配规则列表
    if not attr_path.is_file(): return patterns # 文件不存在则返回空列表
    with open(attr_path, "r", encoding="utf-8", errors="replace") as f: # 读取属性配置文件
        for line in f: # 逐行解析规则
            stripped = line.strip() # 去除首尾空白
            if not stripped or stripped.startswith("#"): continue # 跳过空行与注释行
            if "filter=lfs" in stripped: # 识别包含LFS过滤器的规则行
                pat = stripped.split(None, 1)[0].strip('"') # 提取首列文件路径或通配符模式并去掉引号
                patterns.append(pat) # 加入LFS模式列表
    return patterns # 返回所有LFS匹配模式
def _matches_lfs_patterns(rel_path: str, patterns: list[str]) -> bool: # 判断相对路径是否命中任一.gitattributes中的LFS规则
    norm = rel_path.replace("\\", "/").lstrip("/") # 统一路径分隔符为正斜杠
    for pat in patterns: # 遍历所有LFS匹配规则
        clean_pat = pat.lstrip("/") # 去除模式开头的斜杠
        if norm == clean_pat or fnmatch.fnmatch(norm, clean_pat) or fnmatch.fnmatch(Path(norm).name, clean_pat): return True # 精确匹配、路径通配或文件名通配命中
    return False # 未命中任何规则返回False
def _file_to_lfs_pointer_bytes(file_path: Path, controldir: Path) -> bytes: # 将本地大文件存入.git/lfs/objects并生成标准LFS指针字节串
    raw_first = b"" # 读取文件头部以判断是否已经是LFS指针
    with open(file_path, "rb") as f: raw_first = f.read(128) # 预读前128字节
    if raw_first.startswith(LFS_POINTER_PREFIX): # 若文件本身已是LFS指针则直接返回其内容
        return file_path.read_bytes() # 原样返回指针字节
    h = hashlib.sha256() # 创建SHA-256哈希计算器
    size = 0 # 初始化文件字节计数器
    with open(file_path, "rb") as f: # 以二进制流方式分块读取大文件避免内存溢出
        while chunk := f.read(1024 * 1024): # 每次读取1MiB数据块
            h.update(chunk); size += len(chunk) # 更新SHA-256摘要并累加字节数
    oid = h.hexdigest() # 获取64位十六进制SHA-256对象ID
    obj_dir = controldir / "lfs" / "objects" / oid[:2] / oid[2:4] # 按Git LFS规范构造两级子目录路径
    obj_dir.mkdir(parents=True, exist_ok=True) # 确保LFS本地对象目录存在
    dest_obj = obj_dir / oid # 目标LFS原始对象文件路径
    if not dest_obj.exists(): shutil.copy2(file_path, dest_obj) # 将真实大文件内容复制到LFS本地对象库
    return f"version https://git-lfs.github.com/spec/v1\noid sha256:{oid}\nsize {size}\n".encode("ascii") # 返回标准Git LFS v1指针文本字节
def stage_all_and_renormalize(repo_root: Path, lfs_paths: set[str] | None = None, cleanup_deleted: bool = True) -> bool: # 使用Dulwich执行全量暂存与LFS指针规范化
    if not remove_stale_index_lock(repo_root): return False # 操作索引前先检查并清理陈旧锁文件
    try: # 操作Dulwich Index与ObjectStore
        r = open_repo(repo_root) # 打开Git仓库
        idx = r.open_index() # 打开当前.git/index索引文件
        controldir = Path(r.controldir()) # 获取.git控制目录路径
        lfs_patterns = _load_lfs_attribute_patterns(repo_root) # 加载.gitattributes中的LFS规则
        if lfs_paths: lfs_patterns.extend(list(lfs_paths)) # 合并本次扫描到的显式大文件路径集合
        seen_rel_bytes = set() # 记录工作区当前实际存在的所有文件相对路径字节
        skip_dirs = {".git", "dist", "__pycache__"} # 跳过特殊目录及内部目录
        for current_root, dirnames, filenames in os.walk(repo_root, topdown=True, followlinks=False): # 遍历工作树文件
            dirnames[:] = [d for d in dirnames if d != ".git" and not (Path(current_root) / d / ".git").exists()] # 跳过.git目录及子模块目录
            for fname in filenames: # 遍历当前目录下的每个文件
                fpath = Path(current_root) / fname # 构造完整文件路径
                rel_str = str(fpath.relative_to(repo_root)).replace("\\", "/") # 计算POSIX格式相对路径
                rel_bytes = rel_str.encode("utf-8", errors="surrogateescape") # 编码为Git索引键字节串
                seen_rel_bytes.add(rel_bytes) # 标记该路径在工作区中存在
                try: st = fpath.lstat() # 获取文件lstat状态信息
                except OSError: continue # 文件不可访问时跳过
                if stat.S_ISLNK(st.st_mode): # 处理符号链接文件
                    target = os.readlink(fpath).encode("utf-8", errors="surrogateescape") # 读取符号链接目标路径字节
                    blob = Blob.from_string(target) # 构造符号链接内容Blob
                    mode = 0o120000 # Git符号链接模式常量
                elif stat.S_ISREG(st.st_mode): # 处理普通文件
                    is_lfs = (lfs_paths and rel_str in lfs_paths) or _matches_lfs_patterns(rel_str, lfs_patterns) # 判断该文件是否应以LFS指针入库
                    if is_lfs: data = _file_to_lfs_pointer_bytes(fpath, controldir) # 转换为LFS指针并归档原始大文件到.git/lfs
                    else: data = fpath.read_bytes() # 普通文件直接读取字节内容
                    blob = Blob.from_string(data) # 创建Dulwich Blob对象
                    mode = 0o100755 if (st.st_mode & 0o100) else 0o100644 # 根据可执行权限位设置Git文件模式
                else: continue # 忽略命名管道或套接字等非常规文件
                r.object_store.add_object(blob) # 将Blob写入Git对象数据库
                ctime = int(st.st_ctime); mtime = int(st.st_mtime) # 获取整数时间戳
                idx[rel_bytes] = dulwich.index.IndexEntry(ctime=(ctime, 0), mtime=(mtime, 0), dev=st.st_dev, ino=st.st_ino, mode=mode, uid=st.st_uid, gid=st.st_gid, size=len(blob.data), sha=blob.id, flags=0) # 更新或新增IndexEntry条目
        if cleanup_deleted: # 当需要清理已删除文件的暂存状态时（等同git add -A / -u）
            for indexed_path in list(idx.keys()): # 遍历索引中原有全部路径
                entry = idx[indexed_path] # 获取对应索引项
                if getattr(entry, "mode", 0) == 0o160000: continue # 保留子模块gitlink条目不误删
                if indexed_path not in seen_rel_bytes and not (repo_root / indexed_path.decode("utf-8", errors="surrogateescape")).exists(): # 若工作区已删除该文件
                    del idx[indexed_path] # 从Git索引中移除该条目
        idx.write() # 将更新后的索引写回.git/index
        r.close(); return True # 关闭仓库并返回成功
    except Exception as exc: logger.error(f"Dulwich 暂存与 LFS 规范化失败: {exc}"); return False # 捕获异常并记录错误
def renormalize_lfs(repo_root: Path, paths: set[str] | None = None, cleanup_deleted: bool = True) -> bool: # 重新规范化已跟踪LFS大文件确保转为LFS指针
    logger.info("执行 Git LFS 重新规范化，确保已跟踪大文件转换为 LFS 指针...") # 打印规范化提示信息
    return stage_all_and_renormalize(repo_root, lfs_paths=paths, cleanup_deleted=cleanup_deleted) # 调用Dulwich暂存与LFS指针转换函数
def verify_staged_lfs_files(repo_root: Path) -> bool: # 在提交与推送前校验所有匹配LFS规则的暂存文件是否均为LFS指针而非原始大Blob
    try: # 使用Dulwich检查暂存区与.gitattributes规则一致性
        r = open_repo(repo_root) # 打开仓库
        idx = r.open_index() # 打开暂存区索引
        patterns = _load_lfs_attribute_patterns(repo_root) # 读取.gitattributes中的filter=lfs模式
        if not patterns: r.close(); return True # 无LFS规则时直接放行
        head_tree = {} # 存储HEAD提交中的文件路径与SHA映射以识别本次新增或修改的暂存文件
        try: # 尝试读取HEAD提交的Tree状态
            head_commit = r[r.head()] # 获取HEAD Commit对象
            for entry in r.object_store.iter_tree_contents(head_commit.tree): head_tree[entry.path] = entry.sha # 记录HEAD中所有文件的SHA
        except Exception: pass # 尚无HEAD提交时保持为空字典
        invalid_files = [] # 收集未转换为LFS指针的违规文件路径
        for path_bytes, index_entry in idx.items(): # 遍历当前索引中的所有条目
            if head_tree.get(path_bytes) == index_entry.sha: continue # 与HEAD一致说明未在本次暂存中变更
            path_str = path_bytes.decode("utf-8", errors="surrogateescape") # 解码文件路径
            if not _matches_lfs_patterns(path_str, patterns): continue # 未命中LFS规则的文件无需校验
            try: # 从Dulwich对象库读取该暂存条目对应的Blob对象
                obj = r.object_store[index_entry.sha] # 按SHA读取对象
                if obj.type_name != b"blob" or not obj.data.startswith(LFS_POINTER_PREFIX): # 若不是Blob或内容不以LFS标准头开头
                    if len(obj.data) > 0: invalid_files.append(path_str) # 非空普通Blob则判定为未转换的违规大文件
            except Exception: invalid_files.append(path_str) # 对象缺失或损坏同样记入违规列表
        r.close() # 关闭仓库句柄
        if invalid_files: # 发现违规普通Blob时阻止提交并输出修复指引
            logger.error(f"以下暂存文件匹配 LFS 规则，但仍是普通 Git Blob: {invalid_files}") # 打印违规文件列表
            logger.error("已阻止提交，请执行 git lfs install --local，再执行 git add --renormalize . && git add -A。") # 打印修复建议
            return False # 校验不通过返回False
        return True # 全部校验通过返回True
    except Exception as exc: logger.warning(f"检查 Git 属性或暂存 Blob 异常: {exc}"); return True # 异常时告警放行
def parse_github_subdirectory_url(remote_url: str) -> tuple[str, str | None, str | None]: # 解析GitHub树/文件URL为（仓库URL, 分支名, 子目录路径）
    parsed = urlparse(remote_url) # 解析URL结构
    if parsed.scheme not in ("http", "https") or (parsed.hostname or "").lower() not in ("github.com", "www.github.com"): return remote_url, None, None # 非GitHub HTTP(S)链接原样返回
    parts = [part for part in parsed.path.strip("/").split("/") if part] # 拆分路径段
    if len(parts) == 3: # 形如https://github.com/owner/repo/branch的三段式URL
        owner, repository, branch = parts # 解包所有者、仓库名与分支名
        repository = repository.removesuffix(".git") # 去掉可能存在的.git后缀
        repository_url = urlunparse(parsed._replace(path=f"/{owner}/{repository}.git", params="", query="", fragment="")) # 组装标准仓库克隆URL
        return repository_url, branch, None # 返回仓库URL与分支名，子目录为None
    if len(parts) < 5 or parts[2] not in ("blob", "tree"): return remote_url, None, None # 非标准tree/blob子路径URL原样返回
    owner, repository, _, branch, *subdirectory = parts # 解包五段及以上的子目录URL
    repository = repository.removesuffix(".git") # 移除仓库名后缀
    repository_url = urlunparse(parsed._replace(path=f"/{owner}/{repository}.git", params="", query="", fragment="")) # 构造标准.git仓库URL
    return repository_url, branch, "/".join(subdirectory) # 返回（标准仓库URL, 分支名, 子目录相对路径）
def scan_large_files(repo_root: Path, threshold: int) -> set[str]: # 扫描工作区超过阈值的大文件（自动跳过特定目录与子模块）
    large_files, skip_dirs = set(), {".git", "dist", "__pycache__"} # 初始化大文件集合与忽略目录集合
    scanned_files, scanned_dirs, last_report = 0, 0, time.monotonic() # 初始化文件计数、目录计数与进度刷新计时器
    for current_root, dirnames, filenames in os.walk(repo_root, topdown=True, followlinks=False): # 自顶向下遍历工作目录且不跟随符号链接
        dirnames[:] = [name for name in dirnames if name not in skip_dirs] # 过滤掉.git、dist与__pycache__目录
        dirnames[:] = [name for name in dirnames if not (Path(current_root) / name / ".git").exists()] # 过滤掉包含.git的独立子模块工作树
        scanned_dirs += 1 # 累加已扫描目录数
        for filename in filenames: # 遍历当前目录下的所有文件名
            path = Path(current_root) / filename # 拼接文件完整路径
            if path.is_symlink(): continue # 跳过符号链接文件
            scanned_files += 1 # 累加已扫描文件数
            try: fsize = path.lstat().st_size # 读取文件物理字节大小
            except OSError: continue # 忽略无法访问的文件
            if fsize >= threshold: large_files.add(str(path.relative_to(repo_root)).replace("\\", "/")) # 达到或超过阈值则记录POSIX格式相对路径
            now = time.monotonic() # 获取当前单调时钟时间
            if now - last_report >= 1: # 每满1秒在终端同一行刷新一次扫描进度
                display_path = str(path.relative_to(repo_root)).replace("\\", "/") # 格式化当前文件路径
                prefix = f"扫描文件: {scanned_files:,} | 目录: {scanned_dirs:,} | 当前: " # 构造状态栏前缀
                width = shutil.get_terminal_size(fallback=(120, 1)).columns # 获取当前终端列宽
                available = max(1, width - len(prefix) - 1) # 计算可用于显示路径的剩余字符数
                if len(display_path) > available: display_path = "..." + display_path[-max(1, available - 3):] # 超长路径左侧截断并加省略号
                sys.stdout.write("\r\033[2K" + prefix + display_path); sys.stdout.flush(); last_report = now # 清空当前行并输出最新进度
    if scanned_files: sys.stdout.write("\r\033[2K"); sys.stdout.flush() # 扫描结束后清除终端进度行
    return large_files # 返回所有超限大文件的相对路径集合
def clean_and_apply_lfs(repo_root: Path, large_patterns: set[str]): # 清理.gitattributes中的无效规则并写入最新LFS追踪规则
    attr_path = repo_root / ".gitattributes" # 定位仓库根目录下的.gitattributes文件
    other_lines, lfs_lines, nested_repo_prefixes = [], set(), set() # 初始化非LFS行列表、LFS规则集合与嵌套子仓库前缀集合
    for current_root, dirnames, _ in os.walk(repo_root, topdown=True, followlinks=False): # 遍历查找所有嵌套Git子仓库
        dirnames[:] = [name for name in dirnames if name != ".git"] # 排除顶层.git目录本身
        for name in list(dirnames): # 检查子目录是否含有.git
            nested_root = Path(current_root) / name # 子目录路径
            if (nested_root / ".git").exists(): # 若该子目录是嵌套仓库或子模块
                nested_repo_prefixes.add(nested_root.relative_to(repo_root).as_posix() + "/") # 记录其相对路径前缀
                dirnames.remove(name) # 不再深入遍历该嵌套仓库内部
    if attr_path.exists(): # 若已存在.gitattributes文件则先读取清洗
        with open(attr_path, "r", encoding="utf-8") as f: # 打开现有.gitattributes文件
            for line in f.readlines(): # 逐行检查现有规则
                stripped = line.strip() # 去除首尾空白
                if not stripped: continue # 忽略空行
                if "filter=lfs" in stripped: # 对已有的LFS规则进行合法性过滤
                    rule_path = stripped.split(None, 1)[0].strip('"') # 提取规则作用路径
                    if any(rule_path.startswith(prefix) for prefix in nested_repo_prefixes): continue # 剔除指向子模块内部路径的非法规则
                    if (repo_root / rule_path).is_symlink(): continue # 剔除指向符号链接的规则
                    lfs_lines.add(stripped) # 保留合法的既有LFS规则
                else: other_lines.append(stripped) # 保留其他非LFS属性配置行
    for pat in large_patterns: # 将本次新扫描到的大文件路径加入LFS规则集
        safe_pat = f'"{pat}"' if " " in pat else pat # 路径含空格时自动包裹双引号
        lfs_lines.add(f"{safe_pat} filter=lfs diff=lfs merge=lfs -text") # 生成标准LFS属性行
    all_rules = other_lines + sorted(lfs_lines) # 合并普通规则与排序后的LFS规则
    if all_rules: # 若存在有效规则则写回文件
        with open(attr_path, "w", encoding="utf-8") as f: f.write("\n".join(all_rules) + "\n") # 写入UTF-8编码的.gitattributes
    logger.info(f".gitattributes 更新完成，LFS追踪总数: {len(lfs_lines)}") # 输出当前LFS追踪规则总数
def run_network_retry(action_fn, operation: str, remote_url: str, branch: str, retry_count: int = 10, retry_seconds: int = 5, is_debug: bool = False, connect_timeout: int = 45, before_attempt=None): # 通用Dulwich网络操作重试器
    old_timeout = socket.getdefaulttimeout() # 备份当前全局Socket默认超时时间
    socket.setdefaulttimeout(float(connect_timeout)) # 应用命令行指定的连接超时时间
    try: # 开始重试循环
        for attempt in range(1, retry_count + 1): # 从第1次尝试循环至最大重试次数
            logger.info(f"===== {operation} {redact_url(remote_url)} {branch} (尝试 {attempt}/{retry_count}) 间隔 {retry_seconds}s =====") # 打印当前尝试日志
            if before_attempt is not None: # 若传入了尝试前钩子（如clone清理残留目录）
                try: before_attempt(attempt) # 执行尝试前钩子函数
                except Exception as exc: logger.warning(f"⚠️ 第 {attempt} 次尝试前的钩子异常: {exc!r}") # 钩子异常仅告警不中断
            if is_debug or attempt > 1: # 调试模式或第2次以上重试时启用详细连接追踪
                os.environ["GIT_CURL_VERBOSE"] = "1"; os.environ["GIT_TRACE"] = "1" # 设置跟踪环境变量
                if attempt > 1: logger.info("🔍 启用详细连接日志") # 提示已开启详细日志
            try: # 执行传入的Dulwich网络操作闭包
                return action_fn() # 成功执行则直接返回结果
            except KeyboardInterrupt: # 捕获Ctrl+C用户中断信号
                logger.warning("\n[CANCEL] 收到中断信号，终止网络操作。") # 记录取消日志
                sys.exit(130) # 以标准中断码130退出
            except Exception as exc: # 捕获Dulwich传输异常或协议错误
                output = f"{exc} {repr(exc)}".lower() # 将异常信息转为小写便于关键字匹配
                if any(keyword in output for keyword in RETRY_LARGE_FILE_KEYWORDS): # 检查是否为GitHub历史大文件拒绝错误
                    logger.error("❌ GitHub 拒绝了历史中的大文件，当前工作区扫描不到并不代表历史对象已清除。") # 提示历史中含有超限Blob
                    logger.error("请先执行 ./git.py list-big，确认 Blob；再执行 ./git.py remove-big，完成历史改写后使用 git push --force 推送。") # 提示清理步骤
                    logger.error("如果希望保留这些文件，请先配置 Git LFS 并迁移历史，而不是只新增 .gitattributes。") # 提示LFS迁移说明
                    sys.exit(1) # 历史大文件属于不可重试错误，立即退出
                is_net = any(keyword in output for keyword in RETRY_NET_KEYWORDS) or isinstance(exc, (OSError, socket.timeout, urllib.error.URLError)) # 判断是否为网络层异常
                is_auth = any(keyword in output for keyword in RETRY_AUTH_KEYWORDS) # 判断是否为权限或认证失败
                if is_auth: # 认证失败不重试直接退出
                    logger.error(f"❌ {operation}认证或权限失败: {exc}"); sys.exit(1) # 输出错误并退出
                elif is_net: logger.warning(f"⚠️ 网络错误，稍后重试 ({exc})") # 网络异常输出重试警告
                else: logger.warning(f"⚠️ 操作异常: {repr(exc)}，稍后重试") # 其他瞬态异常同样等待重试
            if attempt < retry_count: time.sleep(retry_seconds) # 未达最大次数前按指定间隔休眠
            else: logger.error(f"❌ {operation}达到最大重试次数 {retry_count}"); sys.exit(1) # 耗尽重试次数后报错退出
    finally: socket.setdefaulttimeout(old_timeout) # 恢复原始Socket超时设置
def _dulwich_detect_default_branch(remote_url: str) -> str | None: # 使用Dulwich传输层探测远端仓库HEAD指向的默认分支
    try: # 尝试通过Dulwich客户端连接远端获取symref信息
        client, path = dulwich.client.get_transport_and_path(remote_url) # 根据URL创建Dulwich GitClient与远端路径
        res = client.get_refs(path) # 获取远端引用字典与symrefs扩展信息
        symrefs = getattr(res, "symrefs", {}) or {} # 读取服务端返回的symrefs映射
        head_target = symrefs.get(b"HEAD") # 查找HEAD指向的符号引用
        if head_target and head_target.startswith(b"refs/heads/"): return head_target[len(b"refs/heads/"):].decode("utf-8", errors="replace") # 命中时直接返回默认分支名
        refs_dict = res.refs if hasattr(res, "refs") else res # 兼容不同版本Dulwich返回结构
        head_sha = refs_dict.get(b"HEAD") # 获取远端HEAD的Commit SHA
        if head_sha: # 若未返回symref则通过比对HEAD SHA与refs/heads/*的SHA推断默认分支
            for ref_name, sha in refs_dict.items(): # 遍历远端所有引用
                if ref_name.startswith(b"refs/heads/") and sha == head_sha: return ref_name[len(b"refs/heads/"):].decode("utf-8", errors="replace") # 找到SHA一致的分支名
    except Exception: pass # 探测失败时静默忽略
    return None # 无法探测时返回None
def _is_healthy_repo(path: Path) -> bool: # 使用Dulwich检验目标目录中的.git仓库是否完整可用且HEAD指向有效对象
    try: # 尝试打开仓库并解析HEAD对象
        if not (path / ".git").exists(): return False # 必须存在.git目录
        r = open_repo(path) # 打开Dulwich Repo
        head_sha = r.head() # 获取HEAD指向的Commit SHA（若无提交会抛KeyError）
        has_obj = head_sha in r.object_store # 验证该SHA确实存在于对象库中
        r.close(); return bool(has_obj) # 关闭仓库并返回健康状态
    except Exception: return False # 任何异常均视为仓库不完整或损坏
def _checkout_branch_worktree(repo_root: Path, branch: str): # 使用Dulwich将工作区与索引检出并硬重置到origin/或指定分支
    r = open_repo(repo_root) # 打开目标仓库
    remote_ref = f"refs/remotes/origin/{branch}".encode("utf-8") # 构造远端跟踪分支引用名
    local_ref = f"refs/heads/{branch}".encode("utf-8") # 构造本地分支引用名
    target_sha = r.refs[remote_ref] if remote_ref in r.refs else r.refs[local_ref] # 优先取origin/最新Commit SHA
    r.refs[local_ref] = target_sha # 将本地分支引用更新到目标SHA
    r.refs.set_symbolic_ref(b"HEAD", local_ref) # 将HEAD符号引用指向该本地分支
    commit_obj = r[target_sha] # 读取目标Commit对象
    dulwich.index.build_index_from_tree(r.path, r.index_path(), r.object_store, commit_obj.tree) # 根据Commit的Tree重建工作区文件与.git/index
    r.close() # 关闭仓库句柄
def _clean_untracked(repo_root: Path): # 清理工作区中未被Git索引跟踪的残留文件与空目录（等同git clean -fdx）
    r = open_repo(repo_root) # 打开目标仓库
    idx = r.open_index() # 读取当前索引
    tracked = {k.decode("utf-8", errors="surrogateescape") for k in idx.keys()} # 获取所有受跟踪文件的相对路径集合
    r.close() # 关闭仓库句柄
    for current_root, dirnames, filenames in os.walk(repo_root, topdown=False, followlinks=False): # 自底向上遍历工作树
        if ".git" in Path(current_root).relative_to(repo_root).parts: continue # 跳过.git内部一切文件
        for fname in filenames: # 检查每个文件是否受跟踪
            fpath = Path(current_root) / fname # 完整文件路径
            rel = str(fpath.relative_to(repo_root)).replace("\\", "/") # 计算POSIX相对路径
            if rel not in tracked: # 若不在索引中则删除该残留文件
                try: fpath.unlink() # 删除未跟踪文件
                except OSError: pass # 忽略删除异常
        for dname in dirnames: # 检查并清理空余未跟踪目录
            if dname == ".git": continue # 跳过.git目录
            dpath = Path(current_root) / dname # 子目录路径
            try: # 若目录为空则移除
                if not any(dpath.iterdir()): dpath.rmdir() # 删除空目录
            except OSError: pass # 非空或权限受限时忽略
def _lfs_pull_objects(repo_root: Path, sparse_path: str | None = None): # 恢复工作区中的LFS指针文件（优先用本地缓存或调用git lfs pull）
    r = open_repo(repo_root) # 打开目标仓库
    controldir = Path(r.controldir()) # 获取.git目录路径
    idx = r.open_index() # 打开索引遍历工作区文件
    restored = 0 # 统计从本地LFS对象库直接恢复的文件数
    for path_bytes in idx.keys(): # 遍历所有受管文件
        rel_str = path_bytes.decode("utf-8", errors="surrogateescape") # 解码相对路径
        if sparse_path and not rel_str.startswith(sparse_path.strip("/") + "/"): continue # 若配置了子目录稀疏检出则仅处理子目录内文件
        fpath = repo_root / rel_str # 定位工作区文件
        if not fpath.is_file(): continue # 文件不存在则跳过
        try: # 检查文件内容是否为LFS指针
            raw = fpath.read_bytes() # 读取文件内容
            if raw.startswith(LFS_POINTER_PREFIX): # 若是待smudge还原的LFS指针文件
                for line in raw.decode("ascii", errors="ignore").splitlines(): # 解析指针中的oid行
                    if line.startswith("oid sha256:"): # 提取SHA-256哈希值
                        oid = line.split("oid sha256:", 1)[1].strip() # 得到64位哈希字符串
                        cached = controldir / "lfs" / "objects" / oid[:2] / oid[2:4] / oid # 查找本地.git/lfs/objects缓存
                        if cached.is_file(): shutil.copy2(cached, fpath); restored += 1 # 本地存在缓存对象时直接覆写还原工作区文件
        except OSError: pass # 忽略单个文件读取异常
    r.close() # 关闭仓库句柄
    git_bin = shutil.which("git") # 检查系统是否安装了git与git-lfs以拉取远端缺失的LFS对象
    if git_bin and check_lfs_available(): # 若外部git-lfs可用则执行拉取同步远端LFS二进制对象
        lfs_args = [git_bin, "lfs", "pull"] # 构造git lfs pull命令
        if sparse_path: lfs_args.append(f"--include={sparse_path.strip('/')}/**") # 子目录模式下仅按需拉取目标子目录内的LFS对象
        subprocess.run(lfs_args, cwd=repo_root, check=False) # 在仓库根目录执行LFS对象拉取
def git_clone(branch: str, remote_url: str, extra_args: list[str], sparse_path: str | None = None, connect_timeout: int = 45, low_speed_limit: int = 1000, low_speed_time: int = 30, retry_count: int = 10, retry_seconds: int = 5): # 使用Dulwich克隆或断点恢复仓库并还原LFS及稀疏子目录
    if not remote_url: logger.error("clone 缺少远程仓库地址。"); sys.exit(1) # 校验远程URL必填
    base_dir = Path.cwd() # 以启动时的当前工作目录作为基准路径
    branch_display = branch if branch else "" # 日志展示用的分支名占位符
    clone_options = list(extra_args) # 复制额外命令行参数列表
    value_options = {"-b", "--branch", "-o", "--origin", "-c", "--config", "--depth", "--shallow-since", "--shallow-exclude", "--reference", "--reference-if-able", "--dissociate", "--separate-git-dir", "--template", "--upload-pack"} # 定义带值选项集合以识别位置参数
    positional = [arg for index, arg in enumerate(clone_options) if not arg.startswith("-") and (index == 0 or clone_options[index - 1] not in value_options)] # 提取非选项的位置参数（即自定义目标目录）
    destination = Path(positional[-1]) if positional else None # 若有位置参数则取最后一个作为目标克隆目录
    if destination is None: # 未显式传入目标目录时自动根据子目录名或仓库URL推导
        if sparse_path: destination = Path(sparse_path.rstrip("/").rsplit("/", 1)[-1]) # 子目录克隆默认以子目录末级名称命名
        else: # 普通整库克隆以URL末段去掉.git命名
            repo_name = remote_url.rstrip("/").rsplit("/", 1)[-1] # 截取URL最后一段
            if ":" in repo_name and not remote_url.startswith(("http://", "https://")): repo_name = repo_name.rsplit(":", 1)[-1] # 处理SSH scp风格git@host:owner/repo格式
            destination = Path(repo_name.removesuffix(".git")) # 去掉.git后缀得到目录名
    if not destination.is_absolute(): destination = base_dir / destination # 统一转换为绝对路径防止受CWD变化影响
    is_debug = logger.getEffectiveLevel() <= logging.DEBUG # 判断当前是否处于DEBUG级别
    def _do_fresh_clone(): # 定义全新Dulwich克隆闭包（支持重试前自动清理残留目录）
        def _cleanup_destination(_attempt: int): # 每次尝试前清理上一次失败留下的半成品目录
            if destination.exists(): # 若目标路径已存在
                logger.info(f"清理克隆残留目录: {destination}") # 记录清理日志
                if destination.is_dir(): shutil.rmtree(destination, ignore_errors=True) # 递归删除残留目录
                else: # 若为同名文件则直接删除
                    try: destination.unlink() # 删除残留文件
                    except OSError: pass # 忽略删除异常
        def _clone_op(): # 调用Dulwich porcelain.clone执行克隆
            os.environ["GIT_LFS_SKIP_SMUDGE"] = "1" # 克隆阶段跳过smudge以便稍后统一拉取LFS
            b_arg = branch.encode("utf-8") if branch else None # 转换目标分支名为字节串
            r = dulwich.porcelain.clone(remote_url, target=str(destination), checkout=True, branch=b_arg, errstream=sys.stdout.buffer if is_debug else io.BytesIO()) # 执行Dulwich克隆并检出工作树
            r.close() # 关闭克隆后的仓库实例
        run_network_retry(_clone_op, "克隆", remote_url, branch_display, retry_count, retry_seconds, is_debug, connect_timeout, before_attempt=_cleanup_destination) # 带自动清理钩子与网络重试执行克隆
    if destination.exists() and sparse_path and (destination / ".git").exists(): # 若目标目录已存在且处于子目录克隆模式
        existing_origin = get_origin_url(destination) # 读取现有仓库的origin地址
        if existing_origin and existing_origin != remote_url: shutil.rmtree(destination, ignore_errors=True) # 若origin与当前请求URL不一致则清空重来
    if destination.exists(): # 当目标路径已存在时判断走断点恢复还是报错/重克隆
        if not (destination / ".git").exists(): logger.error(f"目标目录已存在且不是 Git 仓库，拒绝覆盖: {destination}"); sys.exit(1) # 保护非Git普通目录不被误删
        if not _is_healthy_repo(destination): # 检查已有.git是否因上次中断而损坏
            logger.warning(f"检测到不完整或损坏的 .git，清理后重新 clone: {destination}") # 打印重克隆警告
            shutil.rmtree(destination, ignore_errors=True); _do_fresh_clone() # 删除损坏目录并执行全新克隆
        else: # .git健康可用时通过Dulwich fetch+reset断点恢复
            logger.info(f"===== 检测到未完成的仓库，开始从远程恢复: {destination} =====") # 打印恢复日志
            effective_branch = branch or _dulwich_detect_default_branch(remote_url) # 未指定分支时自动探测远端默认分支
            if not effective_branch: logger.error("未指定分支，且无法探测远端默认分支。请通过 --branch/-b 显式指定分支后重试。"); sys.exit(1) # 探测失败时提示用户显式指定
            if not branch: logger.info(f"未指定分支，使用远端默认分支: {effective_branch}") # 打印探测到的默认分支名
            set_remote(remote_url, destination) # 更新origin远程地址
            run_network_retry(lambda: dulwich.porcelain.fetch(str(destination), remote_location=remote_url, errstream=sys.stdout.buffer if is_debug else io.BytesIO()), "获取远程提交", remote_url, effective_branch, retry_count, retry_seconds, is_debug, connect_timeout) # 拉取远端最新对象与引用
            _checkout_branch_worktree(destination, effective_branch) # 将工作区与索引重置到远端目标分支
            _clean_untracked(destination) # 清理未跟踪残留文件
    else: _do_fresh_clone() # 目标目录不存在时直接执行全新克隆
    logger.info("===== 开始恢复 Git LFS 大文件 =====") # 打印LFS恢复阶段日志
    _lfs_pull_objects(destination, sparse_path) # 还原LFS大文件（支持子目录按需恢复）
    if sparse_path: # 若用户传入的是GitHub子目录URL则将目标子目录提升为顶层结果目录
        selected_path = destination.joinpath(*sparse_path.strip("/").split("/")) # 定位克隆下来的目标子目录路径
        if not selected_path.exists(): logger.error(f"远程子目录不存在: {sparse_path}"); sys.exit(1) # 子目录不存在时报错退出
        temp_parent = Path(tempfile.mkdtemp(prefix=f".{destination.name}-sparse-", dir=str(destination.parent))) # 在同级父目录创建临时中转目录
        promoted_path = temp_parent / destination.name # 构造中转目标路径
        try: # 将子目录移出并替换原完整仓库目录
            shutil.move(str(selected_path), str(promoted_path)) # 将目标子目录移动到临时目录
            shutil.rmtree(destination) # 删除包含.git的完整克隆外层目录
            shutil.move(str(promoted_path), str(destination)) # 将提取出的子目录移回最终destination位置
        finally: shutil.rmtree(temp_parent, ignore_errors=True) # 清理临时中转父目录
def git_pull(branch: str, extra_args: list[str], remote_url: str = "", connect_timeout: int = 45, low_speed_limit: int = 1000, low_speed_time: int = 30, retry_count: int = 10, retry_seconds: int = 5, repo_root: Path = None): # 使用Dulwich执行带网络重试的拉取与LFS还原
    target_root = repo_root or Path.cwd() # 确定操作的目标仓库根目录
    is_debug = logger.getEffectiveLevel() <= logging.DEBUG # 判断是否开启调试输出
    refspec = f"refs/heads/{branch}:refs/remotes/origin/{branch}".encode("utf-8") if branch else None # 构造拉取分支的refspec字节串
    def _pull_op(): # 定义Dulwich拉取与合并更新工作树操作
        dulwich.porcelain.pull(str(target_root), remote_location=remote_url, refspecs=[refspec] if refspec else None, errstream=sys.stdout.buffer if is_debug else io.BytesIO()) # 调用Dulwich porcelain.pull拉取并快进更新当前分支
    run_network_retry(_pull_op, "拉取", remote_url, branch, retry_count, retry_seconds, is_debug, connect_timeout) # 带网络重试执行拉取
    logger.info("===== 开始执行 git lfs pull =====") # 打印LFS拉取日志
    _lfs_pull_objects(target_root) # 同步还原工作区中的LFS大文件
def extract_remote_user_from_url(remote_url: str) -> str | None: # 从HTTP/HTTPS/SSH远程URL中提取用户名或仓库所有者名称
    if not remote_url: return None # 空URL直接返回None
    parsed = urlparse(remote_url) # 解析URL
    if parsed.scheme and parsed.netloc: # 标准带协议头URL（如https://github.com/owner/repo.git）
        if parsed.username: return parsed.username # 若URL带有显式认证用户名则优先返回
        path_parts = [p for p in parsed.path.strip("/").split("/") if p] # 拆分URL路径段
        if path_parts: return path_parts[0] # 返回第一段owner名称作为用户名
    if remote_url.startswith("git@"): # 处理SSH scp风格URL（如git@github.com:owner/repo.git）
        parts = remote_url.split("@", 1) # 按@符号拆分
        if len(parts) == 2 and ":" in parts[1]: # 检查冒号分隔符
            path_parts = [p for p in parts[1].split(":", 1)[1].strip("/").split("/") if p] # 提取冒号后的路径首段
            if path_parts: return path_parts[0] # 返回owner名称
    path_parts = [p for p in (parsed.path if parsed.path else remote_url).strip("/").split("/") if p] # 兜底拆分路径
    return path_parts[0] if path_parts else None # 返回首段或None
def parse_user_identity_input(value: str, current_name: str, current_email: str, default_name: str, default_email: str) -> tuple[str, str]: # 解析交互式输入的用户名与邮箱配置（支持1/2快捷选项及逗号/空格分隔）
    answer = value.strip() # 去除首尾空白
    if answer in ("", "1"): return current_name, current_email # 回车或输入1保留当前本地配置
    if answer == "2": return default_name, default_email # 输入2采用从远程URL推导的默认配置
    normalized = answer.replace("，", ",").replace("、", ",") # 将中文逗号或顿号统一替换为英文逗号
    if "," in normalized: name, email = (part.strip() for part in normalized.split(",", 1)) # 按逗号拆分为姓名与邮箱
    else: # 未含逗号时按空白字符拆分
        parts = normalized.split() # 按空格切分字段
        if len(parts) < 2: name, email = normalized, f"{normalized}@users.noreply.github.com" # 仅输入单个词时自动补全GitHub隐私邮箱后缀
        else: name, email = " ".join(parts[:-1]).strip(), parts[-1].strip() # 最后一个词作为邮箱，前面部分合并为姓名
    return name or current_name or default_name, email or current_email or default_email # 确保姓名和邮箱均非空
def apply_git_user_config(remote_url: str, user_arg: str, no_ask: bool = False, repo_root: Path = None): # 使用Dulwich检查并配置当前仓库的user.name与user.email
    if not remote_url and not user_arg: return # 无远程URL且未传-u参数时跳过
    remote_user = extract_remote_user_from_url(remote_url) # 从远程URL提取目标用户名
    r = open_repo(repo_root) # 打开目标仓库
    cfg = r.get_config() # 获取本地仓库配置对象
    if user_arg is not None: # 若显式指定了-u/--user参数
        target_user = remote_user if user_arg == "AUTO" else user_arg # AUTO模式取URL用户名，否则取用户传入值
        if not target_user: target_user = "git_user"; logger.warning("无法提取用户名，回退为 'git_user'") # 无法提取时回退默认值
        target_email = f"{target_user}@users.noreply.github.com" # 构造GitHub noreply标准邮箱
        logger.info(f"强制应用用户配置 (-u): user.name=[{target_user}], user.email=[{target_email}]") # 打印强制应用日志
        cfg.set((b"user",), b"name", target_user.encode("utf-8")) # 写入user.name到Dulwich配置
        cfg.set((b"user",), b"email", target_email.encode("utf-8")) # 写入user.email到Dulwich配置
        cfg.write_to_path(); r.close(); return # 保存.git/config并关闭仓库
    if not remote_user: r.close(); return # 未能从URL提取出用户名时直接返回
    if no_ask: logger.info("非交互模式：保留当前 Git 用户配置。"); r.close(); return # 免询问模式下不弹窗直接保留现状
    try: local_name = cfg.get((b"user",), b"name").decode("utf-8", errors="replace").strip() # 读取当前仓库user.name
    except KeyError: local_name = "" # 未设置时为空字符串
    try: local_email = cfg.get((b"user",), b"email").decode("utf-8", errors="replace").strip() # 读取当前仓库user.email
    except KeyError: local_email = "" # 未设置时为空字符串
    default_email = f"{remote_user}@users.noreply.github.com" # 计算远程用户名对应的默认邮箱
    if local_name != remote_user or local_email != default_email: # 当本地配置与远程目标不一致时提示交互选择
        logger.warning("发现当前 Git 用户配置与远程目标不一致！") # 打印不一致提醒
        print(f"  [1] 保留当前配置: name='{local_name or '未设置'}', email='{local_email or '未设置'}' (默认)") # 选项1说明
        print(f"  [2] 使用远程默认: name='{remote_user}', email='{default_email}'") # 选项2说明
        print("  或直接输入新配置: 用户名,邮箱（也支持用空格分隔）") # 自定义格式说明
        try: identity = input("请选择 [1/2] 或输入自定义身份 (直接回车选1): ") # 读取终端用户输入
        except KeyboardInterrupt: r.close(); sys.exit(130) # 用户Ctrl+C中断时退出
        target_name, target_email = parse_user_identity_input(identity, local_name, local_email, remote_user, default_email) # 解析用户输入的身份配置
        if target_name: cfg.set((b"user",), b"name", target_name.encode("utf-8")) # 更新user.name
        if target_email: cfg.set((b"user",), b"email", target_email.encode("utf-8")) # 更新user.email
        cfg.write_to_path() # 保存配置到.git/config
        logger.info(f"✅ 应用本次 Commit 配置: user.name={target_name}, user.email={target_email}") # 输出确认日志
    r.close() # 关闭仓库句柄
def get_staged_blob_sizes(repo_root: Path) -> list[tuple[str, int]]: # 使用Dulwich直接比对Index与HEAD Tree并返回所有暂存变更路径及其Blob字节大小
    try: # 打开仓库读取索引与对象库
        r = open_repo(repo_root) # 打开目标仓库
        idx = r.open_index() # 打开.git/index
        head_tree = {} # 存储HEAD提交中的文件路径与(sha, mode)映射
        try: # 尝试获取HEAD Tree内容
            head_commit = r[r.head()] # 读取HEAD Commit对象
            for entry in r.object_store.iter_tree_contents(head_commit.tree): head_tree[entry.path] = (entry.sha, entry.mode) # 记录每个受管路径的SHA与模式
        except Exception: pass # 初始空仓库无HEAD时保持为空字典
        result = [] # 存储(相对路径字符串, Blob大小)结果列表
        for path_bytes, idx_entry in idx.items(): # 检查索引中新增或修改的条目
            old = head_tree.get(path_bytes) # 查找HEAD中的对应条目
            if old and old[0] == idx_entry.sha and old[1] == idx_entry.mode: continue # SHA与权限均未变则跳过
            path_str = path_bytes.decode("utf-8", errors="surrogateescape") # 解码文件路径
            blob_size = 0 # 默认对象大小为0（例如gitlink子模块条目）
            if idx_entry.sha in r.object_store: # 若对象存在于Dulwich对象库中
                blob_size = r.object_store[idx_entry.sha].raw_length() # 直接获取索引Blob对象的真实大小而不读工作区文件
            result.append((path_str, blob_size)) # 记录变更路径及Blob字节数
        for path_bytes in head_tree: # 检查在索引中被删除的文件条目
            if path_bytes not in idx: result.append((path_bytes.decode("utf-8", errors="surrogateescape"), 0)) # 已删除文件计入变更列表且Blob体积记为0
        r.close(); return result # 关闭仓库并返回暂存变更清单
    except Exception: return [] # 异常时返回空列表
def _dulwich_commit_current_index(repo_root: Path, commit_msg: str) -> str | None: # 使用Dulwich将当前Index直接生成Commit对象并更新HEAD引用
    try: # 构建Tree与Commit对象
        r = open_repo(repo_root) # 打开目标仓库
        cfg = r.get_config_stack() # 获取合并后的配置栈（含仓库级与全局配置）
        try: name = cfg.get((b"user",), b"name").decode("utf-8", errors="replace") # 读取用户名
        except KeyError: name = "git_user" # 默认用户名
        try: email = cfg.get((b"user",), b"email").decode("utf-8", errors="replace") # 读取邮箱
        except KeyError: email = f"{name}@users.noreply.github.com" # 默认邮箱
        author_bytes = f"{name} <{email}>".encode("utf-8") # 组装标准Git签名格式字节串
        commit_sha = dulwich.porcelain.commit(repo=str(repo_root), message=commit_msg.encode("utf-8"), author=author_bytes, committer=author_bytes) # 调用Dulwich生成提交
        r.close() # 关闭仓库句柄
        return commit_sha.decode("ascii") if isinstance(commit_sha, bytes) else str(commit_sha) # 返回40位十六进制Commit SHA字符串
    except Exception as exc: logger.error(f"Dulwich 提交失败: {exc}"); return None # 提交异常时记录错误并返回None
def commit_staged_changes(repo_root: Path, commit_msg: str, max_commit_bytes: int) -> list[str] | None: # 当单次暂存总大小超限时自动用Dulwich拆分为多个有界批次提交
    staged = get_staged_blob_sizes(repo_root) # 获取所有暂存路径及其Blob大小
    if not staged: return None # 暂存区无任何改动时返回None
    total_size = sum(size for _, size in staged) # 计算所有暂存Blob的总字节数
    if total_size <= max_commit_bytes or len(staged) <= 1: # 若未超过单次提交上限或仅有一个文件则单次提交
        cid = _dulwich_commit_current_index(repo_root, commit_msg) # 直接提交当前索引
        return [cid] if cid else None # 返回包含单个Commit ID的列表
    batches, current, current_size = [], [], 0 # 初始化批次列表、当前批次文件列表与当前批次累计体积
    for path, size in sorted(staged, key=lambda item: item[0]): # 按路径字典序稳定排序后贪心分批
        if current and current_size + size > max_commit_bytes: # 若加入当前文件会超过单提交阈值
            batches.append(current); current, current_size = [], 0 # 封存当前批次并开启新批次
        current.append(path); current_size += size # 将文件路径加入当前批次并累加体积
    if current: batches.append(current) # 将最后一批尾随文件加入批次列表
    logger.warning(f"暂存内容约 {total_size / 1024 / 1024 / 1024:.2f} GiB，超过单提交上限 {max_commit_bytes / 1024 / 1024 / 1024:.2f} GiB，将拆分为 {len(batches)} 个提交。") # 打印自动拆分提示
    r = open_repo(repo_root) # 打开仓库以备份当前完整暂存快照并重置索引回HEAD基线
    full_idx = r.open_index() # 打开包含全部暂存变更的当前索引
    staged_snapshot = {k: full_idx[k] for k in full_idx.keys()} # 完整备份所有暂存IndexEntry条目到内存字典
    head_entries = {} # 保存HEAD基准提交的索引状态
    try: # 若存在HEAD提交则提取其Tree作为初始索引基线
        head_commit = r[r.head()] # 获取HEAD Commit对象
        for entry in r.object_store.iter_tree_contents(head_commit.tree): # 遍历HEAD Tree所有条目
            obj = r.object_store[entry.sha] # 读取对应Blob对象
            head_entries[entry.path] = dulwich.index.IndexEntry(ctime=(0, 0), mtime=(0, 0), dev=0, ino=0, mode=entry.mode, uid=0, gid=0, size=obj.raw_length(), sha=entry.sha, flags=0) # 构造基准IndexEntry
    except Exception: pass # 首次提交无HEAD时基线为空
    full_idx.clear() # 清空当前索引（等同git reset -- .）
    for k, v in head_entries.items(): full_idx[k] = v # 将索引恢复为HEAD基线状态
    full_idx.write(); r.close() # 写回基线索引并关闭仓库
    committed_ids = [] # 记录每一批成功提交生成的Commit SHA
    for index, batch in enumerate(batches, 1): # 逐批应用索引增量并生成独立Commit
        try: # 打开索引并仅应用当前批次路径的暂存状态
            r = open_repo(repo_root); idx = r.open_index() # 打开仓库与索引
            for path_str in batch: # 遍历当前批次内的每个文件路径
                p_bytes = path_str.encode("utf-8", errors="surrogateescape") # 转为索引键字节串
                if p_bytes in staged_snapshot: idx[p_bytes] = staged_snapshot[p_bytes] # 新增或修改文件写入快照中的IndexEntry
                elif p_bytes in idx: del idx[p_bytes] # 删除操作则从当前索引中移除该键
            idx.write(); r.close() # 保存当前批次索引状态
        except Exception as error: logger.error(f"第 {index}/{len(batches)} 段重新暂存失败: {error}"); return None # 暂存失败时报错中断
        part_msg = f"【{index}/{len(batches)}】文件数：{len(batch)} {commit_msg}" # 构造带分段序号与文件数的前缀提交说明
        cid = _dulwich_commit_current_index(repo_root, part_msg) # 使用Dulwich提交当前批次
        if not cid: logger.error(f"第 {index}/{len(batches)} 段提交失败！"); return None # 提交失败时返回None
        committed_ids.append(cid) # 记录该段Commit SHA
        logger.info(f"✅ 已提交第 {index}/{len(batches)} 段，文件数: {len(batch)}") # 打印分段提交成功日志
    return committed_ids # 返回所有分段Commit SHA列表
def _inspect_worktree_and_submodules(repo_root: Path) -> tuple[list[str], list[str], set[str]]: # 使用Dulwich检测工作区变更、已暂存变更及子模块路径集合
    staged_list = [p for p, _ in get_staged_blob_sizes(repo_root)] # 获取所有已暂存变更的文件路径列表
    submodule_paths = set() # 存储所有模式为0o160000的子模块路径
    dirty_submodules = [] # 存储内部存在未提交修改的子模块路径
    try: # 读取索引中的gitlink子模块条目
        r = open_repo(repo_root); idx = r.open_index() # 打开仓库与索引
        for path_bytes, entry in idx.items(): # 遍历索引条目识别子模块
            if getattr(entry, "mode", 0) == 0o160000: # 0o160000为Git子模块gitlink标准模式
                sub_rel = path_bytes.decode("utf-8", errors="surrogateescape") # 解码子模块相对路径
                submodule_paths.add(sub_rel) # 加入子模块路径集合
                sub_dir = repo_root / sub_rel # 定位子模块工作目录
                if is_git_repository(sub_dir): # 若子模块已检出为Git仓库则检查其内部是否有未提交改动
                    st = dulwich.porcelain.status(str(sub_dir)) # 使用Dulwich获取子模块status
                    if any(st.staged.values()) or st.unstaged or st.untracked: dirty_submodules.append(sub_rel) # 子模块内部存在暂存/未暂存/未跟踪文件时记入列表
        r.close() # 关闭父仓库句柄
    except Exception: pass # 忽略读取异常
    return staged_list + dirty_submodules, staged_list, submodule_paths # 返回总变更列表、已暂存列表及子模块路径集
def git_push(branch: str, repo_root: Path, extra_args: list[str], commit_msg: str = "", remote_url: str = "", user_arg: str = None, retry_count: int = 10, retry_seconds: int = 5, connect_timeout: int = 45, low_speed_limit: int = 1000, low_speed_time: int = 30, no_ask: bool = False, lfs_paths: set[str] | None = None, max_commit_bytes: int = 1900 * 1024 * 1024): # 使用Dulwich完成全套自动暂存、LFS校验、分段提交与网络重试推送
    EmptyAfterPush = False # 标记推送完成后是否需要清空ReadMe.md
    logger.info(f"当前工作目录: {repo_root.resolve()}") # 打印当前仓库绝对路径
    if not is_git_repository(repo_root): logger.error("当前目录尚未初始化 Git 仓库。"); sys.exit(1) # 校验Git仓库有效性
    apply_git_user_config(remote_url, user_arg, no_ask, repo_root) # 检查并应用Git用户身份配置
    if not stage_all_and_renormalize(repo_root, lfs_paths=lfs_paths, cleanup_deleted=True): logger.error("Dulwich add 暂存失败"); sys.exit(1) # 全量暂存工作区改动并转换LFS指针
    if lfs_paths and not renormalize_lfs(repo_root, lfs_paths, cleanup_deleted=False): sys.exit(1) # 对扫描出的大文件执行二次规范化确认
    if (repo_root / ".gitattributes").is_file(): # 若仓库存在.gitattributes文件
        if not verify_staged_lfs_files(repo_root): sys.exit(1) # 严格校验所有匹配LFS规则的暂存文件必须为LFS指针
    changed_files, staged_files, submodule_paths = _inspect_worktree_and_submodules(repo_root) # 获取工作区、暂存区与子模块状态
    if not staged_files: # 若父仓库没有可提交的暂存内容
        submodule_changes = [path for path in changed_files if path in submodule_paths or any(path.startswith(f"{item}/") for item in submodule_paths)] # 筛选出子模块内部未提交改动
        if submodule_changes: # 提示用户先处理子模块提交
            logger.warning(f"检测到子模块内部有未提交修改，但父仓库没有可提交的暂存内容: {submodule_changes}") # 告警子模块未提交修改
            logger.warning("请进入子模块单独提交，或在父仓库提交子模块更新后的 gitlink。") # 给出操作指引
        changed_files = [] # 将可提交变更置空
    else: changed_files = staged_files # 以实际已暂存文件列表作为本次提交变更集
    if not commit_msg: # 未手动指定-m提交说明时自动选取体积最大的变更文件生成说明
        max_file, max_size = None, -1 # 初始化最大文件名与最大字节数
        for rel in changed_files: # 遍历所有变更文件
            fp = repo_root / rel # 拼接工作区文件路径
            if not fp.is_file(): continue # 已删除文件或目录跳过
            try: sz = fp.stat().st_size # 获取文件字节大小
            except OSError: continue # 忽略stat异常
            if sz > max_size: max_size, max_file = sz, rel.replace("\\", "/") # 更新最大文件记录
        commit_msg = f"[{max_file} {max_size}B] {stime()} {__file__[-20:]} auto" if max_file else f" auto {stime()}" # 生成与原版格式完全一致的自动提交消息
    commit_ids = [] # 保存本次生成的Commit SHA列表
    if changed_files: # 存在暂存变更时执行提交
        logger.info(f"变更文件: {len(changed_files)} 个" + (f" (显示前10: {changed_files[:10]})" if len(changed_files) > 10 else f" {changed_files}")) # 打印变更文件数量与摘要
        for f in changed_files: # 检查是否修改了ReadMe.md且包含#EmptyAfterPush指令
            if f == "ReadMe.md" and (repo_root / "ReadMe.md").is_file(): # 定位ReadMe.md文件
                with open(repo_root / "ReadMe.md", "rb") as fh: # 读取ReadMe.md二进制内容
                    if b"#EmptyAfterPush" in fh.read(): EmptyAfterPush = True # 检测到指令标记时置位EmptyAfterPush
        commit_ids = commit_staged_changes(repo_root, commit_msg, max_commit_bytes) # 执行单次或自动分批提交
        if not commit_ids: logger.error("git commit 失败。请确认暂存内容。"); sys.exit(1) # 提交失败时报错退出
    else: logger.info("暂存区为空") # 无新增变更时直接推送已有提交
    is_debug = logger.getEffectiveLevel() <= logging.DEBUG # 判断是否处于调试日志模式
    force_push = any(a in ("-f", "--force", "--force-with-lease") for a in extra_args) # 识别额外参数中的强制推送标志
    if lfs_paths and shutil.which("git") and check_lfs_available(): # 若包含LFS大文件且安装了git-lfs则先推送LFS二进制对象至远端LFS服务器
        subprocess.run([shutil.which("git"), "lfs", "push", "--all", remote_url, branch], cwd=repo_root, check=False) # 上传本地.git/lfs/objects中的大文件实体
    push_targets = commit_ids or [None] # 若有分段提交则逐段推送，否则直接推送当前分支引用
    for index, commit_id in enumerate(push_targets, 1): # 遍历每个待推送目标
        refspec = f"{commit_id}:refs/heads/{branch}".encode("utf-8") if commit_id else f"refs/heads/{branch}:refs/heads/{branch}".encode("utf-8") # 构造精确推送refspec
        op_label = f"推送第 {index}/{len(push_targets)} 段" if len(push_targets) > 1 else "推送" # 构造日志操作名称
        def _push_op(rs=refspec): # 定义Dulwich推送操作闭包
            dulwich.porcelain.push(str(repo_root), remote_location=remote_url, refspecs=[rs], force=force_push, errstream=sys.stdout.buffer if is_debug else io.BytesIO()) # 使用Dulwich porcelain.push推送对象包并更新远端引用
        run_network_retry(_push_op, op_label, remote_url, branch, retry_count, retry_seconds, is_debug, connect_timeout) # 带网络重试执行推送
    if EmptyAfterPush: # 若触发了推送后清空ReadMe.md特性
        with open(repo_root / "ReadMe.md", "wb") as f: f.write(b"") # 将ReadMe.md截断为空文件
        logger.info(f"EmptyAfterPush 成功 {stime()}") # 记录清空成功日志
    logger.info(f"✅ 推送成功 {stime()}") # 打印最终推送完成日志
def git_list_big(repo_root: Path, threshold_bytes: int) -> list[tuple[int, str, str]]: # 使用Dulwich遍历全库历史所有可达Commit与Tree扫描超过阈值的历史大Blob
    logger.info(f"===== 扫描历史大文件 >= {threshold_bytes / 1024 / 1024:.2f} MB =====") # 打印扫描阈值标题
    try: # 遍历Dulwich对象存储中的所有引用与历史树
        r = open_repo(repo_root) # 打开目标仓库
        store = r.object_store # 获取Git对象存储实例
        visited_commits, visited_trees, found_blobs = set(), set(), {} # 记录已访问Commit、Tree及已命中的大Blob(sha -> (size, path))
        count = 0 # 统计已扫描的Git对象总数
        stack = list(r.refs.as_dict().values()) # 从所有分支与标签引用指向的SHA开始遍历
        def _walk_tree(tree_id: bytes, prefix: str): # 递归遍历Tree对象内部条目
            nonlocal count # 引用外层对象计数器
            if tree_id in visited_trees: return # 避免重复扫描相同子树
            visited_trees.add(tree_id); count += 1 # 标记该Tree已访问并递增计数
            if count % 10000 == 0: logger.info(f"已扫描 {count} 个对象...") # 每扫描10000个对象输出一次进度
            try: tree_obj = store[tree_id] # 从对象库读取Tree实例
            except Exception: return # 忽略缺失对象
            if not isinstance(tree_obj, Tree): return # 类型保护
            for item in tree_obj.items(): # 遍历Tree中的每个子项(name, mode, sha)
                name_str = item.path.decode("utf-8", errors="surrogateescape") # 解码文件名或子目录名
                full_path = f"{prefix}/{name_str}" if prefix else name_str # 拼接相对仓库根目录的完整路径
                if stat.S_ISDIR(item.mode): _walk_tree(item.sha, full_path) # 若为子目录Tree则递归深入
                elif item.sha not in found_blobs: # 若为文件Blob且尚未记录过
                    count += 1 # 累加对象扫描计数
                    if count % 10000 == 0: logger.info(f"已扫描 {count} 个对象...") # 定期输出扫描进度
                    try: # 读取Blob对象大小
                        obj = store[item.sha] # 获取Blob对象
                        if obj.type_name == b"blob": # 确认为Blob类型
                            sz = obj.raw_length() # 获取未压缩字节大小
                            if sz >= threshold_bytes: found_blobs[item.sha.decode("ascii")] = (sz, full_path) # 超过阈值则记入结果字典
                    except Exception: pass # 忽略损坏或浅克隆缺失的Blob
        while stack: # 深度优先遍历所有历史Commit链
            sha = stack.pop() # 弹出一个待访问SHA
            if sha in visited_commits: continue # 已访问过则跳过
            visited_commits.add(sha); count += 1 # 标记已访问并累加计数
            try: obj = store[sha] # 读取对象
            except Exception: continue # 忽略不可读对象
            if isinstance(obj, Tag): stack.append(obj.object[1]); continue # 若是附注标签Tag对象则压入其指向的目标对象SHA
            if isinstance(obj, Commit): # 若是Commit提交对象
                _walk_tree(obj.tree, "") # 扫描该Commit对应的根Tree
                for p in obj.parents: # 将所有父Commit加入待扫描栈
                    if p not in visited_commits: stack.append(p) # 压入未访问的父提交
        r.close() # 关闭仓库句柄
        large_files = [(sz, path, b_hash) for b_hash, (sz, path) in found_blobs.items()] # 转换为(字节大小, 路径, Blob哈希)元组列表
        large_files.sort(key=lambda x: x[0], reverse=True) # 按文件大小从大到小降序排列
        if not large_files: logger.info("🎉 未发现超过阈值的大文件。") # 无大文件时打印祝贺提示
        else: # 打印格式化表格展示大文件清单
            print(f"\n{'大小 (MB)':<12} | {'Blob Hash':<40} | {'文件路径'}") # 打印表头
            print("-" * 85) # 打印分隔线
            for size, path, blob_hash in large_files: print(f"{size / 1024 / 1024:<12.2f} | {blob_hash:<40} | {path}") # 逐行打印MB大小、40位SHA与路径
        return large_files # 返回扫描出的历史大文件列表
    except Exception as e: logger.error(f"扫描失败: {e}"); return [] # 异常时记录日志并返回空列表
def git_remove_big(repo_root: Path, threshold_bytes: int, target_hashes: list[str] = None): # 使用Dulwich纯Python重写包含指定大Blob的历史Tree与Commit链以擦除大文件
    logger.info("===== 准备清理历史大文件 =====") # 打印清理开始标题
    logger.info("🛡️ 仅移除指定 Blob 及其关联 Commit，更早的历史哈希保持不变。\n") # 说明重写策略：未受影响的早期Commit哈希完全不变
    hashes_to_remove = set() # 存储待擦除的40位十六进制Blob SHA集合
    if target_hashes: # 若用户通过--hashes手动指定了目标Blob哈希列表
        for h in target_hashes: # 遍历用户传入的哈希列表
            if h.strip(): hashes_to_remove.add(h.strip().lower()) # 归一化为小写后加入待删集合
        logger.info(f"使用指定 {len(hashes_to_remove)} 个 Blob Hash 进行精准删除。") # 打印指定哈希数量
    else: # 未手动指定哈希时自动调用git_list_big扫描所有超过阈值的大Blob
        large_files = git_list_big(repo_root, threshold_bytes) # 扫描全库历史大文件
        if not large_files: logger.info("没有符合条件的大文件。"); return # 无大文件时直接返回
        for _, _, blob_hash in large_files: hashes_to_remove.add(blob_hash.lower()) # 收集所有超限Blob哈希
    if not hashes_to_remove: return # 集合为空时直接结束
    logger.info(f"即将擦除 {len(hashes_to_remove)} 个 Blob:") # 打印即将擦除的Blob列表
    for h in sorted(hashes_to_remove): logger.info(f"  - {h}") # 逐行输出每个目标Blob哈希
    target_bytes_set = {h.encode("ascii") for h in hashes_to_remove} # 转为字节集合加速Dulwich内部比对
    try: # 使用Dulwich执行拓扑序Commit与Tree历史改写
        r = open_repo(repo_root); store = r.object_store # 打开仓库与对象存储
        tree_map = {} # 缓存旧Tree SHA -> 改写后新Tree SHA（None表示整棵子树被删空）
        def _rewrite_tree(tree_sha: bytes) -> bytes | None: # 递归改写Tree对象剔除目标Blob
            if tree_sha in tree_map: return tree_map[tree_sha] # 命中缓存直接返回
            tree_obj = store[tree_sha] # 读取原始Tree对象
            changed, new_items = False, [] # 标记当前Tree是否发生变更及保留下来的条目列表
            for item in tree_obj.items(): # 遍历Tree中所有条目
                if stat.S_ISDIR(item.mode): # 若是子目录Tree
                    new_sub = _rewrite_tree(item.sha) # 递归改写子Tree
                    if new_sub != item.sha: changed = True # 子Tree变化则标记当前Tree已变更
                    if new_sub is not None: new_items.append((item.path, item.mode, new_sub)) # 非空子Tree保留
                else: # 若是普通文件或符号链接Blob
                    if item.sha in target_bytes_set: changed = True; continue # 命中待删大文件哈希则直接跳过（即从历史树中擦除）
                    new_items.append((item.path, item.mode, item.sha)) # 保留其他正常文件
            if not changed: tree_map[tree_sha] = tree_sha; return tree_sha # 未发生任何删除时完全复用原Tree SHA确保早期历史不变
            if not new_items: tree_map[tree_sha] = None; return None # 所有条目均被清空时返回None
            new_tree = Tree() # 创建新的Dulwich Tree对象
            for p, m, s in new_items: new_tree.add(p, m, s) # 将保留的条目写入新Tree
            store.add_object(new_tree) # 将新Tree写入对象存储
            tree_map[tree_sha] = new_tree.id; return new_tree.id # 缓存并返回新Tree的SHA
        all_refs = r.refs.as_dict() # 获取仓库当前所有分支与标签引用字典
        topo_commits, visited = [], set() # 收集所有可达Commit并按父先于子的拓扑顺序排列
        def _collect_dfs(c_sha: bytes): # 后序DFS收集Commit确保父提交永远排在子提交前面
            if c_sha in visited: return # 已访问则跳过
            visited.add(c_sha) # 标记已访问
            try: obj = store[c_sha] # 读取对象
            except Exception: return # 忽略不可读对象
            if isinstance(obj, Commit): # 仅处理Commit对象
                for p in obj.parents: _collect_dfs(p) # 先递归处理所有父Commit
                topo_commits.append(c_sha) # 再将当前Commit追加到拓扑序列末尾
        for ref_sha in all_refs.values(): _collect_dfs(ref_sha) # 从所有引用起点开始收集拓扑序列
        commit_map = {} # 记录旧Commit SHA -> 新Commit SHA的映射关系
        for old_c_sha in topo_commits: # 按从老到新的拓扑序逐个检查并改写Commit
            c_obj = store[old_c_sha] # 读取原始Commit对象
            new_tree_sha = _rewrite_tree(c_obj.tree) # 获取改写后的根Tree SHA
            if new_tree_sha is None: # 若根Tree变为空树则创建一个空Tree对象承载提交
                empty_t = Tree(); store.add_object(empty_t); new_tree_sha = empty_t.id # 添加空Tree
            new_parents = [commit_map.get(p, p) for p in c_obj.parents] # 将父提交列表替换为映射后的新父提交SHA
            if new_tree_sha == c_obj.tree and new_parents == list(c_obj.parents): # 若Tree未变且所有父提交哈希均未变
                commit_map[old_c_sha] = old_c_sha; continue # 完全保持原Commit哈希不变（守护更早的历史哈希）
            new_c = Commit() # 构造改写后的新Commit对象
            new_c.tree = new_tree_sha; new_c.parents = new_parents # 绑定新Tree与新父提交列表
            new_c.author = c_obj.author; new_c.committer = c_obj.committer # 保留原提交者与作者身份
            new_c.author_time = c_obj.author_time; new_c.commit_time = c_obj.commit_time # 保留原提交时间戳
            new_c.author_timezone = c_obj.author_timezone; new_c.commit_timezone = c_obj.commit_timezone # 保留原时区信息
            new_c.encoding = c_obj.encoding; new_c.message = c_obj.message # 保留原编码与提交说明
            store.add_object(new_c) # 将新Commit写入Dulwich对象库
            commit_map[old_c_sha] = new_c.id # 记录旧Commit到新Commit的映射
        for ref_name, old_sha in all_refs.items(): # 更新所有受影响的分支与引用指向新Commit
            if old_sha in commit_map and commit_map[old_sha] != old_sha: r.refs[ref_name] = commit_map[old_sha] # 原子更新引用指针
        r.close() # 关闭仓库句柄
        msg = "\nfilter-repo / Dulwich 重写历史后，旧对象还在本地 git 库，磁盘空间不会立刻释放，需要手动：\ngit reflog expire --expire=now --all\ngit gc --prune=now --aggressive\n✅ 历史大文件 Blob 已擦除 （ 之前 Commit 保留未动）\n" # 构造完成说明信息
        logger.info(msg); logger.warning("⚠️ 历史已重写，推送需使用 --force") # 输出清理成功日志与强推提醒
    except Exception as exc: logger.error(f"❌ 清理失败: {exc}"); sys.exit(1) # 改写失败时报错退出
def git_undo(repo_root: Path): # 使用Dulwich撤销上一次提交并将改动退回工作区（等同reset --soft HEAD~1 && reset HEAD .）
    logger.info("===== 撤销上一次提交 =====") # 打印撤销标题
    try: # 操作Dulwich引用与索引回退到HEAD~1
        r = open_repo(repo_root) # 打开目标仓库
        head_commit = r[r.head()] # 获取当前HEAD Commit对象
        if not head_commit.parents: logger.error("当前提交没有父提交，无法回退 HEAD~1。"); r.close(); sys.exit(1) # 初始根提交无父节点时报错
        parent_sha = head_commit.parents[0] # 获取第一父提交HEAD~1的SHA
        sym_ref = r.refs.read_ref(b"HEAD") # 读取HEAD符号引用
        if sym_ref and sym_ref.startswith(b"ref: "): r.refs[sym_ref[5:].strip()] = parent_sha # 若在分支上则将该分支引用回退至parent_sha
        else: r.refs[b"HEAD"] = parent_sha # 分离头指针状态下直接回退HEAD
        parent_commit = r[parent_sha] # 读取父提交对象以将其Tree同步回.git/index而不改动工作区文件
        idx = r.open_index(); idx.clear() # 打开并清空当前暂存区索引
        for entry in r.object_store.iter_tree_contents(parent_commit.tree): # 将HEAD~1的Tree条目写回索引（实现reset HEAD .取消暂存效果）
            obj = r.object_store[entry.sha] # 读取Blob对象以获取体积
            idx[entry.path] = dulwich.index.IndexEntry(ctime=(0, 0), mtime=(0, 0), dev=0, ino=0, mode=entry.mode, uid=0, gid=0, size=obj.raw_length(), sha=entry.sha, flags=0) # 重建父提交索引项
        idx.write(); r.close() # 保存索引并关闭仓库，工作区文件保持丝毫未动
        logger.info("✅ 撤销完成，工作区文件未改动。") # 输出撤销完成提示
    except Exception as exc: logger.error(f"撤销失败: {exc}"); sys.exit(1) # 异常时报错退出
def git_init_repo(repo_root: Path, remote_url: str = ""): # 使用Dulwich初始化Git仓库并绑定origin远程地址
    logger.info("===== 执行 git init =====") # 打印初始化日志
    if not (repo_root / ".git").exists(): Repo.init(str(repo_root)) # 若尚未初始化则调用Dulwich Repo.init创建.git目录结构
    if remote_url: set_remote(remote_url, repo_root) # 若提供了远程URL则写入remote.origin配置
    logger.info("✅ 初始化完成！") # 打印完成日志
def main(): # 主入口函数：解析参数并分发执行全部九种模式
    sys.argv = preprocess_args() # 预处理命令行参数
    default_git = os.environ.get("GIT_PATH", "git") # 读取环境变量默认git路径（兼容保留--git参数）
    configured_branch = os.environ.get("BRANCH") # 从环境变量读取默认分支配置
    parser = argparse.ArgumentParser(description="Git Auto LFS Tool (Dulwich Edition)") # 创建命令行参数解析器
    parser.add_argument("--git", default=default_git, help="git 可执行文件路径（兼容参数）") # 保留--git参数完全兼容原CLI
    parser.add_argument("--repo-path", "--repo", "--path", "-path", "-p", dest="repo_path", default=".", help="指定 Git 仓库路径，默认使用当前目录") # 仓库路径参数及全部别名
    parser.add_argument("--branch", "-b", default=configured_branch, help="分支名称") # 分支名称参数
    parser.add_argument("--size", "-s", default="100mb", help="大文件大小限制（默认 100mb）") # 大文件阈值字符串参数
    parser.add_argument("--threshold", type=int, default=0, help="字节数阈值（兼容）") # 兼容精确字节数阈值参数
    parser.add_argument("--hashes", "--hash", default="", help="手动指定 Blob Hash，逗号分隔") # remove-big手动指定Blob哈希参数
    parser.add_argument("--remote", default="", help="完整远程 URL") # 远程仓库URL参数
    parser.add_argument("--commit-msg", "--commit_msg", "-m", default="", help="自定义 commit 消息") # 提交说明参数
    parser.add_argument("--user", "-u", nargs="?", const="AUTO", default=None, help="自动配置 Git 用户") # 自动或指定Git用户配置参数
    parser.add_argument("--noask", "-noask", "--no-ask", "-y", "-yes", dest="no_ask", action="store_true", help="非交互模式：自动确认初始化并跳过用户配置询问") # 免询问开关及所有别名
    parser.add_argument("--retry", "-retry", "-r", type=int, default=10, help="Push/Pull 失败重试次数") # 网络操作最大重试次数
    parser.add_argument("--verbose", "-v", type=int, default=2, help="日志级别: 0=Error, 1=Warn, 2=Info, 3=Debug") # 日志详细程度级别
    parser.add_argument("--connect-timeout", type=int, default=45, help="HTTP TCP连接建立超时时间（秒），默认45") # 连接建立超时秒数
    parser.add_argument("--low-speed-limit", type=int, default=10, help="传输低速阈值（字节/秒），低于该值持续指定时间则断开") # 低速限制阈值参数
    parser.add_argument("--low-speed-time", type=int, default=60, help="低速持续超时时间（秒）") # 低速持续时间参数
    parser.add_argument("--max-commit-size", type=parse_size_str, default=1900 * 1024 * 1024, help="单个提交的最大暂存 Blob 大小（默认 1900mb，超过后自动分段）") # 单次提交最大体积上限
    parser.add_argument("mode", nargs="?", default="push", choices=["push", "pull", "clone", "config", "init", "list-big", "listbig", "remove-big", "undo"]) # 子命令模式位置参数
    args, extra = parser.parse_known_args() # 解析已知参数并将透传参数存入extra
    setup_logging(args.verbose) # 根据--verbose配置日志输出
    repo_root = Path(args.repo_path).expanduser().resolve() # 解析并规范化目标仓库目录路径
    if not repo_root.is_dir(): logger.critical(f"指定的仓库路径不存在或不是目录: {repo_root}"); sys.exit(1) # 目录不存在时报错退出
    os.chdir(repo_root) # 切换当前工作目录至目标仓库路径
    if args.mode == "push" and not is_git_repository(repo_root): # 若在未初始化目录执行push则询问是否自动init
        logger.warning("当前目录尚未初始化 Git 仓库。") # 打印未初始化警告
        choice = "yes" if args.no_ask else "" # 免询问模式下直接默认确认yes
        if not args.no_ask: # 交互模式下询问用户
            try: choice = input("是否执行 git init 初始化当前目录？[Y/n]: ").strip().lower() # 读取用户确认输入
            except KeyboardInterrupt: sys.exit(130) # Ctrl+C中断退出
        if choice not in ("", "y", "yes"): logger.info("已取消初始化，操作终止。"); return # 用户拒绝时终止操作
        try: Repo.init(str(repo_root)) # 使用Dulwich初始化当前目录为Git仓库
        except Exception as exc: logger.error(f"git init 失败: {exc}"); sys.exit(1) # 初始化失败时退出
    if not args.branch and args.mode in ("push", "pull"): args.branch = get_current_branch(repo_root) or "main" # 未指定分支时自动读取当前分支或回退main
    remote_url = args.remote or get_origin_url(repo_root) or get_branch_tracking_url(args.branch, repo_root) # 按命令行->origin->分支tracking顺序解析远程URL
    clone_branch, clone_subdirectory = args.branch, None # 初始化克隆分支与GitHub子目录路径
    explicit_branch = any(option in sys.argv[1:] for option in ("--branch", "-b")) # 检查用户是否在命令行显式指定了分支参数
    if remote_url and args.mode in ("push", "pull", "clone"): # 解析GitHub子目录或分支树URL
        remote_url, url_branch, clone_subdirectory = parse_github_subdirectory_url(remote_url) # 拆解仓库URL、分支名与子目录
        if url_branch and not explicit_branch: args.branch = url_branch; clone_branch = url_branch # 未显式传-b时采用URL中携带的分支名
    if not remote_url and args.mode not in ("list-big", "listbig", "remove-big", "undo"): logger.critical("未提供远程仓库地址，且未找到 origin/tracking 配置。"); sys.exit(1) # 强依赖远端的模式缺失URL时退出
    threshold_bytes = args.threshold if args.threshold > 0 else parse_size_str(args.size) # 计算大文件字节阈值
    logger.info(f"仓库路径: {repo_root.absolute()}") # 输出仓库路径信息
    logger.info(f"Git引擎: Dulwich {dulwich.__version__.__str__() if hasattr(dulwich, '__version__') else 'native'}") # 输出Dulwich引擎版本信息
    if args.mode != "init": logger.info(f"文件限制: {threshold_bytes / 1024 / 1024:.2f} MB ({threshold_bytes} 字节)") # 非init模式输出大文件限制阈值
    if remote_url: logger.info(f"远程地址: {redact_url(remote_url)}") # 输出脱敏后的远程URL
    logger.info(f"分支: {clone_branch if args.mode == 'clone' else args.branch}") # 输出当前操作目标分支
    logger.info(f"连接超时: {args.connect_timeout}s | 低速阈值: {args.low_speed_limit}B/s | 低速超时: {args.low_speed_time}s") # 输出网络超时配置
    try: # 根据mode分发执行对应核心逻辑
        if args.mode == "config": # 仅根据远程URL配置当前仓库用户信息
            logger.info("===== 根据远程 URL 配置当前仓库用户 =====") # 打印config标题
            apply_git_user_config(remote_url, "AUTO", args.no_ask, repo_root) # 强制应用从URL提取的用户配置
            logger.info("✅ 当前仓库用户配置完成！"); return # 完成后返回
        if args.mode == "clone": # 执行克隆或子目录提取及LFS恢复
            git_clone(clone_branch, remote_url, extra, clone_subdirectory, connect_timeout=args.connect_timeout, low_speed_limit=args.low_speed_limit, low_speed_time=args.low_speed_time, retry_count=args.retry) # 调用Dulwich克隆函数
            logger.info("✅ clone 及 LFS 大文件恢复完成！"); return # 完成后返回
        if args.mode == "undo": git_undo(repo_root); return # 执行撤销上一次提交
        if args.mode == "init": git_init_repo(repo_root, remote_url); return # 执行仓库初始化与origin绑定
        if args.mode in ("list-big", "listbig"): git_list_big(repo_root, threshold_bytes); return # 执行历史大文件扫描列表
        if args.mode == "remove-big": # 执行历史大文件擦除
            target_hashes = [h.strip() for h in args.hashes.split(",") if h.strip()] if args.hashes else None # 解析逗号分隔的Blob哈希参数
            git_remove_big(repo_root, threshold_bytes, target_hashes) # 调用Dulwich历史重写函数擦除大Blob
            if remote_url: set_remote(remote_url, repo_root); logger.info("✅ 远程地址已重新绑定。") # 重新绑定origin远程地址
            return # 完成后返回
        large_files = scan_large_files(repo_root, threshold_bytes) # 在pull/push前扫描工作区本地大文件
        has_large = len(large_files) > 0 # 判断是否存在超限本地大文件
        logger.info(f"扫描到 {len(large_files)} 个本地大文件") # 输出扫描统计结果
        if has_large: # 若存在本地大文件则配置LFS并更新.gitattributes
            if not check_lfs_available(): # 检查LFS支持状态
                if not install_lfs() or not check_lfs_available(): logger.critical("Git LFS 安装后仍不可用"); sys.exit(1) # 不可用时报错退出
            if not init_lfs(repo_root): sys.exit(1) # 初始化仓库LFS配置与本地对象目录
            clean_and_apply_lfs(repo_root, large_files) # 更新.gitattributes追踪所有扫描出的大文件
        if remote_url: set_remote(remote_url, repo_root) # 确保origin远程地址已同步更新
        if args.mode == "pull": git_pull(args.branch, extra, remote_url, retry_count=args.retry, connect_timeout=args.connect_timeout, low_speed_limit=args.low_speed_limit, low_speed_time=args.low_speed_time, repo_root=repo_root) # 执行Dulwich拉取
        elif args.mode == "push": git_push(args.branch, repo_root, extra, args.commit_msg, remote_url, args.user, args.retry, connect_timeout=args.connect_timeout, low_speed_limit=args.low_speed_limit, low_speed_time=args.low_speed_time, no_ask=args.no_ask, lfs_paths=large_files, max_commit_bytes=args.max_commit_size) # 执行Dulwich推送
        logger.info("✅ 操作结束！") # 打印全局完成提示
    except KeyboardInterrupt: logger.warning("\n[CANCEL] 用户手动终止。"); sys.exit(130) # 捕获全局Ctrl+C中断信号并以130状态码退出
if __name__ == "__main__": main() # 脚本直接执行时调用main入口函数
