import tempfile
import unittest
from pathlib import Path

from solver.runtime.state_events import StateEventLog


class StateEventLogTests(unittest.TestCase):
    def test_hash_chain_and_replay(self):
        root = Path(tempfile.mkdtemp())
        log = StateEventLog(root)
        first = log.append("memory_added", {"memory_id": "m1"}, attempt_id="a")
        second = log.append("artifact_approved", {"artifact_id": "x"}, attempt_id="observer")
        self.assertNotEqual(first["hash"], second["hash"])
        self.assertEqual(log.validate(), [])
        self.assertEqual([item["seq"] for item in log.events()], [1, 2])

    def test_tamper_is_detected(self):
        root = Path(tempfile.mkdtemp())
        log = StateEventLog(root)
        log.append("command", {"action": "pause_attempt"})
        path = root / "shared" / "state-events.jsonl"
        text = path.read_text(encoding="utf-8").replace("pause_attempt", "close_attempt")
        path.write_text(text, encoding="utf-8")
        self.assertTrue(log.validate())


if __name__ == "__main__":
    unittest.main()
