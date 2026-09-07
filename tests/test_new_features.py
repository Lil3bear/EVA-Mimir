"""Tests for new features: difficulty-based max_rounds, path traversal dedup, forced review."""
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from solver.tools.bash_tool import _extract_url_pattern, _inline_http_variant_count
from solver.runtime.control import ControlPolicy
from solver.runtime.context import RunContext, ctx


class ObserverControlPlaneTests(unittest.TestCase):
    def test_disabled_observer_is_noop(self):
        from solver.observer.loop import ObserverLoop

        observer = ObserverLoop(
            settings={"solver": {"observer_enabled": False}},
            on_correction=MagicMock(),
        )
        observer.on_round_start(1)
        observer.on_tool_call("bash", {"cmd": "id"}, "uid=0")
        observer.on_round_end(1)
        observer.trigger_now()
        observer.on_agent_end()

        self.assertEqual(observer._round_logs, [])
        self.assertIsNone(observer._review_thread)
        self.assertEqual(observer._VECTOR_CYCLE_THRESHOLD, 4)

    def test_stop_discards_pending_review_without_blocking_shutdown(self):
        from solver.observer.loop import ObserverLoop

        observer = ObserverLoop(settings={"solver": {"observer_enabled": True}})
        observer.on_round_start(1)
        observer.on_tool_call("bash", {"cmd": "id"}, "uid=0")
        observer.on_round_end(1)
        observer.stop()

        self.assertFalse(observer.enabled)
        self.assertEqual(observer._round_logs, [])

    def test_late_observer_review_cannot_emit_after_stop(self):
        from solver.observer.loop import ObserverLoop

        correction = MagicMock()
        observer = ObserverLoop(
            settings={"solver": {"observer_enabled": True}},
            on_correction=correction,
        )
        observer.stop()
        review = MagicMock(
            side_effect=lambda **kwargs: kwargs["on_correction"]("late advice")
        )
        with patch("solver.observer.agent.ObserverAgent") as observer_cls, patch.object(
            observer, "_check_progress"
        ) as check_progress:
            observer_cls.return_value.review = review
            path = Path(tempfile.mkdtemp(prefix="observer-late-"))
            observer._run_review([{"round": 3}], path, path)

        correction.assert_not_called()
        check_progress.assert_not_called()

    @patch("solver.observer.agent.OpenAI")
    def test_observer_has_separate_bounded_budget(self, _mock_openai):
        from solver.observer.agent import ObserverAgent

        observer = ObserverAgent(settings={"llm": {}})

        self.assertEqual(observer._reasoning_effort, "medium")
        self.assertFalse(observer._thinking_enabled)
        self.assertEqual(observer._max_output_tokens, 8192)
        self.assertEqual(observer._max_react_rounds, 2)


class ObserverPromptTests(unittest.TestCase):
    def test_used_memory_is_not_reported_as_wholly_unused(self):
        from shared.data.memory import add_memory
        from solver.observer.agent import _build_observer_prompt

        challenge_dir = Path(tempfile.mkdtemp(prefix="observer-prompt-"))
        entry = add_memory(
            challenge_dir,
            "fact",
            "current host 10.0.0.1; old host 10.0.0.2 " + "detail " * 1000,
        )
        rounds = [{
            "round": 8,
            "tool_calls": [{
                "tool": "bash",
                "args": {"cmd": "check 10.0.0.1"},
                "result": "ok",
            }],
        }]

        prompt = _build_observer_prompt(rounds, challenge_dir)

        self.assertEqual(prompt.count(entry.id), 1)
        self.assertLess(len(prompt), 4000)

    def test_observer_history_reader_has_character_cap(self):
        from solver.observer.tools import read_file

        path = Path(tempfile.mkdtemp(prefix="observer-history-")) / "history.jsonl"
        path.write_text("x" * 20000 + "TAIL", encoding="utf-8")

        result = read_file({"path": str(path), "limit": 50})

        self.assertIn("仅保留末尾", result)
        self.assertTrue(result.endswith("TAIL"))
        self.assertLess(len(result), 12100)


class ChallengeRoutingTests(unittest.TestCase):
    def test_c_challenge_does_not_treat_port_as_http_proof(self):
        from solver.ctfplatform.policy import infer_challenge_type

        profile = infer_challenge_type("c-03", ("10.0.0.9:3000",))
        self.assertEqual(profile.primary_skill, "pentest")
        self.assertEqual(profile.protocol_hint, "probe")
        self.assertIn("web", profile.candidate_skills)
        self.assertIn("pwn", profile.candidate_skills)

    def test_known_web_prefix_can_still_use_http_hint(self):
        from solver.ctfplatform.policy import infer_challenge_type

        profile = infer_challenge_type("a-03", ("10.0.0.9:80",))
        self.assertEqual(profile.primary_skill, "web")
        self.assertEqual(profile.protocol_hint, "http")


