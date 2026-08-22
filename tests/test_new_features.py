"""Tests for new features: difficulty-based max_rounds, path traversal dedup, forced review."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from solver.tools.bash_tool import _extract_url_pattern, _inline_http_variant_count
from solver.runtime.control import ControlPolicy


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

    @patch("solver.observer.agent.OpenAI")
    def test_observer_has_separate_bounded_budget(self, _mock_openai):
        from solver.observer.agent import ObserverAgent

        observer = ObserverAgent(settings={"llm": {}})

        self.assertEqual(observer._reasoning_effort, "high")
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
        self.assertEqual(easy.max_rounds, 30)
        self.assertEqual(hard_pentest.max_rounds, 200)
        self.assertEqual(easy.observer_every_rounds, 15)
        self.assertEqual(hard_pentest.observer_every_rounds, 8)

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


class DifficultyMaxRoundsTests(unittest.TestCase):
    """P0: max_rounds 按难度分级"""

    @patch("solver.agent.ObserverLoop")
    @patch("solver.agent.OpenAI")
    @patch("solver.agent.search_tool")
    def test_easy_gets_30_rounds(self, mock_search, mock_openai, mock_observer):
        from solver.agent import SolverAgent
        task = "# CTF 题目：a-05\n- 难度：easy\n- 目标地址：http://10.0.1.1"
        settings = {"llm": {"base_url": "http://x", "api_key": "k"}}
        agent = SolverAgent(task=task, settings=settings, skills_dir="/skills")
        self.assertEqual(agent.max_rounds, 30)
        self.assertEqual(agent._context_window_tokens, 1_000_000)
        self.assertEqual(
            agent._context_window_tokens - agent._reserve_tokens,
            967_232,
        )
        self.assertEqual(agent._max_output_tokens, 8_192)

    @patch("solver.agent.ObserverLoop")
    @patch("solver.agent.OpenAI")
    @patch("solver.agent.search_tool")
    def test_medium_gets_60_rounds(self, mock_search, mock_openai, mock_observer):
        from solver.agent import SolverAgent
        task = "# CTF 题目：a-03\n- 难度：medium\n- 目标地址：http://10.0.1.1"
        settings = {"llm": {"base_url": "http://x", "api_key": "k"}}
        agent = SolverAgent(task=task, settings=settings, skills_dir="/skills")
        self.assertEqual(agent.max_rounds, 60)

    @patch("solver.agent.ObserverLoop")
    @patch("solver.agent.OpenAI")
    @patch("solver.agent.search_tool")
    def test_hard_gets_120_rounds(self, mock_search, mock_openai, mock_observer):
        from solver.agent import SolverAgent
        task = "# CTF 题目：a-13\n- 难度：hard\n- 目标地址：http://10.0.1.1"
        settings = {"llm": {"base_url": "http://x", "api_key": "k"}}
        agent = SolverAgent(task=task, settings=settings, skills_dir="/skills")
        self.assertEqual(agent.max_rounds, 120)

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
        cmd = "for value in one two three four; do curl -s http://example.invalid/$value; done"
        with ctx.bind(context):
            result = execute({"cmd": cmd})

        self.assertIn("[阻止]", result)
        run.assert_not_called()

    @patch("solver.tools.bash_tool.subprocess.run")
    def test_blocks_fourth_matching_request(self, run):
        from solver.tools.bash_tool import execute
        from solver.worker_context import RunContext, ctx

        run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
        base = tempfile.mkdtemp(prefix="bash-budget-")
        context = RunContext.create(base, "case")
        with ctx.bind(context):
            for value in ("one", "two", "three"):
                self.assertNotIn(
                    "[阻止]", execute({"cmd": f"curl -s http://example.invalid/check?v={value}"})
                )
            result = execute({"cmd": "curl -s http://example.invalid/check?v=four"})

        self.assertIn("[阻止]", result)
        self.assertEqual(run.call_count, 3)


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

    def test_extracts_credentials(self):
        from solver.tools.bash_tool import _auto_extract
        result = _auto_extract('DB_PASS="config_password = s3cret123"\ntoken=abc')
        self.assertIn("凭据", result)

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


if __name__ == "__main__":
    unittest.main()
