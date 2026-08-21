"""Atomic, challenge-scoped submission state."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

if sys.platform != "win32":
    import fcntl


@dataclass(frozen=True)
class SubmissionOutcome:
    status: str
    response: dict | None
    duplicate: bool
    wrong_count: int


class SubmissionStore:
    """Serialize check-submit-record as one transaction per challenge."""

    MAX_WRONG_SUBMITS = 8  # 每题累计错误 flag 上限，超限拒绝继续提交（防刷提交）

    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(self, challenge_dir: str | Path):
        self.challenge_dir = Path(challenge_dir)
        self.submissions_path = self.challenge_dir / ".submitted_flags.json"
        self.score_path = self.challenge_dir / ".cumulative_score"
        self.lock_path = self.challenge_dir / "locks" / "submission.lock"

    def submit(self, flag: str, submitter: Callable[[], dict]) -> SubmissionOutcome:
        with self._locked():
            submissions = self._read_submissions()
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
            self._write_json(self.submissions_path, submissions)
            if status == "correct" and response.get("cumulative_score") is not None:
                self._record_score(response.get("cumulative_score"))
            return SubmissionOutcome(
                status=status,
                response=response,
                duplicate=False,
                wrong_count=self._wrong_count(submissions),
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

    def _read_submissions(self) -> dict[str, str]:
        if not self.submissions_path.exists():
            return {}
        data = json.loads(self.submissions_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"invalid submission state: {self.submissions_path}")
        return {
            str(flag): str(status)
            for flag, status in data.items()
            if status in {"correct", "wrong"}
        }

    def _record_score(self, score) -> None:
        new_score = int(score or 0)
        try:
            old_score = int(self.score_path.read_text(encoding="utf-8").strip() or "0")
        except FileNotFoundError:
            old_score = 0
        self._write_text(self.score_path, str(max(old_score, new_score)))

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
