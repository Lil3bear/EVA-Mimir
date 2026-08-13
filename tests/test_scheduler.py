import os
import tempfile
import unittest
import threading
from unittest.mock import MagicMock, patch

from solver.ctfplatform.tsecbench_client import (
    Challenge,
    InvalidState,
    StartResult,
    CloseResult,
    TsecbenchClient,
    VpnCheckResult,
)
from solver.ctfplatform.scheduler import (
    Scheduler,
    SchedulerReport,
    _build_task_from_challenge,
    _sort_challenges,
)


def _make_challenge(
    unique_code: str,
    difficulty: str = "easy",
    is_completed: bool = False,
    flag_count: int = 1,
    correct_flag_count: int = 0,
    description: str = "",
) -> Challenge:
    return Challenge(
        unique_code=unique_code,
        description=description,
        difficulty=difficulty,
        level=1,
        total_score=100,
        flag_count=flag_count,
        correct_flag_count=correct_flag_count,
        is_completed=is_completed,
        container_status="stopped",
        container_addr=(),
    )


class SortChallengesTests(unittest.TestCase):
    def test_sorts_by_difficulty_then_code(self):
        challenges = [
            _make_challenge("hard-02", difficulty="hard"),
            _make_challenge("easy-01", difficulty="easy"),
            _make_challenge("medium-01", difficulty="medium"),
            _make_challenge("easy-02", difficulty="easy"),
        ]
        result = _sort_challenges(challenges)
        codes = [c.unique_code for c in result]
        self.assertEqual(codes, ["easy-01", "easy-02", "medium-01", "hard-02"])


