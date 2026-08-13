"""
Per-worker thread-local context for parallel challenge solving.

When running multiple SolverAgents concurrently, each thread needs its own:
- challenge unique_code (for bridge_tools to know which challenge to submit to)
- tsecbench client reference
- workspace directory
- bash_tool dedup counters

Usage:
    from solver.worker_context import ctx

    # In scheduler, before launching a worker:
    ctx.unique_code = "web-01"
    ctx.client = tsecbench_client

    # In bridge_tools / bash_tool:
    code = ctx.unique_code  # thread-safe, per-worker
"""

import threading
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from solver.ctfplatform.tsecbench_client import TsecbenchClient


class _WorkerContext(threading.local):
    """Thread-local storage for per-challenge worker state."""

    def __init__(self) -> None:
        super().__init__()
        self.unique_code: str = ""
        self.client = None  # TsecbenchClient | None
        self.workspace: str = "/workspace"
        self.challenge_id: str = ""
        self.target_url: str = ""
        self.challenge_dir: str = "/workspace"  # 每题独立的工作目录

        # bash_tool dedup state (per-worker)
        self.recent_fingerprints: list[str] = []
        self.approach_counter: Counter = Counter()
        self.host_fail_counter: Counter = Counter()
        self.observer_trigger_callback = None

    def reset(self) -> None:
        """Reset all state for a new challenge."""
        self.unique_code = ""
        self.challenge_id = ""
        self.target_url = ""
        self.challenge_dir = "/workspace"
        self.recent_fingerprints = []
        self.approach_counter = Counter()
        self.host_fail_counter = Counter()
        self.observer_trigger_callback = None


# Singleton - each thread gets its own copy of all attributes
ctx = _WorkerContext()
