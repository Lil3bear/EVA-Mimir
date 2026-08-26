import tempfile
import unittest
from pathlib import Path

from solver.runtime.lineage import SessionLineage
from solver.runtime.replay import LineageReplay, validate_scoped_tree
from solver.runtime.retry_ledger import RetryLedger


class RetryReplayTests(unittest.TestCase):
    def test_retry_state_survives_new_store_instance_and_abandons(self):
        root = Path(tempfile.mkdtemp())
        first = RetryLedger(root, "task-a")
        first.record_round(round_num=1, failed_codes={"b-03"}, partial_codes=set(), solved_codes=set(), max_fail_streak=2)
        self.assertIn("b-03", first.snapshot().get("cooldown_until_round", {}))
        self.assertTrue(first.should_skip("b-03", round_num=2))
        second = RetryLedger(root, "task-a")
        state = second.record_round(round_num=2, failed_codes={"b-03"}, partial_codes=set(), solved_codes=set(), max_fail_streak=2)
        self.assertIn("b-03", state["abandoned"])
        self.assertTrue(second.should_skip("b-03", round_num=3))
        self.assertNotIn("b-03", RetryLedger(root, "task-b").snapshot()["abandoned"])

    def test_lineage_replay_and_scope_validation(self):
        root = Path(tempfile.mkdtemp())
        path = root / "attempts" / "aggressive" / ".session-lineage.jsonl"
        lineage = SessionLineage(path, scope={"challenge_id": "b-03", "attempt_id": "aggressive"})
        start = lineage.start()
        lineage.checkpoint(round_num=1, messages=[])
        lineage.compact("facts", round_num=2)
        lineage.finish("test")
        replay = LineageReplay(path)
        self.assertEqual(replay.validate(), [])
        self.assertEqual(replay.branch()[-1]["kind"], "session_finished")
        self.assertEqual(validate_scoped_tree(root), [])
        self.assertTrue(start)


if __name__ == "__main__":
    unittest.main()
