"""Challenge-scoped hypothesis claims and leases.

Claims are coordination metadata, not solver memory.  They prevent parallel
attempts from spending the same budget on one hypothesis while allowing an
expired lease to be reclaimed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

if sys.platform != "win32":
    import fcntl


class ClaimStore:
    VERSION = 1
    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(self, challenge_dir: str | Path):
        self.challenge_dir = Path(challenge_dir)
        self.path = self.challenge_dir / "shared" / "claims.json"
        self.lock_path = self.challenge_dir / "locks" / "claims.lock"

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

    @staticmethod
    def key(description: str) -> str:
        normalized = " ".join(str(description or "").strip().lower().split())
        normalized = re.sub(r"\s+", " ", normalized)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]

    def claim(
        self,
        description: str,
        *,
        owner: str,
        round_num: int = 0,
        lease_rounds: int = 8,
    ) -> tuple[bool, dict]:
        key = self.key(description)
        now_round = int(round_num or 0)
        lease_until = now_round + max(1, int(lease_rounds or 8))
        with self._locked():
            state = self._load()
            self._expire(state, now_round)
            existing = state["claims"].get(key)
            if existing and existing.get("status") == "claimed" and existing.get("owner") != owner:
                self._write(state)
                return False, dict(existing)
            record = {
                "key": key,
                "description": str(description).strip(),
                "owner": str(owner or "primary"),
                "status": "claimed",
                "round": now_round,
                "lease_until": lease_until,
                "updated_at": time.time(),
            }
            state["claims"][key] = record
            self._write(state)
            try:
                from solver.runtime.state_events import StateEventLog
                StateEventLog(self.challenge_dir).append(
                    "hypothesis_claimed",
                    {"claim_key": key, "status": "claimed"},
                    attempt_id=owner,
                )
            except Exception:
                pass
            return True, record

    def release_owner(self, owner: str, *, status: str = "released") -> int:
        """Release all claims held by an attempt when its session ends."""
        released = 0
        with self._locked():
            state = self._load()
            for record in state["claims"].values():
                if record.get("status") == "claimed" and record.get("owner") == owner:
                    record["status"] = status
                    record["lease_until"] = 0
                    record["updated_at"] = time.time()
                    released += 1
            if released:
                self._write(state)
                try:
                    from solver.runtime.state_events import StateEventLog
                    StateEventLog(self.challenge_dir).append(
                        "hypothesis_claims_released",
                        {"count": released, "status": status},
                        attempt_id=owner,
                    )
                except Exception:
                    pass
        return released

    def release(self, description: str, *, owner: str, status: str = "released") -> bool:
        key = self.key(description)
        with self._locked():
            state = self._load()
            record = state["claims"].get(key)
            if not record or record.get("owner") != owner:
                return False
            record["status"] = status
            record["updated_at"] = time.time()
            record["lease_until"] = 0
            self._write(state)
            return True

    def list_active(self, *, round_num: int = 0) -> list[dict]:
        with self._locked():
            state = self._load()
            self._expire(state, int(round_num or 0))
            self._write(state)
            return [dict(value) for value in state["claims"].values() if value.get("status") == "claimed"]

    def _expire(self, state: dict, round_num: int) -> None:
        for value in state["claims"].values():
            if value.get("status") == "claimed" and int(value.get("lease_until", 0)) < round_num:
                value["status"] = "expired"
                value["updated_at"] = time.time()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"version": self.VERSION, "claims": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or int(value.get("version", self.VERSION)) != self.VERSION:
                raise ValueError("unsupported claims state")
            value.setdefault("claims", {})
            return value
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {"version": self.VERSION, "claims": {}}

    def _write(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        state = {"version": self.VERSION, "claims": state.get("claims", {}), "updated_at": time.time()}
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
