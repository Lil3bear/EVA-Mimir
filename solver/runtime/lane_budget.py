"""Scheduler-scoped concurrency budget for solver *lanes*.

A "lane" is one concurrently-running solver thread (one LLM-driven ReAct
loop).  The platform caps active containers at 3, but each challenge may want
several solver threads (competing hypotheses / racing strategies).  Without a
global cap those extra threads pile up on the shared LLM slot semaphore, so
adding parallelism past the LLM concurrency does not speed anything up — it
only makes *every* lane queue behind the others (run-12752 tail: three pro
solvers on one hard challenge starved each other while easy challenges waited).

``LaneBudget`` keeps the number of *running* lanes at or below the LLM
concurrency, split into two tiers:

* ``base`` lanes are reserved one-per-parallel-challenge, so every active
  container always has one guaranteed lane and can make progress;
* ``extra`` lanes (``total - base``) are handed out opportunistically and
  never block, so a hard challenge can deepen with a second lane only when the
  capacity is genuinely free — never by starving another container.

With the default ``total = LLM concurrency (4)`` and ``base = max_parallel
(3)`` there is exactly one extra lane: while three challenges run, only one of
them (typically the hard one) gets a second lane and the other two churn
simple challenges at one lane each.  Bumping ``max_lanes`` widens the extra
tier for local runs with a larger LLM gateway.
"""

from __future__ import annotations

import threading


class LaneBudget:
    """Two-tier lane semaphore: guaranteed base lanes + opportunistic extras."""

    def __init__(self, total_lanes: int, base_lanes: int):
        base_lanes = max(1, int(base_lanes))
        total_lanes = max(base_lanes, int(total_lanes))
        self.total_lanes = total_lanes
        self.base_lanes = base_lanes
        self.extra_lanes = total_lanes - base_lanes
        self._base = threading.Semaphore(base_lanes)
        self._extra = (
            threading.Semaphore(self.extra_lanes) if self.extra_lanes > 0 else None
        )

    def acquire_primary(self, timeout: float | None = None) -> bool:
        """Take the one guaranteed lane for an active challenge.

        Always satisfiable in steady state because ``base_lanes ==
        max_parallel`` and at most ``max_parallel`` challenges run at once; a
        finite ``timeout`` only guards against unexpected contention so the
        caller can proceed rather than hang.
        """
        if timeout is None:
            self._base.acquire()
            return True
        return bool(self._base.acquire(timeout=max(0.0, float(timeout))))

    def release_primary(self) -> None:
        self._base.release()

    def try_acquire_extra(self) -> bool:
        """Grab one opportunistic lane without blocking; ``False`` if none free."""
        if self._extra is None:
            return False
        return bool(self._extra.acquire(blocking=False))

    def release_extra(self) -> None:
        if self._extra is not None:
            self._extra.release()

    def snapshot(self) -> dict[str, int]:
        return {
            "total_lanes": self.total_lanes,
            "base_lanes": self.base_lanes,
            "extra_lanes": self.extra_lanes,
        }
