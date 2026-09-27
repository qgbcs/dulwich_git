#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scan_lfs_cache.py —— 扫描指定仓库的大文件,生成可写入 .git/config 的 LFS 哈希缓存注释行。
用法:
    python scan_lfs_cache.py <repo-root> [--write] [--min-mb 100] [--no-reuse]
默认只打印注释行;加 --write 才真正写回 .git/config(只动同前缀注释行,真实配置一字不改)。
"""
import argparse
import hashlib
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

CACHE_PREFIX = "#lfs-cache\t"
# CACHE_PREFIX = "# purepush-lfs-cache\t"  # 模块级常量,与 pure_push.py 保持一致
CHUNK = 1024 * 1024
HEX64 = re.compile(r"[0-9a-f]{64}")


def find_git_dir(root):
    """从 root 向上找 .git;支持 .git 是目录(普通仓库)或文件(worktree/submodule)。找不到返回 None。"""
    cur = Path(root).resolve()
    for candidate_root in [cur, *cur.parents]:
        cand = candidate_root / ".git"
        if cand.is_dir():
            return cand
        if cand.is_file():
            try:
                line = cand.read_text(encoding="utf-8", errors="surrogateescape").strip()
                if line.startswith("gitdir:"):
                    target = line.split(":", 1)[1].strip()
                    return Path(target).expanduser().resolve()
            except OSError:
                pass
    return None


def load_old_cache(cfg_path):
    """读取 .git/config 里已有的缓存注释,返回 {relpath: (sha256, size, mtime_ns)}。"""
    old = {}
    try:
        data = cfg_path.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError:
        return old
    for line in data.splitlines():
        if not line.startswith(CACHE_PREFIX):
            continue
        parts = line[len(CACHE_PREFIX):].split("\t", 3)
        if len(parts) != 4 or not HEX64.fullmatch(parts[0]):
            continue
        try:
            size = int(parts[1])
            mtime_ns = int(parts[2])
        except ValueError:
            continue
        old[parts[3]] = (parts[0], size, mtime_ns)
    return old


def atomic_write(path, data):
    """同目录临时文件原子替换;失败不留半写文件,不覆盖符号链接。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError(f"拒绝覆盖符号链接: {path}")
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(prefix=".scan-lfs-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, str(path))
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def scan_large_files(root, min_size, reuse_cache=True, emit=None):
    """扫描 root 下所有子目录,列出 >= min_size 的普通文件,生成可贴进 .git/config 的注释行。
    reuse_cache=True 时,若 .git/config 里已有同路径、同 size、同 mtime_ns 的记录,直接复用其 sha256,不重复读盘。
    返回 (lines, stats);lines 是注释行列表,stats 是统计信息字典。"""
    if emit is None:
        emit = lambda msg: print(msg, file=sys.stderr)

    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"仓库路径不存在或不是目录: {root}")
    git_dir = find_git_dir(root)
    if git_dir is None:
        raise SystemExit(f"在 {root} 及上级目录找不到 .git;请确认这是仓库根或子目录")
    cfg_path = git_dir / "config"

    old = load_old_cache(cfg_path) if reuse_cache else {}
    emit(f"# 仓库根: {root}")
    emit(f"# .git 目录: {git_dir}")
    emit(f"# 已有缓存条目: {len(old)}")
    emit(f"# 阈值: {min_size} bytes ({min_size / 1024 / 1024:.2f} MiB)")

    lines = []
    stats = {"hit": 0, "miss": 0, "total_bytes": 0, "count": 0}

    for base, dirs, names in os.walk(root, followlinks=False):
        # 任何层级的 .git 都不扫;.git 可能是目录也可能是文件(worktree)
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in names:
            p = Path(base) / name
            try:
                st = p.lstat()
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):  # 只处理普通文件,跳过符号链接/目录/socket/fifo/设备
                continue
            if st.st_size < min_size:
                continue
            try:
                rel = p.relative_to(root).as_posix()
            except ValueError:
                continue  # 理论上不会发生,防御性保留

            prev = old.get(rel)
            if reuse_cache and prev is not None and prev[1] == st.st_size and prev[2] == st.st_mtime_ns:
                sha256 = prev[0]
                stats["hit"] += 1
                emit(f"# 缓存命中,跳过磁盘读取: {rel} ({st.st_size} bytes)")
            else:
                stats["miss"] += 1
                emit(f"# 计算 SHA256: {rel} ({st.st_size} bytes) ...")
                h = hashlib.sha256()
                total = 0
                with open(p, "rb") as f:
                    for block in iter(lambda: f.read(CHUNK), b""):
                        h.update(block)
                        total += len(block)
                if total != st.st_size:
                    emit(f"# 警告: {rel} 读取期间大小变化({total} != {st.st_size}),已跳过")
                    continue
                sha256 = h.hexdigest()

            stats["count"] += 1
            stats["total_bytes"] += st.st_size
            lines.append(f"{CACHE_PREFIX}{sha256}\t{st.st_size}\t{st.st_mtime_ns}\t{rel}")

    emit(f"# 完成: 命中 {stats['hit']} | 重算 {stats['miss']} | 合计 {stats['count']} 个 | {stats['total_bytes']} bytes")
    return lines, stats, git_dir


def write_cache_to_config(git_dir, lines):
    """把缓存行写回 .git/config:先删掉所有同前缀旧行,再把新行追加到末尾。
    只动注释行,绝不动任何真实配置;用 atomic_write 保证不写半截。"""
    cfg_path = Path(git_dir) / "config"
    if not cfg_path.exists():
        raise SystemExit(f".git/config 不存在: {cfg_path}")
    try:
        data = cfg_path.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError as exc:
        raise SystemExit(f"读取 {cfg_path} 失败: {exc}")
    kept = [ln for ln in data.splitlines() if not ln.startswith(CACHE_PREFIX)]
    while kept and not kept[-1].strip():  # 去掉尾部空行堆积
        kept.pop()
    out = "\n".join(kept + list(lines)) + "\n"
    atomic_write(cfg_path, out.encode("utf-8", "surrogateescape"))
    return cfg_path


def main(argv=None):
    ap = argparse.ArgumentParser(prog="scan_lfs_cache.py", description="扫描指定仓库的大文件并生成 .git/config 缓存注释")
    ap.add_argument("repo", help="仓库根路径(例如 C:\\Users\\Administrator\\Documents\\energetic)")
    ap.add_argument("--min-mb", type=float, default=100.0, help="最小文件大小(MiB),默认 100")
    ap.add_argument("--write", action="store_true", help="把生成的行写回 .git/config(默认只打印)")
    ap.add_argument("--no-reuse", action="store_true", help="忽略已有缓存,强制重算所有 sha256")
    ap.add_argument("--quiet", action="store_true", help="只输出注释行,不输出进度信息到 stderr")
    a = ap.parse_args(argv)

    min_size = int(a.min_mb * 1024 * 1024)
    if min_size <= 0:
        raise SystemExit("--min-mb 必须为正数")
    emit = (lambda msg: None) if a.quiet else (lambda msg: print(msg, file=sys.stderr))

    lines, stats, git_dir = scan_large_files(a.repo, min_size, reuse_cache=not a.no_reuse, emit=emit)

    if a.write:
        cfg = write_cache_to_config(git_dir, lines)
        print(f"已写入 {len(lines)} 条缓存到 {cfg}", file=sys.stderr)
    else:
        # 纯打印模式:stdout 只输出注释行,方便重定向
        for ln in lines:
            print(ln)
        print(f"# 提示: 加 --write 可写回 {Path(git_dir) / 'config'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)