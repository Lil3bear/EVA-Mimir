"""Explicit execution context for parallel challenge attempts.

Challenge state is shared through ``challenge_dir``. An attempt gets its own
``attempt_dir`` for scripts, tool output, and conversation history.
"""

from __future__ import annotations

import os
import tempfile
import threading
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class RunContext:
    unique_code: str
    challenge_id: str
    challenge_dir: str
    target_url: str = ""
    attempt_id: str = "primary"
    attempt_dir: str = ""
    # Monotonic wall-clock deadline for the current benchmark run.  A zero
    # value means that the caller did not provide a deadline (local bridge
    # mode remains backwards compatible).
    deadline: float = 0.0
    # Stable identifier shared by retries in one process.  It is deliberately
    # not the benchmark token, so it is safe to persist in local state files.
    run_id: str = ""

    def __post_init__(self) -> None:
        challenge_dir = str(Path(self.challenge_dir))
        attempt_dir = str(Path(self.attempt_dir or challenge_dir))
        object.__setattr__(self, "challenge_dir", challenge_dir)
        object.__setattr__(self, "attempt_dir", attempt_dir)

    @classmethod
    def create(
        cls,
        workspace_dir: str,
        unique_code: str,
        *,
        target_url: str = "",
        attempt_id: str = "primary",
        isolate_attempt: bool = False,
        deadline: float = 0.0,
        run_id: str = "",
    ) -> "RunContext":
        challenge_dir = Path(workspace_dir) / unique_code
        attempt_dir = (
            challenge_dir / "attempts" / attempt_id
            if isolate_attempt
            else challenge_dir
        )
        return cls(
            unique_code=unique_code,
            challenge_id=unique_code,
            challenge_dir=str(challenge_dir),
            target_url=target_url,
            attempt_id=attempt_id,
            attempt_dir=str(attempt_dir),
            deadline=deadline,
            run_id=run_id,
        )

    @classmethod
    def from_environment(cls) -> "RunContext":
        workspace = os.environ.get("CTF_WORKSPACE") or str(
            Path(tempfile.gettempdir()) / "eva-mimir"
        )
        challenge_id = os.environ.get("CTF_CHALLENGE_ID", "")
        challenge_dir = Path(workspace)
        if challenge_id and challenge_dir.name != challenge_id:
            challenge_dir /= challenge_id
        return cls(
            unique_code=challenge_id,
            challenge_id=challenge_id,
            challenge_dir=str(challenge_dir),
            target_url=os.environ.get("CTF_TARGET_URL", ""),
            deadline=float(os.environ.get("SOLVER_DEADLINE_EPOCH", "0") or 0),
            run_id=os.environ.get("CTF_RUN_ID", ""),
        )

    def for_attempt(self, attempt_id: str) -> "RunContext":
        return replace(
            self,
            attempt_id=attempt_id,
            attempt_dir=str(Path(self.challenge_dir) / "attempts" / attempt_id),
        )


class WorkerContext(threading.local):
    """Thread-local holder populated from an explicit :class:`RunContext`."""

    def __init__(self) -> None:
        super().__init__()
        self.reset()

    def configure(self, run: RunContext, client=None) -> None:
        Path(run.challenge_dir).mkdir(parents=True, exist_ok=True)
        Path(run.attempt_dir).mkdir(parents=True, exist_ok=True)
        self.run = run
        self.unique_code = run.unique_code
        self.challenge_id = run.challenge_id
        self.challenge_dir = run.challenge_dir
        self.target_url = run.target_url
        self.attempt_id = run.attempt_id
        self.attempt_dir = run.attempt_dir
        self.deadline = run.deadline
        self.run_id = run.run_id
        self.workspace = str(Path(run.challenge_dir).parent)
        self.client = client

    def snapshot(self) -> RunContext:
        if self.run is not None:
            return self.run
        return RunContext.from_environment()

    @contextmanager
    def bind(self, run: RunContext, client=None) -> Iterator["WorkerContext"]:
        previous = self.run
        previous_client = self.client
        self.reset()
        self.configure(run, client)
        try:
            yield self
        finally:
            self.reset()
            if previous is not None:
                self.configure(previous, previous_client)

    def reset(self) -> None:
        self.run: RunContext | None = None
        self.unique_code = ""
        self.client = None
        self.terminal_error = None
        self.workspace = "/workspace"
        self.challenge_id = ""
        self.target_url = ""
        self.challenge_dir = "/workspace"
        self.attempt_id = "primary"
        self.attempt_dir = "/workspace"
        self.deadline = 0.0
        self.run_id = ""
        self.recent_fingerprints: list[str] = []
        self.approach_counter: Counter = Counter()
        self.host_fail_counter: Counter = Counter()
        self.observer_trigger_callback = None


ctx = WorkerContext()
