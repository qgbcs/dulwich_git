'''

test_repo_head_is_symbolic_ref (__main__.TestRepoInit.test_repo_head_is_symbolic_ref)
验证新仓库的 HEAD 是指向 refs/heads/master 的符号引用。 ... ok
test_repo_initialized (__main__.TestRepoInit.test_repo_initialized)
验证仓库初始化成功，且 .git 目录存在。 ... ok
test_stage_and_commit (__main__.TestRepoInit.test_stage_and_commit)
验证基本的暂存与提交功能在初始化的仓库中可用。 ... ok

----------------------------------------------------------------------
Ran 3 tests in 0.123s

OK
An exception has occurred, use %tb to see the full traceback.

SystemExit: 0

'''
import os
import shutil
import tempfile
import unittest

from dulwich.repo import Repo


class TestRepoInit(unittest.TestCase):
    """针对 dulwich 1.2.15 的 Repo.init 自测用例。"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="dulwich_test_")
        self.addCleanup(shutil.rmtree, self.temp_dir, ignore_errors=True)
        self.repo = Repo.init(self.temp_dir)

    def test_repo_initialized(self):
        """验证仓库初始化成功，且 .git 目录存在。"""
        self.assertTrue(os.path.isdir(self.temp_dir))
        git_dir = os.path.join(self.temp_dir, ".git")
        self.assertTrue(os.path.isdir(git_dir), f".git 目录不存在: {git_dir}")

    def test_repo_head_is_symbolic_ref(self):
        """验证新仓库的 HEAD 是指向 refs/heads/master 的符号引用。

        新仓库处于 'unborn branch' 状态，不能通过 refs[b'HEAD'] 获取值，
        而应使用 read_ref() 或 get_symrefs() 来检查 HEAD 的原始内容。
        """
        # 方式一：使用 read_ref 读取 HEAD 的原始内容
        # read_ref 不会解析符号引用，直接返回文件内容
        head_raw = self.repo.refs.read_ref(b"HEAD")
        self.assertIsNotNone(head_raw)
        self.assertIn(b"ref: refs/heads/", head_raw,
                      f"HEAD 应为符号引用，实际为: {head_raw!r}")

        # 方式二：使用 get_symrefs() 获取所有符号引用
        symrefs = self.repo.refs.get_symrefs()
        self.assertIn(b"HEAD", symrefs)
        self.assertEqual(symrefs[b"HEAD"], b"refs/heads/master")

        # 方式三：验证 HEAD 指向的分支确实不存在（unborn 状态）
        try:
            self.repo.refs[b"refs/heads/master"]
            self.fail("refs/heads/master 不应存在")
        except KeyError:
            pass  # 预期抛出 KeyError

    def test_stage_and_commit(self):
        """验证基本的暂存与提交功能在初始化的仓库中可用。"""
        test_file = os.path.join(self.temp_dir, "hello.txt")
        with open(test_file, "wb") as f:
            f.write(b"Hello, Dulwich!")

        self.repo.get_worktree().stage([b"hello.txt"])
        commit_id = self.repo.get_worktree().commit(
            b"Test commit",
            committer=b"Tester <tester@example.com>",
            author=b"Tester <tester@example.com>",
        )
        self.assertIsNotNone(commit_id)
        # 提交后 HEAD 才真正指向有效的 commit
        self.assertEqual(self.repo.head(), commit_id)

    def tearDown(self):
        self.repo.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)