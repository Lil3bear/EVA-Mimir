import json
import os
import tempfile
import time
import unittest
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

from solver.ctfplatform.tsecbench_client import (
    Challenge,
    InvalidState,
    ResourceUnavailable,
    TaskNotFound,
    StartResult,
    CloseResult,
    TsecbenchClient,
    VpnCheckResult,
)
from solver.ctfplatform.scheduler import (
    Scheduler,
    SchedulerReport,
    SchedulerResult,
    _build_task_from_challenge,
    _retry_delay,
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


class AttemptProgressTests(unittest.TestCase):
    def test_partial_without_new_flag_is_not_progress(self):
        result = SchedulerResult(
            "multi-flag",
            success=False,
            initial_correct_flag_count=1,
            correct_flag_count=1,
            material_progress_count=0,
        )
        self.assertFalse(result.made_progress)

    def test_new_flag_or_material_evidence_is_progress(self):
        new_flag = SchedulerResult(
            "multi-flag",
            success=False,
            initial_correct_flag_count=1,
            correct_flag_count=2,
        )
        evidence = SchedulerResult(
            "unsolved",
            success=False,
            material_progress_count=1,
        )
        self.assertTrue(new_flag.made_progress)
        self.assertTrue(evidence.made_progress)


class RetryPolicyTests(unittest.TestCase):
    @patch("solver.ctfplatform.scheduler.random.uniform", return_value=1.0)
    def test_retry_delay_is_exponential_and_capped(self, _uniform):
        self.assertEqual(_retry_delay(2, 1), 2)
        self.assertEqual(_retry_delay(2, 3), 8)
        self.assertEqual(_retry_delay(30, 4, cap=60), 60)
        self.assertEqual(_retry_delay(0, 5), 0)


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
        self.assertIn("10.0.0.2:8080", task)
        self.assertIn("不保证是 HTTP", task)
        self.assertIn("SQL injection", task)
        self.assertIn("web-01", task)

    def test_includes_every_container_address_without_guessing_protocol(self):
        c = _make_challenge("service-01")
        task = _build_task_from_challenge(
            c, ("10.0.0.2:10086", "10.0.0.2:22")
        )
        self.assertIn("10.0.0.2:10086", task)
        self.assertIn("10.0.0.2:22", task)
        self.assertNotIn("http://10.0.0.2", task)

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
        self.assertIn('skill_load(name="web")', task)

        # b- 前缀 → 多阶段渗透
        c = _make_challenge("b-01", flag_count=4)
        task = _build_task_from_challenge(c, ("10.0.0.2:80",))
        self.assertIn("渗透", task)
        self.assertIn('skill_load(name="pentest")', task)

        # C 类多入口或 SSH/Telnet 服务不能按纯 Web 处理
        c = _make_challenge("c-07")
        task = _build_task_from_challenge(c, ("10.0.0.4:23",))
        self.assertIn("多服务渗透", task)
        self.assertIn('skill_load(name="pentest")', task)

        # e1- 前缀 → 渗透测试
        c = _make_challenge("e1-03")
        task = _build_task_from_challenge(c, ("10.0.0.3:80",))
        self.assertIn("渗透", task)
        self.assertIn('skill_load(name="pentest")', task)

    def test_port_product_hint_guides_c_challenge_recognition(self):
        # 平台不返回题目标题，端口是唯一的强线索；c 类题必须给出产品候选。
        cases = {
            "3000": "Dify",
            "8188": "ComfyUI",
            "8080": "HugeGraph",
            "7860": "Gradio",
            "8443": "OFBiz",
        }
        for port, product in cases.items():
            with self.subTest(port=port):
                c = _make_challenge(f"c-{port}")
                task = _build_task_from_challenge(c, (f"10.0.0.9:{port}",))
                self.assertIn("端口产品候选", task)
                self.assertIn(product, task)

    def test_plain_http_port_has_no_product_hint(self):
        c = _make_challenge("a-01")
        task = _build_task_from_challenge(c, ("10.0.0.9:80",))
        self.assertNotIn("端口产品候选", task)


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

    def test_non_http_endpoint_reaches_agent(self):
        challenges = [_make_challenge("c-07")]
        completed = [_make_challenge("c-07", is_completed=True, correct_flag_count=1)]
        client = self._make_mock_client(challenges)
        client.start_challenge.return_value = StartResult(
            unique_code="c-07", container_addr=("10.0.0.2:23",)
        )
        client.list_challenges.side_effect = [challenges, completed, completed]
        mock_agent = MagicMock(round=2)
        mock_factory = MagicMock(return_value=mock_agent)

        report = Scheduler(
            client,
            settings={"llm": {}, "solver": {}},
            agent_factory=mock_factory,
            workspace_dir=self._tmpdir,
        ).run_all()

        self.assertEqual(report.solved, 1)
        # c-前缀属于前排 web/misc 家族，现在走隔离多解（两个策略各跑一次）。
        mock_agent.run.assert_called()
        self.assertIn("10.0.0.2:23", mock_factory.call_args.kwargs["task"])

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

    def test_unexpected_error_after_start_still_closes_challenge(self):
        challenge = _make_challenge("hard-01", difficulty="hard")
        client = self._make_mock_client([challenge])
        scheduler = Scheduler(
            client,
            settings={"llm": {}, "solver": {}},
            workspace_dir=self._tmpdir,
            close_retry_interval=0,
        )

        with patch.object(
            scheduler, "_attempt_multi_solver", side_effect=RuntimeError("boom")
        ):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                scheduler._attempt_challenge(challenge)

        client.close_challenge.assert_called_once_with("hard-01")
        self.assertNotIn("hard-01", scheduler._active_codes)

    def test_multi_solver_elects_one_observer(self):
        challenge = _make_challenge("hard-01", difficulty="hard")
        client = self._make_mock_client([challenge])
        created_settings = []

        def factory(**kwargs):
            created_settings.append(kwargs["settings"])
            return MagicMock(solved=False, round=1)

        scheduler = Scheduler(
            client,
            settings={"llm": {}, "solver": {}},
            agent_factory=factory,
            workspace_dir=self._tmpdir,
        )
        workspace = os.path.join(self._tmpdir, challenge.unique_code)

        scheduler._attempt_multi_solver(
            challenge,
            ("10.0.0.2:8080",),
            workspace,
            challenge.unique_code,
            "10.0.0.2:8080",
        )

        enabled = [s["solver"]["observer_enabled"] for s in created_settings]
        # 三个竞争假设（foothold/lateral/source）只选一个 Observer 作为控制面。
        self.assertCountEqual(enabled, [True, False, False])

    def test_multi_solver_wires_pro_model(self):
        """hard 竞争假设的 spec.model="pro" 必须真正切换到 pro 模型。"""
        challenge = _make_challenge("hard-01", difficulty="hard")
        client = self._make_mock_client([challenge])
        created_settings = []

        def factory(**kwargs):
            created_settings.append(kwargs["settings"])
            return MagicMock(solved=False, round=1)

        scheduler = Scheduler(
            client,
            settings={
                "llm": {"default_model": "deepseek-v4-flash", "pro_model": "deepseek-v4-pro"},
                "solver": {},
            },
            agent_factory=factory,
            workspace_dir=self._tmpdir,
        )
        workspace = os.path.join(self._tmpdir, challenge.unique_code)

        scheduler._attempt_multi_solver(
            challenge,
            ("10.0.0.2:8080",),
            workspace,
            challenge.unique_code,
            "10.0.0.2:8080",
        )

        models = [s["llm"]["default_model"] for s in created_settings]
        self.assertEqual(models, ["deepseek-v4-pro"] * 3)

    def test_multi_solver_pro_can_be_disabled(self):
        """solver.pro_enabled=false 时，hard 竞争假设仍用默认 flash 模型。"""
        challenge = _make_challenge("hard-01", difficulty="hard")
        client = self._make_mock_client([challenge])
        created_settings = []

        def factory(**kwargs):
            created_settings.append(kwargs["settings"])
            return MagicMock(solved=False, round=1)

        scheduler = Scheduler(
            client,
            settings={
                "llm": {"default_model": "deepseek-v4-flash", "pro_model": "deepseek-v4-pro"},
                "solver": {"pro_enabled": False},
            },
            agent_factory=factory,
            workspace_dir=self._tmpdir,
        )
        workspace = os.path.join(self._tmpdir, challenge.unique_code)

        scheduler._attempt_multi_solver(
            challenge,
            ("10.0.0.2:8080",),
            workspace,
            challenge.unique_code,
            "10.0.0.2:8080",
        )

        models = [s["llm"]["default_model"] for s in created_settings]
        self.assertEqual(models, ["deepseek-v4-flash"] * 3)

    @patch("solver.agent.ObserverLoop")
    @patch("solver.agent.OpenAI")
    @patch("solver.agent.search_tool")
    def test_multi_solver_agent_uses_pro_model_end_to_end(
        self, mock_search, mock_openai, mock_observer
    ):
        """端到端：spec.model="pro" 一路穿透到 SolverAgent.model == llm.pro_model。"""
        from solver.agent import SolverAgent

        challenge = _make_challenge("hard-01", difficulty="hard")
        client = self._make_mock_client([challenge])
        created_agents = []

        def factory(**kwargs):
            agent = SolverAgent(
                task=kwargs["task"],
                settings=kwargs["settings"],
                skills_dir="/skills",
            )
            created_agents.append(agent)
            # 阻止真正发起 LLM 调用，只验证模型接线。
            agent.run = lambda: None
            agent.round = 1
            agent.solved = False
            return agent

        scheduler = Scheduler(
            client,
            settings={
                "llm": {
                    "default_model": "deepseek-v4-flash",
                    "pro_model": "deepseek-v4-pro",
                },
                "solver": {},
            },
            agent_factory=factory,
            workspace_dir=self._tmpdir,
        )
        workspace = os.path.join(self._tmpdir, challenge.unique_code)

        scheduler._attempt_multi_solver(
            challenge,
            ("10.0.0.2:8080",),
            workspace,
            challenge.unique_code,
            "10.0.0.2:8080",
        )

        self.assertEqual([a.model for a in created_agents], ["deepseek-v4-pro"] * 3)


if __name__ == "__main__":
    unittest.main()


class ComplianceHistoryTests(unittest.TestCase):
    """历史题目解法不得进入运行时提示或镜像。"""

    def test_challenge_specific_history_is_disabled(self):
        from solver.ctfplatform.scheduler import _load_recent_chain
        self.assertEqual(_load_recent_chain("a-18", "/tmp/nonexistent-skills"), "")


class TerminalAndDeadlineSchedulerTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="test-terminal-scheduler-")

    def test_invalid_state_from_solver_is_terminal(self):
        challenge = _make_challenge("web-terminal")
        client = MagicMock(spec=TsecbenchClient)
        client.check_vpn.return_value = VpnCheckResult("ok", "10.0.0.1", "now")
        client.list_challenges.return_value = [challenge]
        client.start_challenge.return_value = StartResult(
            "web-terminal", ("10.0.0.2:8080",)
        )
        client.close_challenge.return_value = CloseResult("web-terminal", True)
        agent = MagicMock(round=1)
        agent.run.side_effect = InvalidState("invalid_state", "task ended")

        scheduler = Scheduler(
            client,
            settings={"llm": {}, "solver": {}},
            agent_factory=MagicMock(return_value=agent),
            workspace_dir=self._tmpdir,
        )
        with self.assertRaises(InvalidState):
            scheduler.run_all()
        client.close_challenge.assert_called_with("web-terminal")

    def test_start_retry_respects_deadline(self):
        challenge = _make_challenge("web-deadline")
        client = MagicMock(spec=TsecbenchClient)
        client.check_vpn.return_value = VpnCheckResult("ok", "10.0.0.1", "now")
        client.list_challenges.return_value = [challenge]
        client.start_challenge.side_effect = ResourceUnavailable(
            "resource_unavailable", "not ready"
        )
        client.close_challenge.return_value = CloseResult("web-deadline", True)
        scheduler = Scheduler(
            client,
            settings={"llm": {}, "solver": {}},
            workspace_dir=self._tmpdir,
            start_retry_interval=30,
            start_retry_max=5,
            deadline=time.time() + 0.05,
        )
        started = time.time()
        report = scheduler.run_all()
        self.assertLess(time.time() - started, 1.0)
        self.assertEqual(report.failed, 1)


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