class ControlPolicyTests(unittest.TestCase):
    def test_difficulty_and_challenge_type_share_one_budget_policy(self):
        easy = ControlPolicy.from_settings({"solver": {}}, "easy")
        hard_pentest = ControlPolicy.from_settings(
            {"solver": {}}, "hard", pentest=True
        )
        self.assertEqual(easy.max_rounds, 40)
        self.assertEqual(hard_pentest.max_rounds, 190)
        self.assertEqual(easy.observer_every_rounds, 15)
        self.assertEqual(hard_pentest.observer_every_rounds, 8)
        # hard 多阶段题的 stop_after 必须足够宽，避免侦察阶段就 force_stop
        self.assertEqual(hard_pentest.stop_after, 72)
        self.assertEqual(ControlPolicy.from_settings({"solver": {}}, "hard").stop_after, 48)

    def test_explicit_policy_overrides_are_positive_only(self):
        policy = ControlPolicy.from_settings(
            {"solver": {
                "max_rounds": 7,
                "switch_after_rounds": 3,
                "no_progress_rounds": 5,
                "observer_every_rounds": 2,
            }},
            "medium",
        )
        self.assertEqual(
            (policy.max_rounds, policy.switch_after, policy.stop_after, policy.observer_every_rounds),
            (7, 3, 5, 2),
        )

    def test_same_action_deadloop_stops_deep_lane(self):
        policy = ControlPolicy.from_settings({"solver": {}}, "hard")
        # deep lane、同一条命令连续重复 6 次 → 立即判停，不等 idle
        d = policy.decide(
            round_num=100, last_progress_round=98, lane="deep",
            same_action_streak=6,
        )
        self.assertEqual(d.action, "stop")
        self.assertEqual(d.reason, "same_action_deadloop")

    def test_same_action_deadloop_does_not_stop_easy(self):
        policy = ControlPolicy.from_settings({"solver": {}}, "easy")
        d = policy.decide(
            round_num=100, last_progress_round=0, lane="deep",
            same_action_streak=11,
        )
        self.assertEqual(d.action, "continue")

    def test_low_same_action_streak_continues(self):
        policy = ControlPolicy.from_settings({"solver": {}}, "hard")
        d = policy.decide(
            round_num=100, last_progress_round=98, lane="deep",
            same_action_streak=5,
        )
        self.assertEqual(d.action, "continue")

    def test_time_budget_defaults_scale_with_difficulty_and_type(self):
        self.assertEqual(
            ControlPolicy.from_settings({"solver": {}}, "easy").time_budget_seconds,
            600,
        )
        self.assertEqual(
            ControlPolicy.from_settings({"solver": {}}, "hard").time_budget_seconds,
            1800,
        )
        # hard 多阶段渗透 = 基础 1800 + pentest 900 + ctype 600。
        hard_pentest_ctype = ControlPolicy.from_settings(
            {"solver": {}}, "hard", pentest=True, ctype=True
        )
        self.assertEqual(hard_pentest_ctype.time_budget_seconds, 3300)

    def test_time_budget_exhausted_stops_even_easy(self):
        # 墙钟止损是与 idle/难度正交的硬安全阀：即使 easy 有新进展也照停。
        policy = ControlPolicy.from_settings({"solver": {}}, "easy")
        d = policy.decide(
            round_num=5, last_progress_round=5, lane="fast",
            elapsed_seconds=policy.time_budget_seconds + 1,
        )
        self.assertEqual(d.action, "stop")
        self.assertEqual(d.reason, "time_budget_exhausted")
        self.assertEqual(d.failure_scope, "task_exhausted")

    def test_under_time_budget_does_not_stop(self):
        policy = ControlPolicy.from_settings({"solver": {}}, "easy")
        d = policy.decide(
            round_num=5, last_progress_round=5, lane="fast",
            elapsed_seconds=10,
        )
        self.assertEqual(d.action, "continue")

    def test_time_budget_can_be_disabled(self):
        policy = ControlPolicy.from_settings(
            {"solver": {"time_budget_seconds": 0}}, "easy"
        )
        self.assertEqual(policy.time_budget_seconds, 0.0)
        d = policy.decide(
            round_num=5, last_progress_round=5, lane="fast",
            elapsed_seconds=10_000,
        )
        self.assertEqual(d.action, "continue")

    def test_time_budget_explicit_override(self):
        policy = ControlPolicy.from_settings(
            {"solver": {"time_budget_seconds": 42}}, "hard"
        )
        self.assertEqual(policy.time_budget_seconds, 42)

    def test_soft_time_warning_point(self):
        policy = ControlPolicy.from_settings({"solver": {}}, "medium")
        # 默认 0.75 * 1200 = 900s。
        self.assertEqual(policy.soft_time_warning_seconds(), 900)
        disabled = ControlPolicy.from_settings(
            {"solver": {"time_soft_warn_fraction": 0}}, "medium"
        )
        self.assertEqual(disabled.soft_time_warning_seconds(), 0.0)


