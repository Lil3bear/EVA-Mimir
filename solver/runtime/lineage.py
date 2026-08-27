"""Append-only session lineage for durable solver sessions.

The lineage is a small JSONL tree.  A session never rewrites its prior
messages; compaction, recovery, forks and checkpoints are appended nodes with
parent references.  Higher-level projections may be rebuilt from this log.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable


class SessionLineage:
    """Durable append-only event tree for one solver attempt."""

    VERSION = 1

    def __init__(
        self,
        path: str | Path,
        *,
        session_id: str | None = None,
        parent_id: str = "",
        branch_id: str | None = None,
        scope: dict[str, str] | None = None,
    ) -> None:
        self.path = Path(path)
        self.session_id = session_id or uuid.uuid4().hex
        self.parent_id = parent_id
        self.branch_id = branch_id or self.session_id
        self.scope = dict(scope or {})
        self._lock = threading.RLock()
        # A fork starts its branch at the parent event.
        self._cursor = parent_id

    def start(self, metadata: dict[str, Any] | None = None) -> str:
        return self.append(
            "session_started",
            {"metadata": metadata or {}, "version": self.VERSION},
            parent_id=self.parent_id,
        )

    def append(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        parent_id: str | None = None,
    ) -> str:
        event_id = uuid.uuid4().hex
        event = {
            "event_id": event_id,
            "session_id": self.session_id,
            "branch_id": self.branch_id,
            "parent_id": self._cursor if parent_id is None else parent_id,
            "scope": self.scope,
            "kind": str(kind),
            "payload": _json_safe(payload or {}),
            "timestamp": time.time(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with self._lock:
            with lock_path.open("a+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    event["seq"] = _next_seq(self.path)
                    with self.path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
                        handle.flush()
                        os.fsync(handle.fileno())
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
            self._cursor = event_id
        return event_id

    def checkpoint(self, *, round_num: int, messages: Iterable[dict[str, Any]]) -> str:
        return self.append(
            "history_checkpoint",
            {"round": int(round_num), "messages": list(_json_safe(list(messages)))},
        )

    def compact(
        self,
        summary: str,
        *,
        round_num: int = 0,
        first_kept_event_id: str = "",
    ) -> str:
        return self.append(
            "compaction",
            {
                "round": int(round_num),
                "summary": str(summary),
                "first_kept_event_id": first_kept_event_id,
            },
        )

    def fork(self, *, branch_id: str | None = None) -> "SessionLineage":
        """Create a child lineage whose first event points to this cursor."""
        return SessionLineage(
            self.path,
            session_id=uuid.uuid4().hex,
            parent_id=self._cursor,
            branch_id=branch_id or uuid.uuid4().hex,
            scope=self.scope,
        )

    def finish(self, reason: str) -> str:
        return self.append("session_finished", {"reason": str(reason)})

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


def _next_seq(path: Path) -> int:
    if not path.exists():
        return 1
    last = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                last = max(last, int(json.loads(line).get("seq", 0)))
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
    return last + 1


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
