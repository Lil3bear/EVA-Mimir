import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from solver.ctfplatform.tsecbench_client import Challenge
from solver.runtime.context import RunContext, ctx
from solver.runtime.settings import enforce_medium_only_routing
from solver.runtime.submit_verify import is_decoy_flag_context, submission_message_verified
from solver.runtime.workspace_guard import (
    assert_path_allowed,
    block_foreign_workspace,
    foreign_challenge_codes,
    tool_results_dir,
)
from solver.tools import bridge_tools, bash_tool, file_tools


class RoutingEnforcementTests(unittest.TestCase):
    def test_enforce_medium_only_overrides_local_heavy(self):
        settings = {
            "llm": {
                "routing": {"hard_tier": "heavy", "escalate_rounds": 3},
                "reasoning_effort": "high",
            }
        }
        out = enforce_medium_only_routing(settings)
        self.assertEqual(out["llm"]["routing"]["hard_tier"], "light")
        self.assertEqual(out["llm"]["routing"]["escalate_rounds"], 0)
        self.assertTrue(out.get("_routing_corrected"))


class WorkspaceGuardTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="ws-guard-")
        self._ctx = RunContext.create(self._tmpdir, "a-03")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_blocks_foreign_workspace_in_bash(self):
        with ctx.bind(self._ctx, None):
            msg = block_foreign_workspace("cd /workspace/c-08 && ls")
            self.assertIn("拒绝", msg)
            self.assertIn("c-08", msg)

    def test_allows_current_challenge_workspace(self):
        with ctx.bind(self._ctx, None):
            self.assertEqual(foreign_challenge_codes("cd /workspace/a-03 && ls"), [])
            self.assertEqual(block_foreign_workspace("curl http://x"), "")

    def test_blocks_foreign_read_path(self):
        with ctx.bind(self._ctx, None):
            foreign = str(Path(self._tmpdir) / "c-08" / "notes.txt")
            msg = assert_path_allowed(foreign)
            self.assertIn("拒绝", msg)

    def test_tool_results_dir_scoped_to_challenge(self):
        with ctx.bind(self._ctx, None):
            path = tool_results_dir()
            self.assertIn("/a-03/", path.replace("\\", "/"))
            self.assertTrue(path.endswith(".tool-results"))


class SubmitVerifyTests(unittest.TestCase):
    def test_decoy_flag_from_challenge_path_scan(self):
        raw = (
            "--- /challenge/flag.txt --- len=42 flag=True\n"
            "flag{decoy-decoy-decoy-decoy-decoy12}\n"
        )
        self.assertTrue(is_decoy_flag_context(raw, "flag{decoy-decoy-decoy-decoy-decoy12}"))

    def test_real_flag_line_not_decoy(self):
        raw = 'login ok flag{real-real-real-real-real-real}\n'
        self.assertFalse(is_decoy_flag_context(raw, "flag{real-real-real-real-real-real}"))

    def test_submission_message_verified_rejects_unscored(self):
        msg = "[✗] Flag 提交未计分：flag{x} 平台进度未增加"
        self.assertFalse(submission_message_verified(msg))

    def test_submission_message_verified_accepts_checked_success(self):
        msg = "[✓] Flag 提交正确：flag{x}（进度 1/1） 🎉 全部 Flag 已找到"
        self.assertTrue(submission_message_verified(msg))


class BashIsolationTests(unittest.TestCase):
    def test_execute_blocks_foreign_cd(self):
        root = tempfile.mkdtemp(prefix="bash-iso-")
        run = RunContext.create(root, "a-03")
        with ctx.bind(run, None):
            out = bash_tool.execute({"cmd": "cd /workspace/c-08 && pwd"})
        self.assertIn("拒绝", out)


class FileToolIsolationTests(unittest.TestCase):
    def test_read_file_blocks_foreign_challenge(self):
        root = tempfile.mkdtemp(prefix="file-iso-")
        run = RunContext.create(root, "a-03")
        foreign = str(Path(root) / "c-08" / "secret.txt")
        with ctx.bind(run, None):
            out = file_tools.read_file({"path": foreign})
        self.assertIn("拒绝", out)


class SubmitPlatformVerifyTests(unittest.TestCase):
    def test_api_correct_without_progress_is_downgraded(self):
        root = tempfile.mkdtemp(prefix="submit-verify-")
        run = RunContext.create(root, "a-18")

        class StubClient:
            def submit_flag(self, unique_code, flag):
                return type("R", (), {
                    "correct": True,
                    "awarded": 500,
                    "cumulative_score": 500,
                    "correct_flag_count": 1,
                    "total_flag_count": 1,
                    "matched_flag_index": 0,
                    "is_completed": True,
                })()

            def list_challenges(self):
                return [Challenge(
                    unique_code="a-18",
                    description="",
                    difficulty="hard",
                    level=1,
                    total_score=500,
                    flag_count=1,
                    correct_flag_count=0,
                    is_completed=False,
                    container_status="running",
                    container_addr=(),
                )]

        with ctx.bind(run, StubClient()):
            result = bridge_tools.submit_flag({
                "flag": "flag{decoy-decoy-decoy-decoy-decoy12}",
                "writeup": "test",
            })

        self.assertIn("未计分", result)
        self.assertIn("[✗]", result)


class AutoSubmitDecoyTests(unittest.TestCase):
    @patch("solver.agent.bridge_tools.submit_flag")
    def test_skips_decoy_challenge_flag_scan(self, submit_flag):
        from solver.agent import SolverAgent

        agent = SolverAgent.__new__(SolverAgent)
        agent._auto_submit_count = 0
        raw = (
            "⚡ 发现疑似 flag：['flag{decoy-decoy-decoy-decoy-decoy12}']\n"
            "--- /challenge/flag.txt --- flag=True\n"
            "flag{decoy-decoy-decoy-decoy-decoy12}\n"
        )
        self.assertEqual(agent._auto_submit_flags(raw, "bash", {"cmd": "find / -name flag*"}), "")
        submit_flag.assert_not_called()


if __name__ == "__main__":
    unittest.main()
