"""Single runtime policy for budgets, lanes and terminal decisions.

The policy deliberately separates three different facts:

* an action failed (retry or adjust parameters),
* a strategy stalled (change direction), and
* the task exhausted the evidence/time budget (terminal).

Only :meth:`ControlPolicy.decide` may turn lack of progress into a terminal
result.  Deadline, platform cancellation, peer success and a correct flag are
external terminal events and are handled by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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
_FAST_LANE_ROUNDS = {"easy": 20, "medium": 20}


class LaneMode(str, Enum):
    FAST = "fast"
    DEEP = "deep"


class FailureScope(str, Enum):
    """How much evidence is needed before declaring a failure."""

    NONE = "none"
    ACTION = "action_failure"
    STRATEGY = "strategy_failure"
    TASK = "task_exhausted"


class ControlAction(str, Enum):
    CONTINUE = "continue"
    UPGRADE_LANE = "upgrade_lane"
    SWITCH_STRATEGY = "switch_strategy"
    STOP = "stop"


@dataclass(frozen=True)
class ControlDecision:
    action: str = ControlAction.CONTINUE.value
    reason: str = ""
    failure_scope: str = FailureScope.NONE.value
    idle_rounds: int = 0

    @property
    def terminal(self) -> bool:
        return self.action == ControlAction.STOP.value


@dataclass(frozen=True)
class ControlPolicy:
    max_rounds: int
    switch_after: int
    stop_after: int
    observer_every_rounds: int
    difficulty: str = ""
    fast_lane_rounds: int = 0
    min_strategy_failures_before_stop: int = 2

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

        fast_default = 0 if pentest or ctype else _FAST_LANE_ROUNDS.get(difficulty, 0)
        return cls(
            max_rounds=positive_setting("max_rounds", base),
            switch_after=positive_setting(
                "switch_after_rounds",
                _DEFAULT_SWITCH_AFTER.get(difficulty, 12),
            ),
            stop_after=positive_setting("no_progress_rounds", stop_after),
            observer_every_rounds=positive_setting(
                "observer_every_rounds",
                _OBSERVER_INTERVALS.get(difficulty, 10),
            ),
            difficulty=difficulty,
            fast_lane_rounds=positive_setting(
                "fast_lane_rounds", fast_default
            ) if fast_default else 0,
            min_strategy_failures_before_stop=positive_setting(
                "min_strategy_failures_before_stop", 2
            ),
        )

    @property
    def allows_no_progress_intervention(self) -> bool:
        """Easy never abandons or forcibly rotates only because it is idle."""
        return self.difficulty != "easy"

    def decide(
        self,
        *,
        round_num: int,
        last_progress_round: int,
        lane: str,
        lane_entered_round: int = 0,
        strategy_failures: int = 0,
        switch_already_requested: bool = False,
        hint_focus_exhausted: bool = False,
    ) -> ControlDecision:
        """Return the sole policy decision for lane/switch/no-progress stop.

        A Deep Lane upgrade starts a fresh progress epoch.  This prevents a
        medium task from upgrading at round 20 and immediately inheriting 20
        stale rounds, which previously caused an instant switch/early stop.
        Easy may upgrade to gain Observer help, but it still cannot be stopped
        or forcibly switched merely for having no progress.
        """
        round_num = max(0, int(round_num))
        lane_entered_round = max(0, int(lane_entered_round))
        progress_anchor = max(int(last_progress_round), lane_entered_round)
        idle_rounds = max(0, round_num - progress_anchor)

        if (
            lane == LaneMode.FAST.value
            and self.fast_lane_rounds > 0
            and round_num >= self.fast_lane_rounds
        ):
            return ControlDecision(
                action=ControlAction.UPGRADE_LANE.value,
                reason="fast_lane_budget_exhausted",
                idle_rounds=idle_rounds,
            )

        # The key easy invariant: no idle/hint terminal and no legacy forced
        # switch.  It runs until solved, deadline/platform terminal, or the
        # complete max_rounds budget.
        if not self.allows_no_progress_intervention:
            return ControlDecision(idle_rounds=idle_rounds)

        if lane != LaneMode.DEEP.value:
            return ControlDecision(idle_rounds=idle_rounds)

        enough_failed_strategies = (
            int(strategy_failures) >= self.min_strategy_failures_before_stop
        )
        if enough_failed_strategies and (
            idle_rounds > self.stop_after or hint_focus_exhausted
        ):
            reason = (
                "hint_focus_exhausted"
                if hint_focus_exhausted
                else "no_progress_after_strategy_changes"
            )
            return ControlDecision(
                action=ControlAction.STOP.value,
                reason=reason,
                failure_scope=FailureScope.TASK.value,
                idle_rounds=idle_rounds,
            )

        if idle_rounds > self.switch_after and not switch_already_requested:
            return ControlDecision(
                action=ControlAction.SWITCH_STRATEGY.value,
                reason="strategy_without_new_evidence",
                failure_scope=FailureScope.STRATEGY.value,
                idle_rounds=idle_rounds,
            )

        return ControlDecision(idle_rounds=idle_rounds)
