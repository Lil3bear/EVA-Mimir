import os
from pathlib import Path

from shared.data import memory as mem_store, ideas as idea_store
from solver.tools.registry import ToolRegistry, ToolSpec
from solver.worker_context import ctx as _ctx


def _challenge_dir() -> Path:
    # 优先从 thread-local 上下文读取（并行安全），fallback 到环境变量
    if _ctx.challenge_dir and _ctx.challenge_dir != "/workspace":
        return Path(_ctx.challenge_dir)
    return Path(os.environ.get("CTF_WORKSPACE", "/workspace"))


# Observer 拥有完整的 memory/ideas 管理权（增删改），Solver 只能追加


def _excerpt(text: str, limit: int) -> str:
    text = str(text or "")
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head
    return text[:head] + " ...[省略]... " + text[-tail:]

READ_FILE_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "读取文件内容。用于查阅 Solver 原始对话历史（路径见 user prompt 中的 history_path 字段）。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件绝对路径"},
                "limit": {"type": "integer", "description": "最多读取行数，默认 50", "default": 50},
            },
            "required": ["path"],
        },
    },
}

MEMORY_LIST_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "memory_list",
        "description": "列出所有 Memory 记录，用于审查当前已知事实和失败边界。",
        "parameters": {"type": "object", "properties": {}},
    },
}

MEMORY_ADD_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "memory_add",
        "description": "新增一条 Memory 记录。",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["fact", "evidence", "failure", "note"],
                },
                "content": {"type": "string"},
            },
            "required": ["kind", "content"],
        },
    },
}

MEMORY_DELETE_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "memory_delete",
        "description": "删除一条过时或错误的 Memory 记录（填 id 前缀即可）。",
        "parameters": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "Memory 记录的 id 或 id 前缀"},
            },
            "required": ["memory_id"],
        },
    },
}

MEMORY_UPDATE_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "memory_update",
        "description": (
            "更新一条已有 Memory 记录的内容。当新发现与旧记录矛盾时，"
            "优先用此工具纠正旧条目，而不是新增一条矛盾记录。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string", "description": "Memory 记录的 id 或 id 前缀"},
                "content": {"type": "string", "description": "更新后的内容"},
            },
            "required": ["memory_id", "content"],
        },
    },
}

IDEA_LIST_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "idea_list",
        "description": "列出所有 Ideas，用于审查当前攻击方向假设。",
        "parameters": {"type": "object", "properties": {}},
    },
}

IDEA_ADD_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "idea_add",
        "description": "新增一个攻击方向假设。",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "具体可执行的攻击假设"},
            },
            "required": ["content"],
        },
    },
}

IDEA_UPDATE_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "idea_update",
        "description": "更新一个 Idea 的状态（pending/testing/verified/failed）和结果。",
        "parameters": {
            "type": "object",
            "properties": {
                "idea_id": {"type": "string", "description": "Idea 的 id 或 id 前缀"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "testing", "verified", "failed"],
                },
                "result": {"type": "string", "description": "验证结果说明（可选）"},
            },
            "required": ["idea_id", "status"],
        },
    },
}

SEND_CORRECTION_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "send_correction",
        "description": (
            "向 Solver 发送带版本和失效条件的结构化纠偏。只在 Solver 明显陷入低效循环或方向错误时使用，"
            "不要干扰正常推进。state_version 必须复制当前决策控制状态版本。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "switch_strategy", "verify_evidence", "review_blackboard",
                        "continue_current", "stop_exhausted"
                    ],
                },
                "mode": {
                    "type": "string",
                    "enum": ["MAP", "EXPLORE", "EXPLOIT", "ALTERNATE", "VERIFY", "RECOVER"],
                },
                "reason": {"type": "string"},
                "message": {
                    "type": "string",
                    "description": "发给 Solver 的简短方向性纠偏",
                },
                "state_version": {
                    "type": "integer",
                    "description": "审查时看到的决策控制 state_version",
                },
                "priority": {"type": "integer", "minimum": 0, "maximum": 100},
                "expires_after_rounds": {
                    "type": "integer", "minimum": 1, "maximum": 24,
                },
            },
            "required": ["action", "mode", "reason", "message", "state_version"],
        },
    },
}

OBSERVER_TOOL_DEFS = [
    READ_FILE_TOOL_DEF,
    MEMORY_LIST_TOOL_DEF,
    MEMORY_ADD_TOOL_DEF,
    MEMORY_DELETE_TOOL_DEF,
    MEMORY_UPDATE_TOOL_DEF,
    IDEA_LIST_TOOL_DEF,
    IDEA_ADD_TOOL_DEF,
    IDEA_UPDATE_TOOL_DEF,
    SEND_CORRECTION_TOOL_DEF,
]


