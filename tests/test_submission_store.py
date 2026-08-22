import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from solver.runtime.submission_store import (
    SubmissionStore,
    prepare_challenge_state,
    score_belongs_to_current_task,
)


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

    def test_new_benchmark_task_does_not_reuse_old_submission_state(self):
        root = Path(tempfile.mkdtemp(prefix="submission-task-isolation-"))
        with patch.dict(
            "os.environ",
            {"BENCHMARK_BASE_URL": "https://bench", "BENCHMARK_TOKEN": "old"},
            clear=False,
        ):
            SubmissionStore(root).submit(
                "flag{old}", lambda: {"correct": True, "cumulative_score": 10}
            )
        with patch.dict(
            "os.environ",
            {"BENCHMARK_BASE_URL": "https://bench", "BENCHMARK_TOKEN": "new"},
            clear=False,
        ):
            store = SubmissionStore(root)
            calls = []
            outcome = store.submit(
                "flag{new}",
                lambda: calls.append(True) or {"correct": True, "cumulative_score": 20},
            )
            self.assertFalse(outcome.duplicate)
            self.assertEqual(calls, [True])
            self.assertTrue(score_belongs_to_current_task(root))
            self.assertEqual((root / ".cumulative_score").read_text(), "20")

    def test_new_task_clears_memory_ideas_and_recovery_files_before_solver(self):
        root = Path(tempfile.mkdtemp(prefix="submission-state-reset-"))
        (root / "memory" / "entries").mkdir(parents=True)
        (root / "memory" / "entries" / "old.json").write_text("{}")
        (root / "ideas").mkdir(parents=True)
        (root / "ideas" / "index.json").write_text("[]")
        (root / "attempts" / "primary").mkdir(parents=True)
        (root / "attempts" / "primary" / ".solver-history.jsonl").write_text("old")
        (root / ".execution-journal.jsonl").write_text("old")

        with patch.dict(
            "os.environ",
            {"BENCHMARK_BASE_URL": "https://bench", "BENCHMARK_TOKEN": "task-a"},
            clear=False,
        ):
            self.assertTrue(prepare_challenge_state(root))
            self.assertFalse((root / "memory" / "entries" / "old.json").exists())
            self.assertFalse((root / "ideas" / "index.json").exists())
            self.assertFalse((root / "attempts").exists())
            self.assertFalse((root / ".execution-journal.jsonl").exists())
            self.assertTrue(score_belongs_to_current_task(root))
            self.assertFalse(prepare_challenge_state(root))

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
