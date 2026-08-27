import os
from pathlib import Path

from shared.data import memory as mem_store
from solver.worker_context import ctx as _ctx
from solver.runtime.state_events import StateEventLog
from solver.runtime.scoped_state import (
    private_root,
    publish_memory_proposal,
    solver_memories,
    write_root,
)


def _challenge_dir() -> Path:
    if _ctx.challenge_dir and _ctx.challenge_dir != "/workspace":
        return Path(_ctx.challenge_dir)
    return Path(os.environ.get("CTF_WORKSPACE", "/workspace"))


def _scope() -> str:
    return getattr(_ctx, "memory_scope", "private") or "private"


def _private_dir() -> Path:
    return private_root(getattr(_ctx, "attempt_dir", ""), _challenge_dir())


def _write_dir() -> Path:
    return write_root(_challenge_dir(), getattr(_ctx, "attempt_dir", ""), _scope())


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
        "description": "列出当前 Solver 的私有 Memory，以及 Observer 已批准的本题共享事实。不会读取其他 Solver 的原始思路。",
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


MEMORY_SHARE_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "memory_share",
        "description": (
            "将当前 Solver 已验证的单条事实提交给 Observer 审核共享。"
            "这只是 proposal，不会立即污染其他 Solver 的 Memory。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["fact", "evidence", "failure", "note"]},
                "content": {"type": "string"},
                "refs": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["kind", "content"],
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
        _write_dir(), kind=kind, content=content, refs=refs, source="solver",
        attempt_id=_ctx.attempt_id,
    )
    if not created:
        return f"[Memory] 已存在，未新增 [{entry.kind}] {entry.id}：{entry.content}"
    try:
        StateEventLog(_challenge_dir()).append(
            "memory_added",
            {"memory_id": entry.id, "kind": entry.kind, "scope": _scope()},
            attempt_id=_ctx.attempt_id,
            run_id=getattr(_ctx, "run_id", ""),
        )
    except Exception:
        pass
    return f"[Memory] 已记录 [{entry.kind}] {entry.id}：{entry.content}"


def memory_list(args: dict) -> str:
    limit = args.get("limit", None)
    entries = solver_memories(
        _challenge_dir(), _private_dir(), limit=limit, scope=_scope()
    )

    if not entries:
        return "[Memory] 暂无记录"

    lines = ["[Memory 看板]"]
    for e in entries:
        refs_str = f" (refs: {', '.join(e.refs)})" if e.refs else ""
        lines.append(f"- [{e.kind}] {e.id} ({e.attempt_id}): {e.content}{refs_str}")
    return "\n".join(lines)


def memory_share(args: dict) -> str:
    kind = str(args.get("kind", "fact"))
    content = str(args.get("content", "")).strip()
    refs = args.get("refs", [])
    if not content:
        return "[错误] content 不能为空"
    proposal_id = publish_memory_proposal(
        _challenge_dir(), attempt_id=_ctx.attempt_id, kind=kind,
        content=content, refs=refs if isinstance(refs, list) else [],
    )
    try:
        StateEventLog(_challenge_dir()).append(
            "memory_proposal_created",
            {"proposal_id": proposal_id, "kind": kind},
            attempt_id=_ctx.attempt_id,
            run_id=getattr(_ctx, "run_id", ""),
        )
    except Exception:
        pass
    return f"[共享提案] 已提交 {proposal_id}，等待 Observer 验证；其他 Solver 暂不可见。"
