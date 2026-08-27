import tempfile
import unittest
from pathlib import Path

from solver.runtime.artifacts import ArtifactBus
from solver.runtime.claims import ClaimStore
from solver.runtime.commands import CommandBus
from solver.runtime.contracts import SubtaskContract, write_contract
from solver.runtime.lineage import SessionLineage
from solver.runtime.replay import validate_scoped_tree
from solver.runtime.stage_ledger import StageLedger
from solver.runtime.scoped_state import promote_memory_proposal, publish_memory_proposal


class ScopedArchitectureE2ETests(unittest.TestCase):
    def test_two_attempts_coordinate_without_private_state_leak(self):
        root = Path(tempfile.mkdtemp())
        challenge = root / "b-03"
        aggressive = challenge / "attempts" / "aggressive"
        steady = challenge / "attempts" / "steady"
        for attempt, hypothesis in ((aggressive, "web foothold"), (steady, "internal service")):
            contract = SubtaskContract(
                task_id="run-1", challenge_id="b-03", attempt_id=attempt.name,
                objective="test", hypothesis=hypothesis,
            )
            write_contract(attempt, contract)
            SessionLineage(
                attempt / ".session-lineage.jsonl",
                scope={"challenge_id": "b-03", "attempt_id": attempt.name},
            ).start()

        claims = ClaimStore(challenge)
        self.assertTrue(claims.claim("web foothold", owner="aggressive", round_num=1)[0])
        self.assertFalse(claims.claim("web foothold", owner="steady", round_num=1)[0])

        proposal = publish_memory_proposal(
            challenge, attempt_id="aggressive", kind="evidence", content="shell verified",
        )
        self.assertEqual(len(ArtifactBus(challenge).list(status="approved")), 0)
        promote_memory_proposal(challenge, proposal)
        artifact = ArtifactBus(challenge).publish(
            artifact_type="foothold", value="shell verified", producer_attempt="aggressive",
        )
        ArtifactBus(challenge).approve(artifact["artifact_id"])
        StageLedger(challenge).record_submission({
            "correct": True, "correct_flag_count": 1, "total_flag_count": 2,
            "matched_flag_index": 0, "is_completed": False,
        }, attempt_id="aggressive")
        command = CommandBus(challenge).publish(
            action="assign_hypothesis", target_attempt="steady",
            payload={"next_stage": "stage_2"}, round_num=1,
        )
        self.assertEqual(len(CommandBus(challenge).pending(attempt_id="aggressive", round_num=1)), 0)
        self.assertEqual(len(CommandBus(challenge).pending(attempt_id="steady", round_num=1)), 1)
        self.assertEqual(validate_scoped_tree(challenge), [])
        self.assertTrue(command["command_id"])


if __name__ == "__main__":
    unittest.main()
