"""Build one task prefix for a solver attempt without extra LLM calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from solver.ctfplatform.policy import infer_challenge_type
from solver.ctfplatform.tsecbench_client import Challenge
from solver.runtime.context import RunContext


# 描述关键词 → 必加载 reference（确定性预加载，避免 Agent 识别出漏洞类型
# 却直接 security_search 而跳过本地 skill）。关键词是通用漏洞/产品名，非题号。
_DESCRIPTION_REFERENCE_HINTS = (
    (("jwt", "token", "签名", "oauth"), "JWT/签名 → 必须 skill_load(name=\"web\", resource=\"jwt-attacks.md\")"),
    (("授权", "license", "serial", "序列号", "校验器"), "授权/序列号 → 必须 skill_load(name=\"reverse\", resource=\"embedded-license.md\")"),
    (("云函数", "serverless", "cloudfunc", "lambda"), "Serverless → 必须 skill_load(name=\"cloud\", resource=\"serverless.md\")"),
    (("ssrf", "内网探测", "资产探测", "请求伪造", "同步数据", "合作伙伴", "追踪 api", "导入", "抓取"), "SSRF/URL 请求 → 必须 skill_load(name=\"web\", resource=\"ssrf.md\")"),
    (("xxe", "xml", "实体注入", "图片", "svg"), "XXE/文件上传 → 必须 skill_load(name=\"payloads\", resource=\"xxe-injection.md\") 和 skill_load(name=\"payloads\", resource=\"upload-insecure-files.md\")"),
    (("上传", "upload", "附件", "头像"), "文件上传 → 必须 skill_load(name=\"payloads\", resource=\"upload-insecure-files.md\")"),
    (("图数据库", "hugegraph", "neo4j", "关联检索", "gremlin"), "图数据库 → 必须 skill_load(name=\"web\", resource=\"graph-db.md\")"),
)


def _reference_hints(description: str) -> list[str]:
    """Return mandatory skill_load hints matched by the challenge description."""
    lowered = (description or "").lower()
    hints = []
    for keywords, hint in _DESCRIPTION_REFERENCE_HINTS:
        if any(keyword in lowered for keyword in keywords):
            hints.append(hint)
    return hints


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
        lines.append(
            "- 🎯 描述中点名的目标（产品/服务/凭证/路径）是最高优先级线索：拿到初始权限后优先验证它，"
            "不要先泛扫网段或目录。"
        )
        for hint in _reference_hints(challenge.description):
            lines.append(f"- 📚 {hint}")
    if profile.product_hint:
        lines.append(
            f"- 🔎 端口产品候选：{profile.product_hint}。"
            "先用一次 curl 验证指纹，命中后再加载对应 skill 攻击链；不要跳过验证直接猜。"
        )
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
        role: str = "executor",
        objective: str = "完成当前题目并验证提交结果",
        success_condition: str = "获得可重复验证的 flag 或明确记录终止边界",
        attempt_context: RunContext | None = None,
    ) -> str:
        task = build_task_from_challenge(challenge, container_addr)
        if strategy_name:
            task += f"\n\n## 策略：{strategy_name}（本策略为 Multi-Solver 并行模式，另一策略也在同时解题）"
        task += (
            "\n\n## Attempt 任务契约"
            f"\n- 角色：{role}"
            f"\n- 当前目标：{objective}"
            f"\n- 完成条件：{success_condition}"
            "\n- 每次关键动作前先明确一个可验证假设；动作后用 memory_add 记录新证据、失败边界或阻塞原因。"
            "\n- 不要重复其他 Attempt 已经验证过的同一请求结构；需要复核时必须说明方法发生了什么变化。"
        )
        if strategy_hint:
            task += f"\n{strategy_hint}"
        if attempt_context:
            task += (
                f"\n本 Attempt 私有工作目录：{attempt_context.attempt_dir}"
                f"\n题目共享 Memory/Ideas 目录：{attempt_context.challenge_dir}"
            )

        return task + self.load_experience(challenge.unique_code, self.skills_dir)
