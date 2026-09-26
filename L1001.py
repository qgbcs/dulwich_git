r'''
qevrix-coder-2

C:\Users\Administrator\Documents\energetic>C:\QGB\anaconda3\python D:\test\github\dulwich_git\L1001.py --self-test
test_attr_parse (__main__.PushTests.test_attr_parse) ... ERROR
test_deletion (__main__.PushTests.test_deletion) ... ERROR
test_empty_push_no_changes (__main__.PushTests.test_empty_push_no_changes) ... ERROR
test_global_exclude_precedence (__main__.PushTests.test_global_exclude_precedence) ... ok
test_http_protocol_with_fake_net (__main__.PushTests.test_http_protocol_with_fake_net) ... ERROR
test_idempotent_push (__main__.PushTests.test_idempotent_push) ... ERROR
test_ignore_semantics (__main__.PushTests.test_ignore_semantics) ... ok
test_lfs_batch_upload (__main__.PushTests.test_lfs_batch_upload) ... ERROR
test_lfs_pointer_and_cache (__main__.PushTests.test_lfs_pointer_and_cache) ... ERROR
test_low_speed_watchdog (__main__.PushTests.test_low_speed_watchdog) ... [14:35:05] test 已发送 1B  速度 21.276595788106032B/s  已用 0.0s
ok
test_network_retry_http (__main__.PushTests.test_network_retry_http) ... ERROR
test_normalize (__main__.PushTests.test_normalize) ... ERROR
test_progress_output (__main__.PushTests.test_progress_output) ... ok
test_read_regular_rapid (__main__.PushTests.test_read_regular_rapid) ... ok
test_split_commits_and_local_push (__main__.PushTests.test_split_commits_and_local_push) ... ERROR
test_symlink (__main__.PushTests.test_symlink) ... ERROR
test_url_and_retry_classification (__main__.PushTests.test_url_and_retry_classification) ... ERROR
test_walk_respects_ignore (__main__.PushTests.test_walk_respects_ignore) ... ERROR

======================================================================
ERROR: test_attr_parse (__main__.PushTests.test_attr_parse)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1001.py", line 863, in test_attr_parse
    at = build_attrs(self.root)
         ^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 198, in build_attrs
    at.add_file(os.path.join(dirpath, ".gitattributes"), b"" if base == "." else base.encode() + b"/")
  File "D:\test\github\dulwich_git\L1001.py", line 156, in add_file
    for tok in toks: attrs.update(self._tok(tok))
                                  ^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 169, in _tok
    for m in self.macros[tok]: out.update(self._tok(m))
                                          ^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 169, in _tok
    for m in self.macros[tok]: out.update(self._tok(m))
                                          ^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 169, in _tok
    for m in self.macros[tok]: out.update(self._tok(m))
                                          ^^^^^^^^^^^^
  [Previous line repeated 984 more times]
  File "D:\test\github\dulwich_git\L1001.py", line 166, in _tok
    tok = parse_c_bytes(tok)
          ^^^^^^^^^^^^^^^^^^
RecursionError: maximum recursion depth exceeded

======================================================================
ERROR: test_deletion (__main__.PushTests.test_deletion)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1001.py", line 908, in test_deletion
    prepare(self.repo, self.args, self.identity, self.cache)
  File "D:\test\github\dulwich_git\L1001.py", line 338, in prepare
    changed, lfs_list = stage_all(repo, index, a, ignore, attrs, cache)
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 308, in stage_all
    if ignore.is_ignored(rel, False): continue  # 被忽略:不处理
       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 105, in is_ignored
    parts = rel.split(b"/")
            ^^^^^^^^^^^^^^^
TypeError: must be str or None, not bytes

======================================================================
ERROR: test_empty_push_no_changes (__main__.PushTests.test_empty_push_no_changes)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1001.py", line 994, in test_empty_push_no_changes
    _, empty, _ = prepare(self.repo, self.args, self.identity, self.cache)
                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 338, in prepare
    changed, lfs_list = stage_all(repo, index, a, ignore, attrs, cache)
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 328, in stage_all
    for rel in list(index.keys()):  # 工作区消失的已跟踪文件 -> 从索引删除
                    ^^^^^^^^^^
AttributeError: 'Index' object has no attribute 'keys'

======================================================================
ERROR: test_http_protocol_with_fake_net (__main__.PushTests.test_http_protocol_with_fake_net)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1001.py", line 943, in test_http_protocol_with_fake_net
    ids, _, _ = prepare(self.repo, self.args, self.identity, self.cache)
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 338, in prepare
    changed, lfs_list = stage_all(repo, index, a, ignore, attrs, cache)
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 308, in stage_all
    if ignore.is_ignored(rel, False): continue  # 被忽略:不处理
       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 105, in is_ignored
    parts = rel.split(b"/")
            ^^^^^^^^^^^^^^^
TypeError: must be str or None, not bytes

======================================================================
ERROR: test_idempotent_push (__main__.PushTests.test_idempotent_push)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1001.py", line 933, in test_idempotent_push
    ids, _, _ = prepare(self.repo, self.args, self.identity, self.cache)
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 338, in prepare
    changed, lfs_list = stage_all(repo, index, a, ignore, attrs, cache)
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 308, in stage_all
    if ignore.is_ignored(rel, False): continue  # 被忽略:不处理
       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 105, in is_ignored
    parts = rel.split(b"/")
            ^^^^^^^^^^^^^^^
TypeError: must be str or None, not bytes

======================================================================
ERROR: test_lfs_batch_upload (__main__.PushTests.test_lfs_batch_upload)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1001.py", line 971, in test_lfs_batch_upload
    _, empty, lfs = prepare(self.repo, self.args, self.identity, self.cache)
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 338, in prepare
    changed, lfs_list = stage_all(repo, index, a, ignore, attrs, cache)
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 308, in stage_all
    if ignore.is_ignored(rel, False): continue  # 被忽略:不处理
       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 105, in is_ignored
    parts = rel.split(b"/")
            ^^^^^^^^^^^^^^^
TypeError: must be str or None, not bytes

======================================================================
ERROR: test_lfs_pointer_and_cache (__main__.PushTests.test_lfs_pointer_and_cache)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1001.py", line 881, in test_lfs_pointer_and_cache
    _, empty, lfs = prepare(self.repo, self.args, self.identity, self.cache)
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 338, in prepare
    changed, lfs_list = stage_all(repo, index, a, ignore, attrs, cache)
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 308, in stage_all
    if ignore.is_ignored(rel, False): continue  # 被忽略:不处理
       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 105, in is_ignored
    parts = rel.split(b"/")
            ^^^^^^^^^^^^^^^
TypeError: must be str or None, not bytes

======================================================================
ERROR: test_network_retry_http (__main__.PushTests.test_network_retry_http)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1001.py", line 953, in test_network_retry_http
    prepare(self.repo, self.args, self.identity, self.cache)
  File "D:\test\github\dulwich_git\L1001.py", line 338, in prepare
    changed, lfs_list = stage_all(repo, index, a, ignore, attrs, cache)
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 308, in stage_all
    if ignore.is_ignored(rel, False): continue  # 被忽略:不处理
       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 105, in is_ignored
    parts = rel.split(b"/")
            ^^^^^^^^^^^^^^^
TypeError: must be str or None, not bytes

======================================================================
ERROR: test_normalize (__main__.PushTests.test_normalize)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1001.py", line 871, in test_normalize
    _, empty, _ = prepare(self.repo, make_args(renormalize=True), self.identity, self.cache)
                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 334, in prepare
    ignore = build_ignore_from_repo(repo); attrs = build_attrs_from_repo(repo)
                                                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 254, in build_attrs_from_repo
    def build_attrs_from_repo(repo): return build_attrs(os.fsdecode(repo.path))
                                            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 198, in build_attrs
    at.add_file(os.path.join(dirpath, ".gitattributes"), b"" if base == "." else base.encode() + b"/")
  File "D:\test\github\dulwich_git\L1001.py", line 156, in add_file
    for tok in toks: attrs.update(self._tok(tok))
                                  ^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 169, in _tok
    for m in self.macros[tok]: out.update(self._tok(m))
                                          ^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 169, in _tok
    for m in self.macros[tok]: out.update(self._tok(m))
                                          ^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 169, in _tok
    for m in self.macros[tok]: out.update(self._tok(m))
                                          ^^^^^^^^^^^^
  [Previous line repeated 982 more times]
  File "D:\test\github\dulwich_git\L1001.py", line 166, in _tok
    tok = parse_c_bytes(tok)
          ^^^^^^^^^^^^^^^^^^
RecursionError: maximum recursion depth exceeded

======================================================================
ERROR: test_split_commits_and_local_push (__main__.PushTests.test_split_commits_and_local_push)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1001.py", line 916, in test_split_commits_and_local_push
    ids, empty, _ = prepare(self.repo, self.args, self.identity, self.cache)
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 338, in prepare
    changed, lfs_list = stage_all(repo, index, a, ignore, attrs, cache)
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 308, in stage_all
    if ignore.is_ignored(rel, False): continue  # 被忽略:不处理
       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 105, in is_ignored
    parts = rel.split(b"/")
            ^^^^^^^^^^^^^^^
TypeError: must be str or None, not bytes

======================================================================
ERROR: test_symlink (__main__.PushTests.test_symlink)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1001.py", line 897, in test_symlink
    _, empty, _ = prepare(self.repo, self.args, self.identity, self.cache)
                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 338, in prepare
    changed, lfs_list = stage_all(repo, index, a, ignore, attrs, cache)
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 308, in stage_all
    if ignore.is_ignored(rel, False): continue  # 被忽略:不处理
       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 105, in is_ignored
    parts = rel.split(b"/")
            ^^^^^^^^^^^^^^^
TypeError: must be str or None, not bytes

======================================================================
ERROR: test_url_and_retry_classification (__main__.PushTests.test_url_and_retry_classification)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1001.py", line 980, in test_url_and_retry_classification
    self.assertEqual(redact_url("https://u:tok@github.com/a/b.git"), "https://u:***@github.com/a/b.git")
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 34, in redact_url
    return urlunparse(p._replace(netloc=netloc))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\QGB\anaconda3\Lib\urllib\parse.py", line 514, in urlunparse
    scheme, netloc, url, params, query, fragment, _coerce_result = (
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
ValueError: not enough values to unpack (expected 7, got 6)

======================================================================
ERROR: test_walk_respects_ignore (__main__.PushTests.test_walk_respects_ignore)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "D:\test\github\dulwich_git\L1001.py", line 854, in test_walk_respects_ignore
    _, empty, _ = prepare(self.repo, self.args, self.identity, self.cache)
                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 338, in prepare
    changed, lfs_list = stage_all(repo, index, a, ignore, attrs, cache)
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 308, in stage_all
    if ignore.is_ignored(rel, False): continue  # 被忽略:不处理
       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\test\github\dulwich_git\L1001.py", line 105, in is_ignored
    parts = rel.split(b"/")
            ^^^^^^^^^^^^^^^
TypeError: must be str or None, not bytes

----------------------------------------------------------------------
Ran 18 tests in 16.816s

FAILED (errors=13)

'''

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# dulwich_git_push.py — 纯 dulwich+标准库实现的 git push：gitignore/gitattributes(LFS/text/crlf)/拆分提交/重试/低速看门狗/实时连接详情与速度
# 运行: python dulwich_git_push.py [-v N] [-u] https://[token@]host/owner/repo.git [refspec...]   推送
#       python dulwich_git_push.py --self-test                                                  自检(Windows 临时目录安全)
import argparse, base64, collections, hashlib, http.client, io, json, os, re, shutil, socket, ssl, stat, sys, tempfile, threading, time, unittest
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunparse, unquote
from dulwich.index import Index, IndexEntry
from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import Repo
from dulwich.object_store import DiskObjectStore, iter_tree_contents
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
Z40 = b"0" * 40
EMPTY_TREE = b"4b825dc642cb6eb9a060e54bf8d69288fbee4904"
def log(msg): print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)
def fmt_size(n):  # 字节数转人类可读
    for u in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or u == "GiB": return f"{n}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024
