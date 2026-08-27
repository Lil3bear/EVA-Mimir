import json
import os
from pathlib import Path

from openai import OpenAI

from solver.observer.tools import (
    build_tool_registry,
)
from solver.runtime.llm import assistant_message_dict, completion_kwargs, create_with_retry
from solver.runtime.claims import ClaimStore
from solver.runtime.scoped_state import observer_ideas, observer_memories, list_memory_proposals
from shared.jsonl import write_line
from solver.worker_context import ctx as _ctx


OBSERVER_SYSTEM_PROMPT = """你是 CTF 解题 Agent 的 Observer（旁路审查员）。

## 职责边界
你只审查当前题目各 Solver attempt 的工具行为，维护当前题目的共享 Memory/Ideas，并在确有必要时发送一条方向性纠偏。Solver 的私有记忆默认不可直接注入其他 Solver；只有验证通过的 evidence proposal 才能 promote 到共享层。
你不执行目标请求、不提交 flag、不编造工具名，也不替 Solver 做未经验证的技术判断。
纠偏只能指示 Solver 使用它已有的工具：bash、read_file、write_file、grep、skill_list、skill_load、
memory_add、memory_list、memory_promote、artifact_list、artifact_approve、command_publish、idea_list、security_search、challenge_submit_flag、challenge_get_state、
challenge_get_hint；不要提及 restart 或其它不存在的接口。

## 单一审查循环
1. 先使用用户消息中的 Memory/Ideas、决策控制状态与最近行为摘要；决策状态中的重复计数和版本号优先于你的主观估计，只有存在无法解释的具体矛盾时才读 history。
2. 以当前运行的实测证据为准。evidence（凭据/有效 flag）不可删除；合并重复的 fact/failure，
   删除已经被新证据替代或明显过时的记录。不要把旧实例 IP、旧凭据、题号经验或历史攻击链当作答案。
3. 检查已有 idea 是否应更新为 testing/verified/failed。一次 payload 失败只记录边界，不要轻易关闭整条路线。
4. 只有确认当前 attempt 遗忘了与主线直接相关的已验证事实，或同一请求/方向重复且无新证据，才纠偏。不要因为另一个 attempt 的私有路线不同就强行覆盖当前 Solver。
5. 没有明确改动时返回 NO_CHANGE；需要纠偏时必须调用 `send_correction`，填写当前 `state_version`、动作、模式、优先级和失效轮数。message 保持 1--3 句话，说明已尝试方向、证据边界和一个新的大方向，
   不给未经验证的具体 payload、固定路径或凭据。

## 触发与安全门
- 同一请求结构反复超过 3 次、同一攻击向量约 8--10 轮没有新证据，或目标明确不可达仍在盲扫：建议切换方向。
- 看到“可能未利用情报”时，先排除旧地址、已完成步骤和无关关键词；只有当前主线确实需要才提醒。
- 多 Flag 题：确认 Solver 查询剩余数量并继续下一阶段；不要每次都强制全盘 find、sudo 或内网扫描，
  只建议与已确认权限/拓扑相关的下一步。
- 只有工具输出中出现完整的 `XXX{...}` 才算 flag；标题、注释、示例、脚本字符串或自动提取提示不算证据。
- 不主动建议提前看 hint；是否看 hint 由 Solver 的代码门控决定，提示后的结果必须再次验证。
- 验证码、二进制、Webshell 等专项只做“减少重复、切换方法、验证结果”的方向性提醒，不替 Solver 猜技术细节。

## 合规
本提示不包含任何题目的历史答案、固定目标地址、固定凭据或可直接复用的历史攻击链。
观察到当前题已完成或平台返回终止状态时，不再发新的探索指令。

## 输出
无需改动时只回复 `NO_CHANGE`；有改动时用 1--3 句话说明更新或纠偏内容。"""


def _excerpt(text: str, limit: int) -> str:
    text = str(text or "")
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head
    return text[:head] + " ...[省略]... " + text[-tail:]


