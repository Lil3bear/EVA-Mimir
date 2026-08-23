"""Small, explicit policy for parallel solver attempts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AttemptSpec:
    """A solver attempt contract, not merely a prompt variant."""

    name: str
    role: str = "executor"
    objective: str = "完成当前题目并验证提交结果"
    success_condition: str = "获得可重复验证的 flag 或明确记录终止边界"
    strategy_hint: str = ""


# 能力短板题型（f1=二进制服务 / c=综合杂项 / e2=沙箱逃逸·漏洞利用），
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