def fmt_speed(n): return fmt_size(n) + "/s"
def parse_size_str(val):  # "100MB"/"1g"/"1024" -> 字节
    if not val: return 0
    s = str(val).strip().lower(); m = 1
    for suf, mul in (("gb", 1024**3), ("g", 1024**3), ("mb", 1024**2), ("m", 1024**2), ("kb", 1024), ("k", 1024), ("b", 1)):
        if s.endswith(suf): m = mul; s = s[:-len(suf)]; break
    try: return int(float(s) * m)
    except ValueError: return 0
def redact_url(url):  # 隐藏 URL 中的密码
    p = urlsplit(url)
    if p.username:
        host = p.hostname or ""; netloc = f"{p.username}:***@{host}"
        if p.port: netloc += f":{p.port}"
        return urlunparse(p._replace(netloc=netloc))
    return url
# ---------- 错误类型 ----------
class StopPush(Exception): pass  # 读取文件前后不一致(防 TOCTOU)
class PushError(Exception): pass  # 致命错误(不重试)
class NetError(Exception): pass  # 网络/传输错误(可重试)
class HTTPFailure(NetError):  # HTTP 失败响应
    def __init__(self, status, url, body=b"", retry_after=None):
        self.status = status; self.url = url; self.body = body
        self.delay = float(retry_after) if (retry_after and str(retry_after).isdigit()) else 0.0
        super().__init__(f"HTTP {status} {redact_url(url)}: {bytes(body)[:200]!r}")
# ---------- pkt-line / 文件读取(Windows 安全) ----------
def pkt_line(data): return ("%04x" % (len(data) + 4)).encode() + data
def read_pkt_lines(body):  # 解析 pkt-line 序列,遇 flush 停止
    lines = []; i = 0
    while i + 4 <= len(body):
        ln = int(body[i:i+4], 16); i += 4
        if ln == 0: break
        lines.append(body[i:i + ln - 4]); i += ln - 4
    return lines