class ExploitReuseNoteTests(unittest.TestCase):
    """skill_load 命中含 CVE 的 reference → 生成"回看逐字复制"提醒（对抗知识可达性丢失）。"""

    def test_cve_reference_produces_reuse_note(self):
        from solver.agent import SolverAgent
        note = SolverAgent._exploit_reuse_note(
            "skill_load",
            {"name": "web", "resource": "product-playbooks.md"},
            "... React2Shell CVE-2025-55182 ... payload ...",
        )
        self.assertIsNotNone(note)
        self.assertIn("CVE-2025-55182", note)
        self.assertIn("逐字复制", note)
        self.assertIn("scanner", note)

    def test_non_skill_load_or_no_cve_returns_none(self):
        from solver.agent import SolverAgent
        # 非 skill_load
        self.assertIsNone(
            SolverAgent._exploit_reuse_note("bash", {}, "CVE-2024-27348")
        )
        # 无 resource（只加载了入口 index，不钉）
        self.assertIsNone(
            SolverAgent._exploit_reuse_note("skill_load", {"name": "web"}, "CVE-2024-27348")
        )
        # 内容不含 CVE
        self.assertIsNone(
            SolverAgent._exploit_reuse_note(
                "skill_load", {"name": "web", "resource": "sqli.md"}, "no cve here"
            )
        )

    def test_multiple_cves_deduped_and_capped(self):
        from solver.agent import SolverAgent
        result = ("CVE-2024-27348 CVE-2024-27348 CVE-2025-1001 CVE-2025-1002 "
                  "CVE-2025-1003 CVE-2025-1004 CVE-2025-1005")
        note = SolverAgent._exploit_reuse_note(
            "skill_load", {"name": "web", "resource": "graph-db.md"}, result
        )
        self.assertIsNotNone(note)
        # 去重后首个只出现一次，且最多列 4 个 + 省略号
        self.assertEqual(note.count("CVE-2024-27348"), 1)
        self.assertIn("…", note)


