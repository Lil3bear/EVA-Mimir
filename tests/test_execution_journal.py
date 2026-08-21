import tempfile
import unittest
from pathlib import Path

from solver.runtime.journal import ExecutionJournal


class ExecutionJournalTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "execution.jsonl"

    def test_recovers_call_left_between_prepare_and_complete(self):
        first = ExecutionJournal(self.path)
        first.start()
        first.prepare("call-1", "bash", {"cmd": "reboot"}, 7)

        recovery = ExecutionJournal(self.path).start()

        self.assertEqual(len(recovery["pending"]), 1)
        self.assertEqual(recovery["pending"][0]["call_id"], "call-1")

    def test_completed_call_is_not_pending(self):
        first = ExecutionJournal(self.path)
        first.start()
        first.prepare("call-1", "read_file", {"path": "a"}, 2)
        first.complete("call-1", "read_file", "content")

        recovery = ExecutionJournal(self.path).start()

        self.assertEqual(recovery["pending"], [])
        self.assertEqual(recovery["recent_completed"][0]["result"], "content")

    def test_clean_finished_run_needs_no_recovery(self):
        first = ExecutionJournal(self.path)
        first.start()
        first.prepare("call-1", "grep", {"pattern": "x"}, 1)
        first.complete("call-1", "grep", "match")
        first.finish("solved")

        recovery = ExecutionJournal(self.path).start()

        self.assertEqual(recovery["pending"], [])
        self.assertEqual(recovery["recent_completed"], [])

    def test_truncated_last_line_does_not_destroy_prior_boundary(self):
        first = ExecutionJournal(self.path)
        first.start()
        first.prepare("call-1", "bash", {"cmd": "id"}, 1)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write('{"type":"completed"')

        recovery = ExecutionJournal(self.path).start()

        self.assertEqual(recovery["pending"][0]["call_id"], "call-1")


if __name__ == "__main__":
    unittest.main()