def file_signature(st): return (st.st_size, st.st_mtime_ns // 1000000)  # 毫秒级:规避 Windows/AV 抖动导致的 stat-vs-fstat 误判
def read_regular(path, retries=2):  # 同一 fd 前后对比+毫秒取整+重试:根治"读取前文件已经变化"
    for attempt in range(retries + 1):
        with open(path, "rb") as f:
            before = file_signature(os.fstat(f.fileno()))
            data = f.read()
            after = file_signature(os.fstat(f.fileno()))
        if before == after: return data
    raise StopPush(f"读取前文件已经变化: {path}")
# ---------- gitignore 引擎(含父目录排除不可再包含语义) ----------
def compile_glob(pat):  # gitignore 风格 glob -> 正则核心(无锚)
    out = bytearray(); i = 0; n = len(pat)
    while i < n:
        if pat[i:i + 2] == b"**":
            if (i == 0 or pat[i - 1:i] == b"/") and pat[i + 2:i + 3] == b"/": out += b"(?:.*/)?"; i += 3
            else: out += b".*"; i += 2
        elif pat[i:i + 1] == b"*": out += b"[^/]*"; i += 1
        elif pat[i:i + 1] == b"?": out += b"[^/]"; i += 1
        elif pat[i:i + 1] == b"[":
            j = i + 1
            if j < n and pat[j:j + 1] in (b"^", b"!"): j += 1
            if j < n and pat[j:j + 1] == b"]": j += 1
            while j < n and pat[j:j + 1] != b"]": j += 1
            if j >= n: out += re.escape(b"["); i += 1
            else:
                cls = pat[i + 1:j]
                if cls.startswith(b"!"): cls = b"^" + cls[1:]
                out += b"[" + cls + b"]"; i = j + 1
        else: out += re.escape(pat[i:i + 1]); i += 1
    return bytes(out)
class Ignore:
    def __init__(self): self.rules = []  # (base前缀, 正则, 仅目录, 取反)
    def add_file(self, path, base):  # base: 该 .gitignore 所在目录相对根的前缀(b"" 或 b"docs/")
        try: raw = open(path, "rb").read()
        except OSError: return
        for line in raw.split(b"\n"): self.add_line(line.rstrip(b"\r"), base)
    def add_line(self, line, base):
        if not line or line.startswith(b"#"): return
        neg = line.startswith(b"!")
        if neg: line = line[1:]
        dir_only = line.endswith(b"/")
        if dir_only: line = line[:-1]
        while line.endswith(b" ") and not line.endswith(b"\\ "): line = line[:-1]  # 去尾随空格(反斜杠转义除外)
        line = line.replace(b"\\#", b"#").replace(b"\\!", b"!").replace(b"\\ ", b" ")
        if not line: return
        anchored = line.startswith(b"/") or (b"/" in line)  # 开头或中间有分隔符 -> 相对该 .gitignore 目录
        if line.startswith(b"/"): line = line[1:]
        core = compile_glob(line)
        rx = (b"^" + core + b"$") if anchored else (b"(?:^|/)" + core + b"$")  # 非锚定:任意层级 basename 匹配
        self.rules.append((base, re.compile(rx), dir_only, neg))
    def is_ignored(self, rel, is_dir):
        parts = rel.split(b"/")
        for k in range(1, len(parts)):  # 任一祖先目录被排除 -> 整体排除(不可再包含)
            if self._excluded(b"/".join(parts[:k]), True): return True
        return self._excluded(rel, is_dir)
    def _excluded(self, rel, is_dir):
        result = False
        for base, rx, dir_only, neg in self.rules:
            if base and not rel.startswith(base): continue
            sub = rel[len(base):]
            if dir_only and not is_dir: continue
            if rx.match(sub): result = not neg  # 后匹配优先(文件内后行 > 深层文件)
        return result
def build_ignore(root, global_excludes=None):  # 优先级: 全局 < info/exclude < .gitignore(浅 < 深)
    ig = Ignore()
    if global_excludes:
        p = os.fsdecode(global_excludes)
        if os.path.exists(p): ig.add_file(p, b"")
    info = os.path.join(root, ".git", "info", "exclude")
    if os.path.exists(info): ig.add_file(info, b"")
    for dirpath, dirnames, filenames in os.walk(root):
        if ".git" in dirnames: dirnames.remove(".git")
        if ".gitignore" in filenames:
            base = os.path.relpath(dirpath, root).replace(os.sep, "/")
            ig.add_file(os.path.join(dirpath, ".gitignore"), b"" if base == "." else base.encode() + b"/")
    return ig
# ---------- gitattributes 引擎(C 引号/宏/text/binary/filter/crlf) ----------
def parse_c_bytes(tok):  # 解析 C 风格引号字符串
    if len(tok) >= 2 and tok.startswith(b'"') and tok.endswith(b'"'):
        s = tok[1:-1]; out = bytearray(); i = 0
        esc = {b"n": b"\n", b"t": b"\t", b"r": b"\r", b"a": b"\a", b"b": b"\b", b"f": b"\f", b"v": b"\v"}
        while i < len(s):
            c = s[i:i + 1]
            if c == b"\\" and i + 1 < len(s): out += esc.get(s[i + 1:i + 2], s[i + 1:i + 2]); i += 2
            else: out += c; i += 1
        return bytes(out)
    return tok
class Attrs:
    BUILTIN = {b"binary": {b"diff": False, b"merge": False, b"text": False}, b"text": {b"text": True}, b"diff": {b"diff": True}, b"merge": {b"merge": True}}  # git 内置宏
    def __init__(self): self.rules = []; self.macros = dict(self.BUILTIN)
    def add_file(self, path, base):
        try: raw = open(path, "rb").read()
        except OSError: return
        for line in raw.split(b"\n"):
            line = line.rstrip(b"\r")
            if not line or line.startswith(b"#"): continue
            pat, toks = self._split_line(line)  # 引号感知的 pattern 切分
            if not pat: continue
            if pat == b"[attr]":  # 宏定义 [attr] name attr...
                if len(toks) > 1: self.macros[toks[0]] = toks[1:]
                continue
            pat = parse_c_bytes(pat); attrs = {}
            for tok in toks: attrs.update(self._tok(tok))
            dir_only = pat.endswith(b"/")
            p = pat[:-1] if dir_only else pat
            anchored = p.startswith(b"/") or (b"/" in p)
            if p.startswith(b"/"): p = p[1:]
            core = compile_glob(p)
            if dir_only: rx = re.compile(b"^" + core + b"(/.*)?$")  # dir/ 匹配目录及其下所有内容
            else: rx = re.compile((b"^" + core + b"$") if anchored else (b"(?:^|/)" + core + b"$"))
            self.rules.append((base, rx, attrs))
    def _tok(self, tok):
        tok = parse_c_bytes(tok)
        if tok in self.macros:
            out = {}
            for m in self.macros[tok]: out.update(self._tok(m))
            return out
        if tok.startswith(b"-"): return {tok[1:]: False}
        if tok.startswith(b"+"): return {tok[1:]: True}
        if b"=" in tok: k, v = tok.split(b"=", 1); return {k: v}
        return {tok: True}
    def for_path(self, rel):  # 所有匹配规则合并(深层覆盖浅层)
        result = {}
        for base, rx, attrs in self.rules:
            if base and not rel.startswith(base): continue
            if rx.match(rel[len(base):]): result.update(attrs)
        return result
    def _split_line(self, line):  # pattern 可能带引号("path with space"),按引号切分第一个 token
        if line.startswith(b'"'):
            i = 1; out = bytearray(b'"')
            while i < len(line):
                c = line[i:i + 1]
                if c == b"\\" and i + 1 < len(line): out += line[i:i + 2]; i += 2; continue
                out += c; i += 1
                if c == b'"': break
            return bytes(out), line[i:].split()
        parts = line.split(None, 1)
        return (parts[0], parts[1].split()) if parts else (b"", [])
def build_attrs(root):
    at = Attrs()
    for dirpath, dirnames, filenames in os.walk(root):
        if ".git" in dirnames: dirnames.remove(".git")
        if ".gitattributes" in filenames:
            base = os.path.relpath(dirpath, root).replace(os.sep, "/")
            at.add_file(os.path.join(dirpath, ".gitattributes"), b"" if base == "." else base.encode() + b"/")
    return at
def looks_textual(data): return b"\0" not in data[:8000]  # 无 NUL 视为文本(git text=auto 规则)
def normalize_blob(data, attrs, renormalize):  # text/crlf/eol -> 仓库内存 LF
    if attrs.get(b"binary") is False or attrs.get(b"-text") is False: return data
    text = attrs.get(b"text")
    if text is True: do = True
    elif text is False: do = False
    else: do = renormalize and looks_textual(data)  # 无属性:仅 --renormalize 且看起来是文本
    if attrs.get(b"crlf") is not False or attrs.get(b"eol") in (b"crlf", b"lf"): do = True
    if not do: return data
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
# ---------- LFS ----------
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1024 * 1024), b""): h.update(c)
    return h.hexdigest()
