"""Repo-level skill refinement ledger (RSI layer above per-challenge harness)."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from solver.runtime.harness import _append_lock

_REFINEMENTS_FILE = "refinements.jsonl"


def _skills_rsi_dir(skills_dir: str | Path) -> Path:
    return Path(skills_dir) / ".rsi"


class SkillRefinementLog:
    """Append-only ledger of skill/playbook edits tied to RSI pack runs."""

    def __init__(self, skills_dir: str | Path):
        self.skills_dir = Path(skills_dir)
        self.dir = _skills_rsi_dir(self.skills_dir)
        self.path = self.dir / _REFINEMENTS_FILE
        self.lock_path = self.dir / "refinements.lock"

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        event.setdefault("id", f"skill_{os.urandom(6).hex()}")
        event.setdefault("created_at", time.time())
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        with _append_lock(self.lock_path):
            self.dir.mkdir(parents=True, exist_ok=True)
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

    @staticmethod
    def file_sha256(path: Path) -> str:
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return ""
        return digest

    def record_edit(
        self,
        *,
        pack: str,
        reason: str,
        files: list[str],
        run_id: str = "",
        evidence_codes: list[str] | None = None,
        layer: str = "skill",
    ) -> dict[str, Any]:
        """Record a human/agent skill edit with content hashes for audit."""
        file_entries: list[dict[str, str]] = []
        for rel in files:
            rel = rel.strip().lstrip("/")
            if not rel:
                continue
            abs_path = self.skills_dir / rel
            if not abs_path.is_file():
                abs_path = Path(rel)
            file_entries.append(
                {
                    "path": rel,
                    "sha256": self.file_sha256(abs_path) if abs_path.is_file() else "",
                }
            )
        return self.append(
            {
                "action": "skill_edit",
                "pack": pack,
                "run_id": run_id,
                "layer": layer,
                "reason": reason,
                "files": file_entries,
                "evidence_codes": evidence_codes or [],
            }
        )
