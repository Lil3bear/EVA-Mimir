import tempfile
import threading
import time
import unittest
from pathlib import Path

from solver.runtime.challenge_ledger import ChallengeLedger


class ChallengeLedgerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="challenge-ledger-"))

    def test_evidence_fingerprint_is_fresh_only_once_across_instances(self):
        first = ChallengeLedger(self.root)
        second = ChallengeLedger(self.root)

        self.assertEqual(first.register_fingerprints(["fp-a", "fp-b"]), 2)
        self.assertEqual(second.register_fingerprints(["fp-a"]), 0)
        self.assertEqual(second.register_fingerprints(["fp-c"]), 1)

    def test_concurrent_hint_fetch_calls_provider_once(self):
        calls = 0
        calls_lock = threading.Lock()
        outcomes = []

        def fetch():
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.02)
            return ["cached direction"]

        def worker():
            outcomes.append(ChallengeLedger(self.root).get_or_fetch_hints(fetch))

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(calls, 1)
        self.assertEqual(sum(cached for _, cached in outcomes), 5)
        self.assertTrue(all(hints == ["cached direction"] for hints, _ in outcomes))

    def test_attempt_history_is_bounded(self):
        ledger = ChallengeLedger(self.root)
        for index in range(ChallengeLedger.MAX_ATTEMPTS + 5):
            ledger.record_attempt({"index": index})

        data = ledger._load()
        self.assertEqual(len(data["attempts"]), ChallengeLedger.MAX_ATTEMPTS)
        self.assertEqual(data["attempts"][0]["index"], 5)

    def test_corrupt_ledger_is_quarantined(self):
        path = self.root / ".challenge-ledger.json"
        path.write_text("{bad", encoding="utf-8")

        self.assertEqual(ChallengeLedger(self.root).cached_hints(), [])
        self.assertTrue(list(self.root.glob(".challenge-ledger.json.corrupt.*")))


if __name__ == "__main__":
    unittest.main()
