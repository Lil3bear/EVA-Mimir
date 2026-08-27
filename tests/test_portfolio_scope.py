"""分层排序 + 差异化协作模式（isolated / shared）的行为锁定测试。

背景（run-12717）：b-* 多阶段渗透占满 3 个槽 41 分钟，一道 500 分的 a-10
在队列里干等。修复目标：
  * 前排 web/易题先拿分，pentest/pwn/reverse 家族整体后置；
  * 前排简单题并行多解但 memory 完全隔离；
  * 后排 b-* 多阶段题多 agent 共享 memory 协作。
"""

import tempfile
import unittest
from pathlib import Path

from solver.ctfplatform.policy import sort_challenges
from solver.ctfplatform.tsecbench_client import Challenge
from solver.runtime.portfolio import challenge_memory_scope, challenge_plan
from solver.runtime.scoped_state import solver_memories, write_root
from shared.data import memory as mem_store


def _ch(code, *, difficulty="easy", total_score=100, flag_count=1,
        correct_flag_count=0):
    return Challenge(
        unique_code=code, description=None, difficulty=difficulty, level=1,
        total_score=total_score, flag_count=flag_count,
        correct_flag_count=correct_flag_count, is_completed=False,
        container_status="running", container_addr=("10.0.0.2:80",),
    )


class LayeredOrderingTests(unittest.TestCase):
    def test_pentest_deferred_behind_web_even_with_higher_score(self):
        """一道高分 b-* 多阶段题必须排在低分 a-* 易题之后。"""
        cheap_web = _ch("a-10", difficulty="easy", total_score=50)
        rich_pentest = _ch("b-01", difficulty="medium", total_score=300,
                           flag_count=4)
        order = [c.unique_code for c in sort_challenges([rich_pentest, cheap_web])]
        self.assertEqual(order, ["a-10", "b-01"])

    def test_pwn_and_reverse_family_sink_to_tail(self):
        codes = ["f1-01", "a-02", "b-03", "c-04"]
        challenges = [_ch(code, difficulty="easy") for code in codes]
        order = [c.unique_code for c in sort_challenges(challenges)]
        # web/misc（a-/c-）在前，pentest（b-）与 pwn（f1-）在后。
        self.assertLess(order.index("a-02"), order.index("b-03"))
        self.assertLess(order.index("c-04"), order.index("f1-01"))

    def test_difficulty_gates_within_family(self):
        challenges = [
            _ch("a-hard", difficulty="hard"),
            _ch("a-easy", difficulty="easy"),
            _ch("a-medium", difficulty="medium"),
        ]
        order = [c.unique_code for c in sort_challenges(challenges)]
        self.assertEqual(order, ["a-easy", "a-medium", "a-hard"])

    def test_simple_before_hard(self):
        """简单后难：难度升序为主（easy → medium → hard），不再把瓶颈题放开头。"""
        challenges = [
            _ch("a-05", difficulty="easy"),
            _ch("a-18", difficulty="hard"),
            _ch("b-01", difficulty="medium", flag_count=4),
            _ch("c-03", difficulty="hard"),
        ]
        order = [c.unique_code for c in sort_challenges(challenges)]
        self.assertEqual(order[0], "a-05")
        # medium 的 b-01 也必须排在 hard 的 a-18/c-03 之前（难度为主）。
        self.assertLess(order.index("a-05"), order.index("b-01"))
        self.assertLess(order.index("b-01"), order.index("a-18"))
        self.assertLess(order.index("b-01"), order.index("c-03"))


class CollaborationModeTests(unittest.TestCase):
    def test_multistage_pentest_uses_shared_memory(self):
        attempts, scope = challenge_plan(
            _ch("b-01", difficulty="medium", flag_count=4)
        )
        self.assertEqual(scope, "shared")
        self.assertEqual({a.name for a in attempts}, {"aggressive", "steady"})
        self.assertEqual(challenge_memory_scope(_ch("e1-02", flag_count=3)), "shared")

    def test_front_web_simple_uses_isolated_multi(self):
        for code in ("a-05", "c-07", "g-01", "d-03"):
            attempts, scope = challenge_plan(_ch(code, difficulty="easy"))
            self.assertEqual(scope, "isolated", code)
            self.assertEqual(len(attempts), 2, code)

    def test_hard_challenge_uses_competing_hypotheses(self):
        # hard/瓶颈题：三个正交假设（foothold/lateral/source）并行攻坚，
        # memory 私有隔离（各自独立 context），证据经 artifact/promote 受控共享，
        # claim 互斥、谁先解出谁赢。
        attempts, scope = challenge_plan(_ch("a-09", difficulty="hard"))
        self.assertEqual(scope, "private")
        self.assertEqual(
            {a.name for a in attempts}, {"foothold", "lateral", "source"}
        )
        self.assertTrue(all(a.model == "pro" for a in attempts))

    def test_generic_or_unknown_stays_solo(self):
        for code in ("web-01", "misc-01", "unknown"):
            attempts, scope = challenge_plan(_ch(code, difficulty="easy"))
            self.assertEqual(scope, "private", code)
            self.assertEqual(len(attempts), 1, code)


class ScopeRoutingTests(unittest.TestCase):
    def setUp(self):
        self.challenge = Path(tempfile.mkdtemp())
        self.a1 = self.challenge / "attempts" / "aggressive"
        self.a2 = self.challenge / "attempts" / "steady"

    def _add(self, attempt_dir, scope, text):
        mem_store.add_memory_with_status(
            write_root(self.challenge, attempt_dir, scope),
            kind="fact", content=text, attempt_id=attempt_dir.name,
        )

    def _reads(self, attempt_dir, scope):
        return sorted(
            e.content
            for e in solver_memories(self.challenge, attempt_dir, scope=scope)
        )

    def test_isolated_attempts_never_see_each_other(self):
        self._add(self.a1, "isolated", "A-only")
        self._add(self.a2, "isolated", "B-only")
        self.assertEqual(self._reads(self.a1, "isolated"), ["A-only"])
        self.assertEqual(self._reads(self.a2, "isolated"), ["B-only"])

    def test_shared_pool_is_visible_to_all_attempts(self):
        self._add(self.a1, "shared", "jump host 192.168.10.20")
        self._add(self.a2, "shared", "admin weak password")
        both = ["admin weak password", "jump host 192.168.10.20"]
        self.assertEqual(self._reads(self.a1, "shared"), both)
        self.assertEqual(self._reads(self.a2, "shared"), both)


if __name__ == "__main__":
    unittest.main()
