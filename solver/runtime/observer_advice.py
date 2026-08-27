"""Structured Observer control advice with version and expiry guards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from solver.runtime.decision_state import StrategyMode


_ALLOWED_ACTIONS = {
    "switch_strategy",
    "verify_evidence",
    "review_blackboard",
    "continue_current",
    "stop_exhausted",
}
_ALLOWED_MODES = {item.value for item in StrategyMode}


@dataclass(frozen=True)
class ObserverAdvice:
    action: str
    mode: str
    reason: str
    message: str
    state_version: int
    reviewed_round: int
    priority: int = 50
    expires_after_rounds: int = 4

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any],
        *,
        default_state_version: int,
        default_round: int,
    ) -> "ObserverAdvice":
        action = str(data.get("action", "review_blackboard")).strip()
        if action not in _ALLOWED_ACTIONS:
            action = "review_blackboard"
        mode = str(data.get("mode", StrategyMode.EXPLORE.value)).strip().upper()
        if mode not in _ALLOWED_MODES:
            mode = StrategyMode.EXPLORE.value
        reason = str(data.get("reason", "observer_review")).strip()[:300]
        message = str(data.get("message", "")).strip()[:2000]
        state_version = _safe_int(data.get("state_version"), default_state_version)
        reviewed_round = _safe_int(data.get("reviewed_round"), default_round)
        priority = max(0, min(100, _safe_int(data.get("priority"), 50)))
        expires = max(1, min(24, _safe_int(data.get("expires_after_rounds"), 4)))
        return cls(
            action=action,
            mode=mode,
            reason=reason or "observer_review",
            message=message,
            state_version=state_version,
            reviewed_round=reviewed_round,
            priority=priority,
            expires_after_rounds=expires,
        )

    def is_applicable(self, *, current_state_version: int, current_round: int) -> bool:
        if self.state_version != int(current_state_version):
            return False
        lag = max(0, int(current_round) - self.reviewed_round)
        return lag <= self.expires_after_rounds

    def render(self) -> str:
        details = self.message or self.reason
        return (
            f"[结构化纠偏 action={self.action} mode={self.mode} "
            f"priority={self.priority} state_version={self.state_version}] {details}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "mode": self.mode,
            "reason": self.reason,
            "message": self.message,
            "state_version": self.state_version,
            "reviewed_round": self.reviewed_round,
            "priority": self.priority,
            "expires_after_rounds": self.expires_after_rounds,
        }


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)