class DifficultyMaxRoundsTests(unittest.TestCase):
    """P0: max_rounds 按难度分级"""

    @patch("solver.agent.ObserverLoop")
    @patch("solver.agent.OpenAI")
    @patch("solver.agent.search_tool")
    def test_easy_gets_40_rounds(self, mock_search, mock_openai, mock_observer):
        from solver.agent import SolverAgent
        task = "# CTF 题目：a-05\n- 难度：easy\n- 目标地址：http://10.0.1.1"
        settings = {"llm": {"base_url": "http://x", "api_key": "k"}}
        agent = SolverAgent(task=task, settings=settings, skills_dir="/skills")
        self.assertEqual(agent.max_rounds, 40)
        self.assertEqual(agent._context_window_tokens, 1_000_000)
        self.assertEqual(
            agent._context_window_tokens - agent._reserve_tokens,
            967_232,
        )
        self.assertEqual(agent._max_output_tokens, 8_192)
        # 早期无卡死 → easy 默认拒绝 hint
        agent.round = 5
        agent._last_discovery_round = 5
        self.assertIn("easy 题默认不查看提示", agent._tool_gate("challenge_get_hint", {}))
        # 卡死（连续无发现 15 轮）→ easy 兜底解锁，不再拒绝
        agent.round = 20
        agent._last_discovery_round = 5
        self.assertNotIn(
            "easy 题默认不查看提示",
            agent._tool_gate("challenge_get_hint", {}),
        )
        # easy 早期禁止 security_search
        agent.round = 5
        agent._last_discovery_round = 5
        self.assertIn(
            "security_search",
            agent._tool_gate("security_search", {"query": "x"}),
        )

    @patch("solver.agent.ObserverLoop")
    @patch("solver.agent.OpenAI")
    @patch("solver.agent.search_tool")
    def test_c_medium_starts_fast_lane(self, mock_search, mock_openai, mock_observer):
        from solver.agent import SolverAgent
        task = "# CTF 题目：c-08\n- 难度：medium\n- 目标地址：http://10.0.1.1"
        settings = {"llm": {"base_url": "http://x", "api_key": "k"}}
        agent = SolverAgent(task=task, settings=settings, skills_dir="/skills")
        self.assertEqual(agent._lane, "fast")
        self.assertGreater(agent.max_rounds, 70)  # c-type extra budget

    @patch("solver.agent.ObserverLoop")
    @patch("solver.agent.OpenAI")
    @patch("solver.agent.search_tool")
    def test_medium_gets_70_rounds(self, mock_search, mock_openai, mock_observer):
        from solver.agent import SolverAgent
        task = "# CTF 题目：a-03\n- 难度：medium\n- 目标地址：http://10.0.1.1"
        settings = {"llm": {"base_url": "http://x", "api_key": "k"}}
        agent = SolverAgent(task=task, settings=settings, skills_dir="/skills")
        self.assertEqual(agent.max_rounds, 70)

    @patch("solver.agent.ObserverLoop")
    @patch("solver.agent.OpenAI")
    @patch("solver.agent.search_tool")
    def test_multi_flag_task_widens_auto_submit_limit(self, mock_search, mock_openai, mock_observer):
        from solver.agent import SolverAgent
        task = (
            "# CTF 题目：b-02\n- 难度：hard\n- 目标地址：http://10.0.1.1\n"
            "- ⚠️ 本题包含 6 个 Flag（多阶段渗透题）"
        )
        settings = {"llm": {"base_url": "http://x", "api_key": "k"}}
        agent = SolverAgent(task=task, settings=settings, skills_dir="/skills")
        self.assertEqual(agent._auto_submit_limit, 6)

    @patch("solver.agent.ObserverLoop")
    @patch("solver.agent.OpenAI")
    @patch("solver.agent.search_tool")
    def test_hint_min_round_scales_with_difficulty(self, mock_search, mock_openai, mock_observer):
        from solver.agent import SolverAgent

        def make(difficulty):
            task = f"# CTF 题目：a-01\n- 难度：{difficulty}\n- 目标地址：http://10.0.1.1"
            settings = {"llm": {"base_url": "http://x", "api_key": "k"}}
            return SolverAgent(task=task, settings=settings, skills_dir="/skills")

        self.assertEqual(make("easy")._hint_min_round, 8)
        self.assertEqual(make("medium")._hint_min_round, 8)
        self.assertEqual(make("hard")._hint_min_round, 6)
        self.assertEqual(make("difficult")._hint_min_round, 6)

    @patch("solver.agent.ObserverLoop")
    @patch("solver.agent.OpenAI")
    @patch("solver.agent.search_tool")
    def test_explicit_hint_min_round_overrides_difficulty(self, mock_search, mock_openai, mock_observer):
        from solver.agent import SolverAgent
        task = "# CTF 题目：a-13\n- 难度：hard\n- 目标地址：http://10.0.1.1"
        settings = {
            "llm": {"base_url": "http://x", "api_key": "k"},
            "solver": {"hint_min_round": 15},
        }
        agent = SolverAgent(task=task, settings=settings, skills_dir="/skills")
        self.assertEqual(agent._hint_min_round, 15)

    @patch("solver.agent.ObserverLoop")
    @patch("solver.agent.OpenAI")
    @patch("solver.agent.search_tool")
    def test_hard_gets_110_rounds(self, mock_search, mock_openai, mock_observer):
        from solver.agent import SolverAgent
        task = "# CTF 题目：a-13\n- 难度：hard\n- 目标地址：http://10.0.1.1"
        settings = {"llm": {"base_url": "http://x", "api_key": "k"}}
        agent = SolverAgent(task=task, settings=settings, skills_dir="/skills")
        self.assertEqual(agent.max_rounds, 110)

    @patch("solver.agent.ObserverLoop")
    @patch("solver.agent.OpenAI")
    @patch("solver.agent.search_tool")
    def test_unknown_difficulty_defaults_to_100(self, mock_search, mock_openai, mock_observer):
        from solver.agent import SolverAgent
        task = "# CTF 题目：a-99\n- 目标地址：http://10.0.1.1"
        settings = {"llm": {"base_url": "http://x", "api_key": "k"}}
        agent = SolverAgent(task=task, settings=settings, skills_dir="/skills")
        self.assertEqual(agent.max_rounds, 100)

    @patch("solver.agent.ObserverLoop")
    @patch("solver.agent.OpenAI")
    @patch("solver.agent.search_tool")
    def test_settings_override_still_works(self, mock_search, mock_openai, mock_observer):
        """settings.solver.max_rounds 显式设置时应该覆盖难度默认值"""
        from solver.agent import SolverAgent
        task = "# CTF 题目：a-05\n- 难度：easy\n- 目标地址：http://10.0.1.1"
        settings = {"llm": {"base_url": "http://x", "api_key": "k"}, "solver": {"max_rounds": 50}}
        agent = SolverAgent(task=task, settings=settings, skills_dir="/skills")
        self.assertEqual(agent.max_rounds, 50)