class BuildTaskTests(unittest.TestCase):
    def test_includes_target_url_from_container_addr(self):
        c = _make_challenge("web-01", description="SQL injection")
        task = _build_task_from_challenge(c, ("10.0.0.2:8080",))
        self.assertIn("http://10.0.0.2:8080", task)
        self.assertIn("SQL injection", task)
        self.assertIn("web-01", task)

    def test_multi_flag_hint(self):
        c = _make_challenge("web-02", flag_count=3, correct_flag_count=1)
        task = _build_task_from_challenge(c, ("10.0.0.3:80",))
        self.assertIn("3 个 Flag", task)
        self.assertIn("已找到 1 个", task)
        self.assertIn("还剩 2 个", task)
        self.assertIn("多阶段渗透", task)
        self.assertIn("提权", task)

    def test_single_flag_no_multi_hint(self):
        c = _make_challenge("web-03", flag_count=1)
        task = _build_task_from_challenge(c, ("10.0.0.4:80",))
        self.assertNotIn("多阶段渗透", task)
        self.assertNotIn("还剩", task)

    def test_no_container_addr(self):
        c = _make_challenge("misc-01")
        task = _build_task_from_challenge(c, ())
        self.assertIn("未返回靶场地址", task)

    def test_type_inference_from_code_prefix(self):
        # a- 前缀 → Web 漏洞
        c = _make_challenge("a-05")
        task = _build_task_from_challenge(c, ("10.0.0.1:80",))
        self.assertIn("Web", task)
        self.assertIn("/skills/web/SKILL.md", task)

        # b- 前缀 → 多阶段渗透
        c = _make_challenge("b-01", flag_count=4)
        task = _build_task_from_challenge(c, ("10.0.0.2:80",))
        self.assertIn("渗透", task)
        self.assertIn("/skills/pentest/SKILL.md", task)

        # e1- 前缀 → 二进制/逆向
        c = _make_challenge("e1-03")
        task = _build_task_from_challenge(c, ("10.0.0.3:80",))
        self.assertIn("逆向", task)
        self.assertIn("/skills/reverse/SKILL.md", task)


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="test-scheduler-")

    def _make_mock_client(self, challenges):
        client = MagicMock(spec=TsecbenchClient)
        client.check_vpn.return_value = VpnCheckResult(
            status="ok", client_ip="10.0.0.1", time="2026-08-07T12:00:00"
        )
        client.list_challenges.return_value = challenges
        client.start_challenge.return_value = StartResult(
            unique_code=challenges[0].unique_code if challenges else "",
            container_addr=("10.0.0.2:8080",),
        )
        client.close_challenge.return_value = CloseResult(
            unique_code=challenges[0].unique_code if challenges else "",
            closed=True,
        )
        return client

    def test_skips_completed_challenges(self):
        challenges = [
            _make_challenge("web-01", is_completed=True),
            _make_challenge("web-02", is_completed=True),
        ]
        client = self._make_mock_client(challenges)
        scheduler = Scheduler(client, settings={"llm": {}, "solver": {}},
                              workspace_dir=self._tmpdir)

        report = scheduler.run_all()

        self.assertEqual(report.total_challenges, 2)
        self.assertEqual(report.skipped, 2)
        self.assertEqual(report.attempted, 0)
        client.start_challenge.assert_not_called()

    def test_runs_single_challenge(self):
        """验证调度器能正确走完 启动→解题→关闭 流程。"""
        challenges = [_make_challenge("web-01")]
        client = self._make_mock_client(challenges)

        # solver run 之后，list_challenges 返回已完成状态
        completed = _make_challenge("web-01", is_completed=True, correct_flag_count=1)
        client.list_challenges.side_effect = [
            challenges,       # 第一次：初始列表
            [completed],      # 第二次：solver 结束后查询
            [completed],      # 第三次：最终统计
        ]

        mock_agent = MagicMock()
        mock_agent.round = 5
        mock_factory = MagicMock(return_value=mock_agent)

        scheduler = Scheduler(
            client,
            settings={"llm": {}, "solver": {}},
            agent_factory=mock_factory,
            workspace_dir=self._tmpdir,
        )
        report = scheduler.run_all()

        self.assertEqual(report.attempted, 1)
        self.assertEqual(report.solved, 1)
        client.start_challenge.assert_called_once_with("web-01")
        client.close_challenge.assert_called_once_with("web-01")
        mock_agent.run.assert_called_once()
        # 确认 factory 被调用时传入了正确的 task
        call_kwargs = mock_factory.call_args
        self.assertIn("web-01", call_kwargs.kwargs["task"])

    def test_handles_start_invalid_state(self):
        """启动题目返回 invalid_state 时，重试耗尽后跳过该题。"""
        challenges = [_make_challenge("web-01")]
        client = self._make_mock_client(challenges)
        client.start_challenge.side_effect = InvalidState(
            "invalid_state", "active limit reached"
        )

        scheduler = Scheduler(client, settings={"llm": {}, "solver": {}},
                              workspace_dir=self._tmpdir,
                              start_retry_max=1, start_retry_interval=0)
        report = scheduler.run_all()

        self.assertEqual(report.attempted, 1)
        self.assertEqual(report.failed, 1)
        self.assertIn("active limit", report.results[0].error)
        client.close_challenge.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class ParallelSchedulerTests(unittest.TestCase):
    """并行调度测试。"""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="test-parallel-")

    def _make_mock_client(self, challenges):
        client = MagicMock(spec=TsecbenchClient)
        client.check_vpn.return_value = VpnCheckResult(
            status="ok", client_ip="10.0.0.1", time="2026-08-07T12:00:00"
        )

        def start_side_effect(code):
            return StartResult(
                unique_code=code,
                container_addr=(f"10.0.0.{hash(code) % 254 + 1}:8080",),
            )

        def close_side_effect(code):
            return CloseResult(unique_code=code, closed=True)

        client.start_challenge.side_effect = start_side_effect
        client.close_challenge.side_effect = close_side_effect
        return client

    def test_parallel_runs_all_challenges(self):
        """3 题并行，全部运行完毕。"""
        challenges = [
            _make_challenge("web-01"),
            _make_challenge("web-02"),
            _make_challenge("web-03"),
        ]
        client = self._make_mock_client(challenges)

        completed = [
            _make_challenge(c.unique_code, is_completed=True, correct_flag_count=1)
            for c in challenges
        ]
        # 第一次 list_challenges 返回未完成 → 构建 todo 列表
        # 第二、三次返回已完成 → solver 结束后查状态 + 最终统计
        client.list_challenges.side_effect = [
            challenges,    # 初始列表
            completed,     # solver 结束后查
            completed,     # solver 结束后查
            completed,     # solver 结束后查
            completed,     # 最终统计
        ]

        thread_ids = []
        factory_lock = threading.Lock()

        def mock_factory(task, settings, skills_dir):
            with factory_lock:
                thread_ids.append(threading.current_thread().ident)
            agent = MagicMock()
            agent.round = 3
            return agent

        scheduler = Scheduler(
            client,
            settings={"llm": {}, "solver": {}},
            max_parallel=3,
            agent_factory=mock_factory,
            workspace_dir=self._tmpdir,
        )
        report = scheduler.run_all()

        self.assertEqual(report.attempted, 3)
        self.assertEqual(report.solved, 3)
        self.assertEqual(len(report.results), 3)

        started_codes = {c.args[0] for c in client.start_challenge.call_args_list}
        closed_codes = {c.args[0] for c in client.close_challenge.call_args_list}
        self.assertEqual(started_codes, {"web-01", "web-02", "web-03"})
        self.assertEqual(closed_codes, {"web-01", "web-02", "web-03"})

    def test_parallel_thread_isolation(self):
        """验证并行时各 worker 线程使用不同的 thread-local 上下文。"""
        challenges = [
            _make_challenge("web-01"),
            _make_challenge("web-02"),
        ]
        client = self._make_mock_client(challenges)

        completed = [
            _make_challenge(c.unique_code, is_completed=True, correct_flag_count=1)
            for c in challenges
        ]
        # 第一次返回未完成（构建 todo），后续返回已完成
        client.list_challenges.side_effect = [
            challenges,    # 初始列表
            completed,     # solver 结束后查
            completed,     # solver 结束后查
            completed,     # 最终统计
        ]

        observed_codes = []
        codes_lock = threading.Lock()

        def mock_factory(task, settings, skills_dir):
            from solver.worker_context import ctx
            agent = MagicMock()

            def record_code():
                import time
                time.sleep(0.05)
                with codes_lock:
                    observed_codes.append(ctx.unique_code)

            agent.run.side_effect = record_code
            agent.round = 2
            return agent

        scheduler = Scheduler(
            client,
            settings={"llm": {}, "solver": {}},
            max_parallel=2,
            agent_factory=mock_factory,
            workspace_dir=self._tmpdir,
        )
        report = scheduler.run_all()

        self.assertEqual(len(observed_codes), 2)
        self.assertEqual(set(observed_codes), {"web-01", "web-02"})

    def test_parallel_with_failure(self):
        """并行时单题失败不影响其他题。"""
        challenges = [
            _make_challenge("web-01"),
            _make_challenge("web-02"),
            _make_challenge("web-03"),
        ]
        client = self._make_mock_client(challenges)
        # 第一次返回未完成，后续返回未完成（因为有失败的）
        client.list_challenges.side_effect = [
            challenges,    # 初始列表
            challenges,    # solver 结束后查（未完成）
            challenges,    # solver 结束后查
            challenges,    # solver 结束后查
            challenges,    # 最终统计
        ]

        call_count = 0
        count_lock = threading.Lock()

        def mock_factory(task, settings, skills_dir):
            nonlocal call_count
            agent = MagicMock()

            with count_lock:
                call_count += 1
                current = call_count

            if current == 2:
                agent.run.side_effect = RuntimeError("LLM API 超时")
            agent.round = 1
            return agent

        scheduler = Scheduler(
            client,
            settings={"llm": {}, "solver": {}},
            max_parallel=3,
            agent_factory=mock_factory,
            workspace_dir=self._tmpdir,
        )
        report = scheduler.run_all()

        self.assertEqual(report.attempted, 3)
        errors = [r for r in report.results if r.error]
        self.assertGreaterEqual(len(errors), 1)
        self.assertEqual(client.close_challenge.call_count, 3)

    def test_sequential_fallback(self):
        """max_parallel=1 时走顺序模式。"""
        challenges = [_make_challenge("web-01"), _make_challenge("web-02")]
        client = self._make_mock_client(challenges)

        completed = [
            _make_challenge(c.unique_code, is_completed=True, correct_flag_count=1)
            for c in challenges
        ]
        # 第一次返回未完成，后续返回已完成
        client.list_challenges.side_effect = [
            challenges,    # 初始列表
            completed,     # solver 结束后查
            completed,     # solver 结束后查
            completed,     # 最终统计
        ]

        call_order = []

        def mock_factory(task, settings, skills_dir):
            # extract unique_code from task text
            for line in task.split("\n"):
                if "题目：" in line:
                    code = line.split("：", 1)[1].strip()
                    call_order.append(code)
                    break
            agent = MagicMock()
            agent.round = 1
            return agent

        scheduler = Scheduler(
            client,
            settings={"llm": {}, "solver": {}},
            max_parallel=1,
            agent_factory=mock_factory,
            workspace_dir=self._tmpdir,
        )
        report = scheduler.run_all()

        self.assertEqual(report.attempted, 2)
        self.assertEqual(call_order, ["web-01", "web-02"])

    def test_per_challenge_workspace_isolation(self):
        """验证并行时每题有独立的 challenge_dir。"""
        challenges = [
            _make_challenge("web-01"),
            _make_challenge("web-02"),
        ]
        client = self._make_mock_client(challenges)

        completed = [
            _make_challenge(c.unique_code, is_completed=True, correct_flag_count=1)
            for c in challenges
        ]
        client.list_challenges.side_effect = [
            challenges,
            completed,
            completed,
            completed,
        ]

        observed_dirs = []
        dirs_lock = threading.Lock()

        def mock_factory(task, settings, skills_dir):
            from solver.worker_context import ctx
            agent = MagicMock()

            def record_dir():
                import time
                time.sleep(0.05)
                with dirs_lock:
                    observed_dirs.append(ctx.challenge_dir)

            agent.run.side_effect = record_dir
            agent.round = 1
            return agent

        scheduler = Scheduler(
            client,
            settings={"llm": {}, "solver": {}},
            max_parallel=2,
            agent_factory=mock_factory,
            workspace_dir="/tmp/test-workspace",
        )
        report = scheduler.run_all()

        self.assertEqual(len(observed_dirs), 2)
        # 每题的 challenge_dir 应该是 workspace/unique_code
        # 统一路径分隔符（Windows 下是 \\，Linux 下是 /）
        normalized = [os.path.normpath(d) for d in observed_dirs]
        expected_01 = os.path.normpath("/tmp/test-workspace/web-01")
        expected_02 = os.path.normpath("/tmp/test-workspace/web-02")
        self.assertIn(expected_01, normalized)
        self.assertIn(expected_02, normalized)
        # 两个 dir 应该不同
        self.assertNotEqual(normalized[0], normalized[1])

    def test_start_retry_succeeds_after_transient_failure(self):
        """验证 start_challenge 重试机制：前 2 次 InvalidState，第 3 次成功。"""
        challenges = [_make_challenge("web-01")]
        client = self._make_mock_client(challenges)

        call_count = 0
        def start_side_effect(code):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise InvalidState("invalid_state", "active limit reached")
            return StartResult(unique_code=code, container_addr=("10.0.0.2:8080",))

        client.start_challenge.side_effect = start_side_effect

        completed = [_make_challenge("web-01", is_completed=True, correct_flag_count=1)]
        client.list_challenges.side_effect = [
            challenges,
            completed,
            completed,
        ]

        mock_agent = MagicMock()
        mock_agent.round = 3

        scheduler = Scheduler(
            client,
            settings={"llm": {}, "solver": {}},
            agent_factory=MagicMock(return_value=mock_agent),
            workspace_dir=self._tmpdir,
            start_retry_max=5,
            start_retry_interval=0,
        )
        report = scheduler.run_all()

        self.assertEqual(report.attempted, 1)
        self.assertEqual(report.solved, 1)
        self.assertEqual(client.start_challenge.call_count, 3)

    def test_start_retry_exhausted_skips(self):
        """验证 start_challenge 重试耗尽后跳过。"""
        challenges = [_make_challenge("web-01")]
        client = self._make_mock_client(challenges)
        client.list_challenges.side_effect = [
            challenges,    # 初始列表
            challenges,    # 最终统计
        ]
        client.start_challenge.side_effect = InvalidState(
            "invalid_state", "active limit reached"
        )

        scheduler = Scheduler(
            client,
            settings={"llm": {}, "solver": {}},
            workspace_dir=self._tmpdir,
            start_retry_max=3,
            start_retry_interval=0,
        )
        report = scheduler.run_all()

        self.assertEqual(report.attempted, 1)
        self.assertEqual(report.failed, 1)
        self.assertEqual(client.start_challenge.call_count, 3)

    def test_queue_based_parallel_no_skip(self):
        """验证队列模式：5 题 2 并行，全部跑到（不会跳过）。"""
        challenges = [
            _make_challenge(f"q-{i:02d}") for i in range(5)
        ]
        client = self._make_mock_client(challenges)

        completed = [
            _make_challenge(c.unique_code, is_completed=True, correct_flag_count=1)
            for c in challenges
        ]
        # 初始列表 + 每题结束后查状态 + 最终统计
        client.list_challenges.side_effect = [
            challenges,
        ] + [completed] * 10  # 足够多

        def mock_factory(task, settings, skills_dir):
            import time as _t
            agent = MagicMock()
            agent.run.side_effect = lambda: _t.sleep(0.05)
            agent.round = 3
            return agent

        scheduler = Scheduler(
            client,
            settings={"llm": {}, "solver": {}},
            max_parallel=2,
            agent_factory=mock_factory,
            workspace_dir=self._tmpdir,
        )
        report = scheduler.run_all()

        self.assertEqual(report.attempted, 5)
        self.assertEqual(report.solved, 5)
        started_codes = {c.args[0] for c in client.start_challenge.call_args_list}
        self.assertEqual(len(started_codes), 5)
        # 没有任何题被跳过
        skipped = [r for r in report.results if "skip" in r.error.lower()]
        self.assertEqual(len(skipped), 0)

    def test_skip_codes_filters_abandoned(self):
        """验证 skip_codes 参数：被放弃的题目不会被调度。"""
        challenges = [
            _make_challenge("web-01"),
            _make_challenge("web-02"),
            _make_challenge("web-03"),
        ]
        client = self._make_mock_client(challenges)
        completed = [
            _make_challenge(c.unique_code, is_completed=True, correct_flag_count=1)
            for c in challenges
        ]
        client.list_challenges.side_effect = [
            challenges,
        ] + [completed] * 5

        mock_agent = MagicMock()
        mock_agent.round = 1

        scheduler = Scheduler(
            client,
            settings={"llm": {}, "solver": {}},
            max_parallel=1,
            agent_factory=MagicMock(return_value=mock_agent),
            workspace_dir=self._tmpdir,
            skip_codes={"web-02"},
        )
        report = scheduler.run_all()

        # web-02 被跳过，只跑 web-01 和 web-03
        self.assertEqual(report.attempted, 2)
        started_codes = {c.args[0] for c in client.start_challenge.call_args_list}
        self.assertNotIn("web-02", started_codes)

