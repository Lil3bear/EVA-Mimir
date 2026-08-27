"""Canonical append-only state event log.

JSON state files remain projections for fast reads.  Every state mutation is
also recorded here with a hash chain so projections can be audited/rebuilt.
Sensitive values (raw flags, tokens) must never be passed in payload.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

if sys.platform != "win32":
    import fcntl


class StateEventLog:
    VERSION = 1
    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(self, challenge_dir: str | Path):
        self.challenge_dir = Path(challenge_dir)
        self.path = self.challenge_dir / "shared" / "state-events.jsonl"
        self.lock_path = self.challenge_dir / "locks" / "state-events.lock"

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

    def append(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        attempt_id: str = "",
        run_id: str = "",
    ) -> dict[str, Any]:
        with self._locked():
            previous = self._last_hash()
            event = {
                "event_id": f"state_{uuid.uuid4().hex}",
                "version": self.VERSION,
                "seq": self._next_seq(),
                "kind": str(kind),
                "challenge_id": self.challenge_dir.name,
                "attempt_id": str(attempt_id),
                "run_id": str(run_id),
                "payload": _safe(payload or {}),
                "timestamp": time.time(),
                "prev_hash": previous,
            }
            canonical = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            event["hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return event

    def events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        result = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                result.append(item)
        return result

    def validate(self) -> list[str]:
        errors: list[str] = []
        previous = ""
        expected_seq = 1
        for event in self.events():
            if event.get("seq") != expected_seq:
                errors.append(f"sequence gap: expected {expected_seq}, got {event.get('seq')}")
            if event.get("prev_hash", "") != previous:
                errors.append(f"hash chain break at {event.get('event_id')}")
            provided = event.get("hash", "")
            unsigned = {key: value for key, value in event.items() if key != "hash"}
            canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            calculated = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if provided != calculated:
                errors.append(f"hash mismatch at {event.get('event_id')}")
            previous = provided
            expected_seq += 1
        return errors

    def _next_seq(self) -> int:
        return len(self.events()) + 1

    def _last_hash(self) -> str:
        events = self.events()
        return str(events[-1].get("hash", "")) if events else ""


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
