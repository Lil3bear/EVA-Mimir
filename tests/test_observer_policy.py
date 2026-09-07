"""Tests for Observer interference / Memory pollution policy."""

import unittest

from solver.runtime.observer_policy import (
    content_has_truncation,
    correction_allowed,
    memory_write_allowed,
    normalize_observer_mode,
)


class ObserverPolicyTests(unittest.TestCase):
    def test_normalize_mode(self):
        self.assertEqual(normalize_observer_mode(None), "advisory")
        self.assertEqual(normalize_observer_mode("FULL"), "full")
        self.assertEqual(normalize_observer_mode("off"), "off")

    def test_agent_truncation_markers_blocked(self):
        for marker in ("[截断] 原始 9000 字符", "... (省略中间部分) ...", "[输出过长（8327 字节），已截断]"):
            ok, reason = memory_write_allowed(f"{marker}\npassword=x", kind="note")
            self.assertFalse(ok, marker)
            self.assertEqual(reason, "truncated_evidence")

    def test_playbook_dump_blocked(self):
        dump = "必须先 skill_load(name=\"web\", resource=\"x\")\n" + ("步骤细节\n" * 40)
        ok, reason = memory_write_allowed(dump, kind="note")
        self.assertFalse(ok)
        self.assertEqual(reason, "playbook_dump")

    def test_short_fact_allowed(self):
        ok, reason = memory_write_allowed("目标响应 200，login 表单字段 user/pass", kind="fact")
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_short_skill_pin_fact_allowed(self):
        ok, reason = memory_write_allowed(
            "指纹：JWT kid。必须 skill_load(web, jwt-attacks.md) §5。",
            kind="fact",
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_large_fact_playbook_dump_blocked(self):
        dump = "必须先 skill_load(name=\"web\", resource=\"x\")\n" + ("步骤细节\n" * 80)
        ok, reason = memory_write_allowed(dump, kind="fact")
        self.assertFalse(ok)
        self.assertEqual(reason, "playbook_dump")

    def test_advisory_quiet_by_default(self):
        ok, reason = correction_allowed(mode="advisory", decision={"same_action_streak": 1})
        self.assertFalse(ok)
        self.assertEqual(reason, "quiet_default")

    def test_advisory_allows_on_action_streak(self):
        ok, reason = correction_allowed(
            mode="advisory",
            decision={"same_action_streak": 4, "same_vector_streak": 0},
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "same_action_streak")

    def test_skill_chain_blocks_correction(self):
        ok, reason = correction_allowed(
            mode="advisory",
            decision={"same_action_streak": 9},
            skill_chain_open=True,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "skill_chain_open")

    def test_full_mode_always_allows(self):
        ok, reason = correction_allowed(mode="full", decision={})
        self.assertTrue(ok)
        self.assertEqual(reason, "mode_full")


if __name__ == "__main__":
    unittest.main()
