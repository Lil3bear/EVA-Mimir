"""Small durable control ledger shared by retries and portfolio attempts."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

if sys.platform != "win32":
    import fcntl


class ChallengeLedger:
    """Persist bounded control-plane facts for one challenge.

    This is deliberately not a transcript.  It stores only deterministic
    fingerprints, the platform hint cache, and compact attempt outcomes so a
    new Agent does not treat the same evidence as fresh progress.
    """

    VERSION = 1
    MAX_FINGERPRINTS = 2048
    MAX_ATTEMPTS = 20
    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(self, challenge_dir: str | Path):
        self.challenge_dir = Path(challenge_dir)
        self.path = self.challenge_dir / ".challenge-ledger.json"
        self.lock_path = self.challenge_dir / "locks" / "challenge-ledger.lock"

    def register_fingerprints(self, fingerprints: list[str]) -> int:
        unique = list(dict.fromkeys(str(value) for value in fingerprints if value))
        if not unique:
            return 0
        with self._locked():
            state = self._load()
            existing = list(state.get("evidence_fingerprints") or [])
            seen = set(existing)
            fresh = [value for value in unique if value not in seen]
            if not fresh:
                return 0
            state["evidence_fingerprints"] = (existing + fresh)[-self.MAX_FINGERPRINTS:]
            self._write(state)
            return len(fresh)

    def cached_hints(self) -> list[str]:
        with self._locked():
            state = self._load()
            hint = state.get("hint") or {}
            if not hint.get("fetched"):
                return []
            return [str(value) for value in hint.get("hints") or [] if value]

    def get_or_fetch_hints(
        self,
        fetcher: Callable[[], list[str]],
    ) -> tuple[list[str], bool]:
        """Return hints and whether they came from the local cache.

        The lock intentionally covers the one remote fetch.  Hint is called at
        most once per challenge and the request has its own bounded timeout;
        serializing here prevents two portfolio Agents charging/asking at once.
        """
        with self._locked():
            state = self._load()
            hint = state.get("hint") or {}
            if hint.get("fetched"):
                return [str(v) for v in hint.get("hints") or [] if v], True

            hints = [str(value) for value in fetcher() if value]
            state["hint"] = {
                "fetched": True,
                "hints": hints,
                "fetched_at": time.time(),
            }
            try:
                self._write(state)
            except OSError:
                # The platform call already happened; return its authoritative
                # hint even when the optional local cache is unavailable.
                pass
            return hints, False

    def record_attempt(self, outcome: dict) -> None:
        with self._locked():
            state = self._load()
            attempts = list(state.get("attempts") or [])
            attempts.append({**outcome, "recorded_at": time.time()})
            state["attempts"] = attempts[-self.MAX_ATTEMPTS:]
            self._write(state)

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

    def _load(self) -> dict:
        if not self.path.exists():
            return self._empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("ledger root is not an object")
            if int(data.get("version", self.VERSION)) != self.VERSION:
                raise ValueError("unsupported ledger version")
            return {**self._empty(), **data}
        except (json.JSONDecodeError, UnicodeError, TypeError, ValueError):
            quarantine = self.path.with_name(
                f"{self.path.name}.corrupt.{time.time_ns()}"
            )
            try:
                os.replace(self.path, quarantine)
            except OSError:
                pass
            return self._empty()

    def _write(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        state = {**state, "version": self.VERSION, "updated_at": time.time()}
        tmp = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
        )
        try:
            tmp.write_text(
                json.dumps(state, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)

    @classmethod
    def _empty(cls) -> dict:
        return {
            "version": cls.VERSION,
            "evidence_fingerprints": [],
            "hint": {"fetched": False, "hints": []},
            "attempts": [],
        }
