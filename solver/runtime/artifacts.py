"""Typed, append-only evidence bus for cross-attempt collaboration."""

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


class ArtifactBus:
    VERSION = 1

    def __init__(self, challenge_dir: str | Path):
        self.challenge_dir = Path(challenge_dir)
        self.path = self.challenge_dir / "shared" / "artifacts.jsonl"
        self.lock_path = self.challenge_dir / "locks" / "artifacts.lock"
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
        artifact_type: str,
        value: str,
        producer_attempt: str,
        proof_ref: str = "",
        confidence: float = 0.5,
        contract_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        artifact = {
            "artifact_id": f"artifact_{uuid.uuid4().hex}",
            "version": self.VERSION,
            "status": "pending",
            "artifact_type": str(artifact_type),
            "value": str(value),
            "producer_attempt": str(producer_attempt or "primary"),
            "proof_ref": str(proof_ref),
            "confidence": max(0.0, min(1.0, float(confidence))),
            "contract_id": str(contract_id),
            "metadata": metadata or {},
            "created_at": time.time(),
        }
        self._append(artifact)
        try:
            from solver.runtime.state_events import StateEventLog
            StateEventLog(self.challenge_dir).append(
                "artifact_published",
                {"artifact_id": artifact["artifact_id"], "artifact_type": artifact_type},
                attempt_id=producer_attempt,
                run_id=contract_id,
            )
        except Exception:
            pass
        return artifact

    def list(self, *, status: str = "", limit: int = 100) -> list[dict[str, Any]]:
        with self._locked():
            items = self._read_items()
        if status:
            items = [item for item in items if item.get("status") == status]
        return items[-max(1, int(limit or 100)):]

    def _read_items(self) -> list[dict[str, Any]]:
        items = []
        if not self.path.exists():
            return items
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                items.append(item)
        return items

    def approve(self, artifact_id: str, *, reviewer: str = "observer") -> dict[str, Any] | None:
        with self._locked():
            items = self._read_items()
            target = next((item for item in reversed(items) if item.get("artifact_id") == artifact_id), None)
            if target is None:
                return None
            if target.get("status") == "pending":
                target = {**target, "status": "approved", "reviewer": reviewer, "reviewed_at": time.time()}
                self._append(target)
                try:
                    from solver.runtime.state_events import StateEventLog
                    StateEventLog(self.challenge_dir).append(
                        "artifact_approved",
                        {"artifact_id": artifact_id},
                        attempt_id=reviewer,
                    )
                except Exception:
                    pass
            return target

    def reject(self, artifact_id: str, *, reviewer: str = "observer", reason: str = "") -> dict[str, Any] | None:
        with self._locked():
            items = self._read_items()
            target = next((item for item in reversed(items) if item.get("artifact_id") == artifact_id), None)
            if target is None:
                return None
            target = {**target, "status": "rejected", "reviewer": reviewer, "reason": reason, "reviewed_at": time.time()}
            self._append(target)
            return target

    def _append(self, item: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
