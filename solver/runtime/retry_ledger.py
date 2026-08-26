"""Durable scheduler retry/abandon state scoped to one benchmark task."""

from __future__ import annotations

import hashlib
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


class RetryLedger:
    VERSION = 1
    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(self, workspace_dir: str | Path, task_id: str = ""):
        self.workspace_dir = Path(workspace_dir)
        self.path = self.workspace_dir / ".scheduler-retry-ledger.json"
        self.lock_path = self.workspace_dir / "locks" / "scheduler-retry.lock"
        self.task_id = str(task_id or "")

    @staticmethod
    def task_fingerprint(base_url: str, token: str) -> str:
        if not base_url or not token:
            return ""
        return hashlib.sha256(f"{base_url}\0{token}".encode()).hexdigest()[:24]

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

    def snapshot(self) -> dict[str, Any]:
        with self._locked():
            state = self._load()
            state = self._scope_task(state)
            self._write(state)
            return state

    def record_round(
        self,
        *,
        round_num: int,
        failed_codes: set[str],
        partial_codes: set[str],
        solved_codes: set[str],
        max_fail_streak: int,
    ) -> dict[str, Any]:
        with self._locked():
            state = self._scope_task(self._load())
            fail_streak = state.setdefault("fail_streak", {})
            attempts = state.setdefault("attempts", {})
            abandoned = set(state.setdefault("abandoned", []))
            all_codes = set(failed_codes) | set(partial_codes) | set(solved_codes)
            for code in all_codes:
                attempts[code] = int(attempts.get(code, 0)) + 1
            for code in solved_codes | partial_codes:
                fail_streak.pop(code, None)
                state.setdefault("cooldown_until_round", {}).pop(code, None)
            for code in failed_codes:
                fail_streak[code] = int(fail_streak.get(code, 0)) + 1
                # ``cooldown_until_round`` is the first round that may retry.
                # Set N+2 so round N+1 is actually skipped; round N+2 retries.
                state.setdefault("cooldown_until_round", {})[code] = int(round_num) + 2
                if fail_streak[code] >= int(max_fail_streak):
                    abandoned.add(code)
            state["abandoned"] = sorted(abandoned)
            state["last_round"] = int(round_num)
            state["updated_at"] = time.time()
            self._write(state)
            try:
                from solver.runtime.state_events import StateEventLog
                StateEventLog(self.workspace_dir).append(
                    "scheduler_retry_recorded",
                    {
                        "round": int(round_num),
                        "failed": sorted(failed_codes),
                        "partial": sorted(partial_codes),
                        "solved": sorted(solved_codes),
                        "abandoned": sorted(abandoned),
                    },
                    run_id=self.task_id,
                )
            except Exception:
                pass
            return state

    def should_skip(self, code: str, *, round_num: int) -> bool:
        state = self.snapshot()
        if code in set(state.get("abandoned", [])):
            return True
        cooldown = int(state.get("cooldown_until_round", {}).get(code, 0) or 0)
        return cooldown > int(round_num)

    def _scope_task(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("task_id") == self.task_id:
            return state
        return self._empty()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or int(data.get("version", self.VERSION)) != self.VERSION:
                raise ValueError("unsupported retry ledger")
            return {**self._empty(), **data}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return self._empty()

    def _write(self, state: dict[str, Any]) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        data = {**state, "version": self.VERSION, "task_id": self.task_id, "updated_at": time.time()}
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def _empty(self) -> dict[str, Any]:
        return {
            "version": self.VERSION,
            "task_id": self.task_id,
            "last_round": 0,
            "fail_streak": {},
            "attempts": {},
            "abandoned": [],
            "cooldown_until_round": {},
            "updated_at": time.time(),
        }
