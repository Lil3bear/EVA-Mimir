import json
import tempfile
import unittest
from pathlib import Path

from solver.runtime.lineage import SessionLineage


class SessionLineageTests(unittest.TestCase):
    def test_append_only_parented_compaction_and_finish(self):
        path = Path(tempfile.mkdtemp()) / ".session-lineage.jsonl"
        lineage = SessionLineage(path, scope={"challenge_id": "b-01", "attempt_id": "aggressive"})
        root = lineage.start({"difficulty": "hard"})
        checkpoint = lineage.checkpoint(round_num=1, messages=[{"role": "user", "content": "x"}])
        compact = lineage.compact("facts preserved", round_num=2)
        finish = lineage.finish("max_rounds")

        events = lineage.events()
        self.assertEqual([e["event_id"] for e in events], [root, checkpoint, compact, finish])
        self.assertEqual(events[1]["parent_id"], root)
        self.assertEqual(events[2]["parent_id"], checkpoint)
        self.assertEqual(events[3]["parent_id"], compact)
        self.assertEqual([e["seq"] for e in events], [1, 2, 3, 4])

    def test_fork_has_parent_and_new_branch(self):
        path = Path(tempfile.mkdtemp()) / "lineage.jsonl"
        root = SessionLineage(path)
        root_event = root.start()
        child = root.fork(branch_id="steady")
        child_event = child.append("branch_started", {"role": "evidence"})

        events = child.events()
        event = next(e for e in events if e["event_id"] == child_event)
        self.assertEqual(event["parent_id"], root_event)
        self.assertEqual(event["branch_id"], "steady")
        self.assertNotEqual(event["session_id"], root.session_id)


if __name__ == "__main__":
    unittest.main()
