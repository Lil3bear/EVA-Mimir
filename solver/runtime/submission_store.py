"""Atomic, challenge-scoped submission state."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

if sys.platform != "win32":
    import fcntl


def benchmark_task_id(env: dict[str, str] | None = None) -> str:
    """Return a non-secret identity for the current benchmark task."""
    source = os.environ if env is None else env
    base_url = str(source.get("BENCHMARK_BASE_URL", "")).strip()
    token = str(source.get("BENCHMARK_TOKEN", "")).strip()
    if not base_url or not token:
        return ""
    return hashlib.sha256(f"{base_url}\0{token}".encode()).hexdigest()[:24]


def score_belongs_to_current_task(challenge_dir: str | Path) -> bool:
    """Reject score files left by a different benchmark token."""
    current = benchmark_task_id()
    if not current:
        return True
    marker = Path(challenge_dir) / ".benchmark-task-id"
    try:
        return marker.read_text(encoding="utf-8").strip() == current
    except OSError:
        return False


def prepare_challenge_state(challenge_dir: str | Path) -> bool:
    """Start a clean state namespace when a mounted workspace changes task.

    Submission state was already namespaced, but Memory/Ideas and execution
    journals are also persistent files.  Without this boundary, a new task
    reusing the same ``unique_code`` could see old IPs, credentials, or a
    recoverable tool call before its first submit.  The current task marker is
    a one-way hash of URL+token; the token itself is never persisted.

    Returns ``True`` when old task state was removed.  Local bridge mode (no
    benchmark identity) is intentionally left untouched for backwards
    compatibility.
    """
    current = benchmark_task_id()
    if not current:
        return False

    challenge_path = Path(challenge_dir)
    store = SubmissionStore(challenge_path)
    with store._locked():
        try:
            previous = store.task_marker_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            previous = ""
        if previous == current:
            return False

        # State that can contain answers, target-specific evidence, or a
        # pending tool replay is task-scoped.  Keep generic source files and
        # the lock directory intact.
        for name in (
            ".submitted_flags.json",
            ".cumulative_score",
            ".completed",
            ".submission-run-id",
            ".solver-history.jsonl",
            ".execution-journal.jsonl",
            ".challenge-ledger.json",
            ".decision-state.json",
        ):
            (challenge_path / name).unlink(missing_ok=True)

        entries = challenge_path / "memory" / "entries"
        if entries.is_dir():
            for item in entries.glob("*.json"):
                item.unlink(missing_ok=True)
        (challenge_path / "ideas" / "index.json").unlink(missing_ok=True)
        # Attempt journals and tool-result files are not useful across task
        # identities and can otherwise feed stale recovery summaries.  Never
        # commit the new task marker after a silent cleanup failure: doing so
        # would permanently bless stale state as belonging to the new task.
        for stale_dir in (
            challenge_path / "attempts",
            challenge_path / ".tool-results",
            # Layered solver state: shared evidence/proposals are task-scoped.
            challenge_path / "shared",
        ):
            if stale_dir.exists():
                shutil.rmtree(stale_dir)
            if stale_dir.exists():
                raise OSError(f"无法清理旧任务状态：{stale_dir}")

        store._write_text(store.task_marker_path, current)
        return True


@dataclass(frozen=True)
class SubmissionOutcome:
    status: str
    response: dict | None
    duplicate: bool
    wrong_count: int
    persistence_error: str = ""


class SubmissionStore:
    """Serialize check-submit-record as one transaction per challenge."""

    MAX_WRONG_SUBMITS = 8  # 每题累计错误 flag 上限，超限拒绝继续提交（防刷提交）

    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(self, challenge_dir: str | Path):
        self.challenge_dir = Path(challenge_dir)
        self.submissions_path = self.challenge_dir / ".submitted_flags.json"
        self.score_path = self.challenge_dir / ".cumulative_score"
        self.completed_path = self.challenge_dir / ".completed"
        self.run_marker_path = self.challenge_dir / ".submission-run-id"
        self.task_marker_path = self.challenge_dir / ".benchmark-task-id"
        self.task_id = benchmark_task_id()
        self.run_id = os.environ.get("CTF_RUN_ID", f"pid-{os.getpid()}")
        self.lock_path = self.challenge_dir / "locks" / "submission.lock"

    def submit(self, flag: str, submitter: Callable[[], dict]) -> SubmissionOutcome:
        with self._locked():
            submissions = self._prepare_run_state(self._read_submissions())
            previous = submissions.get(flag)
            if previous in {"correct", "wrong"}:
                return SubmissionOutcome(
                    status=previous,
                    response=None,
                    duplicate=True,
                    wrong_count=self._wrong_count(submissions),
                )

            # 错误 flag 限流：累计达到上限后拒绝继续提交，不调用平台
            wrong_count = self._wrong_count(submissions)
            if wrong_count >= self.MAX_WRONG_SUBMITS:
                return SubmissionOutcome(
                    status="limited",
                    response={"limited": True, "wrong_count": wrong_count},
                    duplicate=False,
                    wrong_count=wrong_count,
                )

            response = submitter()
            status = "correct" if response.get("correct") else "wrong"
            submissions[flag] = status

            # The remote response is authoritative.  Local persistence errors
            # must not turn an accepted flag into an apparent wrong submit.
            # Persist score/completion first: if the process dies before the
            # final submissions index, a platform duplicate can still recover
            # the flag while retaining already-acknowledged score metadata.
            persistence_errors: list[str] = []

            def persist(label: str, operation) -> None:
                try:
                    operation()
                except Exception as exc:
                    persistence_errors.append(f"{label}: {exc}")

            if status == "correct" and response.get("cumulative_score") is not None:
                persist("score", lambda: self._record_score(response.get("cumulative_score")))
            if status == "correct" and response.get("is_completed"):
                persist("completed", lambda: self._write_text(self.completed_path, "1"))
            persist("submissions", lambda: self._write_json(self.submissions_path, submissions))

            try:
                from solver.runtime.state_events import StateEventLog
                StateEventLog(self.challenge_dir).append(
                    "submission_recorded",
                    {
                        "status": status,
                        "correct": status == "correct",
                        "cumulative_score": response.get("cumulative_score"),
                        "correct_flags": response.get("correct_flag_count"),
                        "total_flags": response.get("total_flag_count"),
                        "matched_index": response.get("matched_flag_index"),
                    },
                    run_id=self.run_id,
                )
            except Exception:
                pass
            return SubmissionOutcome(
                status=status,
                response=response,
                duplicate=False,
                wrong_count=self._wrong_count(submissions),
                persistence_error="; ".join(persistence_errors),
            )

    @contextmanager
    def _locked(self) -> Iterator[None]:
        key = str(self.lock_path.resolve())
        with self._locks_guard:
            thread_lock = self._locks.setdefault(key, threading.RLock())
        with thread_lock:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self.lock_path.open("a+") as handle:
                if sys.platform != "win32":
                    fcntl.flock(handle, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if sys.platform != "win32":
                        fcntl.flock(handle, fcntl.LOCK_UN)

    def _prepare_run_state(self, submissions: dict[str, str]) -> dict[str, str]:
        """Keep only state belonging to this task and current retry run.

        A mounted workspace can outlive both a solver process and a benchmark
        token.  Wrong guesses are discarded between runs, while correct flags
        are retained only when the task identity (a hash, never the token)
        matches.  This prevents stale state from blocking submissions or
        inflating a later task's score.
        """
        previous_task = ""
        try:
            previous_task = self.task_marker_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            pass

        if self.task_id and previous_task != self.task_id:
            submissions = {}
            self.score_path.unlink(missing_ok=True)
            self.completed_path.unlink(missing_ok=True)
            self._write_text(self.task_marker_path, self.task_id)

        previous_run = ""
        try:
            previous_run = self.run_marker_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            pass
        if previous_run != self.run_id:
            submissions = {
                flag: status
                for flag, status in submissions.items()
                if status == "correct"
            }
            self._write_json(self.submissions_path, submissions)
            self._write_text(self.run_marker_path, self.run_id)
        return submissions

    def _read_submissions(self) -> dict[str, str]:
        if not self.submissions_path.exists():
            return {}
        try:
            data = json.loads(self.submissions_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("submission state root is not an object")
        except (json.JSONDecodeError, UnicodeError, ValueError):
            self._quarantine_corrupt(self.submissions_path)
            return {}
        return {
            str(flag): str(status)
            for flag, status in data.items()
            if status in {"correct", "wrong"}
        }

    def current_wrong_count(self) -> int:
        """Return the challenge-scoped wrong-submit count without side effects."""
        try:
            submissions = self._read_submissions()
            return self._wrong_count(submissions)
        except Exception:
            return 0

    def _record_score(self, score) -> None:
        new_score = int(score or 0)
        try:
            old_score = int(self.score_path.read_text(encoding="utf-8").strip() or "0")
        except FileNotFoundError:
            old_score = 0
        except ValueError:
            self._quarantine_corrupt(self.score_path)
            old_score = 0
        self._write_text(self.score_path, str(max(old_score, new_score)))

    @staticmethod
    def _quarantine_corrupt(path: Path) -> None:
        """Move malformed state aside so one bad file cannot block a run."""
        if not path.exists():
            return
        quarantine = path.with_name(f"{path.name}.corrupt.{time.time_ns()}")
        try:
            os.replace(path, quarantine)
        except OSError:
            # Persistence may be read-only; the current operation can still
            # use an empty in-memory state and report a later write warning.
            pass

    @staticmethod
    def _wrong_count(submissions: dict[str, str]) -> int:
        return sum(status == "wrong" for status in submissions.values())

    def _write_json(self, path: Path, data: dict) -> None:
        self._write_text(path, json.dumps(data, ensure_ascii=False))

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(
            f".{path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
        )
        try:
            tmp.write_text(content, encoding="utf-8")
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
