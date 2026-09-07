from __future__ import annotations

from dataclasses import dataclass
import threading


@dataclass(frozen=True)
class AttemptSpec:
    """Planner output for one isolated solver attempt."""

    name: str
    role: str = "executor"
    objective: str = "完成当前题目并验证提交结果"
    success_condition: str = "获得可重复验证的 flag 或明确记录终止边界"
    stop_condition: str = "同一假设重复失败且没有新证据"
    hypothesis: str = ""
    allowed_scope: str = "current_challenge"
    strategy_hint: str = ""
    model: str = ""  # 空=默认 flash；"pro"=deepseek-v4-pro（难题攻坚）


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


# 多阶段渗透（b-、e1-）：多 agent 共享 memory 协作推进各阶段。
_COLLAB_PREFIXES = {"b", "e1"}

# 单 flag 的「产品 Web / 云应用 / 对抗」题：一条 playbook 打穿，开
# foothold/lateral/source 只会放大方差并抢 lane（a-13/a-18/c-02 教训）。
_SINGLE_CHAIN_HARD_PREFIXES = {"a", "c", "d", "e2", "e3", "f1", "f2"}


def _is_single_chain_hard(challenge) -> bool:
    """True when hard but one exploit chain — prefer solo + skills over portfolio."""
    diff = (challenge.difficulty or "").lower()
    if diff not in ("hard", "difficult"):
        return False
    if int(getattr(challenge, "flag_count", 1) or 1) > 1:
        return False
    code = (challenge.unique_code or "").lower()
    prefix = code.split("-")[0] if "-" in code else code[:2]
    if prefix in _COLLAB_PREFIXES:
        return False
    return prefix in _SINGLE_CHAIN_HARD_PREFIXES or prefix.startswith("f")

_AGGRESSIVE = AttemptSpec(
    "aggressive",
    role="scout-executor",
    objective="快速验证最高概率的少量候选方向，并把新证据写入共享看板",
    success_condition="得到可复现的入口、权限变化或 flag；否则记录失败边界并释放方向",
    stop_condition="验证少量高概率入口后无新证据，立即释放该假设",
    hypothesis="优先验证最高概率的初始入口或已知漏洞",
    strategy_hint=(
        "激进策略：优先直接尝试已知 CVE/exploit 与最短攻击链，"
        "减少大规模枚举；发现疑似漏洞入口立即打，不要过度侦察。"
    ),
)
_STEADY = AttemptSpec(
    "steady",
    role="evidence-executor",
    objective="建立最小完整事实链，逐条验证入口和前置条件，避免重复猜测",
    success_condition="得到可复现的证据链或确认当前假设不成立",
    stop_condition="完成最小事实链后仍无支持证据，记录边界并释放假设",
    hypothesis="建立最小完整事实链并验证一个可复现入口",
    strategy_hint=(
        "稳健策略：先系统信息收集与攻击面枚举，再逐条验证每个入口；"
        "重视源码/配置泄露与 skill 指南中的标准路径。"
    ),
)
_PRIMARY = AttemptSpec(
    "primary",
    role="primary-executor",
    objective="在当前预算内完成题目并保护简单题的确定性得分",
    hypothesis="选择一个有证据支持的最短解法并验证提交",
    stop_condition="无新证据时停止重复并记录边界",
)
_TWO_STRATEGY = (_AGGRESSIVE, _STEADY)
_SOLO = (_PRIMARY,)

# 竞争假设（agent-team 式）：hard/瓶颈题用三个不同正交假设并行攻坚，
# claim 保证互斥、artifact 共享结构化证据、谁先解出谁赢。
# model="pro" 表示攻坚时切换到 deepseek-v4-pro（稳定深度）。
_HARD_FOOTHOLD = AttemptSpec(
    "foothold",
    role="scout-executor",
    objective="在 Web 入口找可复现的初始访问（LFI/SQLi/上传/已知 CVE）",
    success_condition="得到可复现的入口或 flag",
    stop_condition="验证少量高概率 Web 入口后无新证据，释放该假设",
    hypothesis="优先 Web 初始入口：文件包含/注入/上传/已知产品 CVE",
    strategy_hint="只验证有指纹或 skill 证据支持的最高概率 Web 入口，不做全盘扫描。",
    model="pro",
)
_HARD_LATERAL = AttemptSpec(
    "lateral",
    role="evidence-executor",
    objective="找内网/横向移动/凭据复用的第二条路",
    success_condition="发现新主机、新权限或可复用凭据",
    stop_condition="无 SSRF/内网/凭据证据时释放该假设",
    hypothesis="优先 SSRF/内网枚举/凭据复用/横向移动",
    strategy_hint="先用已有入口和 hint 里的拓扑线索精确探测内网，不盲目全量扫。",
    model="pro",
)
_HARD_SOURCE = AttemptSpec(
    "source",
    role="evidence-executor",
    objective="从源码/配置/泄露找直接 flag 或提权路径",
    success_condition="从源码/配置读到的凭据、漏洞或 flag",
    stop_condition="无明显源码/配置泄露入口时释放该假设",
    hypothesis="优先源码泄露/配置文件/中间件版本对应的已知 CVE",
    strategy_hint="先读源码/配置/环境变量找 flag 定义位置或硬编码凭据。",
    model="pro",
)
_COMPETING_HYPOTHESES = (_HARD_FOOTHOLD, _HARD_LATERAL, _HARD_SOURCE)


