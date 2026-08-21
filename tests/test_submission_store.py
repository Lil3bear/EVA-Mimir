import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from solver.runtime.submission_store import SubmissionStore


class SubmissionStoreTests(unittest.TestCase):
    def test_concurrent_duplicate_submits_once(self):
        root = Path(tempfile.mkdtemp(prefix="submission-store-"))
        calls = 0
        calls_lock = threading.Lock()
        outcomes = []

        def submitter():
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.02)
            return {"correct": True, "cumulative_score": 10}

        def worker():
            outcomes.append(SubmissionStore(root).submit("flag{same}", submitter))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(calls, 1)
        self.assertEqual(sum(outcome.duplicate for outcome in outcomes), 7)
        self.assertEqual(
            json.loads((root / ".submitted_flags.json").read_text(encoding="utf-8")),
            {"flag{same}": "correct"},
        )

    def test_concurrent_scores_keep_maximum(self):
        root = Path(tempfile.mkdtemp(prefix="submission-score-"))

        def worker(flag, score):
            SubmissionStore(root).submit(
                flag, lambda: {"correct": True, "cumulative_score": score}
            )

        threads = [
            threading.Thread(target=worker, args=("flag{one}", 10)),
            threading.Thread(target=worker, args=("flag{two}", 25)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual((root / ".cumulative_score").read_text(), "25")
        self.assertEqual(
            set(json.loads((root / ".submitted_flags.json").read_text())),
            {"flag{one}", "flag{two}"},
        )


if __name__ == "__main__":
    unittest.main()
