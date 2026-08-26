import os
from pathlib import Path

from shared.data import ideas as idea_store
from solver.worker_context import ctx as _ctx
from solver.runtime.scoped_state import private_root, solver_ideas, write_root
from solver.runtime.claims import ClaimStore
from solver.runtime.state_events import StateEventLog


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


IDEA_ADD_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "idea_add",
        "description": (
            "添加一个值得探索的攻击方向假设到 Ideas 看板。"
            "好的 idea 是具体可执行的攻击假设，例如「尝试对 /login 的 username 参数做 union SQLi」。"
            "坏的 idea：「已访问过 /admin」（过程记录）、「再想想」（没有方向）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "攻击方向假设，要具体可执行",
                }
            },
            "required": ["content"],
        },
    },
}

IDEA_LIST_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "idea_list",
        "description": "列出当前题目所有攻击方向假设，查看待探索和已验证的方向。",
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


def idea_add(args: dict) -> str:
    content = args.get("content", "").strip()
    if not content:
        return "[错误] content 不能为空"

    claims = ClaimStore(_challenge_dir())
    claimed, existing = claims.claim(
        content,
        owner=_ctx.attempt_id,
        round_num=int(getattr(_ctx, "current_round", 0) or 0),
        lease_rounds=8,
    )
    if not claimed:
        return (
            f"[Hypothesis busy] 当前方向已被 attempt={existing.get('owner', '?')} 占用，"
            "请选择不同的攻击假设，不要重复同一路线。"
        )

    idea = idea_store.add_idea(
        _write_dir(), content=content, source="solver",
        owner_attempt_id=_ctx.attempt_id,
    )
    try:
        StateEventLog(_challenge_dir()).append(
            "hypothesis_claimed",
            {"claim_key": existing.get("key", claims.key(content)), "idea_id": idea.id},
            attempt_id=_ctx.attempt_id,
            run_id=getattr(_ctx, "run_id", ""),
        )
    except Exception:
        pass
    return (
        f"[Ideas] 已添加 [{idea.status}] {idea.id}：{content}\n"
        f"[Hypothesis] 已领取 claim={existing.get('key', claims.key(content))}，owner={_ctx.attempt_id}"
    )


def idea_list(args: dict) -> str:
    limit = args.get("limit", None)
    ideas = solver_ideas(_challenge_dir(), _private_dir(), limit=limit, scope=_scope())
    claims = ClaimStore(_challenge_dir()).list_active(
        round_num=int(getattr(_ctx, "current_round", 0) or 0)
    )

    lines = ["[Ideas 看板]"]
    if ideas:
        for i in ideas:
            result_str = f" → {i.result}" if i.result else ""
            lines.append(f"- [{i.status}] {i.id} ({i.owner_attempt_id}): {i.content}{result_str}")
    else:
        lines.append("暂无当前 attempt 私有方向")
    if claims:
        lines.append("[已占用方向（仅显示 owner，不显示其他 Solver 的思考）]")
        for claim in claims:
            lines.append(
                f"- {claim.get('owner', '?')}: {claim.get('description', '')} "
                f"(lease_until={claim.get('lease_until', 0)})"
            )
    return "\n".join(lines)
