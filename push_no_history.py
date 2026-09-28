#!/usr/bin/env python3
"""
push_no_history.py
用法:
    python push_no_history.py https://eightobox:ghp_xxxxxxxx@github.com/eightobox/eightobox
    python push_no_history.py https://eightobox:ghp_xxxxxxxx@github.com/eightobox/eightobox.git
    python push_no_history.py https://token@github.com/owner/repo
    python push_no_history.py https://github.com/owner/repo --token ghp_xxxxxxxx

行为:
    1. 解析 URL，提取 username / token / owner / repo
    2. 调用 GitHub API 查询默认分支（main 或 master）
    3. 获取该分支最新 commit SHA
    4. 获取父提交的根树条目
    5. 凭空构建新提交（根目录新增 test.txt）
    6. 只发送新提交 + 新根树 + test.txt blob 到远端

依赖:
    pip install dulwich
"""

import argparse
import json
import os
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import urlparse, urlunparse, quote, parse_qs
from urllib.request import Request, urlopen

from dulwich.client import get_transport_and_path
from dulwich.objects import Blob, Commit, Tree
from dulwich.pack import pack_objects_to_data
from dulwich.repo import Repo


# ===================== URL 解析 =====================

def parse_repo_url(url: str):
    """
    解析形如 https://user:token@github.com/owner/repo[.git] 的 URL。
    返回 (clean_url, owner, repo, token, username)
    """
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ValueError(f"只支持 http/https URL，收到: {p.scheme}")

    if p.hostname not in ("github.com", "www.github.com"):
        raise ValueError(f"本脚本仅面向 github.com，收到: {p.hostname}")

    # ---- 提取路径中的 owner/repo ----
    path = p.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError(f"URL 路径必须包含 owner/repo，收到: {p.path}")
    owner, repo = parts[0], parts[1]

    # ---- 提取 token ----
    token = None
    username = None

    if p.username is not None:
        username = p.username
        if p.password is not None:
            token = p.password
        else:
            if username.startswith(("ghp_", "github_pat_", "gho_", "ghu_", "ghs_")):
                token = username
                username = None
            else:
                token = username
                username = None

    if token is None and p.query:
        qs = parse_qs(p.query)
        for key in ("token", "access_token", "gh_token"):
            if key in qs:
                token = qs[key][0]
                break

    clean_url = urlunparse((p.scheme, "github.com", f"/{owner}/{repo}.git", "", "", ""))

    return clean_url, owner, repo, token, username


# ===================== GitHub REST API =====================

def gh_api(token: str, method: str, path: str, data=None) -> dict:
    url = "https://api.github.com" + path
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "dulwich-push-demo",
    }
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"GitHub API {method} {path} -> HTTP {e.code}: {detail[:500]}")


def get_default_branch(token: str, owner: str, repo: str) -> str:
    info = gh_api(token, "GET", f"/repos/{owner}/{repo}")
    return info["default_branch"]


def get_branch_head_sha(token: str, owner: str, repo: str, branch: str) -> str:
    ref = gh_api(token, "GET", f"/repos/{owner}/{repo}/git/ref/heads/{branch}")
    return ref["object"]["sha"]


def get_commit_tree_sha(token: str, owner: str, repo: str, commit_sha: str) -> str:
    info = gh_api(token, "GET", f"/repos/{owner}/{repo}/git/commits/{commit_sha}")
    return info["tree"]["sha"]


def get_tree_entries(token: str, owner: str, repo: str, tree_sha: str) -> list:
    info = gh_api(token, "GET", f"/repos/{owner}/{repo}/git/trees/{tree_sha}")
    if info.get("truncated"):
        raise RuntimeError("根树条目过多被截断，请改用递归接口")
    return info["tree"]


# ===================== 构建新提交 =====================

def build_new_commit(
    parent_sha: str,
    tree_entries: list,
    file_name: str,
    file_content: bytes,
    author_name: str,
    author_email: str,
    message: str,
):
    """基于父提交 SHA 和根树条目，构建 (blob, tree, commit)。

    注意: dulwich 的 Tree.add() 和 Commit.parents 期望的是
    40 位十六进制字符的 bytes，而不是 20 字节的原始二进制。
    所以这里用 .encode("ascii") 而不是 bytes.fromhex()。
    """
    blob = Blob.from_string(file_content)

    tree = Tree()
    for e in tree_entries:
        if e["path"] == file_name:
            continue
        tree.add(
            e["path"].encode("utf-8"),
            int(e["mode"], 8),
            e["sha"].encode("ascii"),        # ← 修复: 40位hex字符串编码为bytes
        )
    tree.add(file_name.encode("utf-8"), 0o100644, blob.id)

    commit = Commit()
    commit.tree = tree.id
    commit.parents = [parent_sha.encode("ascii")]  # ← 修复: 40位hex字符串编码为bytes
    ident = f"{author_name} <{author_email}>".encode("utf-8")
    commit.author = commit.committer = ident
    now = int(time.time())
    commit.author_time = commit.commit_time = now
    commit.author_timezone = commit.commit_timezone = 0
    commit.encoding = b"UTF-8"
    commit.message = message.encode("utf-8")
    commit.check()

    return blob, tree, commit


