"""Layered state views for solver attempts and the observer.

State is intentionally separated into three physical scopes:

* attempt-private: raw thoughts, failures and ideas owned by one solver;
* challenge-shared: only facts explicitly promoted by the observer;
* proposals: immutable hand-off requests waiting for observer review.

The observer may inspect all attempts for one challenge, but a solver never
reads another attempt's private board directly.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Iterable

from shared.data import ideas as idea_store
from shared.data import memory as memory_store
from shared.types import IdeaRecord, MemoryEntry


PRIVATE_MEMORY_DIR = "memory"
PRIVATE_IDEAS_DIR = "ideas"
SHARED_DIR = "shared"
PROPOSALS_DIR = "proposals"


def private_root(attempt_dir: str | Path, challenge_dir: str | Path | None = None) -> Path:
    """Return the private root for one attempt.

    ``attempt_dir`` is already unique for portfolio attempts.  The fallback to
    challenge_dir keeps local bridge mode and legacy callers compatible.
    """
    attempt = Path(attempt_dir)
    if str(attempt) and str(attempt) != "/workspace":
        return attempt
    return Path(challenge_dir or "/workspace")


def shared_root(challenge_dir: str | Path) -> Path:
    return Path(challenge_dir) / SHARED_DIR


def _dedupe_by_id(items: Iterable[object]) -> list[object]:
    result: list[object] = []
    seen: set[str] = set()
    for item in sorted(items, key=lambda value: (getattr(value, "created_at", 0), getattr(value, "id", ""))):
        identifier = str(getattr(item, "id", ""))
        if identifier and identifier in seen:
            continue
        if identifier:
            seen.add(identifier)
        result.append(item)
    return result


def _legacy_root(challenge_dir: Path) -> Path:
    """Legacy root kept read-only during migration."""
    return challenge_dir


def write_root(
    challenge_dir: str | Path,
    attempt_dir: str | Path,
    scope: str = "private",
) -> Path:
    """Physical directory a solver writes new memory/ideas into.

    ``shared`` routes every attempt into one challenge-wide pool so that a
    fact found by one agent is immediately visible to its peers.  ``private``
    and ``isolated`` both keep writes attempt-local.
    """
    if scope == "shared":
        return shared_root(challenge_dir)
    return private_root(attempt_dir, challenge_dir)


def _read_roots(challenge: Path, private: Path, scope: str) -> list[Path]:
    """Ordered roots a solver reads back, per collaboration scope."""
    if scope == "isolated":
        # Fully independent racer: never sees another attempt or the shared board.
        return [private]
    if scope == "shared":
        # Collaborative pool first, then anything still pending in own private dir.
        shared = shared_root(challenge)
        return [shared] if private == shared else [shared, private]
    # "private" (default/legacy): own board + observer-approved shared facts.
    roots = [private, shared_root(challenge)]
    if private == challenge:
        roots.append(_legacy_root(challenge))
    return roots


def solver_memories(
    challenge_dir: str | Path,
    attempt_dir: str | Path,
    *,
    limit: int | None = None,
    scope: str = "private",
) -> list[MemoryEntry]:
    """Memories visible to one solver, scoped by collaboration mode."""
    challenge = Path(challenge_dir)
    private = private_root(attempt_dir, challenge)
    roots = _read_roots(challenge, private, scope)
    entries: list[MemoryEntry] = []
    for root in roots:
        entries.extend(memory_store.list_memory(root))
    merged = _dedupe_by_id(entries)
    if limit:
        merged = merged[-limit:]
    return [item for item in merged if isinstance(item, MemoryEntry)]


def solver_ideas(
    challenge_dir: str | Path,
    attempt_dir: str | Path,
    *,
    limit: int | None = None,
    scope: str = "private",
) -> list[IdeaRecord]:
    challenge = Path(challenge_dir)
    private = private_root(attempt_dir, challenge)
    roots = _read_roots(challenge, private, scope)
    ideas: list[IdeaRecord] = []
    for root in roots:
        ideas.extend(idea_store.list_ideas(root))
    merged = _dedupe_by_id(ideas)
    if limit:
        merged = merged[-limit:]
    return [item for item in merged if isinstance(item, IdeaRecord)]


def observer_memories(challenge_dir: str | Path) -> list[MemoryEntry]:
    """Observer-only aggregate view of all attempts for one challenge."""
    challenge = Path(challenge_dir)
    roots = [shared_root(challenge), _legacy_root(challenge)]
    attempts = challenge / "attempts"
    if attempts.is_dir():
        roots.extend(path for path in attempts.iterdir() if path.is_dir())
    entries: list[MemoryEntry] = []
    for root in roots:
        entries.extend(memory_store.list_memory(root))
    return [item for item in _dedupe_by_id(entries) if isinstance(item, MemoryEntry)]


def observer_ideas(challenge_dir: str | Path) -> list[IdeaRecord]:
    challenge = Path(challenge_dir)
    roots = [shared_root(challenge), _legacy_root(challenge)]
    attempts = challenge / "attempts"
    if attempts.is_dir():
        roots.extend(path for path in attempts.iterdir() if path.is_dir())
    ideas: list[IdeaRecord] = []
    for root in roots:
        ideas.extend(idea_store.list_ideas(root))
    return [item for item in _dedupe_by_id(ideas) if isinstance(item, IdeaRecord)]


def find_idea_root(challenge_dir: str | Path, idea_id: str) -> Path | None:
    """Find the physical owner of an idea so Observer updates stay scoped."""
    challenge = Path(challenge_dir)
    roots = [shared_root(challenge), _legacy_root(challenge)]
    attempts = challenge / "attempts"
    if attempts.is_dir():
        roots.extend(path for path in attempts.iterdir() if path.is_dir())
    for root in roots:
        for idea in idea_store.list_ideas(root):
            if idea.id == idea_id or idea.id.startswith(idea_id):
                return root
    return None


def _proposal_path(challenge_dir: str | Path, proposal_id: str) -> Path:
    return shared_root(challenge_dir) / PROPOSALS_DIR / f"{proposal_id}.json"


def publish_memory_proposal(
    challenge_dir: str | Path,
    *,
    attempt_id: str,
    kind: str,
    content: str,
    refs: list[str] | None = None,
) -> str:
    """Write an immutable-ish proposal; it is not visible to solvers yet."""
    proposal_id = f"proposal_{os.urandom(6).hex()}"
    path = _proposal_path(challenge_dir, proposal_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "id": proposal_id,
        "status": "pending",
        "kind": kind,
        "content": content,
        "refs": refs or [],
        "source_attempt": attempt_id or "primary",
        "created_at": time.time(),
    }
    tmp = path.with_suffix(f".{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return proposal_id


def list_memory_proposals(challenge_dir: str | Path, *, status: str = "pending") -> list[dict]:
    directory = shared_root(challenge_dir) / PROPOSALS_DIR
    if not directory.is_dir():
        return []
    result = []
    for path in sorted(directory.glob("proposal_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if status and data.get("status") != status:
            continue
        result.append(data)
    return result


def promote_memory_proposal(challenge_dir: str | Path, proposal_id: str) -> str:
    path = _proposal_path(challenge_dir, proposal_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "[错误] proposal 不存在或格式错误"
    if data.get("status") == "approved":
        return f"[共享证据] 已批准 {proposal_id}"
    if data.get("status") != "pending":
        return f"[共享证据] proposal 状态为 {data.get('status', 'unknown')}，未处理"

    entry, created = memory_store.add_memory_with_status(
        shared_root(challenge_dir),
        kind=str(data.get("kind", "fact")),
        content=str(data.get("content", "")),
        refs=list(data.get("refs") or []),
        source="observer-approved",
        attempt_id=str(data.get("source_attempt", "")),
    )
    data["status"] = "approved"
    data["approved_at"] = time.time()
    data["approved_memory_id"] = entry.id
    tmp = path.with_suffix(f".{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return f"[共享证据] {'已新增' if created else '已去重'} {entry.id}（proposal={proposal_id}）"
