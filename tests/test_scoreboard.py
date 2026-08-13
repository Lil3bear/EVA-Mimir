"""Scoreboard 单元测试"""
import os
import tempfile
import unittest

from solver.ctfplatform.scoreboard import Scoreboard


class ScoreboardTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="test-scoreboard-")
        self.board = Scoreboard(self._tmpdir, total_score=1000)
        self._md_path = os.path.join(self._tmpdir, "scoreboard.md")

    def test_register_creates_file(self):
        """注册题目后生成 scoreboard.md。"""
        self.board.register("web-01", "easy", 100, 1)
        self.assertTrue(os.path.exists(self._md_path))
        content = open(self._md_path, encoding="utf-8").read()
        self.assertIn("web-01", content)
        self.assertIn("easy", content)
        self.assertIn("⏳ 排队", content)

    def test_mark_running(self):
        """标记为进行中。"""
        self.board.register("web-01", "easy", 100, 1)
        self.board.mark_running("web-01")
        content = open(self._md_path, encoding="utf-8").read()
        self.assertIn("🔄 进行", content)
        self.assertIn("进行中: 1", content)

    def test_mark_done_success(self):
        """解出题目。"""
        self.board.register("web-01", "easy", 100, 1)
        self.board.mark_running("web-01")
        self.board.mark_done("web-01", success=True, correct_flags=1,
                             total_flags=1, rounds=5)
        content = open(self._md_path, encoding="utf-8").read()
        self.assertIn("✅ 解出", content)
        self.assertIn("已解: 1/1", content)

    def test_mark_done_failure_with_note(self):
        """失败题目带备注。"""
        self.board.register("web-02", "hard", 500, 1)
        self.board.mark_running("web-02")
        self.board.mark_done("web-02", success=False, correct_flags=0,
                             total_flags=1, rounds=30, note="WAF拦截绕不过")
        content = open(self._md_path, encoding="utf-8").read()
        self.assertIn("❌ 失败", content)
        self.assertIn("WAF拦截绕不过", content)

    def test_mark_done_partial(self):
        """部分完成（多 flag 题只解出一部分）。"""
        self.board.register("b-01", "medium", 1200, 4)
        self.board.mark_running("b-01")
        self.board.mark_done("b-01", success=False, correct_flags=2,
                             total_flags=4, rounds=20)
        content = open(self._md_path, encoding="utf-8").read()
        self.assertIn("◐ 部分(2/4)", content)
        self.assertIn("部分: 1", content)

    def test_mark_skipped(self):
        """跳过题目。"""
        self.board.register("web-03", "hard", 500, 1)
        self.board.mark_skipped("web-03", "resource_unavailable")
        content = open(self._md_path, encoding="utf-8").read()
        self.assertIn("⏭ 跳过", content)
        self.assertIn("resource_unavailable", content)

    def test_multiple_challenges_summary(self):
        """多题混合状态的汇总行正确。"""
        self.board.register("c-01", "easy", 100, 1)
        self.board.register("c-02", "medium", 300, 1)
        self.board.register("c-03", "hard", 500, 1)

        self.board.mark_done("c-01", success=True, correct_flags=1,
                             total_flags=1, rounds=3)
        self.board.mark_running("c-02")
        self.board.mark_done("c-03", success=False, correct_flags=0,
                             total_flags=1, rounds=30, note="沙箱逃逸失败")

        content = open(self._md_path, encoding="utf-8").read()
        self.assertIn("已解: 1/3", content)
        self.assertIn("得分: **100/1000**", content)
        self.assertIn("进行中: 1", content)
        self.assertIn("失败: 1", content)

    def test_long_note_truncated(self):
        """超长备注被截断到 60 字符。"""
        long_note = "A" * 100
        self.board.register("web-01", "easy", 100, 1)
        self.board.mark_done("web-01", success=False, correct_flags=0,
                             total_flags=1, rounds=1, note=long_note)
        content = open(self._md_path, encoding="utf-8").read()
        self.assertIn("A" * 60 + "…", content)
        self.assertNotIn("A" * 100, content)

    def test_order_preserved(self):
        """题目按注册顺序显示。"""
        self.board.register("z-99", "hard", 500, 1)
        self.board.register("a-01", "easy", 100, 1)
        content = open(self._md_path, encoding="utf-8").read()
        pos_z = content.index("z-99")
        pos_a = content.index("a-01")
        self.assertLess(pos_z, pos_a, "注册顺序应保持 z-99 在 a-01 前面")


if __name__ == "__main__":
    unittest.main()
