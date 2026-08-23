import tempfile
import threading
import unittest
from pathlib import Path

from solver.runtime.decision_state import (
    ActionOutcomeKind,
    HypothesisStatus,
    classify_action,
    extract_evidence_fingerprints,
)
from solver.runtime.observer_advice import ObserverAdvice
from solver.runtime.portfolio import PortfolioBudget
from solver.runtime.strategy_controller import StrategyController


class DecisionStateClassificationTests(unittest.TestCase):
    def test_identical_http_evidence_is_soft_but_not_novel_twice(self):
        output = "HTTP/1.1 200 OK\nServer: demo"
        first = classify_action("bash", {"cmd": "curl http://target/"}, output)
        known = set(first.evidence_fingerprints)
        second = classify_action(
            "bash", {"cmd": "curl http://target/"}, output, known_evidence=known
        )

        self.assertTrue(first.soft_progress)
        self.assertTrue(first.novel_progress)
        self.assertFalse(second.novel_progress)
        self.assertTrue(second.soft_progress)
        self.assertEqual(second.kind, ActionOutcomeKind.DUPLICATE.value)

    def test_new_negative_boundary_is_novel_but_not_positive(self):
        output = "HTTP/1.1 404 Not Found\n/path/missing"
        outcome = classify_action("bash", {"cmd": "curl http://target/missing"}, output)

        self.assertTrue(outcome.novel_progress)
        self.assertFalse(outcome.positive_progress)
        self.assertEqual(outcome.kind, ActionOutcomeKind.NEGATIVE_BOUNDARY.value)

    def test_control_inputs_do_not_refresh_target_progress(self):
        for tool in ("challenge_get_hint", "skill_load", "memory_list", "idea_list"):
            outcome = classify_action(tool, {}, "HTTP/1.1 200 OK flag{example_only}")
            self.assertFalse(outcome.soft_progress, tool)
            self.assertFalse(outcome.novel_progress, tool)

    def test_wrong_submission_is_not_positive_progress(self):
        outcome = classify_action(
            "challenge_submit_flag", {"flag": "flag{guess}"}, "wrong flag"
        )
        self.assertFalse(outcome.positive_progress)
        self.assertEqual(outcome.kind, ActionOutcomeKind.SUBMISSION.value)


class ObserverAdviceTests(unittest.TestCase):
    def test_version_and_expiry_guard(self):
        advice = ObserverAdvice.from_mapping(
            {
                "action": "switch_strategy",
                "mode": "alternate",
                "reason": "repeat",
                "message": "change direction",
                "state_version": 7,
                "expires_after_rounds": 3,
            },
            default_state_version=0,
            default_round=10,
        )
        self.assertTrue(advice.is_applicable(current_state_version=7, current_round=12))
        self.assertFalse(advice.is_applicable(current_state_version=8, current_round=12))
        self.assertFalse(advice.is_applicable(current_state_version=7, current_round=14))
        self.assertEqual(advice.mode, "ALTERNATE")


class StrategyControllerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="strategy-controller-"))

    def test_switches_after_repeated_action_without_breaking_legacy_counters(self):
        controller = StrategyController(
            self.root,
            attempt_id="steady",
            switch_after=12,
            action_repeat_threshold=4,
        )
        output = "HTTP/1.1 200 OK\nServer: demo"
        advice = None
        for round_num in range(1, 5):
            advice = controller.observe(
                "bash", {"cmd": "curl -s http://target/"}, output, round_num
            )

        self.assertIsNotNone(advice)
        self.assertEqual(advice.action, "switch_strategy")
        self.assertEqual(advice.mode, "ALTERNATE")
        state = controller.snapshot()
        self.assertEqual(state.last_novel_progress_round, 1)
        self.assertEqual(state.last_soft_progress_round, 4)
        self.assertEqual(state.same_action_streak, 4)
        self.assertEqual(state.switch_count, 1)

    def test_switch_advice_has_a_cooldown(self):
        controller = StrategyController(
            self.root,
            switch_after=6,
            action_repeat_threshold=3,
        )
        output = "HTTP/1.1 200 OK\nServer: demo"
        advices = []
        for round_num in range(1, 9):
            advice = controller.observe(
                "bash", {"cmd": "curl http://target/"}, output, round_num
            )
            if advice:
                advices.append(advice)

        self.assertLessEqual(len(advices), 2)
        self.assertEqual(controller.snapshot().switch_count, len(advices))

    def test_hypothesis_lease_prevents_two_attempts_from_claiming(self):
        controller = StrategyController(self.root)
        hypothesis = controller.register_hypothesis(
            "validate the primary application behavior",
            domain="web",
            expected_evidence="a reproducible response difference",
        )
        self.assertTrue(
            controller.claim_hypothesis(
                hypothesis.id, owner="aggressive", round_num=1, lease_rounds=8
            )
        )
        self.assertFalse(
            controller.claim_hypothesis(
                hypothesis.id, owner="steady", round_num=2, lease_rounds=8
            )
        )
        self.assertTrue(
            controller.release_hypothesis(
                hypothesis.id,
                owner="aggressive",
                status=HypothesisStatus.DISPROVED.value,
                result="boundary observed",
            )
        )
        self.assertTrue(
            controller.claim_hypothesis(
                hypothesis.id, owner="steady", round_num=10, lease_rounds=4
            )
        )

    def test_concurrent_updates_are_serialized_and_recoverable(self):
        controller = StrategyController(self.root, action_repeat_threshold=100)
        output = "HTTP/1.1 200 OK\nServer: demo"
        errors = []

        def worker(index):
            try:
                for offset in range(5):
                    controller.observe(
                        "bash",
                        {"cmd": f"curl http://target/{index}/{offset}"},
                        output,
                        index * 5 + offset + 1,
                    )
            except Exception as exc:  # pragma: no cover - diagnostic guard
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        state = controller.snapshot()
        self.assertEqual(state.state_version, 20)
        self.assertEqual(state.total_actions, 20)
        self.assertTrue((self.root / ".decision-state.json").exists())


class PortfolioBudgetTests(unittest.TestCase):
    def test_live_peers_cannot_consume_each_others_reserve(self):
        budget = PortfolioBudget(expected_attempts=2)
        budget.register("aggressive", 2)
        budget.register("steady", 2)

        self.assertTrue(budget.claim_round("aggressive"))
        self.assertTrue(budget.claim_round("aggressive"))
        self.assertFalse(budget.claim_round("aggressive"))
        self.assertTrue(budget.claim_round("steady"))

    def test_survivor_borrows_unused_peer_quota(self):
        budget = PortfolioBudget(expected_attempts=2)
        budget.register("aggressive", 2)
        budget.register("steady", 3)
        self.assertTrue(budget.claim_round("aggressive"))
        budget.mark_done("steady")

        self.assertTrue(budget.claim_round("aggressive"))
        self.assertTrue(budget.claim_round("aggressive"))
        self.assertTrue(budget.claim_round("aggressive"))
        self.assertTrue(budget.claim_round("aggressive"))
        self.assertFalse(budget.claim_round("aggressive"))
        self.assertEqual(budget.snapshot()["total_used"], 5)

    def test_no_tool_round_can_be_returned(self):
        budget = PortfolioBudget(expected_attempts=1)
        budget.register("primary", 1)
        self.assertTrue(budget.claim_round("primary"))
        budget.release_round("primary")
        self.assertTrue(budget.claim_round("primary"))


if __name__ == "__main__":
    unittest.main()