# ===================== 推送 =====================

def push_commit(repo_dir: str, remote_url: str, branch_ref: bytes, blob, tree, commit):
    repo = Repo(repo_dir)
    repo.object_store.add_object(blob)
    repo.object_store.add_object(tree)
    repo.object_store.add_object(commit)

    client, path = get_transport_and_path(remote_url)

    def update_refs(refs):
        refs[branch_ref] = commit.id
        return refs

    def generate_pack_data(have, want, **kwargs):
        objs = [(blob, None), (tree, None), (commit, None)]
        return pack_objects_to_data(
            objs,
            ofs_delta=kwargs.get("ofs_delta", True),
            progress=kwargs.get("progress"),
        )

    print(f"→ 推送到 {remote_url}")
    print(f"  目标分支: {branch_ref.decode()}")
    print(f"  新提交:   {commit.id.decode()}")

    result = client.send_pack(path, update_refs, generate_pack_data, progress=None)

    if result.ref_status:
        for k, v in result.ref_status.items():
            print(f"  {k.decode()}: {v!r}")
            if v:
                raise RuntimeError(f"远端拒绝 {k.decode()}: {v}")
    print("✓ 推送成功")
    repo.close()


# ===================== 主流程 =====================

def main():
    parser = argparse.ArgumentParser(
        description="基于 GitHub URL 自动解析 token/owner/repo，凭空构建新提交并推送",
    )
    parser.add_argument("url", help="带 token 的 GitHub 仓库 URL")
    parser.add_argument("--token", help="如果 URL 中未包含 token，可在此单独提供")
    parser.add_argument("--file", default="test.txt", help="新增文件名 (默认: test.txt)")
    parser.add_argument("--content", default="Hello from dulwich (auto-built commit, no full history).\n",
                        help="新增文件内容")
    parser.add_argument("--name", default="Auto Pusher", help="作者名")
    parser.add_argument("--email", default="auto@example.com", help="作者邮箱")
    parser.add_argument("--message", default="Add test.txt via dulwich (no full history)", help="提交消息")
    args = parser.parse_args()

    # ---- 解析 URL ----
    print("→ 解析 URL ...")
    clean_url, owner, repo, token, username = parse_repo_url(args.url)
    if token is None and args.token:
        token = args.token
    if token is None:
        raise SystemExit("URL 中未找到 token，请用 --token 或把 token 嵌入 URL")
    print(f"  owner : {owner}")
    print(f"  repo  : {repo}")
    print(f"  token : {token[:12]}...{token[-4:] if len(token) > 16 else ''}")

    # ---- 查询默认分支 ----
    print("→ 查询默认分支 ...")
    branch = get_default_branch(token, owner, repo)
    print(f"  默认分支: {branch}")

    # ---- 获取分支 HEAD ----
    print("→ 获取分支 HEAD ...")
    parent_sha = get_branch_head_sha(token, owner, repo, branch)
    print(f"  父提交: {parent_sha}")

    # ---- 获取根树 ----
    print("→ 获取父提交的根树 ...")
    root_tree_sha = get_commit_tree_sha(token, owner, repo, parent_sha)
    entries = get_tree_entries(token, owner, repo, root_tree_sha)
    print(f"  根树条目数: {len(entries)}")

    # ---- 构建新提交 ----
    print("→ 构建新提交对象 ...")
    blob, tree, commit = build_new_commit(
        parent_sha=parent_sha,
        tree_entries=entries,
        file_name=args.file,
        file_content=args.content.encode("utf-8"),
        author_name=args.name,
        author_email=args.email,
        message=args.message,
    )
    print(f"  Blob:   {blob.id.decode()}")
    print(f"  Tree:   {tree.id.decode()}")
    print(f"  Commit: {commit.id.decode()}")

    # ---- 推送 ----
    with tempfile.TemporaryDirectory(prefix="dulwich-push-") as repo_dir:
        Repo.init(repo_dir).close()

        safe_user = quote(username or owner, safe="")
        safe_token = quote(token, safe="")
        remote_url = f"https://{safe_user}:{safe_token}@github.com/{owner}/{repo}.git"

        push_commit(
            repo_dir=repo_dir,
            remote_url=remote_url,
            branch_ref=f"refs/heads/{branch}".encode(),
            blob=blob, tree=tree, commit=commit,
        )

    print("\n全部完成。请到 GitHub 上确认该提交是否已出现在目标分支。")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[失败] {exc}", file=sys.stderr)
        sys.exit(1)