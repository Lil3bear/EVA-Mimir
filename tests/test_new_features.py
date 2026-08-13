"""Tests for new features: difficulty-based max_rounds, path traversal dedup, forced review."""
import unittest
from unittest.mock import MagicMock, patch
from collections import Counter

from solver.tools.bash_tool import _extract_url_pattern


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
    def test_hard_gets_100_rounds(self, mock_search, mock_openai, mock_observer):
        from solver.agent import SolverAgent
        task = "# CTF 题目：a-13\n- 难度：hard\n- 目标地址：http://10.0.1.1"
        settings = {"llm": {"base_url": "http://x", "api_key": "k"}}
        agent = SolverAgent(task=task, settings=settings, skills_dir="/skills")
        self.assertEqual(agent.max_rounds, 100)

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


if __name__ == "__main__":
    unittest.main()
