import tempfile
import unittest
from pathlib import Path

from solver.runtime.contracts import SubtaskContract, load_contract, write_contract


class SubtaskContractTests(unittest.TestCase):
    def test_contract_round_trip_and_prompt_boundary(self):
        root = Path(tempfile.mkdtemp()) / "attempts" / "aggressive"
        contract = SubtaskContract(
            task_id="run-1",
            challenge_id="b-03",
            attempt_id="aggressive",
            objective="verify foothold",
            hypothesis="the upload entry is exploitable",
            success_condition="reproducible shell",
            stop_condition="three failed variants",
        )
        write_contract(root, contract)
        restored = load_contract(root)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.contract_id, contract.contract_id)
        self.assertIn("challenge_id: b-03", restored.prompt_text())
        self.assertIn("attempt_id: aggressive", restored.prompt_text())
        self.assertIn("不要读取其他 attempt", restored.prompt_text())


if __name__ == "__main__":
    unittest.main()