class PathTraversalDedupTests(unittest.TestCase):
    """P1: 方向循环检测升级——path traversal 目标不同时是不同 approach"""

    def test_different_traversal_targets_are_different(self):
        p1 = _extract_url_pattern("curl 'http://host/download.php?id=../config.php'")
        p2 = _extract_url_pattern("curl 'http://host/download.php?id=../../../etc/passwd'")
        self.assertNotEqual(p1, p2)

    def test_same_traversal_target_different_depth_is_same(self):
        p1 = _extract_url_pattern("curl 'http://host/download.php?id=../etc/passwd'")
        p2 = _extract_url_pattern("curl 'http://host/download.php?id=../../etc/passwd'")
        self.assertEqual(p1, p2)

    def test_non_traversal_params_still_deduped(self):
        p1 = _extract_url_pattern("curl 'http://host/api?user=admin&pass=123'")
        p2 = _extract_url_pattern("curl 'http://host/api?user=guest&pass=456'")
        self.assertEqual(p1, p2)

    def test_traversal_to_proc(self):
        p1 = _extract_url_pattern("curl 'http://host/download.php?id=../../proc/self/environ'")
        p2 = _extract_url_pattern("curl 'http://host/download.php?id=../config.php'")
        self.assertNotEqual(p1, p2)

    def test_absolute_etc_path(self):
        """=/etc/passwd should be recognized as traversal-like"""
        p = _extract_url_pattern("curl 'http://host/download.php?id=/etc/passwd'")
        self.assertIsNotNone(p)


