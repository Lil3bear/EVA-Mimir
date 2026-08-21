"""Durable tool-call boundaries for crash-safe solver recovery."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any


SAFE_REPLAY_TOOLS = frozenset({
    "read_file",
    "grep",
    "memory_list",
    "idea_list",
    "challenge_get_state",
    "security_search",
})


class ExecutionJournal:
    """Append-only prepared/completed log, fsynced around every tool effect."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.run_id = uuid.uuid4().hex
        self._lock = threading.Lock()

    def start(self) -> dict[str, Any]:
        events = self._read()
        recovery = self._recovery_state(events)
        self._append({"type": "run_started", "run_id": self.run_id})
        return recovery

    def prepare(self, call_id: str, tool: str, args: dict, round_num: int) -> None:
        self._append({
            "type": "prepared",
            "run_id": self.run_id,
            "call_id": call_id,
            "round": round_num,
            "tool": tool,
            "args": args,
        })

    def complete(
        self,
        call_id: str,
        tool: str,
        result: str,
        *,
        run_id: str | None = None,
        recovered: bool = False,
    ) -> None:
        self._append({
            "type": "completed",
            "run_id": run_id or self.run_id,
            "call_id": call_id,
            "tool": tool,
            "result": self._result_excerpt(result),
            "recovered_by": self.run_id if recovered else None,
        })

    def finish(self, reason: str) -> None:
        self._append({"type": "run_finished", "run_id": self.run_id, "reason": reason})

    def _append(self, event: dict[str, Any]) -> None:
        event = {**event, "timestamp": time.time()}
        payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
        return events

    @staticmethod
    def _recovery_state(events: list[dict[str, Any]]) -> dict[str, Any]:
        if not events:
            return {"pending": [], "recent_completed": [], "previous_run_id": ""}

        started = [e for e in events if e.get("type") == "run_started"]
        previous_run_id = started[-1].get("run_id", "") if started else ""
        finished = {
            e.get("run_id") for e in events if e.get("type") == "run_finished"
        }
        completed_keys = {
            (e.get("run_id"), e.get("call_id"))
            for e in events if e.get("type") == "completed"
        }
        pending_by_key: dict[tuple[Any, Any], dict[str, Any]] = {}
        for event in events:
            if event.get("type") != "prepared":
                continue
            key = (event.get("run_id"), event.get("call_id"))
            if key not in completed_keys:
                pending_by_key[key] = event

        interrupted = bool(previous_run_id and previous_run_id not in finished)
        recent_completed = []
        if interrupted:
            recent_completed = [
                e for e in events
                if e.get("type") == "completed" and e.get("run_id") == previous_run_id
            ][-6:]
        return {
            "pending": list(pending_by_key.values()),
            "recent_completed": recent_completed,
            "previous_run_id": previous_run_id if interrupted else "",
        }

    @staticmethod
    def _result_excerpt(result: str, limit: int = 8000) -> str:
        if len(result) <= limit:
            return result
        half = limit // 2
        return result[:half] + "\n...[journal truncated]...\n" + result[-half:]
