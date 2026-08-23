from __future__ import annotations

from dataclasses import dataclass
import threading


@dataclass(frozen=True)
class AttemptSpec:
    """A solver attempt contract, not merely a prompt variant."""

    name: str
    role: str = "executor"
    objective: str = "完成当前题目并验证提交结果"
    success_condition: str = "获得可重复验证的 flag 或明确记录终止边界"
    strategy_hint: str = ""


class PortfolioBudget:
    """A challenge-scoped round budget shared by parallel Attempts.

    Every Attempt receives its normal quota first.  If a peer exits early,
    the surviving Attempt may borrow the unused quota.  This preserves the
    old aggregate ceiling while removing the waste caused by a failed sibling.
    """

    def __init__(self, expected_attempts: int):
        self.expected_attempts = max(1, int(expected_attempts or 1))
        self._quotas: dict[str, int] = {}
        self._used: dict[str, int] = {}
        self._active: set[str] = set()
        self._lock = threading.RLock()
        self._ready = threading.Event()

    def register(self, attempt_id: str, quota: int) -> None:
        attempt_id = str(attempt_id or "primary")
        quota = max(1, int(quota or 1))
        with self._lock:
            if attempt_id not in self._quotas:
                self._quotas[attempt_id] = quota
                self._used[attempt_id] = 0
            else:
                self._quotas[attempt_id] = max(self._quotas[attempt_id], quota)
            self._active.add(attempt_id)
            if len(self._quotas) >= self.expected_attempts:
                self._ready.set()

    def wait_until_ready(self, timeout: float = 2.0) -> bool:
        return self._ready.wait(max(0.0, float(timeout or 0.0)))

    @property
    def total_quota(self) -> int:
        with self._lock:
            return sum(self._quotas.values())

    @property
    def total_used(self) -> int:
        with self._lock:
            return sum(self._used.values())

    def claim_round(self, attempt_id: str) -> bool:
        """Atomically claim one round for an active Attempt."""
        attempt_id = str(attempt_id or "primary")
        with self._lock:
            if attempt_id not in self._quotas:
                return False
            used = self._used[attempt_id]
            quota = self._quotas[attempt_id]
            total = sum(self._quotas.values())
            if sum(self._used.values()) >= total:
                return False
            if used >= quota and any(
                peer != attempt_id for peer in self._active
            ):
                return False
            self._used[attempt_id] = used + 1
            return True

    def release_round(self, attempt_id: str) -> None:
        """Return a claim when a no-tool nudge did not consume a real round."""
        attempt_id = str(attempt_id or "primary")
        with self._lock:
            if attempt_id in self._used and self._used[attempt_id] > 0:
                self._used[attempt_id] -= 1

    def mark_done(self, attempt_id: str) -> None:
        with self._lock:
            self._active.discard(str(attempt_id or "primary"))

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "expected_attempts": self.expected_attempts,
                "registered": len(self._quotas),
                "quotas": dict(self._quotas),
                "used": dict(self._used),
                "active": sorted(self._active),
                "total_quota": sum(self._quotas.values()),
                "total_used": sum(self._used.values()),
            }


# medium 也开启双策略，提高解出概率。
_MULTI_SOLVE_PREFIXES = {"f1", "c", "e2"}


def build_portfolio(challenge) -> tuple[AttemptSpec, ...]:
    code = (challenge.unique_code or "").lower()
    prefix = code.split("-")[0] if "-" in code else code[:2]
    hard = challenge.difficulty.lower() in ("hard", "difficult")
    multi_flag = challenge.flag_count >= 4
    weak_medium = (
        prefix in _MULTI_SOLVE_PREFIXES
        and challenge.difficulty.lower() == "medium"
    )
    if hard or multi_flag or weak_medium:
        return (
            AttemptSpec(
                "aggressive",
                role="scout-executor",
                objective="快速验证最高概率的少量候选方向，并把新证据写入共享看板",
                success_condition="得到可复现的入口、权限变化或 flag；否则记录失败边界并释放方向",
                strategy_hint=(
                    "激进策略：优先直接尝试已知 CVE/exploit 与最短攻击链，"
                    "减少大规模枚举；发现疑似漏洞入口立即打，不要过度侦察。"
                ),
            ),
            AttemptSpec(
                "steady",
                role="evidence-executor",
                objective="建立最小完整事实链，逐条验证入口和前置条件，避免重复猜测",
                success_condition="得到可复现的证据链或确认当前假设不成立",
                strategy_hint=(
                    "稳健策略：先系统信息收集与攻击面枚举，再逐条验证每个入口；"
                    "重视源码/配置泄露与 skill 指南中的标准路径。"
                ),
            ),
        )
    return (
        AttemptSpec(
            "primary",
            role="primary-executor",
            objective="在当前预算内完成题目并保护简单题的确定性得分",
        ),
    )
