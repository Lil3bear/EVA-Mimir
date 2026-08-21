"""Validated and journaled tool execution."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from solver.runtime.journal import ExecutionJournal


def parse_tool_args(
    tool_name: str, raw_args: str, schemas: Mapping[str, dict]
) -> tuple[dict, str]:
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError as exc:
        return {}, f"[错误] 工具参数不是有效 JSON：{exc.msg}"
    if not isinstance(args, dict):
        return {}, "[错误] 工具参数必须是 JSON object"

    schema = schemas.get(tool_name, {})
    missing = [name for name in schema.get("required", []) if name not in args]
    if missing:
        return args, f"[错误] 工具参数缺少必填字段：{', '.join(missing)}"

    expected_types = {
        "string": str,
        "integer": int,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    properties = schema.get("properties", {})
    for name, value in args.items():
        expected = expected_types.get(properties.get(name, {}).get("type"))
        if expected and (
            not isinstance(value, expected)
            or expected is int
            and isinstance(value, bool)
        ):
            return args, f"[错误] 工具参数 {name} 类型错误，应为 {properties[name]['type']}"
    return args, ""


@dataclass(frozen=True)
class ToolRunResult:
    result: str
    blocked: bool = False
    journal_error: str = ""
    executed: bool = False


class ToolRunner:
    def __init__(
        self,
        executors: Mapping[str, Callable[[dict], str]],
        schemas: Mapping[str, dict],
        journal: ExecutionJournal,
    ):
        self.executors = executors
        self.schemas = schemas
        self.journal = journal

    def parse(self, tool_name: str, raw_args: str) -> tuple[dict, str]:
        return parse_tool_args(tool_name, raw_args, self.schemas)

    def run(
        self,
        *,
        call_id: str,
        tool_name: str,
        tool_args: dict,
        args_error: str,
        round_num: int,
        gate: Callable[[str, dict], str],
    ) -> ToolRunResult:
        if args_error:
            return ToolRunResult(args_error)
        executor = self.executors.get(tool_name)
        if executor is None:
            return ToolRunResult(f"[错误] 未知工具：{tool_name}")

        try:
            self.journal.prepare(call_id, tool_name, tool_args, round_num)
        except Exception as exc:
            return ToolRunResult(f"[错误] 持久化执行日志不可用，工具未执行：{exc}")

        blocked = gate(tool_name, tool_args)
        executed = False
        try:
            if blocked:
                result = blocked
            else:
                result = executor(tool_args)
                executed = True
        except Exception as exc:
            result = f"[错误] 工具执行异常：{exc}"

        try:
            self.journal.complete(call_id, tool_name, result)
            return ToolRunResult(result, bool(blocked), executed=executed)
        except Exception as exc:
            warning = f"工具已执行，但完成状态未能持久化：{exc}"
            return ToolRunResult(
                result + f"\n[警告] {warning}",
                bool(blocked),
                warning,
                executed,
            )
