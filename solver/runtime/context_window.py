"""Context sizing and compaction that is independent of the agent loop."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable


def message_token_estimate(message: dict) -> int:
    raw = json.dumps(message, ensure_ascii=False, default=str)
    return max(1, len(raw.encode("utf-8")) // 4) + 8


def serialize_messages(messages: list[dict]) -> str:
    chunks: list[str] = []
    labels = {"user": "User", "assistant": "Assistant", "tool": "Tool"}
    for message in messages:
        role = labels.get(message.get("role", ""), message.get("role", "Message"))
        content = str(message.get("content") or "")
        if message.get("role") == "tool" and len(content) > 2000:
            content = content[:1000] + "\n...[tool output truncated for summary]...\n" + content[-1000:]
        tool_calls = message.get("tool_calls")
        if tool_calls:
            content += "\nTool calls: " + json.dumps(
                tool_calls, ensure_ascii=False, default=str
            )
        chunks.append(f"[{role}]\n{content}")
    return "\n\n".join(chunks)


@dataclass(frozen=True)
class CompactionResult:
    messages: list[dict]
    summary: str = ""
    changed: bool = False


class ContextWindow:
    def __init__(self, tool_defs: list[dict], keep_recent_tokens: int):
        self.tool_tokens = len(
            json.dumps(tool_defs, ensure_ascii=False).encode("utf-8")
        ) // 4
        self.keep_recent_tokens = keep_recent_tokens

    def estimate(self, messages: list[dict]) -> int:
        return sum(message_token_estimate(message) for message in messages) + self.tool_tokens

    def compact(
        self,
        messages: list[dict],
        summarize: Callable[[list[dict]], str],
    ) -> CompactionResult:
        if len(messages) <= 2:
            return CompactionResult(messages)

        system, task_message = messages[:2]
        observer_messages = [
            message
            for message in messages
            if message.get("role") == "user"
            and isinstance(message.get("content"), str)
            and message["content"].startswith("[OBSERVER]")
        ]
        history = [
            message
            for message in messages[2:]
            if not (
                message.get("role") == "user"
                and isinstance(message.get("content"), str)
                and message["content"].startswith(("[OBSERVER]", "[上下文已压缩"))
            )
        ]

        start = len(history)
        kept_tokens = 0
        while start > 0 and kept_tokens < self.keep_recent_tokens:
            start -= 1
            kept_tokens += message_token_estimate(history[start])
        while start > 0 and history[start].get("role") == "tool":
            start -= 1

        discarded = history[:start] + observer_messages[:-2]
        if not discarded:
            return CompactionResult(messages)

        summary = summarize(discarded)
        summary_message = {
            "role": "user",
            "content": (
                "[上下文已压缩，以下是截至当前的解题状态摘要，请以此为基础继续]\n\n"
                + summary
            ),
        }
        compacted = (
            [system, task_message, summary_message]
            + history[start:]
            + observer_messages[-2:]
        )
        return CompactionResult(compacted, summary, True)
