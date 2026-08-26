import tempfile
import unittest
from pathlib import Path

from solver.runtime.claims import ClaimStore


class ClaimStoreTests(unittest.TestCase):
    def test_mutual_exclusion_and_release(self):
        root = Path(tempfile.mkdtemp())
        store = ClaimStore(root)
        ok, first = store.claim("probe internal ssh", owner="aggressive", round_num=1)
        self.assertTrue(ok)
        ok, second = store.claim("probe internal ssh", owner="steady", round_num=2)
        self.assertFalse(ok)
        self.assertEqual(second["owner"], "aggressive")
        self.assertTrue(store.release("probe internal ssh", owner="aggressive", status="failed"))
        ok, third = store.claim("probe internal ssh", owner="steady", round_num=3)
        self.assertTrue(ok)
        self.assertEqual(third["owner"], "steady")
        self.assertEqual(store.release_owner("steady"), 1)
        self.assertEqual(store.list_active(), [])

    def test_expired_claim_can_be_reclaimed(self):
        root = Path(tempfile.mkdtemp())
        store = ClaimStore(root)
        store.claim("read source", owner="a", round_num=1, lease_rounds=2)
        ok, record = store.claim("read source", owner="b", round_num=4)
        self.assertTrue(ok)
        self.assertEqual(record["owner"], "b")


if __name__ == "__main__":
    unittest.main()
