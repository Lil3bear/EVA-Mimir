"""One runtime policy for budgets, observation cadence, and stopping."""

from __future__ import annotations

from dataclasses import dataclass


_ROUND_BUDGETS = {"easy": 24, "medium": 40, "hard": 64, "difficult": 64}
_NO_PROGRESS_BUDGETS = {"easy": 10, "medium": 14, "hard": 18, "difficult": 18}
_OBSERVER_INTERVALS = {"easy": 20, "medium": 16, "hard": 12, "difficult": 12}


@dataclass(frozen=True)
class ControlPolicy:
    max_rounds: int
    no_progress_rounds: int
    observer_every_rounds: int

    @classmethod
    def from_settings(
        cls,
        settings: dict,
        difficulty: str,
        *,
        multi_flag: bool = False,
    ) -> "ControlPolicy":
        solver = settings.get("solver", {})
        default_rounds = _ROUND_BUDGETS.get(difficulty, 40)
        if multi_flag:
            default_rounds += 16
        return cls(
            max_rounds=int(solver.get("max_rounds") or default_rounds),
            no_progress_rounds=max(
                1,
                int(
                    solver.get("no_progress_rounds")
                    or _NO_PROGRESS_BUDGETS.get(difficulty, 14)
                ),
            ),
            observer_every_rounds=max(
                1,
                int(
                    solver.get("observer_every_rounds")
                    or _OBSERVER_INTERVALS.get(difficulty, 16)
                ),
            ),
        )

    def stop_reason(self, round_num: int, last_progress_round: int) -> str:
        idle_rounds = round_num - last_progress_round
        if idle_rounds > self.no_progress_rounds:
            return f"连续 {idle_rounds} 轮无新证据"
        if round_num > self.max_rounds:
            return f"达到 {self.max_rounds} 轮预算"
        return ""