class BashAttemptBudgetTests(unittest.TestCase):
    def test_counts_values_hidden_in_http_loop(self):
        cmd = "for value in one two three four; do curl -s http://example.invalid/$value; done"
        self.assertEqual(_inline_http_variant_count(cmd), 4)

    @patch("solver.tools.bash_tool.subprocess.run")
    def test_blocks_oversized_http_variant_loop(self, run):
        from solver.tools.bash_tool import execute
        from solver.worker_context import RunContext, ctx

        base = tempfile.mkdtemp(prefix="bash-budget-")
        context = RunContext.create(base, "case")
        # 值爆破：循环变量注入固定端点的查询值 = wordlist 攻击，拦。
        cmd = "for v in one two three four; do curl -s 'http://example.invalid/x?id=$v'; done"
        with ctx.bind(context):
            result = execute({"cmd": cmd})

        self.assertIn("[阻止]", result)
        run.assert_not_called()

    @patch("solver.tools.bash_tool.subprocess.run")
    def test_recon_loop_over_distinct_pages_allowed(self, run):
        """侦察循环（打不同页面/端口）不是值爆破，不应被当作 wordlist 拦截（b-02/b-03 根因）。"""
        run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
        base = tempfile.mkdtemp(prefix="bash-budget-")
        context = RunContext.create(base, "b-03")
        with ctx.bind(context):
            from solver.tools.bash_tool import execute
            result = execute({"cmd": (
                "for p in robots.txt about.php news.php contact.php admin/login.php; "
                "do curl -s http://target/$p; done"
            )})
        self.assertNotIn("[阻止]", result)

    @patch("solver.tools.bash_tool.subprocess.run")
    def test_cross_turn_single_requests_allowed_until_threshold(self, run):
        """跨轮单发的自适应探测放宽到 12（正经简单题也可能需 4~5 次同结构探测）。"""
        from solver.tools.bash_tool import execute
        from solver.worker_context import RunContext, ctx

        run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
        base = tempfile.mkdtemp(prefix="bash-budget-")
        context = RunContext.create(base, "case")
        with ctx.bind(context):
            # 前 12 次单发（含第 4~5 次）都不被硬封，只会在第 3 次起软提醒。
            for value in range(12):
                self.assertNotIn(
                    "[阻止]",
                    execute({"cmd": f"curl -s http://example.invalid/item?id={value}"}),
                )
            # 第 13 次超过兜底阈值才硬封。
            result = execute({"cmd": "curl -s http://example.invalid/item?id=13"})
        self.assertIn("[阻止]", result)
        self.assertEqual(run.call_count, 12)

    @patch("solver.tools.bash_tool.subprocess.run")
    def test_inline_loop_wordlist_blocked_immediately(self, run):
        """把字典塞进一条 shell 循环（≥ 4 变体）= 爆破向量，第一条就拦。"""
        from solver.tools.bash_tool import execute
        from solver.worker_context import RunContext, ctx

        run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
        base = tempfile.mkdtemp(prefix="bash-budget-")
        context = RunContext.create(base, "case")
        with ctx.bind(context):
            result = execute({"cmd": (
                "for p in a b c d e; do curl -s http://target/login?p=$p; done"
            )})
        self.assertIn("[阻止]", result)
        run.assert_not_called()

    @patch("solver.tools.bash_tool.subprocess.run")
    def test_scoring_endpoint_is_not_blocked_at_fourth(self, run):
        """打分/提交型端点（/check /submit …）的迭代提交不能在第 3 次封死。"""
        from solver.tools.bash_tool import execute
        from solver.worker_context import RunContext, ctx

        run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
        base = tempfile.mkdtemp(prefix="bash-budget-")
        context = RunContext.create(base, "case")
        with ctx.bind(context):
            for value in range(6):
                self.assertNotIn(
                    "[阻止]",
                    execute({"cmd": f"curl -s http://example.invalid/check?v={value}"}),
                )
        self.assertEqual(run.call_count, 6)

    @patch("solver.tools.bash_tool.subprocess.run")
    def test_evasion_challenge_exempts_repeated_submissions(self, run):
        """e3 检测对抗题：反复提交代码给评分器是解法本身，不按暴力破解封锁。"""
        from solver.tools.bash_tool import execute
        from solver.worker_context import RunContext, ctx

        run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
        base = tempfile.mkdtemp(prefix="bash-budget-")
        context = RunContext.create(base, "e3-04")
        with ctx.bind(context):
            for value in range(6):
                self.assertNotIn(
                    "[阻止]",
                    execute({"cmd": f"curl -s http://target/anything?v={value}"}),
                )
        self.assertEqual(run.call_count, 6)

    @patch("solver.tools.bash_tool.subprocess.run")
    def test_blind_injection_extraction_is_not_blocked(self, run):
        """盲注 / LFI 需要对同一端点发多次自适应请求，不能在第 3 次封死。"""
        from solver.tools.bash_tool import execute
        from solver.worker_context import RunContext, ctx

        run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
        base = tempfile.mkdtemp(prefix="bash-budget-")
        context = RunContext.create(base, "a-14")
        with ctx.bind(context):
            for i in range(1, 7):
                self.assertNotIn(
                    "[阻止]",
                    execute({"cmd": (
                        "curl -s 'http://target/news.php?id=1 AND "
                        f"SUBSTRING(user(),{i},1)=0x61'"
                    )}),
                )
        self.assertEqual(run.call_count, 6)

    @patch("solver.tools.bash_tool.subprocess.run")
    def test_lfi_reading_many_files_is_not_blocked(self, run):
        """多阶段题靠 LFI 读源码/配置/多个 flag，读第 4+ 个文件不能被封（b-01 根因）。"""
        from solver.tools.bash_tool import execute
        from solver.worker_context import RunContext, ctx

        run.return_value = MagicMock(stdout="root:x:0:0", stderr="", returncode=0)
        base = tempfile.mkdtemp(prefix="bash-budget-")
        context = RunContext.create(base, "b-01")
        files = [
            "etc/passwd", "proc/self/cmdline", "var/www/html/config.php",
            "app/flag1.txt", "app/flag2.txt", "var/www/html/db.php",
        ]
        with ctx.bind(context):
            for path in files:
                cmd = f"curl -s 'http://target/services.php?lang=....//....//{path}'"
                self.assertNotIn("[阻止]", execute({"cmd": cmd}), path)
        self.assertEqual(run.call_count, len(files))

    @patch("solver.tools.bash_tool.subprocess.run")
    def test_ssrf_internal_enumeration_is_not_blocked(self, run):
        """SSRF 端点（/api/import 等）的内网枚举不能在第 3 次封死（a-14 根因）。"""
        from solver.tools.bash_tool import execute
        from solver.worker_context import RunContext, ctx

        run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
        base = tempfile.mkdtemp(prefix="bash-budget-")
        context = RunContext.create(base, "a-14")
        internal = ["10.0.255.53", "127.0.0.1:5000", "192.168.0.1", "169.254.169.254"]
        with ctx.bind(context):
            for i, host in enumerate(internal + internal):
                self.assertNotIn(
                    "[阻止]",
                    execute({"cmd": (
                        "curl -s http://target/api/import "
                        f"-d '{{\"url\":\"http://{host}/\"}}'"
                    )}),
                )
        self.assertEqual(run.call_count, 8)

    @patch("solver.tools.bash_tool.subprocess.run")
    def test_login_bruteforce_loop_still_blocked(self, run):
        """登录爆破的真正向量是字典循环，仍被即时拦截。"""
        from solver.tools.bash_tool import execute
        from solver.worker_context import RunContext, ctx

        run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
        base = tempfile.mkdtemp(prefix="bash-budget-")
        context = RunContext.create(base, "a-01")
        with ctx.bind(context):
            result = execute({"cmd": (
                "for p in 111111 222222 333333 444444; do "
                "curl -s \"http://target/login?u=admin&p=$p\"; done"
            )})
        self.assertIn("[阻止]", result)
        run.assert_not_called()


