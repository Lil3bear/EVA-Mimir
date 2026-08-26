"""Read-only replay and invariant checks for session lineage/evidence state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ReplayError(ValueError):
    pass


class LineageReplay:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.events = self._load()
        self.by_id = {event["event_id"]: event for event in self.events if event.get("event_id")}

    def branch(self, leaf_event_id: str | None = None) -> list[dict[str, Any]]:
        if not self.events:
            return []
        leaf = self.by_id.get(leaf_event_id) if leaf_event_id else self.events[-1]
        if leaf is None:
            raise ReplayError(f"unknown event: {leaf_event_id}")
        result = []
        seen = set()
        current = leaf
        while current:
            event_id = current.get("event_id")
            if event_id in seen:
                raise ReplayError("lineage cycle detected")
            seen.add(event_id)
            result.append(current)
            parent_id = current.get("parent_id", "")
            current = self.by_id.get(parent_id) if parent_id else None
        return list(reversed(result))

    def validate(self) -> list[str]:
        errors: list[str] = []
        seen_seq: set[int] = set()
        for event in self.events:
            event_id = event.get("event_id")
            if not event_id:
                errors.append("event without event_id")
            seq = event.get("seq")
            if seq in seen_seq:
                errors.append(f"duplicate seq: {seq}")
            if isinstance(seq, int):
                seen_seq.add(seq)
            parent_id = event.get("parent_id", "")
            if parent_id and parent_id not in self.by_id:
                errors.append(f"missing parent: {parent_id}")
        return errors

    def last_checkpoint(self) -> dict[str, Any] | None:
        return next((event for event in reversed(self.events) if event.get("kind") == "history_checkpoint"), None)

    def compactions(self) -> list[dict[str, Any]]:
        return [event for event in self.events if event.get("kind") == "compaction"]

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        result = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                result.append(event)
        return result


def validate_scoped_tree(challenge_dir: str | Path) -> list[str]:
    """Check that attempt lineage files carry the expected scope metadata."""
    root = Path(challenge_dir)
    errors: list[str] = []
    attempts = root / "attempts"
    if not attempts.is_dir():
        return errors
    for attempt in attempts.iterdir():
        if not attempt.is_dir():
            continue
        path = attempt / ".session-lineage.jsonl"
        if not path.exists():
            continue
        replay = LineageReplay(path)
        errors.extend(f"{attempt.name}: {error}" for error in replay.validate())
        for event in replay.events:
            scope = event.get("scope") or {}
            if scope.get("attempt_id") != attempt.name:
                errors.append(f"{attempt.name}: event scope mismatch")
    return errors
