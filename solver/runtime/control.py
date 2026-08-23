"""Single runtime policy for budgets, progress and observation cadence.

The solver used to have independent hard-coded stopping rules in Agent,
Observer and the scheduler.  This module is the one source of truth for the
per-challenge policy.  Explicit settings still win, while the defaults keep
the previously validated difficulty budgets.
"""

from __future__ import annotations

from dataclasses import dataclass


_ROUND_BUDGETS = {"easy": 40, "medium": 70, "hard": 110, "difficult": 130}
_UNKNOWN_ROUND_BUDGET = 100
_PENTEST_EXTRA = {"easy": 40, "medium": 120, "hard": 80, "difficult": 80}
_CTYPE_EXTRA = {"easy": 30, "medium": 60, "hard": 40, "difficult": 40}
_OBSERVER_INTERVALS = {"easy": 15, "medium": 12, "hard": 8, "difficult": 8}
_DEFAULT_SWITCH_AFTER = {"easy": 10, "medium": 12, "hard": 12, "difficult": 12}
# stop_after 必须与 max_rounds 成比例。hard 多阶段题前几十轮还在侦察，
# 过紧的 stop_after 会在拿到 flag 前就 force_stop（run-12020 b-02 回退根因）。
_DEFAULT_STOP_AFTER = {"easy": 20, "medium": 30, "hard": 48, "difficult": 48}
_STOP_PENTEST_EXTRA = 24
_STOP_CTYPE_EXTRA = 12


@dataclass(frozen=True)
class ControlPolicy:
    max_rounds: int
    switch_after: int
    stop_after: int
    observer_every_rounds: int

    @classmethod
    def from_settings(
        cls,
        settings: dict,
        difficulty: str,
        *,
        pentest: bool = False,
        ctype: bool = False,
    ) -> "ControlPolicy":
        solver = settings.get("solver", {})
        difficulty = (difficulty or "").lower()
        base = _ROUND_BUDGETS.get(difficulty, _UNKNOWN_ROUND_BUDGET)
        if pentest:
            base += _PENTEST_EXTRA.get(difficulty, 20)
        if ctype:
            base += _CTYPE_EXTRA.get(difficulty, 20)

        def positive_setting(name: str, default: int) -> int:
            value = solver.get(name)
            try:
                value = int(value)
            except (TypeError, ValueError):
                value = 0
            return value if value > 0 else default

        stop_after = _DEFAULT_STOP_AFTER.get(difficulty, 24)
        if pentest:
            stop_after += _STOP_PENTEST_EXTRA
        if ctype:
            stop_after += _STOP_CTYPE_EXTRA

        return cls(
            max_rounds=positive_setting("max_rounds", base),
            switch_after=positive_setting(
                "switch_after_rounds",
                _DEFAULT_SWITCH_AFTER.get(difficulty, 12),
            ),
            stop_after=positive_setting(
                "no_progress_rounds",
                stop_after,
            ),
            observer_every_rounds=positive_setting(
                "observer_every_rounds",
                _OBSERVER_INTERVALS.get(difficulty, 10),
            ),
        )

    def stop_reason(self, round_num: int, last_progress_round: int) -> str:
        idle_rounds = max(0, round_num - last_progress_round)
        if idle_rounds > self.stop_after:
            return f"连续 {idle_rounds} 轮无新证据"
        if round_num > self.max_rounds:
            return f"达到 {self.max_rounds} 轮预算"
        return ""