def lfs_pointer(oid, size): return b"version https://git-lfs.github.com/spec/v1\noid sha256:" + oid.encode() + b"\nsize " + str(size).encode() + b"\n"
def stage_lfs_file(path, cache):  # 大文件存入 LFS 缓存(oid 分片),返回 (指针内容, oid, size)
    oid = sha256_file(path); size = os.path.getsize(path)
    dest = os.path.join(cache, oid[:2], oid[2:4], oid)
    if not os.path.exists(dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".tmp"
        with open(path, "rb") as fi, open(tmp, "wb") as fo: shutil.copyfileobj(fi, fo)
        os.replace(tmp, dest)
    return lfs_pointer(oid, size), oid, size
def upload_lfs(net, base_url, objs, cache, ref_name, done):  # LFS batch API: 查询+上传(实时速度)
    if not objs: return
    url = base_url.rstrip("/") + "/info/lfs/objects/batch"
    payload = json.dumps({"operation": "upload", "transfers": ["basic"], "objects": [{"oid": o, "size": s} for o, s in objs], "ref": {"name": ref_name}}).encode()
    status, _, reader = net.request("POST", url, {"Content-Type": "application/vnd.git-lfs+json", "Accept": "application/vnd.git-lfs+json"}, payload, label="LFS batch")
    resp = json.loads(reader.readall() or b"{}")
    for item in resp.get("objects", []):
        oid = item.get("oid"); size = item.get("size")
        up = (item.get("actions") or {}).get("upload")
        if not up: done.add((oid, size)); continue  # 服务端已有
        path = os.path.join(cache, oid[:2], oid[2:4], oid)
        ahdrs = dict(up.get("header") or {})
        st, _, r2 = net.request("PUT", up["href"], ahdrs, open(path, "rb"), encode_chunked=True, label=f"LFS 上传 {oid[:12]}")
        r2.close()
        if st not in (200, 201): raise NetError(f"LFS 上传失败 HTTP {st}")
        done.add((oid, size))
# ---------- 索引/树/提交 ----------
def get_index(repo):  # 安全取得(可能为空)的索引,绑定到 .git/index
    try:
        idx = repo.open_index()
        if getattr(idx, "_filename", None): return idx
    except Exception: pass
    return Index(os.path.join(os.fsdecode(repo.path), ".git", "index"))
def rel_bytes(full, root): return os.path.relpath(full, root).replace(os.sep, "/").encode()
def build_ignore_from_repo(repo):  # 从仓库配置读取全局排除
    try: excl = repo.get_config().get((b"core",), b"excludesfile", default=None)
    except Exception: excl = None
    return build_ignore(os.fsdecode(repo.path), excl)
def build_attrs_from_repo(repo): return build_attrs(os.fsdecode(repo.path))
def tree_entries(store, tree_sha):  # 递归展开树为 {path: (mode, sha)}
    result = {}; stack = [(b"", tree_sha)]
    while stack:
        prefix, sha = stack.pop()
        for name, mode, s in store[sha].items():
            if stat.S_ISDIR(mode): stack.append((prefix + name + b"/", s))
            else: result[prefix + name] = (mode, s)
    return result
def build_tree(store, entries):  # 由 {path:(mode,sha)} 构建树(目录按 name+"/" 排序,符合 git 规则)
    def helper(prefix):
        dirs = {}; leaves = []
        for path, (mode, sha) in entries.items():
            if not path.startswith(prefix): continue
            rest = path[len(prefix):]
            if b"/" in rest:
                name, _, sub = rest.partition(b"/")
                dirs.setdefault(name, {})[sub] = (mode, sha)
            else: leaves.append((path, mode, sha))
        items = [(n, m, s, False) for n, m, s in leaves]
        for name, sub in dirs.items(): items.append((name, 0o040000, helper(prefix + name + b"/"), True))
        items.sort(key=lambda t: t[0] + (b"/" if t[3] else b""))  # git 树排序:目录视作 name+"/"
        tree = Tree()
        for n, m, s, _ in items: tree.add(n, m, s)
        store.add_object(tree)
        return tree.id
    return helper(b"")
def local_tz():  # 本地时区 +/-HHMM
    off = -time.timezone if (time.localtime().tm_isdst == 0 or not time.daylight) else -time.altzone
    sign = b"+" if off >= 0 else b"-"; off = abs(off)
    return sign + ("%02d%02d" % (off // 3600, (off % 3600) // 60)).encode()
def make_commit(store, tree, parents, author, committer, message):  # 直接构造提交对象
    c = Commit()
    c.tree = tree; c.parents = parents; c.author = author; c.committer = committer
    t = int(time.time())
    c.author_time = c.commit_time = t; c.author_timezone = c.commit_timezone = local_tz()
    c.message = message if isinstance(message, bytes) else message.encode(); c.encoding = b"UTF-8"
    store.add_object(c)
    return c.id
# ---------- 暂存(扫描/忽略/属性/规范化/LFS) ----------
def stage_all(repo, index, a, ignore, attrs, cache):
    store = repo.object_store; root = os.fsdecode(repo.path)
    changed = set(); lfs_list = []; seen = set(); link_dirs = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        keep = []
        for d in dirnames:
            full = os.path.join(dirpath, d)
            if os.path.islink(full): link_dirs.append((rel_bytes(full, root), full))  # 符号链接目录当文件处理
            elif ignore.is_ignored(rel_bytes(full, root), True): pass  # 整目录被忽略:不下降
            else: keep.append(d)
        dirnames[:] = keep
        entries = [(fn, os.path.join(dirpath, fn)) for fn in filenames] + link_dirs; link_dirs = []
        for rel, full in entries:
            if ignore.is_ignored(rel, False): continue  # 被忽略:不处理
            seen.add(rel)
            try:
                if os.path.islink(full):
                    data = os.readlink(full).encode(); mode = 0o120000; at = {}  # 符号链接:存目标路径,绝不跟随
                else:
                    at = attrs.for_path(rel)
                    if at.get(b"filter") == b"lfs":
                        data, oid, size = stage_lfs_file(full, cache); mode = 0o100644; lfs_list.append((oid, size))
                    else:
                        data = normalize_blob(read_regular(full), at, a.renormalize)
                        mode = 0o100755 if (os.name != "nt" and os.access(full, os.X_OK)) else 0o100644  # Windows 无执行位语义
                    if len(data) > a.max_blob: raise PushError(f"文件过大 ({len(data)}B > {a.max_blob}B)，请配置 .gitattributes filter=lfs: {rel.decode()}")
            except OSError: continue
            blob = Blob(); blob.data = data; store.add_object(blob)
            old = index[rel].sha if rel in index else None
            if old != blob.id:
                st = os.lstat(full)
                index[rel] = IndexEntry(ctime=st.st_ctime_ns, mtime=st.st_mtime_ns, dev=st.st_dev, ino=st.st_ino, mode=mode, uid=st.st_uid, gid=st.st_gid, size=len(data), sha=blob.id)
                changed.add(rel)
    for rel in list(index.keys()):  # 工作区消失的已跟踪文件 -> 从索引删除
        if rel not in seen:
            del index[rel]; changed.add(rel)
    return changed, lfs_list
def prepare(repo, a, identity, cache):  # 暂存 + 写索引 + 拆分提交;返回 (提交id列表, 是否空, LFS对象列表)
    config = repo.get_config()
    ignore = build_ignore_from_repo(repo); attrs = build_attrs_from_repo(repo)
    try: expected = repo.refs.follow(b"HEAD")  # 未出生的 HEAD 会抛 KeyError
    except KeyError: expected = None
    index = get_index(repo)
    changed, lfs_list = stage_all(repo, index, a, ignore, attrs, cache)
    index.write()
    if not changed: return [], True, lfs_list
    store = repo.object_store; entries = dict(index.items())
    base = tree_entries(store, repo[expected].tree) if expected else {}
    groups = {}  # 按顶层目录拆分提交
    for rel in changed: groups.setdefault(rel.split(b"/", 1)[0], []).append(rel)
    current = dict(base); ids = []; prev = expected
    for top in sorted(groups):
        for rel in groups[top]:
            if rel in entries: current[rel] = (entries[rel].mode, entries[rel].sha)
            else: current.pop(rel, None)
        cid = make_commit(store, build_tree(store, current), [prev] if prev else [], identity, identity, a.message or b"auto push")
        prev = cid; ids.append(cid)
    if ids: repo.refs[b"refs/heads/" + current_branch(repo).encode()] = ids[-1]  # 提交后更新当前分支引用
    return ids, False, lfs_list
# ---------- 网络层(实时连接详情 + 实时速度 + 重试 + 低速看门狗) ----------
class Progress:  # 实时速度显示(每 0.5s 一行)
    def __init__(self, label, total=None, interval=0.5):
        self.label = label; self.total = total; self.interval = interval
        self.sent = 0; self.start = time.monotonic(); self.last = 0.0
    def update(self, n):
        self.sent += n; now = time.monotonic()
        if now - self.last >= self.interval: self.last = now; self._line(now)
    def _line(self, now):
        el = now - self.start; speed = self.sent / el if el > 0 else 0
        s = f"[{time.strftime('%H:%M:%S')}] {self.label} 已发送 {fmt_size(self.sent)}"
        if self.total: s += f" / {fmt_size(self.total)} ({self.sent * 100 // self.total}%)"
        s += f"  速度 {fmt_speed(speed)}  已用 {el:.1f}s"
        print(s, flush=True)
    def finish(self): self._line(time.monotonic())
class HTTPReader:  # 响应体读取(支持分块)
    def __init__(self, resp): self.resp = resp
    def read(self, n=-1): return self.resp.read(n)
    def readall(self): return self.read()
    def close(self): self.resp.close()
class Net:
    def __init__(self, timeout=45, low_speed=10, low_speed_time=60):
        self.timeout = timeout; self.low_speed = low_speed; self.low_speed_time = low_speed_time
        self._win = []; self._t0 = 0.0
    def request(self, method, url, headers=None, body=None, *, encode_chunked=False, label=""):
        p = urlsplit(url)
        if p.scheme not in ("http", "https"): raise NetError(f"不支持的协议 {p.scheme}，本工具走 HTTP(S)")
        host = p.hostname; port = p.port or (443 if p.scheme == "https" else 80)
        path = p.path or "/"
        if p.query: path += "?" + p.query
        hdrs = dict(headers or {}); token = None
        if p.username:  # URL 内嵌 token -> Basic 认证 + 日志脱敏
            token = unquote(p.username)
            if "Authorization" not in hdrs:
                hdrs["Authorization"] = "Basic " + base64.b64encode((token + ":" + unquote(p.password or "")).encode()).decode()
        t0 = time.monotonic()
        conn = (http.client.HTTPSConnection(host, port, timeout=self.timeout, context=ssl.create_default_context()) if p.scheme == "https" else http.client.HTTPConnection(host, port, timeout=self.timeout))
        conn.connect()
        s = f"[{time.strftime('%H:%M:%S')}] → 已连接 {host}:{port} ({(time.monotonic() - t0) * 1000:.0f}ms)"
        try:
            peer = conn.sock.getpeername(); s += f" 对端 {peer[0]}:{peer[1]}"
        except Exception: pass
        if p.scheme == "https":
            try: s += f" TLS {conn.sock.version()} {conn.sock.cipher()[0]}"
            except Exception: pass
        print(s, flush=True)
        prog = Progress(label or f"{method} {path}")
        try:
            conn.request(method, path, body=self._wrap(body, prog), headers=hdrs, encode_chunked=encode_chunked)
        except Exception:
            conn.close(); raise
        resp = conn.getresponse(); dt = (time.monotonic() - t0) * 1000
        keep = {k: v for k, v in resp.getheaders() if k.lower() in ("content-type", "content-length", "retry-after", "x-github-request-id", "x-ratelimit-remaining")}
        print(f"[{time.strftime('%H:%M:%S')}] ← {resp.status} {resp.reason}  耗时 {dt:.0f}ms  {redact_url(url)}", flush=True)
        if keep: print("  响应头: " + ", ".join(f"{k}: {v[:90]}" for k, v in keep.items()), flush=True)
        if resp.status >= 400:
            preview = resp.read(600); resp.close(); conn.close()
            raise HTTPFailure(resp.status, url, preview, retry_after=resp.getheader("Retry-After"))
        return resp.status, dict(resp.getheaders()), HTTPReader(resp)
    def _wrap(self, body, prog):  # 包装上传体:实时进度 + 低速看门狗
        if body is None: return None
        if isinstance(body, (bytes, bytearray)): prog.update(len(body)); return bytes(body)
        self._win = []; self._t0 = time.monotonic()
        def gen():
            if hasattr(body, "read"):
                while True:
                    c = body.read(262144)
                    if not c: break
                    yield from self._emit(c, prog)
            else:
                for c in body: yield from self._emit(c, prog)
        return gen()
    def _emit(self, chunk, prog):
        prog.update(len(chunk)); self._lowspeed_check(len(chunk)); yield chunk
    def _lowspeed_check(self, nbytes):  # 低速看门狗:low_speed_time 秒内字节数低于阈值 -> 中断
        now = time.monotonic(); self._win.append((now, nbytes))
        while self._win and now - self._win[0][0] > self.low_speed_time: self._win.pop(0)
        total = sum(n for _, n in self._win)
        if now - self._t0 >= self.low_speed_time and total < self.low_speed:
            raise NetError(f"低速传输:{self.low_speed_time}s 内仅 {total}B (< {self.low_speed}B/s)")
def is_retryable(exc):  # 错误分类:5xx/429/网络错误可重试;401/403 等立即失败
    if isinstance(exc, HTTPFailure): return exc.status >= 500 or exc.status == 429
    return isinstance(exc, (NetError, socket.timeout, OSError, http.client.HTTPException))
def with_retry(op, fn, *, retries=5, base_delay=1.0):  # 指数退避重试
    last = None
    for attempt in range(1, retries + 1):
        try: return fn(attempt)
        except HTTPFailure as e:
            if e.status in (401, 403): raise
            if e.status >= 500 or e.status == 429 or e.delay > 0:
                last = e; wait = e.delay or base_delay * attempt
                print(f"[{time.strftime('%H:%M:%S')}] ⚠ {op} HTTP {e.status}，{wait:.1f}s 后重试 ({attempt}/{retries})", flush=True)
                time.sleep(min(wait, 30)); continue
            raise
        except (NetError, socket.timeout, OSError, http.client.HTTPException) as e:
            last = e; wait = base_delay * attempt
            print(f"[{time.strftime('%H:%M:%S')}] ⚠ {op} 网络错误 {e!r}，{wait:.1f}s 后重试 ({attempt}/{retries})", flush=True)
            time.sleep(min(wait, 30)); continue
    raise last
# ---------- git-receive-pack 协议(手写,完全掌控实时进度) ----------
def parse_advertisement(body):  # 解析引用列表(含能力)
    refs = {}; caps = set(); i = 0
    while i + 4 <= len(body):
        ln = int(body[i:i + 4], 16); i += 4
        if ln == 0: break
        line = body[i:i + ln - 4]; i += ln - 4
        if b"^{}" in line: continue
        if b"\0" in line:
            refpart, capstr = line.split(b"\0", 1); caps.update(capstr.split()); line = refpart
        parts = line.split(b" ", 1)
        if len(parts) == 2: refs[parts[0]] = parts[1]
    return refs, caps
def parse_refspec(spec):
    if ":" in spec:
        src, dst = spec.split(":", 1)
        if not dst: raise ValueError(f"非法 refspec: {spec}")
        if not src: return None, expand_ref(dst)
        return expand_ref(src), expand_ref(dst)
    return expand_ref(spec), expand_ref(spec)
def expand_ref(ref):
    ref = ref.encode() if isinstance(ref, str) else ref
    return ref if ref.startswith(b"refs/") else b"refs/heads/" + ref
def head_sha(repo, ref):
    try: return repo.refs[ref]
    except KeyError: return None
def collect_objects(store, heads, exclude):  # 从 heads 收集可达对象(排除已有)
    seen = set(); stack = list(heads)
    while stack:
        sha = stack.pop()
        if sha in seen or sha in exclude or sha == EMPTY_TREE or sha not in store: continue
        seen.add(sha)
        obj = store[sha]
        if isinstance(obj, Commit): stack.extend(obj.parents); stack.append(obj.tree)
        elif isinstance(obj, Tree): stack.extend(s for _, _, s in obj.items())
    return seen
def empty_pack_bytes(): return b"PACK\x00\x00\x00\x02\x00\x00\x00\x00" + hashlib.sha1(b"PACK\x00\x00\x00\x02\x00\x00\x00\x00").digest()
def build_pack_file(store, objects):  # 用临时 DiskObjectStore 生成 pack 文件(版本无关,返回路径与临时目录)
    if not objects: return None, None
    tmpdir = tempfile.mkdtemp(prefix="dulwich_push_pack_")
    s2 = DiskObjectStore.init(tmpdir)
    try:
        s2.add_objects([(o, None) for o in objects])
        try: s2.pack_loose_objects()
        except Exception: pass
    finally: s2.close()
    packs = glob.glob(os.path.join(tmpdir, "*.pack"))
    return (packs[0] if packs else None), tmpdir
def do_receive(net, base, cmds, opts, pack_path, token, caps=b"report-status"):  # 发送 push 请求(分块上传,实时速度)
    url = base + "/git-receive-pack"
    lines = []
    for i, (o, n, r) in enumerate(cmds):
        line = o.decode() + " " + n.decode() + " " + r.decode()
        if i == 0 and caps: line += "\0" + caps.decode()  # 首行命令附带能力列表
        lines.append(pkt_line(line))
    prefix = b"".join(lines) + b"0000"
    if opts: prefix += b"".join(pkt_line(o) for o in opts) + b"0000"  # push-options 段
    total = len(prefix) + (os.path.getsize(pack_path) if pack_path else 0)
    def body():
        yield prefix
        if pack_path:
            with open(pack_path, "rb") as f:
                while True:
                    c = f.read(1024 * 1024)
                    if not c: break
                    yield c
    hdrs = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/x-receive-pack-result", "User-Agent": "dulwich-git-push/1.0"}
    if token: hdrs["Authorization"] = "Basic " + base64.b64encode((token + ":").encode()).decode()
    status, _, reader = net.request("POST", url, hdrs, body(), encode_chunked=True, label="POST git-receive-pack")
    return status, reader.readall()
def parse_report(body):  # 解析 report-status
    unpack = None; results = {}
    for line in read_pkt_lines(body):
        if line.startswith(b"unpack "): unpack = line[7:]
        elif line.startswith(b"ok "): results[line[3:].split(b" ", 1)[0]] = b"ok"
        elif line.startswith(b"ng "):
            parts = line[3:].split(b" ", 1); results[parts[0]] = b"ng " + (parts[1] if len(parts) > 1 else b"")
    return unpack, results
def push_to_remote(app, remote, refspecs):
    repo = app.repo; net = app.net; base = remote.rstrip("/")
    def adv_op(attempt):
        status, hdrs, reader = net.request("GET", base + "/git-receive-pack", {"Accept": "application/x-git-receive-pack-advertisement", "User-Agent": "dulwich-git-push/1.0"}, label="GET 引用列表")
        return reader.readall()
    adv_body = with_retry("获取远程引用", adv_op, retries=app.args.retry)
    refs, caps = parse_advertisement(adv_body)
    print(f"[{time.strftime('%H:%M:%S')}] 远程引用: " + (", ".join(f"{r.decode()}={v.decode()[:12]}" for r, v in sorted(refs.items())) or "(空仓库)"), flush=True)
    cmds = []
    for spec in refspecs:
        src, dst = parse_refspec(spec)
        if src is None:
            new = Z40; old = refs.get(dst)
        else:
            new = head_sha(repo, src)
            if new is None: raise PushError(f"本地分支不存在: {src.decode()}")
            old = refs.get(dst)
        if new == old: continue  # 幂等:已是最新则跳过
        cmds.append((old or Z40, new, dst))
    if not cmds:
        print(f"[{time.strftime('%H:%M:%S')}] 所有分支已是最新，无需推送", flush=True); return
    opts = []
    if app.args.push_option:
        if b"push-options" in caps: opts = [o.encode() for o in app.args.push_option]
        else: print(f"[{time.strftime('%H:%M:%S')}] ⚠ 远程不支持 push-options，已忽略", flush=True)
    req_caps = b"report-status"  # 始终请求 report-status
    if opts: req_caps += b" push-options"
    if app.args.atomic: req_caps += b" atomic"
    store = repo.object_store
    remote_closure = collect_objects(store, list(refs.values()), set())  # 远程已有对象闭包
    objs = collect_objects(store, [c[1] for c in cmds if c[1] != Z40], remote_closure)
    pack_path, tmpdir = build_pack_file(store, objs)
    if app.args.dry_run:
        print(f"[DRY-RUN] 将推送 {len(cmds)} 个引用、{len(objs)} 个对象、pack {fmt_size(os.path.getsize(pack_path) if pack_path else 0)}", flush=True)
        if tmpdir: shutil.rmtree(tmpdir, ignore_errors=True)
        return
    def push_op(attempt): return do_receive(net, base, cmds, opts, pack_path, app.token, req_caps)
    try:
        status, report = with_retry("推送", push_op, retries=app.args.retry)
        unpack, results = parse_report(report)
        if unpack != b"ok": raise PushError(f"服务端 unpack 失败: {unpack!r}")
        ok = True
        for old, new, ref in cmds:
            st = results.get(ref)
            if st == b"ok": print(f"[{time.strftime('%H:%M:%S')}] ✓ {ref.decode()} -> {new.decode()[:12]}", flush=True)
            else: ok = False; print(f"[{time.strftime('%H:%M:%S')}] ✗ {ref.decode()} 失败: {st!r}", flush=True)
        if not ok: raise PushError("推送被服务端拒绝")
        print(f"[{time.strftime('%H:%M:%S')}] ✅ 推送成功({len(cmds)} 个引用, {len(objs)} 个对象)", flush=True)
    finally:
        if tmpdir: shutil.rmtree(tmpdir, ignore_errors=True)
# ---------- 应用/身份 ----------
class App:
    def __init__(self, repo, args, remote=None, net=None):
        self.repo = repo; self.args = args
        self.net = net if net is not None else Net(timeout=getattr(args, "timeout", 45), low_speed=getattr(args, "low_speed", 10), low_speed_time=getattr(args, "low_speed_time", 60))
        self.token = extract_token(remote or getattr(args, "remote", None))
def extract_token(url):
    if url:
        p = urlsplit(url)
        if p.username: return unquote(p.username)
    return None
def owner_from_url(url):
    p = urlsplit(url)
    if p.hostname and p.hostname.lower() in ("github.com", "www.github.com"):
        parts = [x for x in p.path.strip("/").split("/") if x]
        if parts: return parts[0]
    return None
def identity_from_config(repo, remote):  # 提交身份:仓库配置 -> URL owner -> 默认
    try:
        cfg = repo.get_config()
        name = cfg.get((b"user",), b"name", default=None); email = cfg.get((b"user",), b"email", default=None)
        if name and email: return name + b" <" + email + b">"
    except Exception: pass
    owner = owner_from_url(remote)
    if owner: return owner.encode() + b" <" + owner.encode() + b"@users.noreply.github.com>"
    return b"Push <push@localhost>"
def current_branch(repo):
    try:
        sym = repo.refs.get_symrefs().get(b"HEAD")
        if sym and sym.startswith(b"refs/heads/"): return sym[len(b"refs/heads/"):].decode()
    except Exception: pass
    return "master"
# ---------- CLI ----------
def make_args(**kw):  # 测试/默认参数
    d = dict(renormalize=False, max_blob=100 * 1024 * 1024, message=None, atomic=False, push_option=[], identity=None, retry=3, dry_run=False, timeout=10, low_speed=1, low_speed_time=60, update=False)
    d.update(kw); return SimpleNamespace(**d)
def main(argv=None):
    p = argparse.ArgumentParser(prog="dulwich_git_push", description="纯 Python(dulwich+标准库) git push:gitignore/gitattributes/LFS/拆分提交/重试/实时速度")
    p.add_argument("-v", "--verbose", nargs="?", type=int, const=1, default=0, help="详细级别(兼容 -v 3)")
    p.add_argument("-u", "--update", action="store_true", help="允许非快进更新(强制推送)")
    p.add_argument("--atomic", action="store_true")
    p.add_argument("--push-option", action="append", default=[], metavar="OPT")
    p.add_argument("--renormalize", action="store_true")
    p.add_argument("--lfs-threshold", type=parse_size_str, default=100 * 1024 * 1024)
    p.add_argument("--max-blob", type=parse_size_str, default=100 * 1024 * 1024)
    p.add_argument("--lfs-cache", default=None)
    p.add_argument("--identity", default=None)
    p.add_argument("-m", "--message", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--retry", type=int, default=5)
    p.add_argument("--timeout", type=float, default=45)
    p.add_argument("--low-speed", type=int, default=10)
    p.add_argument("--low-speed-time", type=int, default=60)
    p.add_argument("--repo", default=".")
    p.add_argument("--self-test", action="store_true")
    p.add_argument("remote", nargs="?")
    p.add_argument("refspec", nargs="*")
    args = p.parse_args(argv)
    if args.self_test: return run_self_test()
    if args.remote == "push":  # 兼容 "push <url>" 子命令写法
        args.remote = args.refspec[0] if args.refspec else None
        args.refspec = args.refspec[1:]
    if not args.remote: p.error("缺少远程地址")
    if "://" not in args.remote: p.error("远程必须是 http(s):// 地址")
    if args.remote.startswith("git@"): p.error("本工具走 HTTP(S)，请使用 https:// 地址")
    repo = Repo(args.repo)
    identity = args.identity.encode() if args.identity else identity_from_config(repo, args.remote)
    cache = args.lfs_cache or os.path.join(os.fsdecode(repo.path), ".git", "lfs")
    os.makedirs(cache, exist_ok=True)
    app = App(repo, args, remote=args.remote)
    ids, empty, lfs_list = prepare(repo, args, identity, cache)
    if empty: print("无更改，跳过提交"); return 0
    print(f"提交 {len(ids)} 个: " + ", ".join(i.decode()[:12] for i in ids))
    if lfs_list:
        print(f"上传 LFS 对象 {len(lfs_list)} 个")
        upload_lfs(app, args.remote, dict(lfs_list), cache, (parse_refspec(args.refspec[0])[1] if args.refspec else b"refs/heads/" + current_branch(repo).encode()).decode(), app.net)
    refspecs = args.refspec or [f"{current_branch(repo)}:{current_branch(repo)}"]
    push_to_remote(app, args.remote, refspecs)
    return 0
# ================= 自检(Windows 临时目录安全;修复 L988 全部问题) =================
class BytesReader:  # 内存响应体
    def __init__(self, data): self.data = data; self.pos = 0
    def read(self, n=-1):
        if n is None or n < 0: r = self.data[self.pos:]; self.pos = len(self.data); return r
        r = self.data[self.pos:self.pos + n]; self.pos += len(r); return r
    def readall(self): return self.read()
    def close(self): pass
def dechunk(rfile):  # 解析 chunked 传输
    out = bytearray()
    while True:
        line = rfile.readline().strip()
        if not line: break
        size = int(line.split(b";")[0], 16)
        if size == 0: break
        out += rfile.read(size); rfile.read(2)
    return bytes(out)
def read_http_body(handler):  # 读取请求体(自动解 chunked)
    if handler.headers.get("Transfer-Encoding", "").lower() == "chunked": return dechunk(handler.rfile)
    n = int(handler.headers.get("Content-Length", "0") or "0")
    return handler.rfile.read(n) if n else b""
def split_commands(body):  # 拆分 pkt-line 命令段与其后内容
    lines = []; i = 0
    while True:
        if body[i:i + 4] == b"0000": i += 4; break
        ln = int(body[i:i + 4], 16); i += 4
        lines.append(body[i:i + ln - 4]); i += ln - 4
    return lines, body[i:]
class TestReceiveServer:  # 本地真实 socket 的 git-receive-pack 测试服务端(disk store,避开 MemoryObjectStore.add_thin_pack bug)
    def __init__(self, bare): self.bare = bare; self.httpd = None; self.thread = None
    def start(self):
        outer = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *a): pass
            def do_GET(self):
                refs = {}
                try:
                    for r in outer.bare.refs.keys(): refs[r] = outer.bare.refs[r]
                except Exception: pass
                caps = b"report-status status delete-refs ofs-delta agent=dulwich-test"
                out = b""; first = True
                for r in sorted(refs):
                    line = refs[r] + b" " + r
                    if first: line += b"\0" + caps; first = False
                    out += pkt_line(line)
                out += b"0000"
                self.send_response(200); self.send_header("Content-Type", "application/x-git-receive-pack-advertisement"); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
            def do_POST(self):
                body = read_http_body(self)
                lines, rest = split_commands(body)
                if rest.startswith(b"PACK"): opts = b""; pack = rest  # 无 push-options
                else:
                    i = 0; opts = []
                    while True:
                        if rest[i:i + 4] == b"0000": i += 4; break
                        ln = int(rest[i:i + 4], 16); i += 4
                        opts.append(rest[i:i + ln - 4]); i += ln - 4
                    pack = rest[i:]
                with outer.bare.lock if hasattr(outer.bare, "lock") else _dummy():
                    buf = io.BytesIO(pack)
                    outer.bare.object_store.add_thin_pack(buf.read, buf.read)  # 位置参数,不传 max_input_size
                    refs_ok = []
                    for line in lines:
                        if b"\0" in line: line = line.split(b"\0", 1)[0]  # 去掉能力列表
                        parts = line.split(b" ")
                        if len(parts) != 3: continue
                        old, new, ref = parts
                        if new != Z40: outer.bare.refs[ref] = new
                        elif old != Z40:
                            try: del outer.bare.refs[ref]
                            except KeyError: pass
                        refs_ok.append(ref)
                out = pkt_line(b"unpack ok") + b"".join(pkt_line(b"ok " + r) for r in refs_ok) + b"0000"
                self.send_response(200); self.send_header("Content-Type", "application/x-x-receive-pack-result"); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True); self.thread.start()
        return self.port
    def stop(self):
        try: self.httpd.shutdown()
        except Exception: pass
        try: self.httpd.server_close()
        except Exception: pass
class _dummy:
    def __enter__(self): return self
    def __exit__(self, *a): return False
class FakeNet(Net):  # 协议级假网络(记录请求/失败注入)
    def __init__(self, adv=None, fail_times=0, **kw):
        super().__init__(**kw)
        self.adv = adv or {}; self.fail_times = fail_times; self.fail_count = 0
        self.requests = []; self.last_body = b""; self.post_count = 0; self.cmds = []
    def request(self, method, url, headers=None, body=None, *, encode_chunked=False, label=""):
        self.requests.append((method, url))
        data = b""
        if body is not None:
            if isinstance(body, (bytes, bytearray)): data = bytes(body)
            elif hasattr(body, "read"):
                while True:
                    c = body.read(65536)
                    if not c: break
                    data += c
            else:
                for c in body: data += c
        if method == "GET":
            out = b""; first = True
            for r in sorted(self.adv):
                line = self.adv[r] + b" " + r
                if first: line += b"\0report-status status delete-refs push-options atomic"; first = False
                out += pkt_line(line)
            out += b"0000"
            return 200, {}, BytesReader(out)
        self.post_count += 1
        if self.fail_count < self.fail_times:
            self.fail_count += 1
            raise HTTPFailure(503, url, b"unavailable")
        self.last_body = data
        lines, rest = split_commands(data)
        self.cmds = [(l.split(b"\0", 1)[0]).split(b" ") for l in lines]  # 去掉能力列表
        report = pkt_line(b"unpack ok") + b"".join(pkt_line(b"ok " + c[2]) for c in self.cmds) + b"0000"
        return 200, {}, BytesReader(report)
class FakeLFSServer:  # 假 LFS 服务端
    def __init__(self): self.uploaded = {}; self.batches = []
    def start(self):
        outer = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *a): pass
            def _send(self, code, body, ctype="application/vnd.git-lfs+json"):
                self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            def do_POST(self):
                n = int(self.headers.get("Content-Length", "0") or "0")
                req = json.loads(self.rfile.read(n) or b"{}")
                if self.path.endswith("/objects/batch"):
                    outer.batches.append(req)
                    objs = []
                    for o in req.get("objects", []):
                        objs.append({"oid": o["oid"], "size": o["size"], "actions": {"upload": {"href": f"http://127.0.0.1:{outer.port}/upload?oid={o['oid']}", "header": {}}}})
                    self._send(200, json.dumps({"transfer": "basic", "objects": objs}).encode())
                else:
                    oid = self.path.split("oid=")[-1]
                    data = read_http_body(self)  # 支持 chunked 上传
                    outer.uploaded[oid] = data
                    self._send(200, b"")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True); self.thread.start()
        return self.port
    def stop(self):
        try: self.httpd.shutdown()
        except Exception: pass
        try: self.httpd.server_close()
        except Exception: pass
class PushTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="dulwich_push_test_")  # 用 mkdtemp 而非 NamedTemporaryFile:修复 Windows 仓库初始化错误
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.repo = Repo.init(self.root)  # repo_init.py 正确写法:对已存在目录 Repo.init
        self.addCleanup(self.repo.close)
        self.identity = b"Test <test@example.com>"
        self.cache = os.path.join(self.root, ".git", "lfs")
        self.args = make_args()
    def write(self, rel, data):
        path = os.path.join(self.root, rel.replace("/", os.sep))
        d = os.path.dirname(path)
        if d: os.makedirs(d, exist_ok=True)
        with open(path, "wb") as f: f.write(data)
        return path
    # ---- gitignore ----
    def test_ignore_semantics(self):
        self.write(".gitignore", b"*.tmp\n!keep.tmp\nblocked/\n!blocked/no.txt\nselect/*\n!select/keep.txt\n**/logs\n/root.txt\ndoc/*.log\n")
        ig = build_ignore(self.root, None)
        self.assertFalse(ig.is_ignored(b"keep.tmp", False))
        self.assertTrue(ig.is_ignored(b"drop.tmp", False))
        self.assertTrue(ig.is_ignored(b"blocked/no.txt", False))  # 父目录被排除:无法再包含
        self.assertTrue(ig.is_ignored(b"blocked/keep.txt", False))
        self.assertTrue(ig.is_ignored(b"blocked", True))  # blocked/ 目录本身被排除
        self.assertFalse(ig.is_ignored(b"select/keep.txt", False))
        self.assertTrue(ig.is_ignored(b"select/no.txt", False))
        self.assertTrue(ig.is_ignored(b"a/logs/x", False))
        self.assertTrue(ig.is_ignored(b"root.txt", False))
        self.assertFalse(ig.is_ignored(b"sub/root.txt", False))
        self.assertTrue(ig.is_ignored(b"doc/a.log", False))
        self.assertFalse(ig.is_ignored(b"doc/sub/a.log", False))
    def test_global_exclude_precedence(self):
        gf = os.path.join(self.root, "global.ignore")
        with open(gf, "wb") as f: f.write(b"*.tmp\n")
        self.write(".gitignore", b"!keep.tmp\n")
        ig = build_ignore(self.root, gf.encode())  # 全局 < .gitignore
        self.assertFalse(ig.is_ignored(b"keep.tmp", False))
        self.assertTrue(ig.is_ignored(b"other.tmp", False))
    def test_walk_respects_ignore(self):
        self.write(".gitignore", b"*.log\n")
        self.write("a.log", b"x"); self.write("b.txt", b"y"); self.write("sub/c.log", b"x")
        _, empty, _ = prepare(self.repo, self.args, self.identity, self.cache)
        self.assertFalse(empty)
        index = get_index(self.repo)
        self.assertIn(b"b.txt", index)
        self.assertNotIn(b"a.log", index)
        self.assertNotIn(b"sub/c.log", index)
    # ---- gitattributes / 规范化 ----
    def test_attr_parse(self):
        self.write(".gitattributes", b'*.lfs filter=lfs diff=lfs merge=lfs -text\n[attr]macro text\n*.txt macro\n"path with space" binary\ncrlf.txt text crlf\n')
        at = build_attrs(self.root)
        self.assertEqual(at.for_path(b"a.lfs"), {b"filter": b"lfs", b"diff": b"lfs", b"merge": b"lfs", b"text": False})
        self.assertEqual(at.for_path(b"a.txt"), {b"text": True})  # 宏展开
        self.assertEqual(at.for_path(b"path with space"), {b"diff": False, b"merge": False, b"text": False})  # binary 内置宏
        self.assertEqual(at.for_path(b"crlf.txt"), {b"text": True, b"crlf": True})
    def test_normalize(self):
        self.write(".gitattributes", b"*.txt text\n*.bin -text\n")
        self.write("a.txt", b"line1\r\nline2\r\n"); self.write("b.bin", b"x\r\ny\r\n")
        _, empty, _ = prepare(self.repo, make_args(renormalize=True), self.identity, self.cache)
        self.assertFalse(empty)
        index = get_index(self.repo)
        self.assertEqual(self.repo.object_store[index[b"a.txt"].sha].data, b"line1\nline2\n")  # text -> LF
        self.assertEqual(self.repo.object_store[index[b"b.bin"].sha].data, b"x\r\ny\r\n")  # -text -> 原样
    # ---- LFS ----
    def test_lfs_pointer_and_cache(self):
        self.write(".gitattributes", b"*.bin filter=lfs diff=lfs merge=lfs -text\n")
        payload = b"q" * 600
        self.write("big.bin", payload)
        _, empty, lfs = prepare(self.repo, self.args, self.identity, self.cache)
        self.assertEqual(len(lfs), 1)
        oid, size = lfs[0]
        self.assertEqual(size, 600)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), oid)
        index = get_index(self.repo)
        self.assertEqual(self.repo.object_store[index[b"big.bin"].sha].data, lfs_pointer(oid, 600))
        cached = os.path.join(self.cache, oid[:2], oid[2:4], oid)
        self.assertTrue(os.path.exists(cached))
        with open(cached, "rb") as f: self.assertEqual(f.read(), payload)
    # ---- 符号链接 ----
    def test_symlink(self):
        if not hasattr(os, "symlink"): self.skipTest("平台无 symlink")
        try: os.symlink("target.txt", os.path.join(self.root, "link.txt"))
        except (OSError, NotImplementedError): self.skipTest("无法创建 symlink")
        self.write("target.txt", b"t")
        _, empty, _ = prepare(self.repo, self.args, self.identity, self.cache)
        self.assertFalse(empty)
        index = get_index(self.repo)
        self.assertEqual(index[b"link.txt"].mode, 0o120000)
        self.assertEqual(self.repo.object_store[index[b"link.txt"].sha].data, b"target.txt")
    # ---- 读取健壮性(L988 的 StopPush 误报) ----
    def test_read_regular_rapid(self):
        p = self.write("f.txt", b"data")
        for _ in range(10): self.assertEqual(read_regular(p), b"data")  # 快速连续读取不应误报
    def test_deletion(self):
        self.write("f.txt", b"x")
        prepare(self.repo, self.args, self.identity, self.cache)
        os.remove(os.path.join(self.root, "f.txt"))
        ids, empty, _ = prepare(self.repo, self.args, self.identity, self.cache)
        self.assertFalse(empty)
        self.assertNotIn(b"f.txt", get_index(self.repo))
    # ---- 拆分提交 + 本地真实推送(修复 MemoryObjectStore.add_thin_pack bug:用 disk store) ----
    def test_split_commits_and_local_push(self):
        self.write("dirA/f1", b"a"); self.write("dirB/f2", b"b"); self.write("dirC/f3", b"c")
        ids, empty, _ = prepare(self.repo, self.args, self.identity, self.cache)
        self.assertFalse(empty)
        self.assertEqual(len(ids), 3)  # 3 个顶层目录 -> 3 个提交
        bare_dir = os.path.join(self.root, "bare.git"); os.makedirs(bare_dir, exist_ok=True)
        bare = Repo.init_bare(bare_dir); self.addCleanup(bare.close)
        server = TestReceiveServer(bare)
        port = server.start(); self.addCleanup(server.stop)
        url = f"http://127.0.0.1:{port}/test.git"
        app = App(self.repo, self.args, remote=url, net=Net(timeout=10, low_speed=1, low_speed_time=60))
        push_to_remote(app, url, ["master:refs/heads/main"])
        self.assertEqual(bare.refs[b"refs/heads/main"], ids[-1])
        remote_commit = bare[bare.refs[b"refs/heads/main"]]  # refs -> sha -> 提交对象
        self.assertEqual(len(remote_commit.parents), 2)  # 链式 3 提交: 最后提交有 2 个父
        paths = {path for path, mode, sha in iter_tree_contents(bare.object_store, remote_commit.tree)}
        self.assertEqual(paths, {b"dirA/f1", b"dirB/f2", b"dirC/f3"})  # 远程树含全部文件
    def test_idempotent_push(self):
        self.write("f.txt", b"x")
        ids, _, _ = prepare(self.repo, self.args, self.identity, self.cache)
        net = FakeNet(adv={b"refs/heads/main": ids[-1]})  # 远程已是最新
        app = App(self.repo, self.args, remote="http://x/test.git", net=net)
        push_to_remote(app, "http://x/test.git", ["master:refs/heads/main"])
        self.assertEqual(net.post_count, 0)  # 幂等:不发请求
    # ---- HTTP 协议(push-options/atomic/重试) ----
    def test_http_protocol_with_fake_net(self):
        adv = {b"refs/heads/main": b"1" * 40}
        net = FakeNet(adv=adv)
        self.write("f.txt", b"hello")
        ids, _, _ = prepare(self.repo, self.args, self.identity, self.cache)
        app = App(self.repo, make_args(atomic=True, push_option=["ci skip"]), remote="http://example.com/test.git", net=net)
        push_to_remote(app, "http://example.com/test.git", ["master:refs/heads/main"])
        self.assertEqual(net.post_count, 1)
        self.assertIn(b"ci skip", net.last_body)  # push-options 已发送
        self.assertIn(b"atomic", net.last_body)  # atomic 能力已协商
        self.assertTrue(any(c[2] == b"refs/heads/main" for c in net.cmds))
    def test_network_retry_http(self):
        net = FakeNet(adv={b"refs/heads/main": b"1" * 40}, fail_times=2)
        self.write("f.txt", b"hello")
        prepare(self.repo, self.args, self.identity, self.cache)
        app = App(self.repo, self.args, remote="http://example.com/test.git", net=net)
        push_to_remote(app, "http://example.com/test.git", ["master:refs/heads/main"])
        self.assertEqual(net.fail_count, 2)  # 失败两次后重试成功
        self.assertEqual(net.post_count, 1)
    def test_low_speed_watchdog(self):
        net = Net(low_speed_time=0.2, low_speed=10)
        def slow_body():
            for _ in range(10):
                time.sleep(0.05); yield b"x"
        prog = Progress("test")
        with self.assertRaises(NetError):
            for _ in net._wrap(slow_body(), prog): pass  # 低速看门狗应中断
    # ---- LFS 批量上传 ----
    def test_lfs_batch_upload(self):
        srv = FakeLFSServer(); port = srv.start(); self.addCleanup(srv.stop)
        self.write(".gitattributes", b"*.bin filter=lfs diff=lfs merge=lfs -text\n")
        self.write("big.bin", b"z" * 600)
        _, empty, lfs = prepare(self.repo, self.args, self.identity, self.cache)
        self.assertEqual(len(lfs), 1)
        oid, size = lfs[0]
        done = set()
        upload_lfs(Net(timeout=10), f"http://127.0.0.1:{port}/repo", {oid: size}, self.cache, b"refs/heads/main", done)
        self.assertIn((oid, size), done)
        self.assertEqual(srv.uploaded[oid], b"z" * 600)
    # ---- 辅助函数 ----
    def test_url_and_retry_classification(self):
        self.assertEqual(redact_url("https://u:tok@github.com/a/b.git"), "https://u:***@github.com/a/b.git")
        self.assertEqual(parse_size_str("100MB"), 100 * 1024 * 1024)
        self.assertEqual(parse_size_str("1g"), 1024 ** 3)
        self.assertTrue(is_retryable(HTTPFailure(503, "u", b"")))
        self.assertTrue(is_retryable(HTTPFailure(429, "u", b"")))
        self.assertFalse(is_retryable(HTTPFailure(401, "u", b"")))
    def test_progress_output(self):
        import io, contextlib
        prog = Progress("下载", total=100)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            prog.update(50); prog.update(50)
        self.assertIn("速度", buf.getvalue())
    def test_empty_push_no_changes(self):
        _, empty, _ = prepare(self.repo, self.args, self.identity, self.cache)
        self.assertTrue(empty)  # 空仓库无文件:不提交
def run_self_test():
    suite = unittest.TestLoader().loadTestsFromTestCase(PushTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1
if __name__ == "__main__":
    sys.exit(main())
