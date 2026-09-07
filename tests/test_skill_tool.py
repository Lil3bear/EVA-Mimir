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

    def test_hit_does_not_push_security_search(self):
        # run c-03 回归：命中条目不再注入 security_search（离线无用且带偏），
        # 且 quick_check 只作指纹参考、不作命中判据。
        out = knowledge_router.lookup("<title>Gradio</title>")
        self.assertNotIn("security_search", out)
        self.assertNotIn("补充搜索", out)
        self.assertIn("skill_load", out)

    def test_curl_verbose_echo_is_not_web_response(self):
        # run c-08 回归：curl -sv 在 RST 前会打印 "GET / HTTP/1.1"，
        # 不能据此触发端口弱信号（Gradio@7860 等）。
        verbose_rst = (
            "* Connected to 10.0.169.97 (10.0.169.97) port 7860\n"
            "> GET / HTTP/1.1\n"
            "> Host: 10.0.169.97:7860\n"
            "* Recv failure: Connection reset by peer\n"
        )
        self.assertFalse(knowledge_router._looks_like_web(verbose_rst.lower()))
        self.assertEqual(
            knowledge_router.lookup(verbose_rst, "curl -sv http://10.0.169.97:7860/"),
            "",
        )

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


class SkillRouterTests(unittest.TestCase):
    def test_jwt_kid_routes_to_jwt_attacks(self):
        from solver.tools import skill_router

        out = skill_router.lookup(
            'header={"alg":"HS256","kid":"prod.key"}',
            "python decode jwt",
        )
        self.assertIn("JWT kid", out)
        self.assertIn("jwt-attacks.md", out)

    def test_flask_login_500_routes_to_session_playbook(self):
        from solver.tools import skill_router

        out = skill_router.lookup(
            "HTTP/1.1 500 INTERNAL SERVER ERROR\nServer: gunicorn\n",
            "curl -s -i http://10.0.186.88:80/login",
        )
        self.assertIn("资产管理系统", out)
        self.assertIn("common-vulnerabilities.md", out)
        self.assertIn("SQLi", out)

    def test_langflow_routes_before_gradio(self):
        from solver.tools import skill_router

        out = skill_router.lookup(
            '{"paths":{"/api/v1/webhook/{flow_id_or_name}":{}}}',
            "curl http://10.0.186.88:7860/openapi.json",
        )
        self.assertIn("Langflow", out)
        self.assertNotIn("Gradio 4.x", out)

    def test_comfyui_routes_to_playbook(self):
        from solver.tools import skill_router

        out = skill_router.lookup(
            "ComfyUI",
            "curl http://10.0.1.1:8188/api/manager/version",
        )
        self.assertIn("ComfyUI", out)
        self.assertIn("product-playbooks.md", out)

    def test_target_ip_drift_warning(self):
        from solver.tools import skill_router
        from solver.worker_context import RunContext, ctx

        base = tempfile.mkdtemp(prefix="skill-route-")
        context = RunContext.create(base, "c-08", target_url="http://10.0.181.73:7860")
        with ctx.bind(context):
            out = skill_router.lookup(
                "ok",
                "curl -s http://10.0.181.74:80/login",
            )
        self.assertIn("目标 IP 锁定", out)
        self.assertIn("10.0.181.73", out)

    def test_ssrf_routes_to_playbook(self):
        from solver.tools import skill_router

        out = skill_router.lookup(
            "curl http://127.0.0.1/admin",
            "metadata",
        )
        self.assertIn("SSRF", out)
        self.assertIn("ssrf.md", out)

    def test_check_endpoint_routes_to_evasion(self):
        from solver.tools import skill_router

        out = skill_router.lookup(
            'curl -X POST http://x/check -d "code=..."',
            "triggered 3 rules",
        )
        self.assertIn("检测对抗", out)
        self.assertIn("process-injection-bypass.md", out)

    def test_pydash_routes_to_playbook(self):
        from solver.tools import skill_router

        out = skill_router.lookup(
            "PyDash Pollution Challenge",
            "import pydash\nfrom sanic import Sanic",
        )
        self.assertIn("PyDash", out)
        self.assertIn("prototype-pollution-pydash.md", out)

    def test_engineering_error_oracle_sdist(self):
        from solver.tools import skill_router

        out = skill_router.lookup(
            "ERROR: does not appear to be a Python project: "
            "neither 'setup.py' nor 'pyproject.toml' found",
            "pip install file:///ComfyUI/input/evil.tar.gz",
        )
        self.assertIn("sdist", out)
        self.assertIn("setup.py sdist", out)


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

    def test_product_routes_align_with_reference_content(self):
        """knowledge_router/policy 的产品→reference 映射必须指向含该产品内容的文件。"""
        from solver.tools import knowledge_router

        product_keyword = {
            "Gradio": "gradio",
            "Dify": "dify",
            "HugeGraph": "hugegraph",
            "ComfyUI-Manager": "comfyui",
            "Apache OFBiz": "ofbiz",
            "1Panel": "1panel",
            "GeoServer": "geoserver",
        }
        for product, (skill, resource) in knowledge_router._PRODUCT_ROUTES.items():
            path = self.root / skill / "references" / resource
            with self.subTest(product=product, resource=resource):
                self.assertTrue(path.exists(), f"缺少 {path}")
                content = path.read_text(encoding="utf-8", errors="replace").lower()
                keyword = product_keyword[product]
                self.assertIn(keyword, content, f"{path} 不含 {product} 内容")

    def test_port_hints_align_with_product_content(self):
        from solver.ctfplatform.policy import _PORT_PRODUCT_HINTS

        keyword_by_product = {
            "ComfyUI": "comfyui",
            "Dify": "dify",
            "Gradio": "gradio",
            "OFBiz": "ofbiz",
            "HugeGraph": "hugegraph",
            "1Panel": "1panel",
        }
        for port, hint in _PORT_PRODUCT_HINTS.items():
            for product, keyword in keyword_by_product.items():
                if product.lower() in hint.lower():
                    # 解析 hint 里的 reference 路径
                    match = re.search(
                        r"(web|cloud|pentest|reverse)/([a-z0-9-]+\.md)|product-playbooks",
                        hint,
                    )
                    self.assertIsNotNone(match, f"端口 {port} 的 hint 缺少 reference 路径")
                    if match.group(1):
                        path = self.root / match.group(1) / "references" / match.group(2)
                    else:
                        path = self.root / "web" / "references" / "product-playbooks.md"
                    self.assertTrue(path.exists(), f"缺少 {path}")
                    content = path.read_text(encoding="utf-8", errors="replace").lower()
                    self.assertIn(keyword, content, f"端口 {port} → {path} 不含 {product} 内容")
                    break


if __name__ == "__main__":
    unittest.main()
