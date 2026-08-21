"""Small, explicit policy for parallel solver attempts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AttemptSpec:
    name: str
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
                strategy_hint=(
                    "激进策略：优先直接尝试已知 CVE/exploit 与最短攻击链，"
                    "减少大规模枚举；发现疑似漏洞入口立即打，不要过度侦察。"
                ),
            ),
            AttemptSpec(
                "steady",
                strategy_hint=(
                    "稳健策略：先系统信息收集与攻击面枚举，再逐条验证每个入口；"
                    "重视源码/配置泄露与 skill 指南中的标准路径。"
                ),
            ),
        )
    return (AttemptSpec("primary"),)