class ExtractDifficultyTests(unittest.TestCase):
    """SolverAgent._extract_difficulty()"""

    def test_extracts_easy(self):
        from solver.agent import SolverAgent
        self.assertEqual(SolverAgent._extract_difficulty("- 难度：easy\n"), "easy")

    def test_extracts_hard(self):
        from solver.agent import SolverAgent
        self.assertEqual(SolverAgent._extract_difficulty("- 难度：hard\n"), "hard")

    def test_case_insensitive(self):
        from solver.agent import SolverAgent
        self.assertEqual(SolverAgent._extract_difficulty("- 难度：MEDIUM\n"), "medium")

    def test_no_difficulty_returns_empty(self):
        from solver.agent import SolverAgent
        self.assertEqual(SolverAgent._extract_difficulty("no difficulty here"), "")


class AutoSubmitSafetyTests(unittest.TestCase):
    @patch("solver.agent.bridge_tools.submit_flag")
    def test_rejects_flag_echoed_by_password_script(self, submit_flag):
        """A dictionary result must not turn a failed password into a flag."""
        from solver.agent import SolverAgent

        agent = SolverAgent.__new__(SolverAgent)
        agent._auto_submit_count = 0
        output = (
            "⚡ 发现疑似 flag：['flag{candidate123}']\n"
            "[0] admin/flag{candidate123} => nope\n"
        )

        self.assertEqual(
            agent._auto_submit_flags(
                output,
                tool_name="bash",
                tool_args={"cmd": "./try-passwords.sh"},
            ),
            "",
        )
        submit_flag.assert_not_called()

    @patch("solver.agent.bridge_tools.submit_flag")
    def test_marker_without_visible_source_line_is_not_evidence(self, submit_flag):
        from solver.agent import SolverAgent

        agent = SolverAgent.__new__(SolverAgent)
        agent._auto_submit_count = 0
        marker_only = "⚡ 发现疑似 flag：['flag{truncated123}']"

        self.assertEqual(agent._auto_submit_flags(marker_only, "bash", {}), "")
        submit_flag.assert_not_called()


