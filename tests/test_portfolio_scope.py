"""分层排序 + 差异化协作模式（isolated / shared）的行为锁定测试。

背景（run-12717）：b-* 多阶段渗透占满 3 个槽 41 分钟，一道 500 分的 a-10
在队列里干等。修复目标：
  * 前排 web/易题先拿分，pentest/pwn/reverse 家族整体后置；
  * 前排简单题并行多解但 memory 完全隔离；
  * 后排 b-* 多阶段题多 agent 共享 memory 协作。
"""

import json
import tempfile
import unittest
from pathlib import Path

from solver.runtime.salvage import (
    collect_salvage_targets,
    is_long_hard_challenge,
    salvage_abandoned_codes,
    sort_challenges_salvage,
)
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


class LateGameSalvageTests(unittest.TestCase):
    def test_partial_progress_sorted_first(self):
        fresh = _ch("a-01", difficulty="easy")
        almost = _ch("b-02", difficulty="hard", flag_count=6, correct_flag_count=2)
        order = [
            c.unique_code
            for c in sort_challenges_salvage([fresh, almost], Path("/tmp/ws"))
        ]
        self.assertEqual(order[0], "a-01")

    def test_long_hard_detected(self):
        self.assertTrue(is_long_hard_challenge(_ch("b-02", difficulty="hard", flag_count=6)))
        self.assertFalse(is_long_hard_challenge(_ch("a-03", difficulty="easy")))

    def test_salvage_abandoned_easy_and_partial(self):
        challenges = [
            _ch("a-03", difficulty="easy"),
            _ch("b-02", difficulty="hard", flag_count=6, correct_flag_count=1),
            _ch("c-08", difficulty="hard"),
        ]
        salvaged = salvage_abandoned_codes(
            {"a-03", "b-02", "c-08"}, challenges
        )
        self.assertEqual(salvaged, {"a-03", "b-02"})
        self.assertNotIn("c-08", salvaged)

    def test_collect_salvage_targets_transient(self):
        ws = Path(tempfile.mkdtemp())
        code = "a-05"
        (ws / code).mkdir(parents=True)
        (ws / code / ".challenge-ledger.json").write_text(
            json.dumps({
                "attempts": [{
                    "rounds": 0,
                    "new_flags": 0,
                    "success": False,
                    "error": "Connection error.",
                }],
            }),
            encoding="utf-8",
        )
        ch = _ch(code, difficulty="easy")
        targets = collect_salvage_targets(
            [ch],
            abandoned=set(),
            fail_streak={},
            workspace_dir=ws,
        )
        self.assertIn(code, targets)


class CollaborationModeTests(unittest.TestCase):
    def test_multistage_pentest_uses_shared_memory(self):
        attempts, scope = challenge_plan(
            _ch("b-01", difficulty="medium", flag_count=4)
        )
        self.assertEqual(scope, "shared")
        self.assertEqual({a.name for a in attempts}, {"aggressive", "steady"})
        self.assertEqual(challenge_memory_scope(_ch("e1-02", flag_count=3)), "shared")

    def test_front_web_simple_single_flag_stays_solo(self):
        # 简单单 flag web 题不再双路赛跑：单路 30s 内就解，双路只翻倍 LLM
        # 成本并抢占难题的并发 lane（run-12752 拥挤根因）。
        for code in ("a-05", "c-07", "g-01", "d-03"):
            attempts, scope = challenge_plan(_ch(code, difficulty="easy"))
            self.assertEqual(scope, "private", code)
            self.assertEqual(len(attempts), 1, code)

    def test_multi_flag_web_still_races_two_strategies(self):
        # 多 flag（≥4）非 b/e1 题仍值得隔离双路赛跑。
        attempts, scope = challenge_plan(
            _ch("a-20", difficulty="medium", flag_count=4)
        )
        self.assertEqual(scope, "isolated")
        self.assertEqual({a.name for a in attempts}, {"aggressive", "steady"})

    def test_hard_single_chain_stays_solo(self):
        # 单 flag hard Web/产品题：单 agent + skills，不开 foothold/lateral/source。
        for code in ("a-09", "a-13", "a-18", "c-02", "c-08", "e3-04"):
            attempts, scope = challenge_plan(_ch(code, difficulty="hard"))
            self.assertEqual(scope, "private", code)
            self.assertEqual(len(attempts), 1, code)
            self.assertEqual(attempts[0].name, "primary", code)

    def test_hard_multi_flag_still_uses_competing_hypotheses(self):
        attempts, scope = challenge_plan(
            _ch("a-99", difficulty="hard", flag_count=3)
        )
        self.assertEqual(scope, "private")
        self.assertEqual(
            {a.name for a in attempts}, {"foothold", "lateral", "source"}
        )

    def test_hard_competing_opt_in(self):
        settings = {"solver": {"hard_competing_hypotheses": True}}
        attempts, scope = challenge_plan(
            _ch("a-13", difficulty="hard"), settings
        )
        self.assertEqual(scope, "private")
        self.assertEqual(
            {a.name for a in attempts}, {"foothold", "lateral", "source"}
        )

    def test_late_game_uses_solo_even_for_hard(self):
        settings = {"solver": {"late_game_mode": True}}
        attempts, scope = challenge_plan(_ch("a-09", difficulty="hard"), settings)
        self.assertEqual(scope, "private")
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].name, "primary")

    def test_late_game_partial_pentest_keeps_shared(self):
        settings = {"solver": {"late_game_mode": True}}
        attempts, scope = challenge_plan(
            _ch("b-02", difficulty="hard", flag_count=6, correct_flag_count=1),
            settings,
        )
        self.assertEqual(scope, "shared")
        self.assertEqual(len(attempts), 1)

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
