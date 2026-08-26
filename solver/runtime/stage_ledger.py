"""Durable multi-flag stage ledger.

The ledger records progress by platform flag index, not raw flag values.  It
lets parallel attempts coordinate stage dependencies without sharing secrets
or transcripts.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

if sys.platform != "win32":
    import fcntl


class StageLedger:
    VERSION = 1
    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(self, challenge_dir: str | Path):
        self.challenge_dir = Path(challenge_dir)
        self.path = self.challenge_dir / "shared" / "stage-ledger.json"
        self.lock_path = self.challenge_dir / "locks" / "stage-ledger.lock"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        key = str(self.lock_path.resolve())
        with self._locks_guard:
            lock = self._locks.setdefault(key, threading.RLock())
        with lock:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self.lock_path.open("a+") as handle:
                if sys.platform != "win32":
                    fcntl.flock(handle, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if sys.platform != "win32":
                        fcntl.flock(handle, fcntl.LOCK_UN)

    def initialize(self, total_flags: int) -> dict[str, Any]:
        with self._locked():
            state = self._load()
            total = max(int(total_flags or 0), int(state.get("total_flags", 0)))
            state["total_flags"] = total
            self._write(state)
            return state

    def record_submission(
        self,
        response: dict[str, Any],
        *,
        attempt_id: str = "primary",
    ) -> dict[str, Any]:
        """Record authoritative platform progress without storing raw flags."""
        with self._locked():
            state = self._load()
            correct = bool(response.get("correct"))
            total = int(response.get("total_flag_count", 0) or 0)
            count = int(response.get("correct_flag_count", 0) or 0)
            matched = response.get("matched_flag_index")
            if total > 0:
                state["total_flags"] = max(int(state.get("total_flags", 0)), total)
            state["correct_flags"] = max(int(state.get("correct_flags", 0)), count)
            if matched is not None and correct:
                index = str(int(matched))
                state.setdefault("flags", {}).setdefault(index, {})
                state["flags"][index].update({
                    "status": "submitted",
                    "last_attempt": str(attempt_id),
                    "updated_at": time.time(),
                })
            state["completed"] = bool(response.get("is_completed"))
            if correct:
                state["current_stage"] = self._stage_for(
                    state["correct_flags"], state["total_flags"]
                )
            state.setdefault("events", []).append({
                "kind": "submission_result",
                "correct": correct,
                "correct_flags": state["correct_flags"],
                "total_flags": state["total_flags"],
                "matched_index": matched,
                "attempt_id": str(attempt_id),
                "timestamp": time.time(),
            })
            state["events"] = state["events"][-50:]
            self._write(state)
            try:
                from solver.runtime.state_events import StateEventLog
                StateEventLog(self.challenge_dir).append(
                    "flag_progressed",
                    {
                        "correct": correct,
                        "correct_flags": state["correct_flags"],
                        "total_flags": state["total_flags"],
                        "matched_index": matched,
                    },
                    attempt_id=attempt_id,
                )
            except Exception:
                pass
            return state

    def reconcile_state(self, state_response: dict[str, Any]) -> dict[str, Any]:
        with self._locked():
            state = self._load()
            total = int(state_response.get("flag_count", 0) or 0)
            count = int(state_response.get("correct_flag_count", 0) or 0)
            state["total_flags"] = max(int(state.get("total_flags", 0)), total)
            state["correct_flags"] = max(int(state.get("correct_flags", 0)), count)
            state["completed"] = bool(state_response.get("is_completed"))
            state["current_stage"] = self._stage_for(
                state["correct_flags"], state["total_flags"]
            )
            self._write(state)
            return state

    def snapshot(self) -> dict[str, Any]:
        with self._locked():
            return self._load()

    @staticmethod
    def _stage_for(correct: int, total: int) -> str:
        if total > 0 and correct >= total:
            return "complete"
        return f"stage_{correct + 1}"

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or int(data.get("version", self.VERSION)) != self.VERSION:
                raise ValueError("unsupported stage ledger")
            return {**self._empty(), **data}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return self._empty()

    def _write(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {**state, "version": self.VERSION, "updated_at": time.time()}
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    @classmethod
    def _empty(cls) -> dict[str, Any]:
        return {
            "version": cls.VERSION,
            "total_flags": 0,
            "correct_flags": 0,
            "current_stage": "stage_1",
            "completed": False,
            "flags": {},
            "events": [],
        }
