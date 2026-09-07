import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from shared.data import memory as mem_store
from solver.runtime.state_events import StateEventLog
from solver.runtime.scoped_state import (
    private_root,
    publish_memory_proposal,
    solver_memories,
    write_root,
)
from solver.worker_context import ctx as _ctx

_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _current_target_host() -> str:
    value = (getattr(_ctx, "target_url", "") or "").strip()
    if not value:
        return ""
    try:
        return urlsplit(value if "://" in value else f"//{value}").hostname or ""
    except ValueError:
        return ""


def _rotated_host_note(content: str, target: str) -> str:
    """标记"同网段实例轮换"导致的疑似过期条目。

    评测里同一题重跑常换实例 IP（如 .97→.98，同 /24 只改末段）。此时上一轮
    针对旧 IP 的主机结论会误导本轮（见 run c-08：memory 说 .98 是 FastAPI，
    实际目标是 .97，模型在两个 IP 间反复横跳耗尽预算）。只在"同 /24、末段不同、
    且当前目标未出现在该条里"时提示，避免误伤横向移动记录的内网 IP。
    """
    if not target or target in content:
        return ""
    tparts = target.split(".")
    if len(tparts) != 4:
        return ""
    tprefix = ".".join(tparts[:3])
    for ip in _IP_RE.findall(content):
        parts = ip.split(".")
        if len(parts) == 4 and ".".join(parts[:3]) == tprefix and parts[3] != tparts[3]:
            return (
                f"  ⚠️ 疑似旧实例：当前目标 {target}，此条是 {ip}（同网段轮换）。"
                f"主机相关结论用前必须对 {target} 重新验证，别直接照搬。"
            )
    return ""


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

    from solver.runtime.observer_policy import memory_write_allowed

    allowed, gate_reason = memory_write_allowed(content, kind=str(kind or "note"))
    if not allowed:
        return (
            f"[拒绝] Memory 写入被污染门控拦截（{gate_reason}）。"
            "不要把截断历史或 playbook 长文写入 Memory。"
        )

    entry, created = mem_store.add_memory_with_status(
        _write_dir(), kind=kind, content=content, refs=refs, source="solver",
        attempt_id=_ctx.attempt_id,
    )
    if not created:
        return f"[Memory] 已存在，未新增 [{entry.kind}] {entry.id}：{entry.content}"
    # Explicit scope ledger: solver-private discoveries are recorded with
    # attempt_private scope so the whole board is auditable per challenge.
    try:
        from solver.runtime.harness import RefinementLog, classify_scope
        write_dir = _write_dir()
        RefinementLog(_challenge_dir()).append({
            "action": "create",
            "kind": kind,
            "memory_id": entry.id,
            "scope": classify_scope(_challenge_dir(), write_dir).value,
            "reason": "solver discovery",
            "root": str(write_dir),
            "before": None,
            "after": entry.__dict__,
            "source": "solver",
            "attempt_id": _ctx.attempt_id,
        })
    except Exception:
        pass
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

    target = _current_target_host()
    lines = ["[Memory 看板]"]
    for e in entries:
        refs_str = f" (refs: {', '.join(e.refs)})" if e.refs else ""
        stale = _rotated_host_note(e.content, target)
        lines.append(f"- [{e.kind}] {e.id} ({e.attempt_id}): {e.content}{refs_str}{stale}")
    return "\n".join(lines)


def memory_share(args: dict) -> str:
    kind = str(args.get("kind", "fact"))
    content = str(args.get("content", "")).strip()
    refs = args.get("refs", [])
    if not content:
        return "[错误] content 不能为空"
    from solver.runtime.observer_policy import memory_write_allowed

    allowed, gate_reason = memory_write_allowed(content, kind=kind or "fact")
    if not allowed:
        return (
            f"[拒绝] 共享提案被污染门控拦截（{gate_reason}）。"
            "不得把截断历史或 playbook 长文提交共享。"
        )
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
