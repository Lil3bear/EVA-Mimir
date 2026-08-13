import os
from pathlib import Path

from shared.data import ideas as idea_store
from solver.worker_context import ctx as _ctx


def _challenge_dir() -> Path:
    # 优先从 thread-local 上下文读取（并行安全），fallback 到环境变量
    if _ctx.challenge_dir and _ctx.challenge_dir != "/workspace":
        return Path(_ctx.challenge_dir)
    return Path(os.environ.get("CTF_WORKSPACE", "/workspace"))


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

    idea = idea_store.add_idea(_challenge_dir(), content=content, source="solver")
    return f"[Ideas] 已添加 [{idea.status}] {idea.id}：{content}"


def idea_list(args: dict) -> str:
    limit = args.get("limit", None)
    ideas = idea_store.list_ideas(_challenge_dir(), limit=limit)

    if not ideas:
        return "[Ideas] 暂无攻击方向"

    lines = ["[Ideas 看板]"]
    for i in ideas:
        result_str = f" → {i.result}" if i.result else ""
        lines.append(f"- [{i.status}] {i.id}: {i.content}{result_str}")
    return "\n".join(lines)