class AutoExtractTests(unittest.TestCase):
    def test_extracts_flag_format(self):
        from solver.tools.bash_tool import _auto_extract
        result = _auto_extract("some output flag{test_flag_123} more text")
        self.assertIn("flag{test_flag_123}", result)
        self.assertIn("发现疑似 flag", result)

    def test_css_is_not_flagged_as_flag(self):
        # run c-03 回归：404 页里的 CSS body{...}/h1{...} 不能被误报成 flag
        from solver.tools.bash_tool import _auto_extract
        css = "body{color:#000;background:#fff;margin:0}h1{border-right:1px solid #000}"
        result = _auto_extract(css)
        self.assertNotIn("发现疑似 flag", result)

    def test_ctf_prefix_flag_still_detected(self):
        from solver.tools.bash_tool import _auto_extract
        result = _auto_extract("here is CTF{abcd_efgh}")
        self.assertIn("发现疑似 flag", result)

    def test_extracts_credentials(self):
        from solver.tools.bash_tool import _auto_extract
        result = _auto_extract('DB_PASS="config_password = s3cret123"\ntoken=abc')
        self.assertIn("凭据", result)

    def test_passwd_status_scan_is_not_credential(self):
        # b-02 回归：路径探测把 /etc/passwd: 200 误报成凭据 ['200']
        from solver.tools.bash_tool import _auto_extract
        scan = (
            "### OA .git & common files ###\n"
            "/.git/HEAD: 200 len=153 | <html>\n"
            "/etc/passwd: 200 len=153 | <html>\n"
            "/.git/HEAD/../../etc/passwd: 200 len=153\n"
            "/.GIT/HEAD: 403 len=153\n"
        )
        result = _auto_extract(scan)
        self.assertNotIn("凭据", result)
        self.assertNotIn("['200']", result)
        self.assertNotIn("发现疑似凭据", result)

    def test_mid_dump_credentials_survive_full_extract(self):
        from solver.tools.bash_tool import _auto_extract
        mid = ("noise\n" * 400) + "mysql_password=KeepMeAlive42\n" + ("tail\n" * 400)
        result = _auto_extract(mid)
        self.assertIn("KeepMeAlive42", result)
        self.assertIn("凭据", result)

    def test_http_status_token_value_rejected(self):
        from solver.tools.bash_tool import _auto_extract
        result = _auto_extract("auth token: 401\nsecret: 403")
        self.assertNotIn("凭据", result)

    def test_extracts_internal_ip(self):
        from solver.tools.bash_tool import _auto_extract
        result = _auto_extract("inet 172.18.0.3/16 brd 172.18.255.255")
        self.assertIn("172.18.0.3", result)
        self.assertIn("内网", result)

    def test_detects_middleware(self):
        from solver.tools.bash_tool import _auto_extract
        result = _auto_extract("Server: GeoServer 2.23.1")
        self.assertIn("geoserver", result)
        self.assertIn("CVE", result)

    def test_cve_hint_deduped_within_attempt(self):
        import json
        from pathlib import Path
        from solver.tools import knowledge_router
        from solver.tools.bash_tool import _auto_extract
        from solver.worker_context import RunContext, ctx

        tmp = tempfile.mkdtemp(prefix="cve-dedup-")
        Path(tmp).joinpath("cve-cheatsheet.json").write_text(
            json.dumps({
                "middleware": {
                    "GeoServer": {
                        "cves": ["CVE-2024-36401"],
                        "match": {"body_any": ["geoserver"]},
                    }
                }
            }),
            encoding="utf-8",
        )
        old = os.environ.get("CTF_SKILLS_DIR")
        os.environ["CTF_SKILLS_DIR"] = tmp
        knowledge_router._CACHE = None
        try:
            base = tempfile.mkdtemp(prefix="cve-dedup-ws-")
            context = RunContext.create(base, "case", target_url="http://10.0.1.1:80")
            with ctx.bind(context):
                first = _auto_extract("Server: GeoServer 2.23.1")
                second = _auto_extract("Server: GeoServer 2.23.1 again")
            self.assertIn("本地利用条目", first)
            self.assertNotIn("本地利用条目", second)
        finally:
            knowledge_router._CACHE = None
            if old is None:
                os.environ.pop("CTF_SKILLS_DIR", None)
            else:
                os.environ["CTF_SKILLS_DIR"] = old

    def test_no_findings_returns_empty(self):
        from solver.tools.bash_tool import _auto_extract
        result = _auto_extract("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n")
        self.assertEqual(result, "")

    def test_ignores_error_output(self):
        from solver.tools.bash_tool import _auto_extract
        result = _auto_extract("[错误] 命令执行异常")
        self.assertEqual(result, "")

    def test_filters_vpn_gateway_ip(self):
        from solver.tools.bash_tool import _auto_extract
        result = _auto_extract("route via 10.0.100.1 dev tun0")
        # VPN 网关 10.0.100.x 应被过滤
        self.assertNotIn("内网", result)

    def test_configured_target_is_not_reported_as_lateral_host(self):
        from solver.tools.bash_tool import _auto_extract
        from solver.worker_context import RunContext, ctx

        base = tempfile.mkdtemp(prefix="auto-extract-")
        context = RunContext.create(base, "case", target_url="http://10.0.1.1:80")
        with ctx.bind(context):
            result = _auto_extract("request to 10.0.1.1 completed")

        self.assertNotIn("内网", result)

    def test_target_ip_does_not_trigger_phase_transition(self):
        from solver.agent import SolverAgent

        agent = SolverAgent.__new__(SolverAgent)
        agent._phase = "INITIAL_ACCESS"
        agent._got_shell = True
        agent._target_url = "http://10.0.1.1:80"
        agent._found_internal_ips = set()
        agent._pending_injections = []
        agent._injection_lock = threading.Lock()

        agent._detect_phase_transition(
            "bash", {"cmd": "curl http://10.0.1.1"}, "connected to 10.0.1.1"
        )

        self.assertEqual(agent._phase, "INITIAL_ACCESS")
        self.assertEqual(agent._found_internal_ips, set())


class RotatedHostMemoryTests(unittest.TestCase):
    def test_marks_same_subnet_old_ip(self):
        from solver.tools.memory_tools import _rotated_host_note

        note = _rotated_host_note(
            "端口 10.0.169.98:7860 是 FastAPI/uvicorn",
            "10.0.169.97",
        )
        self.assertIn("疑似旧实例", note)
        self.assertIn("10.0.169.97", note)
        self.assertIn("10.0.169.98", note)

    def test_same_ip_is_not_stale(self):
        from solver.tools.memory_tools import _rotated_host_note

        self.assertEqual(
            _rotated_host_note("目标 10.0.169.97:7860 TCP open", "10.0.169.97"),
            "",
        )

    def test_other_subnet_not_flagged(self):
        # 横向移动记录的内网 IP 不应被当成实例轮换
        from solver.tools.memory_tools import _rotated_host_note

        self.assertEqual(
            _rotated_host_note("内网可达 172.18.0.5:22", "10.0.169.97"),
            "",
        )


if __name__ == "__main__":
    unittest.main()