def challenge_plan(
    challenge,
    settings: dict | None = None,
) -> tuple[tuple[AttemptSpec, ...], str]:
    """Return ``(attempts, memory_scope)`` for one challenge.

    并发是稀缺资源（同时运行的 solver 线程数受 LaneBudget 卡在 ≤ LLM 槽位），
    所以只在"多路真正能提高解出概率"时才申请多路，把额外 lane 让给难题：

    * 多阶段渗透 (b-/e1-, ≥ 2 flags) -> 两个 agent 共享 ``shared`` memory，
      一个 agent 证明的事实（跳板机 / 横向凭据）立即被另一个复用；
    * hard 单链产品题 (a-/c-/d-/e2-/e3-/f* 且 flag_count≤1) -> **单 agent**，
      把预算交给 skill_chain + playbook，不开 foothold/lateral/source
      （并行假设对 JWT/pydash/Comfy 单链题是方差放大器）；
    * 其余 hard（多 flag 或未知家族）-> 竞争假设（foothold/lateral/source），
      private memory，证据经 artifact/promote 受控共享；
    * 多 flag 题（≥4 flag，非 b/e1）-> 两个隔离策略赛跑，值得翻倍；
    * 其余 web/misc 单 flag 简单题、附件分析、未知码 -> **单 agent**。
      简单题单路 30s 内就解，双路只翻倍 LLM 成本并抢占难题的 lane，得不偿失
      （run-12752：难题尾段被拥挤的 pro solver 互相饿死）。
    """
    code = (challenge.unique_code or "").lower()
    prefix = code.split("-")[0] if "-" in code else code[:2]
    diff = (challenge.difficulty or "").lower()
    hard = diff in ("hard", "difficult")
    multi_flag = challenge.flag_count >= 4

    if bool((settings or {}).get("solver", {}).get("late_game_mode")):
        # 尾段抢分：一律单 agent，避免多路占 slot；b-* 有部分进展时保留 shared memory。
        if prefix in _COLLAB_PREFIXES and challenge.correct_flag_count > 0:
            return (_SOLO, "shared")
        return (_SOLO, "private")

    # 多阶段渗透 / 多 flag pentest：多 agent 协作，共享 memory。
    if prefix in _COLLAB_PREFIXES and (
        multi_flag or hard or challenge.flag_count >= 2
    ):
        return (_TWO_STRATEGY, "shared")

    # hard 单链：单 agent + skills（默认）。opt-in 才开竞争假设。
    if hard and _is_single_chain_hard(challenge):
        force_compete = bool(
            (settings or {}).get("solver", {}).get("hard_competing_hypotheses", False)
        )
        if force_compete:
            return (_COMPETING_HYPOTHESES, "private")
        return (_SOLO, "private")

    # 其余 hard（多 flag / 未知家族）：竞争假设；pro 是否启用看 solver.pro_enabled。
    if hard:
        return (_COMPETING_HYPOTHESES, "private")

    # 多 flag（非 b/e1）：隔离双策略赛跑，翻倍成本换更高的多阶段解出率。
    if multi_flag:
        return (_TWO_STRATEGY, "isolated")

    # 其余（前排 web/misc 单 flag 简单题 / 附件分析 / 未知码）：单 agent，
    # 把并发 lane 留给真正需要深度的难题。
    return (_SOLO, "private")


def build_portfolio(challenge, settings: dict | None = None) -> tuple[AttemptSpec, ...]:
    return challenge_plan(challenge, settings=settings)[0]


def challenge_memory_scope(challenge, settings: dict | None = None) -> str:
    return challenge_plan(challenge, settings=settings)[1]
