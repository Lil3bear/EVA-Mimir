"""Tests for mandatory skill-chain closure."""

from __future__ import annotations

import unittest

from solver.tools.skill_chain import (
    SkillChainTracker,
    chains_from_bash,
    chains_from_description,
)


class SkillChainTests(unittest.TestCase):
    def test_description_seeds_pydash_and_evasion(self):
        desc = "利用pydash库的原型链污染漏洞，Cookie八进制编码绕过"
        found = chains_from_description(desc)
        self.assertIn("pydash", found)

        evasion = "注入技术对抗评估，POST /check 检测规则"
        self.assertIn("evasion-check", chains_from_description(evasion))

    def test_bash_flask_session_fingerprint(self):
        out = "HTTP/1.1 500 INTERNAL SERVER ERROR\nServer: gunicorn\n"
        ctx = "curl -s -i http://10.0.0.1/login"
        self.assertIn("flask-session", chains_from_bash(out, ctx))

    def test_gate_blocks_search_until_load(self):
        tracker = SkillChainTracker(pending={"pydash"})
        block = tracker.gate("security_search", {"query": "pydash rce"})
        self.assertIn("[拒绝]", block)
        self.assertIn("prototype-pollution-pydash", block)

        tracker.mark_loaded("web", "prototype-pollution-pydash.md")
        self.assertEqual(tracker.gate("security_search", {"query": "x"}), "")

    def test_gate_blocks_comfyui_view_traversal_and_git_url(self):
        tracker = SkillChainTracker(active={"comfyui"})
        # Traversal blocked before playbook load
        block = tracker.gate(
            "bash",
            {"cmd": "curl -s 'http://10.0.0.1:8188/view?filename=../etc/passwd'"},
        )
        self.assertIn("[拒绝]", block)

        git_block = tracker.gate(
            "bash",
            {"cmd": "curl -s -X POST http://10.0.0.1:8188/api/customnode/install/git_url"},
        )
        self.assertIn("[拒绝]", git_block)
        self.assertIn("git_url", git_block)

        tracker.mark_loaded("web", "product-playbooks.md")
        # After load: flag readback via type=input is allowed; traversal pattern still in patterns but gate off
        self.assertEqual(
            tracker.gate(
                "bash",
                {"cmd": "curl -s 'http://x/view?filename=pwnflag.txt&type=input'"},
            ),
            "",
        )

    def test_gate_allows_comfy_png_block_only_pre_load(self):
        tracker = SkillChainTracker(active={"comfyui"})
        block = tracker.gate(
            "bash",
            {"cmd": "curl -s 'http://10.0.0.1:8188/view?filename=x.png'"},
        )
        self.assertIn("[拒绝]", block)
        tracker.mark_loaded("web", "product-playbooks.md")
        self.assertEqual(
            tracker.gate("bash", {"cmd": "curl /view?filename=x.png"}),
            "",
        )

    def test_pentest_gate_allows_single_login_form(self):
        tracker = SkillChainTracker(active={"pentest-lateral"})
        # Playbook logins must not be hard-blocked.
        self.assertEqual(
            tracker.gate(
                "bash",
                {"cmd": "curl -d 'username=admin&password=1qaz@WSX' http://x/login"},
            ),
            "",
        )
        # Mass brute tools still blocked until playbook loaded.
        block = tracker.gate("bash", {"cmd": "hydra -l admin -P pass.txt ssh://10.0.0.1"})
        self.assertIn("[拒绝]", block)
        tracker.mark_loaded("pentest", "initial-access.md")
        self.assertEqual(
            tracker.gate("bash", {"cmd": "hydra -l admin -P pass.txt ssh://10.0.0.1"}),
            "",
        )

    def test_task_banner_seeds_chains(self):
        task = (
            "# CTF 题目：a-03\n"
            "- 描述：Flask 资产管理系统，/login 返回 500\n"
            "- 📚 Flask 资产系统 → common-vulnerabilities §2.5\n"
        )
        tracker = SkillChainTracker.from_task(task)
        self.assertIn("flask-session", tracker.pending)

    def test_reverse_vm_description_seeds(self):
        found = chains_from_description("自制字节码虚拟机 validator 混淆")
        self.assertIn("reverse-vm", found)
        tracker = SkillChainTracker(pending={"reverse-vm"})
        block = tracker.gate("security_search", {"query": "angr flag"})
        self.assertIn("[拒绝]", block)
        tracker.mark_loaded("reverse", "vm-and-firmware.md")
        self.assertEqual(tracker.gate("security_search", {"query": "x"}), "")


if __name__ == "__main__":
    unittest.main()
