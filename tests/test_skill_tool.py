"""skill_tool 与 knowledge_router 的单元测试。"""

import os
import re
import tempfile
import unittest
from pathlib import Path

from solver.tools import skill_tool, knowledge_router


class SkillToolTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="test-skills-")
        self._old = os.environ.get("CTF_SKILLS_DIR")
        os.environ["CTF_SKILLS_DIR"] = self._tmp
        # 构造最小 skill 目录
        web = Path(self._tmp) / "web"
        refs = web / "references"
        refs.mkdir(parents=True)
        (web / "SKILL.md").write_text(
            "---\nname: web\ndescription: Web 题指南\n---\n# Web\n## 路由\n- 见 references\n",
            encoding="utf-8",
        )
        (refs / "sql.md").write_text("SELECT payload" * 2000, encoding="utf-8")

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CTF_SKILLS_DIR", None)
        else:
            os.environ["CTF_SKILLS_DIR"] = self._old

    def test_list_uses_frontmatter(self):
        out = skill_tool.skill_list({})
        self.assertIn("web", out)
        self.assertIn("Web 题指南", out)
        self.assertIn("sql.md", out)

    def test_load_reference_returns_full_within_limit(self):
        expected = (Path(self._tmp) / "web" / "references" / "sql.md").read_text(
            encoding="utf-8"
        )
        out = skill_tool.skill_load({"name": "web", "resource": "sql.md"})
        self.assertIn("[Skill: web/references/sql.md]", out)
        self.assertIn(expected, out)
        self.assertNotIn("内容过长已截断", out)

    def test_load_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            skill_tool.skill_load({"name": "web", "resource": "../SKILL.md"})

    def test_load_unknown_skill(self):
        out = skill_tool.skill_load({"name": "nope"})
        self.assertIn("不存在", out)


class KnowledgeRouterTests(unittest.TestCase):
    def setUp(self):
        knowledge_router._CACHE = None
        self._tmp = tempfile.mkdtemp(prefix="test-kr-")
        self._old = os.environ.get("CTF_SKILLS_DIR")
        os.environ["CTF_SKILLS_DIR"] = self._tmp
        Path(self._tmp).joinpath("cve-cheatsheet.json").write_text(
            '{"middleware": {"Gradio": {"cves": ["CVE-2024-1561"], '
            '"quick_check": "curl file=../../../etc/passwd", '
            '"search_query": "Gradio CVE"}}}',
            encoding="utf-8",
        )

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CTF_SKILLS_DIR", None)
        else:
            os.environ["CTF_SKILLS_DIR"] = self._old
        knowledge_router._CACHE = None

    def test_gradio_hit(self):
        out = knowledge_router.lookup("<title>Gradio</title>")
        self.assertIn("CVE-2024-1561", out)
        self.assertIn("curl file=", out)

    def test_no_hit(self):
        self.assertEqual(knowledge_router.lookup("normal page"), "")

    def test_nextjs_not_mistaken_for_dify(self):
        # 只有 Gradio 在表里，Next.js 不应命中
        self.assertEqual(knowledge_router.lookup("Next.js app"), "")
        self.assertNotIn(
            "Dify",
            knowledge_router._fingerprint_products(
                "Next.js app", "curl http://target:3000/"
            ),
        )
        self.assertIn(
            "Dify",
            knowledge_router._fingerprint_products(
                "Next.js app", "curl http://target:3000/console/api/"
            ),
        )

    def test_endpoint_context_can_complete_product_fingerprint(self):
        out = knowledge_router.lookup(
            "HTTP/1.1 200 OK\nPython server\n", "curl http://target:8188/api/manager"
        )
        # The local fixture has no ComfyUI entry; this assertion exercises the
        # context path without making a false positive for an unrelated page.
        self.assertEqual(out, "")

    def test_port_alone_is_a_weak_hint_not_a_cve(self):
        path = Path(self._tmp).joinpath("cve-cheatsheet.json")
        path.write_text(
            '{"middleware": {"Apache OFBiz": {"cves": ["CVE-X"], '
            '"match": {"ports": ["8443"]}}}}',
            encoding="utf-8",
        )
        knowledge_router._CACHE = None
        result = knowledge_router.lookup(
            "HTTP/1.1 200 OK\n<html><body>x</body></html>",
            "curl http://target:8443/",
        )
        # 端口弱信号只引导验证，不直接给 CVE。
        self.assertIn("端口弱信号", result)
        self.assertIn("Apache OFBiz", result)
        self.assertNotIn("CVE-X", result)

    def test_port_without_web_response_is_silent(self):
        path = Path(self._tmp).joinpath("cve-cheatsheet.json")
        path.write_text(
            '{"middleware": {"Apache OFBiz": {"cves": ["CVE-X"], '
            '"match": {"ports": ["8443"]}}}}',
            encoding="utf-8",
        )
        knowledge_router._CACHE = None
        self.assertEqual(
            knowledge_router.lookup("Connection refused", "curl http://target:8443/"),
            "",
        )

    def test_match_table_uses_body_and_path_signals(self):
        path = Path(self._tmp).joinpath("cve-cheatsheet.json")
        path.write_text(
            '{"middleware": {"Demo": {"cves": ["CVE-X"], '
            '"match": {"body_any": ["x-demo"], "path_any": ["/special"]}}}}',
            encoding="utf-8",
        )
        knowledge_router._CACHE = None
        self.assertIn("CVE-X", knowledge_router.lookup("x-demo banner"))
        self.assertIn("CVE-X", knowledge_router.lookup("plain", "GET /special HTTP/1.1"))


class RepositorySkillIntegrityTests(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("CTF_SKILLS_DIR")
        self.root = Path(__file__).resolve().parents[1] / "skills"
        os.environ["CTF_SKILLS_DIR"] = str(self.root)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CTF_SKILLS_DIR", None)
        else:
            os.environ["CTF_SKILLS_DIR"] = self._old

    def test_all_references_are_loadable_without_truncation(self):
        skills = skill_tool._list_skills()
        self.assertIn("experiences", {item["name"] for item in skills})
        for item in skills:
            for resource in item["references"]:
                with self.subTest(skill=item["name"], resource=resource):
                    out = skill_tool.skill_load({
                        "name": item["name"],
                        "resource": resource,
                    })
                    self.assertNotIn("[错误]", out)
                    self.assertNotIn("内容过长已截断", out)

    def test_markdown_routes_point_to_existing_references(self):
        for item in skill_tool._list_skills():
            entry = self.root / item["name"] / "SKILL.md"
            mentioned = set(re.findall(r"`([A-Za-z0-9_.-]+\.md)`", entry.read_text()))
            with self.subTest(skill=item["name"]):
                self.assertTrue(mentioned.issubset(set(item["references"])))


if __name__ == "__main__":
    unittest.main()
