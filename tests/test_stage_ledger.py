import tempfile
import unittest
from pathlib import Path

from solver.runtime.stage_ledger import StageLedger


class StageLedgerTests(unittest.TestCase):
    def test_submission_progress_and_stage(self):
        root = Path(tempfile.mkdtemp())
        ledger = StageLedger(root)
        state = ledger.record_submission({
            "correct": True,
            "correct_flag_count": 1,
            "total_flag_count": 4,
            "matched_flag_index": 0,
            "is_completed": False,
        }, attempt_id="aggressive")
        self.assertEqual(state["current_stage"], "stage_2")
        self.assertEqual(state["flags"]["0"]["status"], "submitted")
        self.assertEqual(ledger.snapshot()["correct_flags"], 1)

    def test_reconcile_never_decreases_progress(self):
        root = Path(tempfile.mkdtemp())
        ledger = StageLedger(root)
        ledger.reconcile_state({"correct_flag_count": 3, "flag_count": 4, "is_completed": False})
        state = ledger.reconcile_state({"correct_flag_count": 1, "flag_count": 4, "is_completed": False})
        self.assertEqual(state["correct_flags"], 3)


if __name__ == "__main__":
    unittest.main()
