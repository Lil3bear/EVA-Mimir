import tempfile
import unittest
from pathlib import Path

from solver.runtime.commands import CommandBus


class CommandBusTests(unittest.TestCase):
    def test_targeted_command_is_pending_then_acknowledged(self):
        root = Path(tempfile.mkdtemp())
        bus = CommandBus(root)
        command = bus.publish(
            action="assign_hypothesis",
            target_attempt="aggressive",
            payload={"hypothesis": "verify service"},
            round_num=2,
        )
        self.assertEqual(len(bus.pending(attempt_id="steady", round_num=2)), 0)
        self.assertEqual(len(bus.pending(attempt_id="aggressive", round_num=2)), 1)
        self.assertTrue(bus.acknowledge(command["command_id"], attempt_id="aggressive", result="accepted"))
        self.assertEqual(bus.pending(attempt_id="aggressive", round_num=2), [])

    def test_expired_command_is_not_delivered(self):
        root = Path(tempfile.mkdtemp())
        bus = CommandBus(root)
        bus.publish(action="review_blackboard", payload={}, round_num=1, expires_after_rounds=2)
        self.assertEqual(bus.pending(attempt_id="primary", round_num=4), [])


if __name__ == "__main__":
    unittest.main()