def build_tool_registry(send_correction) -> ToolRegistry:
    return ToolRegistry((
        ToolSpec(READ_FILE_TOOL_DEF, read_file),
        ToolSpec(MEMORY_LIST_TOOL_DEF, memory_list),
        ToolSpec(MEMORY_ADD_TOOL_DEF, memory_add),
        ToolSpec(MEMORY_DELETE_TOOL_DEF, memory_delete),
        ToolSpec(MEMORY_UPDATE_TOOL_DEF, memory_update),
        ToolSpec(IDEA_LIST_TOOL_DEF, idea_list),
        ToolSpec(IDEA_ADD_TOOL_DEF, idea_add),
        ToolSpec(IDEA_UPDATE_TOOL_DEF, idea_update),
        ToolSpec(SEND_CORRECTION_TOOL_DEF, send_correction),
    ))


def read_file(args: dict) -> str:
    path = args.get("path", "").strip()
    limit = int(args.get("limit", 50))
    if not path:
        return "[错误] path 不能为空"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if len(lines) > limit:
            lines = lines[-limit:]
            prefix = f"[文件过长，只显示最后 {limit} 行]\n"
        else:
            prefix = ""
        content = prefix + "".join(lines)
        if len(content) > 12000:
            content = "[历史输出过长，仅保留末尾 12000 字符]\n" + content[-12000:]
        return content
    except FileNotFoundError:
        return f"[错误] 文件不存在：{path}"
    except Exception as e:
        return f"[错误] 读取失败：{e}"


def memory_list(args: dict) -> str:
    entries = mem_store.list_memory(_challenge_dir())
    if not entries:
        return "[Memory] 暂无记录"
    lines = ["[Memory 看板]"]
    for e in entries:
        lines.append(f"- [{e.kind}] {e.id} ({e.attempt_id}): {_excerpt(e.content, 700)}")
    return "\n".join(lines)


def memory_add(args: dict) -> str:
    kind = args.get("kind", "note")
    content = args.get("content", "").strip()
    if not content:
        return "[错误] content 不能为空"
    entry, created = mem_store.add_memory_with_status(
        _challenge_dir(), kind=kind, content=content, source="observer",
        attempt_id=_ctx.attempt_id,
    )
    if not created:
        return f"[Memory] 已存在，未新增 [{entry.kind}] {entry.id}: {entry.content}"
    return f"[Memory] 已添加 [{entry.kind}] {entry.id}: {entry.content}"


def memory_delete(args: dict) -> str:
    memory_id = args.get("memory_id", "")
    ok = mem_store.delete_memory(_challenge_dir(), memory_id)
    return f"[Memory] {'已删除' if ok else '未找到'} {memory_id}"


def memory_update(args: dict) -> str:
    memory_id = args.get("memory_id", "")
    content = args.get("content", "").strip()
    if not content:
        return "[错误] content 不能为空"
    ok = mem_store.update_memory(_challenge_dir(), memory_id, content=content)
    return f"[Memory] {'已更新' if ok else '未找到'} {memory_id}"


def idea_list(args: dict) -> str:
    ideas = idea_store.list_ideas(_challenge_dir())
    if not ideas:
        return "[Ideas] 暂无攻击方向"
    lines = ["[Ideas 看板]"]
    for i in ideas:
        result_str = f" → {i.result}" if i.result else ""
        lines.append(
            f"- [{i.status}] {i.id} ({i.owner_attempt_id}): "
            f"{_excerpt(i.content + result_str, 450)}"
        )
    return "\n".join(lines)


def idea_add(args: dict) -> str:
    content = args.get("content", "").strip()
    if not content:
        return "[错误] content 不能为空"
    idea = idea_store.add_idea(
        _challenge_dir(), content=content, source="observer",
        owner_attempt_id=_ctx.attempt_id,
    )
    return f"[Ideas] 已添加 [{idea.status}] {idea.id}: {content}"


def idea_update(args: dict) -> str:
    idea_id = args.get("idea_id", "")
    status = args.get("status", "")
    result = args.get("result", None)
    ok = idea_store.update_idea(_challenge_dir(), idea_id, status=status, result=result)
    return f"[Ideas] {'已更新' if ok else '未找到'} {idea_id} → {status}"
