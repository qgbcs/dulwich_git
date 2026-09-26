#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""git_logic_dulwich.py —— 用 dulwich + Python 标准库复刻 QGB/git.bat 的 git_logic.py 全部细节功能。
   模式: push / pull / clone / config / init / undo / list-big(listbig) / remove-big
   不依赖任何 git 可执行文件与 git-lfs / git-filter-repo 外部程序。"""
import argparse, base64, json, logging, netrc, os, posixpath, shutil, stat as statmod, sys, tempfile, time, urllib.error, urllib.request  # 仅标准库
from fnmatch import fnmatch  # .gitattributes / 通配符匹配
from pathlib import Path
from urllib.parse import urlparse, urlunparse, quote
from dulwich import porcelain  # 高层命令
from dulwich.repo import Repo  # 仓库对象
from dulwich.objects import Blob, Tree, Commit  # 底层对象
from dulwich.index import Index, IndexEntry  # 索引读写
from dulwich.errors import NotGitRepository  # 异常
from dulwich.ignore import IgnoreFilterManager  # .gitignore 支持
logger = logging.getLogger("GitAutoLFS")  # 与原版同名 logger
LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1\n"  # LFS 指针文件头
DEFAULT_THRESHOLD = 104857600  # 默认大文件阈值 100MB
def setup_logging(verbosity: int):
    levels = {0: logging.ERROR, 1: logging.WARNING, 2: logging.INFO, 3: logging.DEBUG}  # -v 次数映射日志级别
    level = levels.get(verbosity, logging.DEBUG if verbosity > 3 else logging.ERROR)  # 超过 3 个 v 一律 DEBUG
    handler = logging.StreamHandler(sys.stdout)  # 输出到 stdout，便于管道重定向
    handler.setFormatter(logging.Formatter(fmt='%(asctime)s | %(levelname)-7s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))  # 与原版格式一致
    logger.setLevel(level)
    if not logger.handlers: logger.addHandler(handler)  # 避免重复添加 handler
def stime() -> str:
    ft = time.time()  # 当前时间戳
    return time.strftime('%Y-%m-%d__%H.%M.%S', time.localtime(ft)) + '__.' + f"{ft:.3f}".split('.')[1]  # 形如 2026-01-01__12.00.00__.123
def looks_like_url(s: str) -> bool:
    return s.startswith("https://") or s.startswith("git@") or "://" in s  # 判断参数是否是远程地址
def redact_url(value: str) -> str:
    parsed = urlparse(value)  # 日志里隐藏 URL 中的密码
    if parsed.scheme and parsed.netloc and "@" in parsed.netloc:
        userinfo, host = parsed.netloc.rsplit("@", 1)
        return urlunparse(parsed._replace(netloc=f"{userinfo.split(':', 1)[0]}:***@{host}"))
    return value
def parse_size_str(val) -> int:
    if not val: return DEFAULT_THRESHOLD  # 空值用默认阈值
    s = str(val).strip().lower(); multiplier = 1
    if s.endswith("gb") or s.endswith("g"): multiplier, s = 1024 ** 3, s.rstrip("gb").rstrip("g")  # GiB
    elif s.endswith("mb") or s.endswith("m"): multiplier, s = 1024 ** 2, s.rstrip("mb").rstrip("m")  # MiB
    elif s.endswith("kb") or s.endswith("k"): multiplier, s = 1024, s.rstrip("kb").rstrip("k")  # KiB
    elif s.endswith("b"): s = s.rstrip("b")  # 纯字节
    try: return int(float(s) * multiplier)
    except ValueError: return DEFAULT_THRESHOLD  # 解析失败回落默认值
# ===================== 仓库基础封装（替代 git 子进程） =====================
def open_repo(path: Path) -> Repo:
    try: return Repo.discover(str(path))  # 向上查找 .git，等价 git rev-parse --git-dir
    except NotGitRepository:
        logger.error("当前目录尚未初始化 Git 仓库。"); sys.exit(1)
def is_git_repository(path: Path) -> bool:
    try: Repo.discover(str(path)); return True  # 探测是否在仓库内
    except NotGitRepository: return False
def repo_root_of(repo: Repo) -> Path:
    return Path(repo.path).resolve()  # 工作区根目录
def get_current_branch(repo: Repo) -> str:
    try:
        ref = repo.refs.follow(b"HEAD")[0][-1]  # 解析符号引用，未出生分支同样可得
        return ref.decode().removeprefix("refs/heads/") if ref.startswith(b"refs/heads/") else ""
    except Exception: return ""
def get_origin_url(repo: Repo, remote: str = "origin") -> str:
    try: return repo.get_config().get((b"remote", remote.encode()), b"url").decode()  # 读取 remote.origin.url
    except KeyError: return ""
def get_branch_tracking_url(repo: Repo, branch: str) -> str:
    cfg = repo.get_config()
    try: remote_name = cfg.get((b"branch", branch.encode()), b"remote").decode()  # branch.<name>.remote
    except KeyError: return ""
    url = get_origin_url(repo, remote_name)
    return url or (remote_name if looks_like_url(remote_name) else "")  # 允许直接把 URL 写在 branch.remote 里
def set_remote(repo: Repo, remote_url: str):
    if not remote_url: return
    cfg = repo.get_config(); key = (b"remote", b"origin")
    try: old = cfg.get(key, b"url").decode()
    except KeyError: old = ""
    if old == remote_url: return  # 地址未变则不写盘
    logger.info("更新远程 origin 地址..." if old else "添加远程 origin 地址...")
    cfg.set(key, b"url", remote_url.encode()); cfg.set(key, b"fetch", b"+refs/heads/*:refs/remotes/origin/*"); cfg.write_to_path()
# ===================== 用户身份配置（对应 apply_git_user_config） =====================
def infer_user_from_url(remote_url: str):
    if not remote_url: return None
    parsed = urlparse(remote_url)
    if parsed.scheme and parsed.netloc:
        if parsed.username: return parsed.username  # 优先 URL 内嵌用户名
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if parts: return parts[0]  # https://host/<owner>/repo.git
    if remote_url.startswith("git@") and ":" in remote_url:
        parts = [p for p in remote_url.split("@", 1)[1].split(":", 1)[1].strip("/").split("/") if p]
        if parts: return parts[0]  # git@host:<owner>/repo.git
    parts = [p for p in remote_url.strip("/").split("/") if p]
    return parts[0] if parts else None
def parse_user_identity_input(value: str, current_name: str, current_email: str, default_name: str, default_email: str):
    answer = value.strip()
    if answer in ("", "1"): return current_name, current_email  # 回车/1 保持现状
    if answer == "2": return default_name, default_email  # 2 使用远端推断值
    normalized = answer.replace("，", ",").replace("、", ",")  # 兼容中文逗号
    if "," in normalized:
        name, email = (p.strip() for p in normalized.split(",", 1)); return name, email
    parts = normalized.split()
    if len(parts) >= 2: return parts[0], parts[1]  # "name email"
    single = parts[0] if parts else current_name
    return (current_name, single) if "@" in single else (single, current_email)  # 只给一个值时按是否含 @ 判断
def apply_git_user_config(repo: Repo, remote_url: str, user_arg, no_ask: bool):
    cfg = repo.get_config()
    def _get(k, d=""):
        try: return cfg.get((b"user",), k).decode()
        except KeyError: return d
    current_name, current_email = _get(b"name"), _get(b"email")  # 当前仓库级身份
    guess = infer_user_from_url(remote_url) or current_name or "git"  # 从远端地址推断用户名
    default_name, default_email = guess, f"{guess}@users.noreply.github.com"  # 默认邮箱用 noreply
    name, email = current_name, current_email
    if user_arg and user_arg != "AUTO":
        name, email = parse_user_identity_input(user_arg, current_name or default_name, current_email or default_email, default_name, default_email)  # 命令行显式指定
    elif not (current_name and current_email) or user_arg == "AUTO":
        if no_ask: name, email = (current_name or default_name), (current_email or default_email)  # -y 时不交互
        else:
            print(f"请选择 Git 身份: 1) 保持 [{current_name} <{current_email}>]  2) 使用 [{default_name} <{default_email}>]  或直接输入 'name,email'")
            try: name, email = parse_user_identity_input(input("> "), current_name or default_name, current_email or default_email, default_name, default_email)
            except EOFError: name, email = default_name, default_email  # 无 tty 时退回默认
    if name: cfg.set((b"user",), b"name", name.encode())
    if email: cfg.set((b"user",), b"email", email.encode())
    cfg.write_to_path(); logger.info(f"Git 身份: {name} <{email}>")
    return name, email
# ===================== 凭据（供 dulwich 与 LFS HTTP 复用） =====================
def get_credentials(remote_url: str):
    parsed = urlparse(remote_url)
    if parsed.username: return parsed.username, (parsed.password or os.environ.get("GIT_PASSWORD") or os.environ.get("GIT_TOKEN") or "")  # URL 内嵌
    u, p = os.environ.get("GIT_USERNAME"), os.environ.get("GIT_PASSWORD") or os.environ.get("GIT_TOKEN")
    if u and p: return u, p  # 环境变量
    host = parsed.hostname or ""
    try:
        auth = netrc.netrc().authenticators(host)  # ~/.netrc
        if auth: return auth[0], auth[2]
    except Exception: pass
    cred = Path.home() / ".git-credentials"
    if host and cred.is_file():
        for line in cred.read_text(encoding="utf-8", errors="replace").splitlines():
            q = urlparse(line.strip())
            if q.hostname == host and q.username: return q.username, q.password or ""  # ~/.git-credentials
    return None, None
# ===================== 本地大文件扫描（对应 scan_large_files） =====================
def scan_large_files(repo_root: Path, threshold: int):
    large_files, skip_dirs = set(), {".git", "dist", "__pycache__"}  # 跳过目录与原版一致
    scanned_files = scanned_dirs = 0; last_report = time.monotonic()
    for current_root, dirnames, filenames in os.walk(repo_root, topdown=True, followlinks=False):
        dirnames[:] = [n for n in dirnames if n not in skip_dirs]
        dirnames[:] = [n for n in dirnames if not (Path(current_root) / n / ".git").exists()]  # 子模块是独立工作区，必须排除
        scanned_dirs += 1
        for filename in filenames:
            path = Path(current_root) / filename
            if path.is_symlink(): continue  # 符号链接不计入
            scanned_files += 1
            try: fsize = path.lstat().st_size
            except OSError: continue
            if fsize >= threshold: large_files.add(str(path.relative_to(repo_root)).replace("\\", "/"))  # 统一 POSIX 分隔符
            now = time.monotonic()
            if now - last_report >= 1:  # 每秒刷新一行进度
                display = str(path.relative_to(repo_root)).replace("\\", "/")
                prefix = f"扫描文件: {scanned_files:,} | 目录: {scanned_dirs:,} | 当前: "
                available = max(1, shutil.get_terminal_size(fallback=(120, 1)).columns - len(prefix) - 1)
                if len(display) > available: display = "..." + display[-max(1, available - 3):]
                sys.stdout.write("\r\033[2K" + prefix + display); sys.stdout.flush(); last_report = now
    if scanned_files: sys.stdout.write("\r\033[2K"); sys.stdout.flush()  # 清掉进度行
    return large_files
def clean_and_apply_lfs(repo_root: Path, large_patterns):
    attr_path = repo_root / ".gitattributes"; other_lines, lfs_lines, nested = [], set(), set()
    for current_root, dirnames, _ in os.walk(repo_root, topdown=True, followlinks=False):
        dirnames[:] = [n for n in dirnames if n != ".git"]
        for name in list(dirnames):
            nested_root = Path(current_root) / name
            if (nested_root / ".git").exists(): nested.add(nested_root.relative_to(repo_root).as_posix() + "/"); dirnames.remove(name)  # 记录嵌套仓库前缀
    if attr_path.exists():
        for line in attr_path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped: continue
            if "filter=lfs" in stripped:
                rule_path = stripped.split(None, 1)[0].strip('"')
                if any(rule_path.startswith(p) for p in nested): continue  # 丢弃指向子模块的旧规则
                if (repo_root / rule_path).is_symlink(): continue  # 丢弃指向软链的旧规则
                lfs_lines.add(stripped)
            else: other_lines.append(stripped)
    for pat in large_patterns:
        safe = f'"{pat}"' if " " in pat else pat  # 含空格的路径加引号
        lfs_lines.add(f"{safe} filter=lfs diff=lfs merge=lfs -text")
    all_rules = other_lines + sorted(lfs_lines)
    if all_rules:
        attr_path.write_text("\n".join(all_rules) + "\n", encoding="utf-8")
        logger.info(f".gitattributes 更新完成，LFS追踪总数: {len(lfs_lines)}")
def load_lfs_patterns(repo_root: Path):
    patterns, attr_path = [], repo_root / ".gitattributes"
    if attr_path.exists():
        for line in attr_path.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s and "filter=lfs" in s: patterns.append(s.split(None, 1)[0].strip('"'))  # 收集所有 LFS 通配规则
    return patterns
def path_is_lfs(rel: str, patterns) -> bool:
    return any(fnmatch(rel, p) or fnmatch(posixpath.basename(rel), p) or rel == p for p in patterns)  # 简化版 check-attr filter=lfs
# ===================== 纯 Python 的 LFS 实现（clean / smudge / batch 传输） =====================
def lfs_dir(repo: Repo) -> Path:
    return Path(repo.controldir()) / "lfs" / "objects"  # .git/lfs/objects
def lfs_object_path(repo: Repo, oid: str) -> Path:
    return lfs_dir(repo) / oid[:2] / oid[2:4] / oid  # 与官方 git-lfs 目录布局一致
def lfs_clean(repo: Repo, full: Path):
    import hashlib
    h, size = hashlib.sha256(), 0
    with open(full, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk); size += len(chunk)  # 分块计算 sha256
    oid = h.hexdigest(); dst = lfs_object_path(repo, oid)
    if not dst.exists(): dst.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(full, dst)  # 入库大文件本体
    return (LFS_PREFIX + f"oid sha256:{oid}\nsize {size}\n".encode()), oid, size  # 返回指针内容
def parse_lfs_pointer(data: bytes):
    if not data.startswith(LFS_PREFIX) or len(data) > 1024: return None  # 非指针
    oid = size = None
    for line in data.decode("utf-8", "replace").splitlines():
        if line.startswith("oid sha256:"): oid = line.split(":", 1)[1].strip()
        elif line.startswith("size "): size = int(line.split()[1])
    return (oid, size) if oid else None
def lfs_endpoint(remote_url: str) -> str:
    p = urlparse(remote_url)
    if p.scheme not in ("http", "https"):
        if remote_url.startswith("git@") and ":" in remote_url:  # SSH 地址推断出 https LFS 端点
            host, path = remote_url.split("@", 1)[1].split(":", 1); remote_url = f"https://{host}/{path}"; p = urlparse(remote_url)
        else: return ""
    path = p.path.removesuffix("/").removesuffix(".git")
    return urlunparse(p._replace(netloc=p.netloc.rsplit("@", 1)[-1], path=path + ".git/info/lfs", query="", fragment=""))
def lfs_batch(remote_url: str, operation: str, objects):
    endpoint = lfs_endpoint(remote_url)
    if not endpoint or not objects: return []
    body = json.dumps({"operation": operation, "transfers": ["basic"], "objects": objects}).encode()
    req = urllib.request.Request(endpoint + "/objects/batch", data=body, method="POST")
    req.add_header("Accept", "application/vnd.git-lfs+json"); req.add_header("Content-Type", "application/vnd.git-lfs+json")
    user, pwd = get_credentials(remote_url)
    if user: req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{pwd or ''}".encode()).decode())  # Basic 认证
    with urllib.request.urlopen(req, timeout=60) as resp: return json.loads(resp.read().decode()).get("objects", [])
def lfs_push(repo: Repo, remote_url: str, oids):
    oids = [o for o in oids if o]  # 需要上传的 oid 列表
    if not oids: return
    objs = []
    for oid in set(oids):
        p = lfs_object_path(repo, oid)
        if p.exists(): objs.append({"oid": oid, "size": p.stat().st_size})
    if not objs: return
    logger.info(f"LFS: 向远端申请上传 {len(objs)} 个对象...")
    for item in lfs_batch(remote_url, "upload", objs):
        action = (item.get("actions") or {}).get("upload")
        if not action: continue  # 远端已存在则无 upload action
        src = lfs_object_path(repo, item["oid"])
        with open(src, "rb") as f:
            req = urllib.request.Request(action["href"], data=f.read(), method="PUT")
            for k, v in (action.get("header") or {}).items(): req.add_header(k, v)
            try:
                urllib.request.urlopen(req, timeout=600); logger.info(f"LFS 上传完成: {item['oid'][:12]} ({item['size']}B)")
            except urllib.error.HTTPError as e: logger.error(f"LFS 上传失败 {item['oid'][:12]}: {e}")
def lfs_smudge_worktree(repo: Repo, remote_url: str):
    root, pending = repo_root_of(repo), {}
    for cur, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != ".git"]
        for fn in files:
            p = Path(cur) / fn
            try:
                if p.is_symlink() or p.stat().st_size > 1024: continue  # 指针文件很小，先按大小过滤
                info = parse_lfs_pointer(p.read_bytes())
            except OSError: continue
            if info: pending.setdefault(info[0], []).append((p, info[1]))  # oid -> 若干路径
    if not pending: return
    logger.info(f"LFS: 需要还原 {len(pending)} 个大文件对象...")
    objs = [{"oid": oid, "size": v[0][1] or 0} for oid, v in pending.items()]
    for item in lfs_batch(remote_url, "download", objs):
        action = (item.get("actions") or {}).get("download")
        if not action: continue
        req = urllib.request.Request(action["href"])
        for k, v in (action.get("header") or {}).items(): req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=600) as resp: data = resp.read()
        except urllib.error.HTTPError as e: logger.error(f"LFS 下载失败 {item['oid'][:12]}: {e}"); continue
        store = lfs_object_path(repo, item["oid"]); store.parent.mkdir(parents=True, exist_ok=True); store.write_bytes(data)  # 落本地缓存
        for p, _ in pending[item["oid"]]: p.write_bytes(data); logger.info(f"LFS 还原: {p.relative_to(repo_root_of(repo))}")
# ===================== 索引 / 暂存 / 提交（dulwich 版） =====================
def make_entry(st, sha: bytes, size: int, mode=None) -> IndexEntry:
    return IndexEntry(ctime=int(getattr(st, "st_ctime", 0)), mtime=int(getattr(st, "st_mtime", 0)), dev=getattr(st, "st_dev", 0), ino=getattr(st, "st_ino", 0),
                      mode=mode or (0o100755 if getattr(st, "st_mode", 0) & 0o111 else 0o100644), uid=getattr(st, "st_uid", 0), gid=getattr(st, "st_gid", 0),
                      size=size, sha=sha)  # 手工构造索引条目，兼容各版本 dulwich
def head_tree(repo: Repo):
    try: return repo[repo[repo.head()].tree]  # HEAD 提交对应的树
    except (KeyError, IndexError): return None
def iter_tree(repo: Repo, tree, prefix=b""):
    for entry in tree.items():
        full = prefix + entry.path
        obj = repo[entry.sha]
        if isinstance(obj, Tree): yield from iter_tree(repo, obj, full + b"/")  # 递归子目录
        else: yield full, entry.mode, entry.sha
def reset_index_to_head(repo: Repo):
    idx = repo.open_index(); idx.clear() if hasattr(idx, "clear") else [idx.__delitem__(k) for k in list(idx)]  # 清空索引
    tree = head_tree(repo)
    if tree is not None:
        for path, mode, sha in iter_tree(repo, tree): idx[path] = IndexEntry(0, 0, 0, 0, mode, 0, 0, 0, sha)  # 只对齐索引，不动工作区
    idx.write()
def collect_worktree_changes(repo: Repo, patterns):
    """返回 (待更新路径, 待删除路径)：对比工作区与 HEAD/索引，尊重 .gitignore。"""
    root, ignorer = repo_root_of(repo), IgnoreFilterManager.from_repo(repo)
    idx = repo.open_index(); present, updates = set(), []
    for cur, dirs, files in os.walk(root, topdown=True, followlinks=False):
        dirs[:] = [d for d in dirs if d != ".git" and not (Path(cur) / d / ".git").exists()]  # 跳过 .git 与子模块
        dirs[:] = [d for d in dirs if not ignorer.is_ignored(str((Path(cur) / d).relative_to(root)).replace("\\", "/") + "/")]
        for fn in files:
            p = Path(cur) / fn; rel = str(p.relative_to(root)).replace("\\", "/")
            if ignorer.is_ignored(rel): continue  # 被忽略
            present.add(rel.encode())
            try: st = p.lstat()
            except OSError: continue
            e = idx.get(rel.encode())
            if e is None or int(e.mtime) != int(st.st_mtime) or (e.size != st.st_size and not path_is_lfs(rel, patterns)): updates.append(rel)  # 变更判定
    deletions = [k.decode() for k in list(idx) if k not in present]  # 索引里有、工作区没有 → 删除
    return updates, deletions
def stage_changes(repo: Repo, updates, deletions, patterns):
    idx, root, staged_oids, sizes = repo.open_index(), repo_root_of(repo), [], {}
    for rel in deletions:
        try: del idx[rel.encode()]  # 记录删除
        except KeyError: pass
    for rel in updates:
        full = root / rel
        try: st = full.lstat()
        except OSError: continue
        if path_is_lfs(rel, patterns):
            data, oid, _ = lfs_clean(repo, full); staged_oids.append(oid)  # 大文件转为 LFS 指针
        else: data = full.read_bytes()
        blob = Blob.from_string(data); repo.object_store.add_object(blob)  # 写入对象库
        idx[rel.encode()] = make_entry(st, blob.id, len(data)); sizes[rel] = len(data)
    idx.write(); return staged_oids, sizes
def verify_lfs_pointers(repo: Repo, sizes, patterns, threshold: int) -> bool:
    for rel, size in sizes.items():
        if path_is_lfs(rel, patterns) and size > 1024:
            logger.error(f"❌ 命中 LFS 规则但仍是大 Blob: {rel} ({size}B)，请检查 .gitattributes 与规范化流程。"); return False  # 对应 verify_staged_lfs_blobs
    return True
def do_commit(repo: Repo, message: str, name: str, email: str):
    author = f"{name or 'git'} <{email or 'git@localhost'}>".encode()
    return repo.do_commit(message=message.encode(), committer=author, author=author)  # 由当前索引生成树并提交
def commit_staged_changes(repo: Repo, updates, deletions, sizes, commit_msg: str, max_commit_bytes: int, name, email, patterns):
    """暂存内容过大时按字节上限自动拆成多个提交（对应 commit_staged_changes）。"""
    total = sum(sizes.values())
    if total <= max_commit_bytes or len(updates) <= 1:
        return [do_commit(repo, commit_msg, name, email)]
    batches, current, cur_size = [], [], 0
    for rel in updates:
        sz = sizes.get(rel, 0)
        if current and cur_size + sz > max_commit_bytes: batches.append(current); current, cur_size = [], 0  # 切段
        current.append(rel); cur_size += sz
    if current: batches.append(current)
    logger.warning(f"暂存内容约 {total / 1024 ** 3:.2f} GiB，超过单提交上限 {max_commit_bytes / 1024 ** 3:.2f} GiB，将拆分为 {len(batches)} 个提交。")
    reset_index_to_head(repo); ids = []
    for i, batch in enumerate(batches, 1):
        stage_changes(repo, batch, deletions if i == 1 else [], patterns)  # 删除只放在第一段
        cid = do_commit(repo, f"【{i}/{len(batches)}】文件数：{len(batch)} {commit_msg}", name, email)
        ids.append(cid); logger.info(f"✅ 已提交第 {i}/{len(batches)} 段，文件数: {len(batch)}")
    return ids
# ===================== 网络重试（对应 run_network_retry 全部关键字） =====================
RETRY_NET_KEYWORDS = ["could not read from remote repository", "ssh: connect to host", "connection timed out", "the remote end hung up unexpectedly",
    "fatal: unable to access", "failed to connect to", "network is unreachable", "remote: fatal:", "dial tcp", "connectex", "a connection attempt failed",
    "connected party did not properly respond", "connected host has failed to respond", "curl 28", "rpc failed", "expected flush after ref listing",
    "connection was reset", "empty reply from server", "timed out", "temporary failure in name resolution", "eof occurred"]  # 可重试的网络错误
RETRY_AUTH_KEYWORDS = ["http 401", "http 403", "error: 401", "error: 403", "fatal: authentication failed", "permission to ", "permission denied (publickey)",
    "unauthorized", "forbidden"]  # 认证错误不重试
RETRY_LARGE_FILE_KEYWORDS = ["gh001: large files detected", "exceeds github's file size limit", "exceeds github's file size limit of 100.00 mb"]  # 历史大文件不可重试
def run_network_retry(action, operation: str, remote_url: str, branch: str, retry_count: int = 10, retry_seconds: int = 5, before_attempt=None):
    """通用网络重试：action 是无参可调用对象；成功返回其结果，历史大文件/认证失败立即退出。"""
    for attempt in range(1, retry_count + 1):
        logger.info(f"===== {operation} {redact_url(remote_url)} {branch} (尝试 {attempt}/{retry_count}) 间隔 {retry_seconds}s =====")
        if before_attempt is not None:
            try: before_attempt(attempt)  # clone 用它清理上次残留目录
            except Exception as exc: logger.warning(f"⚠️ 第 {attempt} 次尝试前的钩子异常: {exc!r}")
        try: return action()
        except SystemExit: raise
        except BaseException as exc:
            text = f"{exc!r} {exc}".lower()
            if any(k in text for k in RETRY_LARGE_FILE_KEYWORDS):
                logger.error("❌ 远端拒绝了历史中的大文件，当前工作区扫描不到并不代表历史对象已清除。")
                logger.error("请先执行 list-big 确认 Blob，再执行 remove-big 改写历史，然后使用 push --force 推送。")
                logger.error("如果希望保留这些文件，请先配置 LFS 并迁移历史，而不是只新增 .gitattributes。"); sys.exit(1)
            is_net, is_auth = any(k in text for k in RETRY_NET_KEYWORDS), any(k in text for k in RETRY_AUTH_KEYWORDS)
            if is_net and not is_auth: logger.warning(f"⚠️ 网络错误，稍后重试: {exc!r}")
            elif is_auth: logger.error(f"❌ {operation}失败（认证问题，不重试）: {exc!r}"); sys.exit(1)
            else: logger.warning(f"⚠️ 未知错误，重试: {exc!r}")
        if attempt < retry_count: time.sleep(retry_seconds)
    logger.error(f"❌ {operation} 在 {retry_count} 次尝试后仍然失败。"); sys.exit(1)
# ===================== GitHub 子目录 URL 解析（对应 parse_github_subdirectory_url） =====================
def parse_github_subdirectory_url(remote_url: str):
    parsed = urlparse(remote_url)
    if parsed.scheme not in ("http", "https") or (parsed.hostname or "").lower() not in ("github.com", "www.github.com"): return remote_url, None, None
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) == 3:
        owner, repository, branch = parts; repository = repository.removesuffix(".git")
        return urlunparse(parsed._replace(path=f"/{owner}/{repository}.git", params="", query="", fragment="")), branch, None  # owner/repo/branch
    if len(parts) > 4 and parts[2] in ("tree", "blob"):
        owner, repository, _, branch = parts[:4]; repository = repository.removesuffix(".git")
        return urlunparse(parsed._replace(path=f"/{owner}/{repository}.git", params="", query="", fragment="")), branch, "/".join(parts[4:])  # 子目录
    return remote_url, None, None
# ===================== clone / pull / push =====================
def porcelain_kwargs(remote_url: str):
    user, pwd = get_credentials(remote_url)
    return {"username": user, "password": pwd} if user else {}  # dulwich 支持 username/password 关键字
def git_clone(branch, remote_url, extra_args, sparse_path=None, retry_count=10, retry_seconds=5, depth=None):
    base_dir = Path.cwd()
    positional = [a for a in extra_args if not a.startswith("-")]
    destination = Path(positional[-1]) if positional else None
    if destination is None:
        name = (sparse_path.rstrip("/").rsplit("/", 1)[-1] if sparse_path else remote_url.rstrip("/").rsplit("/", 1)[-1])
        if ":" in name and not remote_url.startswith(("http://", "https://")): name = name.rsplit(":", 1)[-1]
        destination = Path(name.removesuffix(".git"))  # 从 URL 推断目录名
    if not destination.is_absolute(): destination = base_dir / destination  # 统一绝对路径，不依赖 CWD
    branch_display = branch or "<default>"
    def _cleanup(_attempt):
        if destination.exists():
            logger.info(f"清理克隆残留目录: {destination}")
            shutil.rmtree(destination, ignore_errors=True) if destination.is_dir() else destination.unlink(missing_ok=True)
    def _clone():
        kw = dict(porcelain_kwargs(remote_url))
        if branch: kw["branch"] = branch.encode()
        if depth: kw["depth"] = int(depth)
        return porcelain.clone(remote_url, str(destination), errstream=sys.stdout.buffer, **kw)  # 实际克隆
    if destination.exists() and (destination / ".git").exists():
        logger.info(f"目标目录已存在且是仓库，改为执行 pull: {destination}")  # 恢复路径：已有健康仓库直接 pull
        git_pull(branch, [], remote_url, retry_count, retry_seconds, destination); return
    repo = run_network_retry(_clone, "克隆", remote_url, branch_display, retry_count, retry_seconds, before_attempt=_cleanup)
    if isinstance(repo, Repo):
        set_remote(repo, remote_url)
        if sparse_path: apply_sparse(repo, sparse_path)  # 仅保留子目录
        lfs_smudge_worktree(repo, remote_url)  # 还原 LFS 指针为真实文件
        repo.close()
def apply_sparse(repo: Repo, sparse_path: str):
    root, keep = repo_root_of(repo), sparse_path.strip("/")
    logger.info(f"应用稀疏检出，仅保留子目录: {keep}")
    for child in list(root.iterdir()):
        if child.name == ".git": continue
        rel = child.name
        if not (keep == rel or keep.startswith(rel + "/")): shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink(missing_ok=True)  # 删掉无关顶层项
def git_pull(branch, extra_args, remote_url, retry_count=10, retry_seconds=5, repo_root: Path = None):
    repo = open_repo(repo_root or Path.cwd())
    remote_url = remote_url or get_branch_tracking_url(repo, branch or get_current_branch(repo)) or get_origin_url(repo)
    if not remote_url: logger.error("未找到远程地址，无法 pull。"); sys.exit(1)
    branch = branch or get_current_branch(repo) or "master"
    def _pull():
        porcelain.pull(repo, remote_url, refspecs=[f"refs/heads/{branch}".encode()], errstream=sys.stdout.buffer, **porcelain_kwargs(remote_url)); return True
    run_network_retry(_pull, "拉取", remote_url, branch, retry_count, retry_seconds)
    try: porcelain.reset(repo, "hard", repo.head())  # 把工作区更新到最新提交
    except Exception as exc: logger.warning(f"⚠️ 检出工作区时告警: {exc!r}")
    lfs_smudge_worktree(repo, remote_url); logger.info(f"✅ 拉取成功 {stime()}"); repo.close()
def git_push(branch, repo_root: Path, extra_args, commit_msg="", remote_url="", user_arg=None, retry_count=10, retry_seconds=5,
             no_ask=False, threshold=DEFAULT_THRESHOLD, max_commit_bytes=1900 * 1024 * 1024, force=False):
    EmptyAfterPush = False  # ReadMe.md 内含 #EmptyAfterPush 时推送后清空该文件
    logger.info(f"当前工作目录: {repo_root.resolve()}")
    if not is_git_repository(repo_root): logger.error("当前目录尚未初始化 Git 仓库。"); sys.exit(1)
    repo = open_repo(repo_root); root = repo_root_of(repo)
    remote_url = remote_url or get_origin_url(repo)
    name, email = apply_git_user_config(repo, remote_url, user_arg, no_ask)
    patterns = load_lfs_patterns(root)
    updates, deletions = collect_worktree_changes(repo, patterns)
    max_file, max_size = "", 0
    for rel in updates:
        try: sz = (root / rel).lstat().st_size
        except OSError: continue
        if sz > max_size: max_size, max_file = sz, rel  # 找出最大变更文件用于提交信息
    commit_msg = commit_msg or (f"[{max_file} {max_size}B] {stime()} {Path(__file__).name[-20:]} auto" if max_file else f" auto {stime()}")
    commit_ids, oids = [], []
    if updates or deletions:
        shown = updates[:10]
        logger.info(f"变更文件: {len(updates)} 个" + (f" (显示前10: {shown})" if len(updates) > 10 else f" {updates}") + (f" 删除: {len(deletions)} 个" if deletions else ""))
        if "ReadMe.md" in updates and (root / "ReadMe.md").exists() and b"#EmptyAfterPush" in (root / "ReadMe.md").read_bytes(): EmptyAfterPush = True
        oids, sizes = stage_changes(repo, updates, deletions, patterns)
        if not verify_lfs_pointers(repo, sizes, patterns, threshold): sys.exit(1)
        commit_ids = commit_staged_changes(repo, updates, deletions, sizes, commit_msg, max_commit_bytes, name, email, patterns)
        if not commit_ids: logger.error("提交失败，请检查索引与工作区状态。"); sys.exit(1)
        logger.info(f"已生成提交: {[c.decode()[:12] for c in commit_ids]}")
    else: logger.info("暂存区为空")
    branch = branch or get_current_branch(repo) or "master"
    if not remote_url: logger.error("未配置远程地址，无法推送。"); sys.exit(1)
    if oids: lfs_push(repo, remote_url, oids)  # 先传 LFS 本体，再推指针，顺序不可颠倒
    def _push():
        porcelain.push(repo, remote_url, [f"refs/heads/{branch}:refs/heads/{branch}".encode()], errstream=sys.stdout.buffer, force=force, **porcelain_kwargs(remote_url)); return True
    run_network_retry(_push, "强制推送" if force else "推送", remote_url, branch, retry_count, retry_seconds)
    if EmptyAfterPush:
        (root / "ReadMe.md").write_bytes(b""); logger.info(f"EmptyAfterPush 成功 {stime()}")
    logger.info(f"✅ 推送成功 {stime()}"); repo.close()
# ===================== 历史大文件：list-big / remove-big =====================
def all_commits(repo: Repo):
    seen, stack = set(), [sha for sha in repo.refs.as_dict().values()]
    try: stack.append(repo.head())
    except KeyError: pass
    order = []
    while stack:
        sha = stack.pop()
        if sha in seen: continue
        obj = repo.get_object(sha) if sha in repo.object_store else None
        if not isinstance(obj, Commit): continue
        seen.add(sha); order.append(sha); stack.extend(obj.parents)  # 遍历所有引用可达的提交
    return order
def blob_paths(repo: Repo):
    mapping = {}
    for csha in all_commits(repo):
        try: tree = repo[repo[csha].tree]
        except KeyError: continue
        for path, mode, sha in iter_tree(repo, tree): mapping.setdefault(sha, path.decode("utf-8", "replace"))  # blob → 历史路径
    return mapping
def git_list_big(repo_root: Path, threshold_bytes: int):
    repo = open_repo(repo_root)
    logger.info(f"===== 扫描历史大文件 >= {threshold_bytes / 1024 / 1024:.2f} MB =====")
    mapping, large, count = blob_paths(repo), [], 0
    for sha in repo.object_store:
        count += 1
        if count % 10000 == 0: logger.info(f"已扫描 {count} 个对象...")
        try: obj = repo.object_store[sha]
        except KeyError: continue
        if obj.type_name == b"blob" and obj.raw_length() >= threshold_bytes:
            large.append((obj.raw_length(), mapping.get(sha, "<unreachable>"), sha.decode()))
    large.sort(key=lambda x: x[0], reverse=True)
    if not large: logger.info("🎉 未发现超过阈值的大文件。")
    else:
        print(f"\n{'大小 (MB)':>12}  {'对象哈希':<42}  路径")
        for size, path, sha in large: print(f"{size / 1024 / 1024:12.2f}  {sha:<42}  {path}")
        print(f"\n合计 {len(large)} 个大 Blob，可执行 remove-big 改写历史后 push --force。")
    repo.close(); return large
def rewrite_tree(repo: Repo, tree: Tree, drop_shas, threshold, prefix=b"", to_lfs=False):
    new = Tree(); changed = False
    for entry in tree.items():
        obj = repo[entry.sha]
        if isinstance(obj, Tree):
            sub, sub_changed = rewrite_tree(repo, obj, drop_shas, threshold, prefix + entry.path + b"/", to_lfs)
            changed |= sub_changed
            if len(sub.items()): new.add(entry.path, entry.mode, sub.id)  # 空目录自动丢弃
            continue
        if obj.type_name == b"blob" and (entry.sha in drop_shas or (threshold and obj.raw_length() >= threshold)):
            changed = True; continue  # 命中则从历史中剔除该文件
        new.add(entry.path, entry.mode, entry.sha)
    repo.object_store.add_object(new); return new, changed
def git_remove_big(repo_root: Path, threshold_bytes: int, target_hashes=None):
    repo = open_repo(repo_root)
    drop = {h.strip().encode() for h in (target_hashes or []) if h.strip()}  # 指定哈希优先
    threshold = 0 if drop else threshold_bytes
    logger.info("===== 改写历史，移除大文件（等效 git filter-repo，纯 dulwich 实现） =====")
    commits = list(reversed(all_commits(repo)))  # 从最老的提交开始
    mapping, rewritten = {}, 0
    for csha in commits:
        commit = repo[csha]
        try: tree = repo[commit.tree]
        except KeyError: continue
        new_tree, changed = rewrite_tree(repo, tree, drop, threshold)
        parents = [mapping.get(p, p) for p in commit.parents]
        if not changed and parents == list(commit.parents): mapping[csha] = csha; continue  # 无变化则复用原提交
        nc = Commit(); nc.tree = new_tree.id; nc.parents = parents
        nc.author, nc.committer = commit.author, commit.committer
        nc.author_time, nc.commit_time = commit.author_time, commit.commit_time
        nc.author_timezone, nc.commit_timezone = commit.author_timezone, commit.commit_timezone
        nc.encoding, nc.message = commit.encoding, commit.message
        repo.object_store.add_object(nc); mapping[csha] = nc.id; rewritten += 1
    for ref, sha in list(repo.refs.as_dict().items()):
        if sha in mapping and mapping[sha] != sha: repo.refs[ref] = mapping[sha]  # 重定向所有引用
    logger.info(f"✅ 历史改写完成，重写提交 {rewritten} 个。请执行 push --force 推送，并让远端 GC 回收旧对象。")
    try:
        porcelain.reset(repo, "hard", repo.head()); reset_index_to_head(repo)  # 同步工作区与索引
    except Exception as exc: logger.warning(f"⚠️ 重置工作区告警: {exc!r}")
    repo.close()
def git_undo(repo_root: Path):
    repo = open_repo(repo_root)
    try: head = repo[repo.head()]
    except KeyError: logger.error("没有可撤销的提交。"); sys.exit(1)
    if not head.parents: logger.error("这是初始提交，无法 reset --soft HEAD~1。"); sys.exit(1)
    ref = repo.refs.follow(b"HEAD")[0][-1]; repo.refs[ref] = head.parents[0]  # 等价 reset --soft HEAD~1
    reset_index_to_head(repo)  # 等价 reset HEAD .，工作区文件不动
    logger.info("✅ 撤销完成，工作区文件未改动。"); repo.close()
def git_init(repo_root: Path, remote_url: str):
    logger.info("===== 执行 init =====")
    repo = Repo.init(str(repo_root)) if not (repo_root / ".git").exists() else open_repo(repo_root)
    if remote_url:
        cfg = repo.get_config()
        try: cfg.__delitem__((b"remote", b"origin"))  # 先移除旧 origin
        except Exception: pass
        cfg.write_to_path(); set_remote(repo, remote_url)
    logger.info("✅ 初始化完成！"); repo.close()
# ===================== 参数解析（对应 preprocess_args + main） =====================
def preprocess_args():
    valid_modes = {"push", "pull", "clone", "config", "init", "list-big", "listbig", "remove-big", "undo"}  # 合法模式
    no_ask_aliases = {"--noask", "-noask", "--no-ask", "-y", "-yes"}  # -y 系列别名
    raw, new, mode_found, i = sys.argv[1:], [], False, 0
    while i < len(raw):
        arg = raw[i]
        if arg in no_ask_aliases: new.append("--no-ask"); i += 1; continue  # 归一化
        if arg in ("-u", "--user") and (i + 1 >= len(raw) or raw[i + 1].startswith("-")): new += ["--user", "AUTO"]; i += 1; continue  # -u 不带值时自动推断
        if looks_like_url(arg): new += ["--url", arg]; i += 1; continue  # 裸 URL 转成 --url
        if not mode_found and arg in valid_modes: mode_found = True; new.append(arg); i += 1; continue
        new.append(arg); i += 1
    if not mode_found: new.insert(0, "push")  # 默认 push
    return new
def build_parser():
    p = argparse.ArgumentParser(description="dulwich 版 git 自动化工具（LFS / 重试 / 历史大文件治理）")
    p.add_argument("mode", nargs="?", default="push", help="push|pull|clone|config|init|undo|list-big|remove-big")
    p.add_argument("--url", default="", help="远程地址，也可直接写裸 URL")
    p.add_argument("-b", "--branch", default="", help="分支名，默认当前分支")
    p.add_argument("-m", "--commit-msg", default="", help="提交信息，默认自动生成")
    p.add_argument("-u", "--user", default=None, help="'name,email' 或 AUTO")
    p.add_argument("-s", "--size", default="", help="大文件阈值，如 100MB / 2g")
    p.add_argument("--retry", type=int, default=10, help="网络重试次数")
    p.add_argument("--retry-seconds", type=int, default=5, help="重试间隔秒")
    p.add_argument("--connect-timeout", type=int, default=45, help="连接超时秒")
    p.add_argument("--low-speed-limit", type=int, default=1000, help="低速阈值 B/s")
    p.add_argument("--low-speed-time", type=int, default=30, help="低速超时秒")
    p.add_argument("--depth", type=int, default=0, help="clone 浅克隆深度")
    p.add_argument("--force", action="store_true", help="push --force")
    p.add_argument("--hashes", default="", help="remove-big 指定的对象哈希，逗号分隔")
    p.add_argument("--max-commit-size", type=parse_size_str, default=1900 * 1024 * 1024, help="单次提交字节上限，超出自动拆分")
    p.add_argument("--no-ask", action="store_true", help="不交互，全部使用默认值")
    p.add_argument("-v", "--verbose", action="count", default=2, help="可重复：-v 警告 -vv 信息 -vvv 调试")
    p.add_argument("extra", nargs=argparse.REMAINDER, help="透传给底层命令的其余参数（如 clone 目标目录）")
    return p
def main():
    args = build_parser().parse_args(preprocess_args())
    setup_logging(args.verbose)
    socket_timeout = args.connect_timeout
    import socket; socket.setdefaulttimeout(socket_timeout)  # 用标准库超时代替 http.connectTimeout
    repo_root = Path.cwd(); extra = [a for a in args.extra if a != "--"]
    remote_url, clone_branch, clone_subdirectory = args.url, args.branch, None
    if args.mode == "clone" and remote_url:
        remote_url, url_branch, clone_subdirectory = parse_github_subdirectory_url(remote_url)  # 支持 tree/blob 子目录地址
        clone_branch = clone_branch or url_branch
    if not remote_url and args.mode not in ("clone", "init") and is_git_repository(repo_root):
        r = open_repo(repo_root); remote_url = get_branch_tracking_url(r, args.branch or get_current_branch(r)) or get_origin_url(r); r.close()  # 回退到已配置远端
    threshold_bytes = parse_size_str(args.size)
    logger.info(f"仓库路径: {repo_root.absolute()}")
    logger.info("Git 后端: dulwich（纯 Python，无需外部 git）")
    if args.mode != "init": logger.info(f"文件限制: {threshold_bytes / 1024 / 1024:.2f} MB ({threshold_bytes} 字节)")
    if remote_url: logger.info(f"远程地址: {redact_url(remote_url)}")
    logger.info(f"分支: {clone_branch if args.mode == 'clone' else (args.branch or '<current>')}")
    logger.info(f"连接超时: {args.connect_timeout}s | 低速阈值: {args.low_speed_limit}B/s | 低速超时: {args.low_speed_time}s")
    try:
        if args.mode == "config":
            logger.info("===== 根据远程 URL 配置当前仓库用户 =====")
            r = open_repo(repo_root); apply_git_user_config(r, remote_url, "AUTO", args.no_ask); r.close()
            logger.info("✅ 当前仓库用户配置完成！"); return
        if args.mode == "clone":
            git_clone(clone_branch, remote_url, extra, clone_subdirectory, args.retry, args.retry_seconds, args.depth or None)
            logger.info("✅ clone 及 LFS 大文件恢复完成！"); return
        if args.mode == "undo": logger.info("===== 撤销上一次提交 ====="); git_undo(repo_root); return
        if args.mode == "init": git_init(repo_root, remote_url); return
        if args.mode in ("list-big", "listbig"): git_list_big(repo_root, threshold_bytes); return
        if args.mode == "remove-big":
            git_remove_big(repo_root, threshold_bytes, [h for h in args.hashes.split(",") if h.strip()] or None)
            if remote_url:
                r = open_repo(repo_root); set_remote(r, remote_url); r.close(); logger.info("✅ 远程地址已重新绑定。")
            return
        large_files = scan_large_files(repo_root, threshold_bytes)  # push/pull 前统一扫描本地大文件
        logger.info(f"扫描到 {len(large_files)} 个本地大文件")
        if large_files:
            logger.info("检测到大文件，启用内置 LFS（纯 Python clean/smudge + batch API）。")
            clean_and_apply_lfs(repo_root, large_files)
        if remote_url and is_git_repository(repo_root):
            r = open_repo(repo_root); set_remote(r, remote_url); r.close()
        if args.mode == "pull":
            git_pull(args.branch, extra, remote_url, args.retry, args.retry_seconds, repo_root)
        elif args.mode == "push":
            git_push(args.branch, repo_root, extra, args.commit_msg, remote_url, args.user, args.retry, args.retry_seconds,
                     args.no_ask, threshold_bytes, args.max_commit_size, args.force)
        logger.info("✅ 操作结束！")
    except KeyboardInterrupt:
        logger.warning("\n[CANCEL] 用户手动终止。"); sys.exit(130)  # Ctrl+C 退出码与原版一致
if __name__ == "__main__": main()
