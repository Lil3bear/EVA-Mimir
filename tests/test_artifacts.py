import tempfile
import unittest
from pathlib import Path

from solver.runtime.artifacts import ArtifactBus


class ArtifactBusTests(unittest.TestCase):
    def test_pending_is_invisible_until_approved(self):
        root = Path(tempfile.mkdtemp())
        bus = ArtifactBus(root)
        item = bus.publish(
            artifact_type="foothold",
            value="confirmed shell",
            producer_attempt="aggressive",
            proof_ref="attempts/aggressive/.execution-journal.jsonl#42",
            confidence=0.9,
        )
        self.assertEqual(len(bus.list(status="pending")), 1)
        self.assertEqual(bus.list(status="approved"), [])
        approved = bus.approve(item["artifact_id"])
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(bus.list(status="approved")[0]["value"], "confirmed shell")

    def test_artifact_preserves_contract_and_owner(self):
        root = Path(tempfile.mkdtemp())
        item = ArtifactBus(root).publish(
            artifact_type="credential",
            value="admin credential verified",
            producer_attempt="steady",
            contract_id="contract_x",
        )
        self.assertEqual(item["producer_attempt"], "steady")
        self.assertEqual(item["contract_id"], "contract_x")


if __name__ == "__main__":
    unittest.main()
