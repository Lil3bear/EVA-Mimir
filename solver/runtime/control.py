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
# 单题墙钟止损（秒）。轮次预算无法反映真实耗时：一轮可能 10s，也可能因一条
# 长 bash 或一次大 LLM 调用耗 5min。一道题只要每隔几轮制造点"微进展"就能一直
# 重置 idle 计数，把整场时间烧光而不解出（run: b-02/c-01/c-02 长时间占槽仍无
# flag）。墙钟预算是与轮次/idle 正交的硬止损，对所有难度与 lane 生效，防单题
# 独吞全场时间；预算内正常解题不受影响，仅截断病态长尾。
_TIME_BUDGETS = {"easy": 600, "medium": 1200, "hard": 1800, "difficult": 1800}
_UNKNOWN_TIME_BUDGET = 1200
_PENTEST_TIME_EXTRA = 900  # 多阶段渗透合理地更久（侦察→立足→横向）
_CTYPE_TIME_EXTRA = 600
# 软预警：达到墙钟预算的该比例时注入一次"收敛/提交已验证 flag"提示，给
# "速度 vs 准确"一个缓冲，而不是到点才硬停。<=0 或 >=1 关闭软预警。
_TIME_SOFT_WARN_FRACTION = 0.75
# stop_after 必须与 max_rounds 成比例。hard 多阶段题前几十轮还在侦察，
# 过紧的 stop_after 会在拿到 flag 前就 force_stop（run-12020 b-02 回退根因）。
_DEFAULT_STOP_AFTER = {"easy": 20, "medium": 30, "hard": 48, "difficult": 48}
_STOP_PENTEST_EXTRA = 24
_STOP_CTYPE_EXTRA = 12
_FAST_LANE_ROUNDS = {"easy": 30, "medium": 30}
# 同一条命令（空白归一后）连续重复达到该次数，判定为确定的死循环。
# run-12388 中 VERIFY 模式实例把同一个 no-op heredoc 重复 11 次仍不停，
# 因为 decide() 只数 strategy_failures/idle，从不看 same_action_streak。
_ACTION_DEADLOOP_THRESHOLD = 6


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
    time_budget_seconds: float = 0.0
    soft_warn_fraction: float = _TIME_SOFT_WARN_FRACTION

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

        time_budget = _TIME_BUDGETS.get(difficulty, _UNKNOWN_TIME_BUDGET)
        if pentest:
            time_budget += _PENTEST_TIME_EXTRA
        if ctype:
            time_budget += _CTYPE_TIME_EXTRA

        def budget_setting(name: str, default: float) -> float:
            # 缺省用难度默认；显式配 0/负数即关闭止损；正数覆盖。
            if name not in solver:
                return float(default)
            try:
                value = float(solver.get(name))
            except (TypeError, ValueError):
                return float(default)
            return max(0.0, value)

        try:
            warn_fraction = float(
                solver.get("time_soft_warn_fraction", _TIME_SOFT_WARN_FRACTION)
            )
        except (TypeError, ValueError):
            warn_fraction = _TIME_SOFT_WARN_FRACTION

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
            time_budget_seconds=budget_setting("time_budget_seconds", time_budget),
            soft_warn_fraction=warn_fraction,
        )

    def soft_time_warning_seconds(self) -> float:
        """墙钟软预警触发点（秒）；<=0 表示不预警。"""
        if self.time_budget_seconds <= 0 or not (0.0 < self.soft_warn_fraction < 1.0):
            return 0.0
        return self.time_budget_seconds * self.soft_warn_fraction

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
        same_action_streak: int = 0,
        elapsed_seconds: float = 0.0,
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

        # 墙钟硬止损：与轮次/idle/难度正交的安全阀，优先于所有其它判定。
        # 即便是 easy 的"永不因 idle 放弃"不变式，也不能让单题无限吃时间——
        # 到点即停，把剩余时间让给其它题（deadline 之外的第二道闸）。
        elapsed_seconds = max(0.0, float(elapsed_seconds))
        if self.time_budget_seconds > 0 and elapsed_seconds >= self.time_budget_seconds:
            return ControlDecision(
                action=ControlAction.STOP.value,
                reason="time_budget_exhausted",
                failure_scope=FailureScope.TASK.value,
                idle_rounds=idle_rounds,
            )

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

        # 同一条命令连续重复 = 最确定的死循环信号，与 idle 正交。
        # 达到阈值直接判停，不等到 stop_after 的 idle 计数，避免继续
        # 空转吃掉共享 portfolio 预算（run-12388 going-in-circles 根因）。
        if int(same_action_streak) >= _ACTION_DEADLOOP_THRESHOLD:
            return ControlDecision(
                action=ControlAction.STOP.value,
                reason="same_action_deadloop",
                failure_scope=FailureScope.TASK.value,
                idle_rounds=idle_rounds,
            )

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
