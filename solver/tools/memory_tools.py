import os
from pathlib import Path

from shared.data import memory as mem_store
from solver.worker_context import ctx as _ctx


def _challenge_dir() -> Path:
    # 优先从 thread-local 上下文读取（并行安全），fallback 到环境变量
    if _ctx.challenge_dir and _ctx.challenge_dir != "/workspace":
        return Path(_ctx.challenge_dir)
    return Path(os.environ.get("CTF_WORKSPACE", "/workspace"))


MEMORY_ADD_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "memory_add",
        "description": (
            "记录一条可复用的发现到 Memory 看板。"
            "适合记录：已确认的事实（fact）、攻击证据（evidence）、"
            "失败边界（failure，如「SQLi 对 username 字段无效」）、笔记（note）。"
            "不要记录过程日志，只记录有复用价值的结论。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["fact", "evidence", "failure", "note"],
                    "description": "记忆类型",
                },
                "content": {
                    "type": "string",
                    "description": "记忆内容，要具体可执行，不要写过程描述",
                },
                "refs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "相关的文件路径或 URL（可选）",
                },
            },
            "required": ["kind", "content"],
        },
    },
}

MEMORY_LIST_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "memory_list",
        "description": "列出当前题目的所有 Memory 记录，查看已有发现和失败边界。",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "最多返回多少条（默认全部）",
                }
            },
        },
    },
}


def memory_add(args: dict) -> str:
    kind = args.get("kind", "note")
    content = args.get("content", "").strip()
    refs = args.get("refs", [])

    if not content:
        return "[错误] content 不能为空"

    entry, created = mem_store.add_memory_with_status(
        _challenge_dir(), kind=kind, content=content, refs=refs, source="solver",
        attempt_id=_ctx.attempt_id,
    )
    if not created:
        return f"[Memory] 已存在，未新增 [{entry.kind}] {entry.id}：{entry.content}"
    return f"[Memory] 已记录 [{entry.kind}] {entry.id}：{entry.content}"


def memory_list(args: dict) -> str:
    limit = args.get("limit", None)
    entries = mem_store.list_memory(_challenge_dir(), limit=limit)

    if not entries:
        return "[Memory] 暂无记录"

    lines = ["[Memory 看板]"]
    for e in entries:
        refs_str = f" (refs: {', '.join(e.refs)})" if e.refs else ""
        lines.append(f"- [{e.kind}] {e.id} ({e.attempt_id}): {e.content}{refs_str}")
    return "\n".join(lines)
