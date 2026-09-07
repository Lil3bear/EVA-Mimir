"""Structured, rollback-able refinement log for one challenge's memory board.

Adapts Prime Agent's continual-harness idea (small, evidence-backed
create/update/delete edits with recorded history and rollback) to EVA-Mimir's
compliance boundary:

- every event carries an explicit :class:`HarnessScope` (attempt-private vs
  challenge-shared);
- the ledger lives physically under the challenge directory, so facts,
  flags and credentials can never leak across challenges;
- rollback is supported but refuses to delete ``evidence`` entries — verified
  flags/credentials are ground truth the Observer may never erase.

The ledger is append-only (like Prime Agent's ``refinements.jsonl``): rollback
appends a tombstone instead of rewriting history, so every edit is auditable.
"""

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any

from shared.data import memory as memory_store
from shared.types import MemoryEntry

if sys.platform != "win32":
    import fcntl


class HarnessScope(str, Enum):
    """Explicit state-scope semantics.

    Both scopes are physically inside the challenge directory; there is
    deliberately no cross-challenge scope.
    """

    ATTEMPT_PRIVATE = "attempt_private"    # one solver's raw thoughts/failures
    CHALLENGE_SHARED = "challenge_shared"  # observer-approved facts, all attempts


_EVIDENCE_KIND = "evidence"
_REFINEMENTS_FILE = "refinements.jsonl"
_LOCK_TIMEOUT = 5.0
_LOCK_RETRY = 0.025


def shared_root(challenge_dir: str | Path) -> Path:
    """Challenge-wide pool (mirrors scoped_state without importing it)."""
    return Path(challenge_dir) / "shared"


def classify_scope(challenge_dir: str | Path, write_dir: str | Path) -> HarnessScope:
    """Infer the explicit scope from the physical write directory."""
    if Path(write_dir).resolve() == shared_root(challenge_dir).resolve():
        return HarnessScope.CHALLENGE_SHARED
    return HarnessScope.ATTEMPT_PRIVATE


@contextmanager
def _append_lock(lock_path: Path):
    if sys.platform == "win32":
        yield
        return
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + _LOCK_TIMEOUT
    handle = None
    while True:
        try:
            handle = open(lock_path, "w")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except (IOError, OSError):
            if handle:
                handle.close()
                handle = None
            if time.time() > deadline:
                raise TimeoutError(f"无法获取锁：{lock_path}")
            time.sleep(_LOCK_RETRY)
    try:
        yield
    finally:
        if handle:
            fcntl.flock(handle, fcntl.LOCK_UN)
            handle.close()