def _build_observer_prompt(
    recent_rounds: list[dict], challenge_dir: Path, attempt_dir: Path | None = None
) -> str:
    memories = observer_memories(challenge_dir)[-12:]
    ideas = observer_ideas(challenge_dir)[-8:]
    proposals = list_memory_proposals(challenge_dir)
    claims = ClaimStore(challenge_dir).list_active()
    approved_artifacts = __import__("solver.runtime.artifacts", fromlist=["ArtifactBus"]).ArtifactBus(challenge_dir).list(status="approved", limit=20)

    lines = ["## 当前看板状态"]

    # The deterministic control plane is the source of truth for repetition
    # and strategy mode.  Observer may advise, but must not infer these fields
    # from a truncated six-round window alone.
    try:
        from solver.runtime.strategy_controller import load_decision_summary
        decision = load_decision_summary(attempt_dir or challenge_dir)
    except Exception:
        decision = {}
    if decision:
        lines.append(
            "### 决策控制状态\n"
            f"- mode={decision.get('strategy_mode', 'EXPLORE')}"
            f", stage={decision.get('stage', 'CLASSIFY')}"
            f", state_version={decision.get('state_version', 0)}"
            f", same_action_streak={decision.get('same_action_streak', 0)}"
            f", same_vector_streak={decision.get('same_vector_streak', 0)}"
            f", switch_count={decision.get('switch_count', 0)}"
        )

    if memories:
        lines.append(f"### Memory（{len(memories)} 条）")
        # 超限时注入强制清理指令
        non_evidence = [m for m in memories if m.kind != "evidence"]
        if len(non_evidence) > 10:
            lines.append(f"\n⚠️ **Memory 超限**：非 evidence 条目已达 {len(non_evidence)} 条（上限 10）。"
                         f"请先合并同类项或删除过时条目，再做其他工作。\n")
        for m in memories:
            lines.append(f"- [{m.kind}] {m.id}: {_excerpt(m.content, 700)}")
    else:
        lines.append("### Memory（空）")

    if approved_artifacts:
        lines.append("### 已批准 Artifacts")
        for artifact in approved_artifacts:
            lines.append(
                f"- {artifact.get('artifact_type')}: {_excerpt(artifact.get('value', ''), 500)} "
                f"(owner={artifact.get('producer_attempt')}, confidence={artifact.get('confidence')})"
            )

    if claims:
        lines.append("### 当前 Hypothesis Claims")
        for claim in claims:
            lines.append(
                f"- {claim.get('owner', '?')}: {_excerpt(claim.get('description', ''), 500)} "
                f"(lease_until={claim.get('lease_until', 0)})"
            )

    if proposals:
        lines.append("### 待审核共享提案")
        for proposal in proposals[-8:]:
            lines.append(
                f"- {proposal.get('id')} ({proposal.get('source_attempt', '')}): "
                f"{_excerpt(proposal.get('content', ''), 500)}"
            )

    if ideas:
        lines.append("### Ideas")
        for i in ideas:
            result_str = f" → {i.result}" if i.result else ""
            lines.append(f"- [{i.status}] {i.id}: {_excerpt(i.content + result_str, 450)}")
    else:
        lines.append("### Ideas（空）")

    # 告知 Observer 真实的 history 文件路径
    history_path = str(((attempt_dir or challenge_dir) / ".solver-history.jsonl").resolve())
    lines.append(f"\n## history_path\n`{history_path}`")

    lines.append("\n## Solver 最近行为摘要")
    for r in recent_rounds[-6:]:
        round_num = r.get("round", "?")
        tool_calls = r.get("tool_calls", [])
        lines.append(f"\n### 第 {round_num} 轮")
        if tool_calls:
            for tc in tool_calls:
                tool = tc.get("tool", "")
                args_str = str(tc.get("args", ""))[:100]
                result_str = str(tc.get("result", ""))[-200:]
                lines.append(f"- 工具: {tool}({args_str})")
                lines.append(f"  结果: {result_str}")
        else:
            lines.append("- 无工具调用")

    # ━━ 未利用情报检测 ━━
    # 扫描 evidence/fact 中的关键信息，检查是否出现在最近工具调用参数中
    intel_memories = [m for m in memories if m.kind in ("evidence", "fact")]
    if intel_memories and recent_rounds:
        import re
        # 收集最近所有工具调用的参数文本
        all_args_text = ""
        for r in recent_rounds:
            for tc in r.get("tool_calls", []):
                all_args_text += str(tc.get("args", "")).lower() + " "
                all_args_text += str(tc.get("result", ""))[-500:].lower() + " "

        unused_intel = []
        for m in intel_memories:
            content = m.content
            keywords = []
            # IP 地址
            keywords.extend(re.findall(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', content))
            # 密码/token/key 值（key=value 格式）
            keywords.extend(re.findall(
                r'(?:password|passwd|pwd|token|key|secret|密码|口令)[=：:\s]+([^\s,，。;；]+)',
                content, re.IGNORECASE
            ))
            # 用户名
            keywords.extend(re.findall(
                r'(?:user|username|用户名|账号)[=：:\s]+([^\s,，。;；]+)',
                content, re.IGNORECASE
            ))
            # user/password 格式（如 admin/admin123、root/toor）
            # 匹配「单词/单词」的凭据对，并分别提取
            cred_pairs = re.findall(r'([a-zA-Z0-9_]{2,20})/([a-zA-Z0-9_@!*#$%^&+=]{2,30})', content)
            for u, p in cred_pairs:
                keywords.append(u)
                keywords.append(p)
            # user:password 格式
            cred_pairs2 = re.findall(r'([a-zA-Z0-9_]{2,20}):([a-zA-Z0-9_@!*#$%^&+=]{2,30})', content)
            for u, p in cred_pairs2:
                keywords.append(u)
                keywords.append(p)
            # 中文语境：凭据/泄露/密码/账号 后紧跟的单词（如「泄露 admin/admin123」）
            cn_creds = re.findall(
                r'(?:凭据|泄露|密码|口令|账号|默认)[：:\s]*([a-zA-Z0-9_/@!*#$%^&+=]{2,40})',
                content
            )
            for c in cn_creds:
                keywords.append(c)
            # URL 路径
            paths = re.findall(r'(/[a-zA-Z0-9_\-./]+)', content)
            keywords.extend([p for p in paths if len(p) > 3])
            # 端口
            keywords.extend(re.findall(
                r'(?:端口|port)[=：:\s]*(\d{2,5})', content, re.IGNORECASE
            ))

            if not keywords:
                continue

            keywords = list(dict.fromkeys(keywords))
            used_keys = [k for k in keywords if k.lower() in all_args_text]
            if keywords and not used_keys:
                unused_intel.append({
                    "memory_id": m.id,
                    "content": content,
                    "unused_keywords": keywords,
                })

        if unused_intel:
            lines.append("\n## 可能未利用的情报（仅表示最近审查窗口未命中）")
            for item in unused_intel[:3]:
                keys_str = ", ".join(item["unused_keywords"][:5])
                lines.append(f"- Memory `{item['memory_id']}`: {_excerpt(item['content'], 350)}")
                lines.append(f"  最近窗口未出现: {keys_str}")
            lines.append("")
            lines.append("先排除旧地址、已完成步骤和无关信息；只有确认遗忘时才 send_correction。")

    lines.append("\n请审查以上信息，按 Core Loop 执行。")
    return "\n".join(lines)


def _emit(event_type: str, data=None) -> None:
    write_line({"type": event_type, "data": data})


class ObserverAgent:
    def __init__(self, settings: dict):
        llm_cfg = settings.get("llm", {})
        self.client = OpenAI(
            base_url=llm_cfg.get("base_url") or os.environ.get("LLM_BASE_URL", ""),
            api_key=llm_cfg.get("api_key") or os.environ.get("LLM_API_KEY", ""),
            timeout=__import__("httpx").Timeout(60.0, connect=10.0),
        )
        self.model = llm_cfg.get("observer_model") or llm_cfg.get("default_model") or os.environ.get("LLM_MODEL", "deepseek-v4-flash")
        self._reasoning_effort = llm_cfg.get("observer_reasoning_effort", "high")
        self._thinking_enabled = bool(llm_cfg.get("observer_thinking_enabled", False))
        self._max_output_tokens = int(llm_cfg.get("observer_max_output_tokens", 8192))
        self._max_react_rounds = int(llm_cfg.get("observer_max_react_rounds", 2))

    def review(self, recent_rounds: list[dict], challenge_dir: Path,
               attempt_dir: Path | None = None,
               on_correction: callable = None) -> str:
        user_prompt = _build_observer_prompt(recent_rounds, challenge_dir, attempt_dir)

        tool_registry = build_tool_registry(
            lambda args: _handle_correction(
                args,
                on_correction,
                challenge_dir=challenge_dir,
                attempt_dir=attempt_dir,
                reviewed_round=recent_rounds[-1].get("round", 0) if recent_rounds else 0,
            )
        )

        messages = [
            {"role": "system", "content": OBSERVER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # Observer 是控制面，不应消耗接近 Solver 的推理预算。
        for _ in range(self._max_react_rounds):
            kwargs = completion_kwargs(
                model=self.model,
                messages=messages,
                tools=tool_registry.definitions,
                tool_choice="auto",
                max_tokens=self._max_output_tokens,
                reasoning_effort=self._reasoning_effort,
                thinking_enabled=self._thinking_enabled,
            )
            deadline = float(getattr(_ctx, "deadline", 0.0) or 0.0)

            def create_observer_completion(**request_kwargs):
                client = self.client
                if deadline:
                    remaining = deadline - __import__("time").time()
                    if remaining <= 0:
                        raise TimeoutError("observer deadline exceeded")
                    with_options = getattr(client, "with_options", None)
                    if callable(with_options):
                        client = with_options(timeout=max(0.1, min(60.0, remaining)))
                return client.chat.completions.create(**request_kwargs)

            try:
                response = create_with_retry(
                    create_observer_completion,
                    **kwargs,
                    max_attempts=3,
                    deadline=deadline,
                )
            except TimeoutError:
                return "NO_CHANGE"

            msg = response.choices[0].message
            messages.append(assistant_message_dict(msg))

            if not msg.tool_calls:
                summary = getattr(msg, "content", None) or "NO_CHANGE"
                _emit("observer_end", {"summary": summary})
                return summary

            for tool_call in msg.tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                executor = tool_registry.executors.get(tool_name)
                if executor:
                    try:
                        result = executor(tool_args)
                    except Exception as e:
                        result = f"[错误] {e}"
                else:
                    result = f"[错误] 未知工具：{tool_name}"

                _emit("observer_tool", {"tool": tool_name, "result": result[:200]})

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        return "NO_CHANGE"


def _handle_correction(
    args: dict,
    on_correction: callable,
    *,
    challenge_dir: Path | None = None,
    attempt_dir: Path | None = None,
    reviewed_round: int = 0,
) -> str:
    from solver.runtime.observer_advice import ObserverAdvice
    from solver.runtime.strategy_controller import load_decision_summary

    summary = load_decision_summary(attempt_dir or challenge_dir) if (attempt_dir or challenge_dir) else {}
    current_version = int(summary.get("state_version", 0) or 0)
    advice = ObserverAdvice.from_mapping(
        args,
        default_state_version=current_version,
        default_round=reviewed_round,
    )
    if not advice.message:
        return "[错误] 纠偏消息不能为空"
    if advice.state_version != current_version:
        _emit("observer_correction_stale", {
            "reason": "state_version_mismatch",
            "advice": advice.to_dict(),
            "current_state_version": current_version,
        })
        return (
            f"[过期] state_version={advice.state_version}，"
            f"当前版本={current_version}，未发送纠偏"
        )
    if on_correction:
        try:
            on_correction(advice)
        except TypeError:
            # Compatibility with local callbacks that still accept text.
            on_correction(advice.render())
    _emit("observer_correction", advice.to_dict())
    return f"[纠偏] 已发送：{advice.render()}"
