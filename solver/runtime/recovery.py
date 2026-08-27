"""Crash recovery policy for prepared tool calls."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping

from solver.runtime.journal import SAFE_REPLAY_TOOLS, ExecutionJournal


def recover_execution(
    state: dict,
    journal: ExecutionJournal,
    executors: Mapping[str, Callable[[dict], str]],
) -> str:
    pending = state.get("pending", [])
    recent = state.get("recent_completed", [])
    if not pending and not recent:
        return ""

    lines = ["[持久化恢复] 上一次执行未在安全边界结束。以下内容来自本地 fsync 日志。"]
    if recent:
        lines.append("最近已确认完成的工具调用：")
        for event in recent:
            lines.append(f"- {event.get('tool')}：{str(event.get('result', ''))[:1200]}")

    safe_pending = [event for event in pending if event.get("tool") in SAFE_REPLAY_TOOLS]
    unsafe_pending = [event for event in pending if event.get("tool") not in SAFE_REPLAY_TOOLS]
    if safe_pending:
        lines.append("已自动重放的只读调用：")
        for event in safe_pending:
            tool = str(event.get("tool", ""))
            executor = executors.get(tool)
            try:
                result = executor(dict(event.get("args") or {})) if executor else "[错误] 未知工具"
            except Exception as exc:
                result = f"[错误] 恢复重放失败：{exc}"
            journal.complete(
                str(event.get("call_id", "")),
                tool,
                result,
                run_id=str(event.get("run_id", "")),
                recovered=True,
            )
            lines.append(f"- {tool}：{result[:1200]}")

    if unsafe_pending:
        lines.append("状态不确定且禁止自动重放的调用：")
        for event in unsafe_pending:
            args = json.dumps(event.get("args") or {}, ensure_ascii=False, default=str)
            lines.append(f"- {event.get('tool')} {args[:1000]}")
        lines.append("这些调用可能已经产生副作用。不要直接重复执行；先读取目标状态、文件或平台状态进行验证。")
    return "\n".join(lines)
