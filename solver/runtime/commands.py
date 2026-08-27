"""Append-only Observer command bus.

Commands are durable, scoped to one challenge/attempt, versioned and
acknowledged by the receiving Solver.  Text corrections remain supported, but
coordination no longer depends on parsing free-form prose.
"""

from __future__ import annotations

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


COMMAND_ACTIONS = frozenset({
    "assign_hypothesis",
    "approve_artifact",
    "promote_evidence",
    "review_blackboard",
    "switch_strategy",
    "pause_attempt",
    "resume_attempt",
    "fork_attempt",
    "close_attempt",
})


class CommandBus:
    VERSION = 1

    def __init__(self, challenge_dir: str | Path):
        self.challenge_dir = Path(challenge_dir)
        self.path = self.challenge_dir / "shared" / "commands.jsonl"
        self.lock_path = self.challenge_dir / "locks" / "commands.lock"
        self._local_lock = threading.RLock()

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._local_lock, self.lock_path.open("a+") as handle:
            if sys.platform != "win32":
                fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if sys.platform != "win32":
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def publish(
        self,
        *,
        action: str,
        target_attempt: str = "*",
        payload: dict[str, Any] | None = None,
        state_version: int = 0,
        expires_after_rounds: int = 8,
        issued_by: str = "observer",
        round_num: int = 0,
    ) -> dict[str, Any]:
        action = str(action).strip()
        if action not in COMMAND_ACTIONS:
            raise ValueError(f"unsupported command action: {action}")
        command = {
            "command_id": f"command_{uuid.uuid4().hex}",
            "version": self.VERSION,
            "status": "pending",
            "action": action,
            "target_attempt": str(target_attempt or "*"),
            "payload": payload or {},
            "state_version": int(state_version or 0),
            "issued_by": str(issued_by or "observer"),
            "round_num": int(round_num or 0),
            "expires_after_rounds": max(1, int(expires_after_rounds or 8)),
            "created_at": time.time(),
        }
        self._append(command)
        try:
            from solver.runtime.state_events import StateEventLog
            StateEventLog(self.challenge_dir).append(
                "observer_command_published",
                {"command_id": command["command_id"], "action": action, "target": target_attempt},
                attempt_id=issued_by,
                run_id=str(payload.get("run_id", "")) if isinstance(payload, dict) else "",
            )
        except Exception:
            pass
        return command

    def pending(self, *, attempt_id: str, round_num: int = 0) -> list[dict[str, Any]]:
        with self._locked():
            events = self._read_events()
        latest: dict[str, dict[str, Any]] = {}
        for event in events:
            command_id = event.get("command_id")
            if command_id:
                latest[command_id] = event
        result = []
        current_round = int(round_num or 0)
        for command in latest.values():
            if command.get("status") != "pending":
                continue
            target = command.get("target_attempt", "*")
            if target not in {"*", attempt_id}:
                continue
            issued_round = int(command.get("round_num", 0) or 0)
            ttl = int(command.get("expires_after_rounds", 8) or 8)
            if current_round and issued_round and current_round > issued_round + ttl:
                continue
            result.append(command)
        return sorted(result, key=lambda item: (item.get("created_at", 0), item.get("command_id", "")))

    def acknowledge(self, command_id: str, *, attempt_id: str, result: str = "") -> bool:
        with self._locked():
            events = self._read_events()
            target = next(
                (event for event in reversed(events)
                 if event.get("command_id") == command_id and event.get("status") == "pending"),
                None,
            )
            if target is None:
                return False
            self._append({
                **target,
                "status": "acknowledged",
                "ack_attempt": str(attempt_id),
                "ack_result": str(result),
                "acknowledged_at": time.time(),
            })
            try:
                from solver.runtime.state_events import StateEventLog
                StateEventLog(self.challenge_dir).append(
                    "observer_command_acknowledged",
                    {"command_id": command_id, "result": result},
                    attempt_id=attempt_id,
                )
            except Exception:
                pass
            return True

    def _append(self, event: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _read_events(self) -> list[dict[str, Any]]:
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