class RefinementLog:
    """Append-only JSONL ledger of memory-board edits with rollback."""

    def __init__(self, challenge_dir: str | Path):
        self.challenge_dir = Path(challenge_dir)
        self.path = self.challenge_dir / "memory" / _REFINEMENTS_FILE
        self.lock_path = self.challenge_dir / "locks" / "refinements.lock"

    # ---- ledger -------------------------------------------------------

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        event.setdefault("id", f"ref_{os.urandom(6).hex()}")
        event.setdefault("created_at", time.time())
        event.setdefault("rolled_back", False)
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        with _append_lock(self.lock_path):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(line)
        return event

    def list(self, limit: int | None = None) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        with open(self.path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        if limit:
            events = events[-limit:]
        return events

    def get(self, refinement_id: str) -> dict[str, Any] | None:
        for event in self.list():
            if event.get("id") == refinement_id or event.get("id", "").startswith(
                refinement_id
            ):
                return event
        return None

    def is_rolled_back(self, refinement_id: str) -> bool:
        return any(
            event.get("action") == "rollback" and event.get("rollback_of") == refinement_id
            for event in self.list()
        )

    # ---- refine operations -------------------------------------------

    def refine_add(
        self,
        root: str | Path,
        *,
        kind: str,
        content: str,
        refs: list[str] | None = None,
        source: str = "observer",
        attempt_id: str = "",
        reason: str = "",
        round_num: int = 0,
    ) -> tuple[MemoryEntry, bool, dict[str, Any] | None]:
        """Add a memory entry and record a ``create`` refinement event.

        Returns ``(entry, created, event)``.  ``event`` is None when the entry
        was deduplicated (no board change to record).
        """
        root = Path(root)
        entry, created = memory_store.add_memory_with_status(
            root,
            kind=kind,
            content=content,
            refs=refs or [],
            source=source,
            attempt_id=attempt_id,
        )
        if not created:
            return entry, False, None
        event = self.append(
            {
                "action": "create",
                "kind": kind,
                "memory_id": entry.id,
                "scope": classify_scope(self.challenge_dir, root).value,
                "reason": reason,
                "root": str(root),
                "before": None,
                "after": entry.__dict__,
                "source": source,
                "attempt_id": attempt_id,
                "round_num": round_num,
            }
        )
        return entry, True, event

    def refine_update(
        self,
        root: str | Path,
        *,
        memory_id: str,
        content: str,
        reason: str = "",
        round_num: int = 0,
    ) -> tuple[bool, dict[str, Any] | None]:
        root = Path(root)
        before = self._find_entry(root, memory_id)
        ok = memory_store.update_memory(root, memory_id, content=content)
        if not ok:
            return False, None
        event = self.append(
            {
                "action": "update",
                "kind": before.kind if before else "note",
                "memory_id": memory_id,
                "scope": classify_scope(self.challenge_dir, root).value,
                "reason": reason,
                "root": str(root),
                "before": before.__dict__ if before else None,
                "after": (before.__dict__ if before else {}) | {"content": content},
                "source": "observer",
                "attempt_id": getattr(before, "attempt_id", "") if before else "",
                "round_num": round_num,
            }
        )
        return True, event

    def refine_delete(
        self,
        root: str | Path,
        *,
        memory_id: str,
        reason: str = "",
        round_num: int = 0,
    ) -> tuple[bool, dict[str, Any] | None]:
        root = Path(root)
        before = self._find_entry(root, memory_id)
        ok = memory_store.delete_memory(root, memory_id)
        if not ok:
            return False, None
        event = self.append(
            {
                "action": "delete",
                "kind": before.kind if before else "note",
                "memory_id": memory_id,
                "scope": classify_scope(self.challenge_dir, root).value,
                "reason": reason,
                "root": str(root),
                "before": before.__dict__ if before else None,
                "after": None,
                "source": "observer",
                "attempt_id": getattr(before, "attempt_id", "") if before else "",
                "round_num": round_num,
            }
        )
        return True, event

    # ---- rollback -----------------------------------------------------

    def rollback(self, refinement_id: str) -> dict[str, Any]:
        """Undo one refinement event and record a tombstone.

        Refuses to delete an ``evidence`` entry so verified flags/credentials
        are never lost by an automated rollback.
        """
        event = self.get(refinement_id)
        if event is None:
            return {"ok": False, "error": f"未找到 refinement {refinement_id}"}
        if self.is_rolled_back(refinement_id):
            return {"ok": False, "error": f"{refinement_id} 已回滚过"}

        action = event.get("action")
        root = Path(event.get("root", self.challenge_dir))
        before = event.get("before") or {}
        after = event.get("after") or {}
        memory_id = str(event.get("memory_id", ""))
        kind = str(event.get("kind", "note"))

        # create（solver/observer 新增）和 promote（批准提案进共享层）在物理
        # 上都是"新增了一条记忆"，回滚即删除该条；evidence 永不删除。
        if action in ("create", "promote"):
            if kind == _EVIDENCE_KIND:
                return {"ok": False, "error": f"evidence 不可删除，拒绝回滚 {action}"}
            undone = memory_store.delete_memory(root, memory_id)
        elif action == "update":
            undone = memory_store.update_memory(
                root, memory_id, content=str(before.get("content", ""))
            )
        elif action == "delete":
            # 用原始 id 恢复，保持审计链一致（而非 add 出一个新 id）。
            undone = memory_store.restore_memory(root, before)
            memory_id = str(before.get("id", memory_id)) or memory_id
        else:
            return {"ok": False, "error": f"不支持回滚 action={action}"}

        if not undone:
            return {"ok": False, "error": f"回滚失败（条目可能已不存在）：{memory_id}"}

        tombstone = self.append(
            {
                "action": "rollback",
                "rollback_of": refinement_id,
                "kind": kind,
                "memory_id": memory_id,
                "scope": event.get("scope"),
                "root": str(root),
                "reason": "rollback",
            }
        )
        return {
            "ok": True,
            "refinement_id": refinement_id,
            "tombstone_id": tombstone["id"],
            "action": action,
            "memory_id": memory_id,
        }

    # ---- helpers ------------------------------------------------------

    def _find_entry(self, root: Path, memory_id: str) -> MemoryEntry | None:
        for entry in memory_store.list_memory(root):
            if entry.id == memory_id or entry.id.startswith(memory_id):
                return entry
        return None
