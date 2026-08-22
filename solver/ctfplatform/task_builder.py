"""Build one task prefix for a solver attempt without extra LLM calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from solver.ctfplatform.policy import infer_challenge_type
from solver.ctfplatform.tsecbench_client import Challenge
from solver.runtime.context import RunContext


def build_task_from_challenge(
    challenge: Challenge, container_addr: tuple[str, ...]
) -> str:
    addresses = ", ".join(container_addr) if container_addr else "（未返回靶场地址）"
    profile = infer_challenge_type(challenge.unique_code, container_addr)
    lines = [
        f"# CTF 题目：{challenge.unique_code}",
        f"- 类型：{profile.type_name}",
        f"- 主 Skill：`skill_load(name=\"{profile.primary_skill}\")`",
        f"- 候选 Skill：{', '.join(profile.candidate_skills) if profile.candidate_skills else '无'}",
        f"- 难度：{challenge.difficulty}",
        f"- 目标地址：{addresses}",
        "- 入口协议：平台只保证 IP:端口可直连，不保证是 HTTP；请按端口和响应选择 curl、nc、telnet、ssh 或 pwntools。",
        "- Flag 格式：flag{...}",
    ]
    if challenge.description:
        lines.append(f"- 描述：{challenge.description}")
    if challenge.flag_count > 1:
        remaining = challenge.flag_count - challenge.correct_flag_count
        lines.extend([
            f"- ⚠️ 本题包含 {challenge.flag_count} 个 Flag（多阶段渗透题），已找到 {challenge.correct_flag_count} 个，还剩 {remaining} 个",
            "- ❗ 每找到一个 flag 就立即提交，然后继续渗透下一阶段（提权/横向移动/内网），直到全部找到",
        ])
    if challenge.correct_flag_count > 0:
        lines.extend([
            f"\n## 已找到 {challenge.correct_flag_count} 个 Flag（继续寻找剩余的）",
            "\n⚠️ **这是重跑轮次**。上一轮发现的内网 IP 和端口可能已变化，必须重新扫描确认。",
            "不要直接使用 memory 中的旧 IP 地址，先重新执行 `ip addr` + `cat /proc/net/arp` + 端口探测。",
            "\n💡 **优先复用本次运行已验证的事实**：如果 memory 中已经记录了可复现的入口、凭据或成功判据，",
            "先按当前实例重新验证这些事实，再继续下一阶段；不得把旧地址、旧凭据或未验证的历史方法当作答案。",
        ])
    lines.append("\n请开始解题，找到 flag 后调用 challenge_submit_flag 工具提交。")
    return "\n".join(lines)


@dataclass
class TaskBuilder:
    skills_dir: str
    load_experience: Callable[[str, str], str]

    def build(
        self,
        challenge: Challenge,
        container_addr: tuple[str, ...],
        challenge_workspace: str,
        *,
        strategy_name: str = "",
        strategy_hint: str = "",
        attempt_context: RunContext | None = None,
    ) -> str:
        task = build_task_from_challenge(challenge, container_addr)
        if strategy_name:
            task += f"\n\n## 策略：{strategy_name}（本策略为 Multi-Solver 并行模式，另一策略也在同时解题）"
        if strategy_hint:
            task += f"\n{strategy_hint}"
        if attempt_context:
            task += (
                f"\n本 Attempt 私有工作目录：{attempt_context.attempt_dir}"
                f"\n题目共享 Memory/Ideas 目录：{attempt_context.challenge_dir}"
            )

        return task + self.load_experience(challenge.unique_code, self.skills_dir)
