import os
import json
import threading
from typing import Any

from shared.jsonl import deserialize, write_line
from solver.ctfplatform.tsecbench_client import (
    Challenge,
    DuplicateSubmit,
    InvalidState,
    TaskNotFound,
    TsecbenchClient,
)
from solver.runtime.challenge_ledger import ChallengeLedger
from solver.runtime.submission_store import SubmissionOutcome, SubmissionStore
from solver.worker_context import ctx as _ctx


# Host Bridge 响应等待表（request_id → threading.Event）— 全局共享，线程安全
_pending: dict[str, threading.Event] = {}
_responses: dict[str, dict] = {}
_lock = threading.Lock()


def configure_tsecbench(client: TsecbenchClient, unique_code: str) -> None:
    """选择当前 Tsecbench 题目（线程安全，写入 thread-local）。"""
    _ctx.client = client
    _ctx.unique_code = unique_code.strip()


def clear_tsecbench() -> None:
    _ctx.client = None
    _ctx.unique_code = ""


def _current_unique_code(params: dict | None = None) -> str:
    code = (params or {}).get("unique_code", "")
    return str(code or _ctx.unique_code or "").strip()


def register_response(request_id: str, response: dict) -> None:
    with _lock:
        _responses[request_id] = response
        event = _pending.pop(request_id, None)
    if event:
        event.set()


def _request_bridge(action: str, params: dict, timeout: float = 30.0) -> dict:
    request_id = os.urandom(4).hex()
    done = threading.Event()
    with _lock:
        _pending[request_id] = done

    msg = {
        "type": "host_bridge_request",
        "request_id": request_id,
        "action": action,
        "params": params,
    }
    write_line(msg)

    done.wait(timeout=timeout)

    with _lock:
        response = _responses.pop(request_id, None)
        _pending.pop(request_id, None)

    if response is None:
        raise TimeoutError(f"Host Bridge 响应超时：{action}")
    if not response.get("success"):
        raise RuntimeError(response.get("error", "Host Bridge 返回失败"))
    return response.get("data", {})


SUBMIT_FLAG_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "challenge_submit_flag",
        "description": (
            "提交找到的 flag。找到 flag 后必须立即调用此工具提交，"
            "同时提供简短的解题路线说明（writeup）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "flag": {
                    "type": "string",
                    "description": "找到的 flag 字符串",
                },
                "writeup": {
                    "type": "string",
                    "description": "简短的解题路线说明，例如「登录接口 username 参数 union SQLi，从 flags 表读取 flag」",
                },
            },
            "required": ["flag", "writeup"],
        },
    },
}

GET_STATE_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "challenge_get_state",
        "description": "获取当前题目状态，包括已找到的 flag、题目信息等。",
        "parameters": {"type": "object", "properties": {}},
    },
}

GET_HINT_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "challenge_get_hint",
        "description": "获取题目提示。在尝试多种方向仍无进展时使用。",
        "parameters": {"type": "object", "properties": {}},
    },
}

START_CHALLENGE_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "challenge_start",
        "description": "启动指定的 Tsecbench 题目并返回靶场地址。多题调度器通常会自动调用，不要猜测题目编号。",
        "parameters": {
            "type": "object",
            "properties": {"unique_code": {"type": "string"}},
            "required": ["unique_code"],
        },
    },
}

CLOSE_CHALLENGE_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "challenge_close",
        "description": "关闭指定的 Tsecbench 题目容器并释放资源。",
        "parameters": {
            "type": "object",
            "properties": {"unique_code": {"type": "string"}},
            "required": ["unique_code"],
        },
    },
}


def _request_tsecbench(action: str, params: dict) -> dict:
    client = _ctx.client
    if client is None:
        raise RuntimeError("Tsecbench 客户端未配置")

    if action == "challenge_submit_flag":
        result = client.submit_flag(
            _current_unique_code(params), params.get("flag", "")
        )
        return {
            "correct": result.correct,
            "awarded": result.awarded,
            "cumulative_score": result.cumulative_score,
            "correct_flag_count": result.correct_flag_count,
            "total_flag_count": result.total_flag_count,
            "matched_flag_index": result.matched_flag_index,
            "is_completed": result.is_completed,
        }

    if action == "challenge_get_state":
        challenges = client.list_challenges()
        code = _current_unique_code(params)
        selected = next((item for item in challenges if item.unique_code == code), None)
        if selected is None:
            return {"challenges": [item.__dict__ for item in challenges]}
        return _challenge_to_state(selected)

    if action == "challenge_get_hint":
        result = client.get_hint(_current_unique_code(params))
        return {"unique_code": result.unique_code, "hints": [result.hint] if result.hint else []}

    if action == "challenge_start":
        result = client.start_challenge(_current_unique_code(params))
        return {"unique_code": result.unique_code, "container_addr": list(result.container_addr)}

    if action == "challenge_close":
        result = client.close_challenge(_current_unique_code(params))
        return {"unique_code": result.unique_code, "closed": result.closed}

    raise ValueError(f"Tsecbench 不支持 action: {action}")


def _challenge_to_state(challenge: Challenge) -> dict:
    return {
        "name": challenge.unique_code,
        "category": "unknown",
        "difficulty": challenge.difficulty,
        "url": "",
        "description": challenge.description or "",
        "is_completed": challenge.is_completed,
        "correct_flags": [],
        "unique_code": challenge.unique_code,
        "flag_count": challenge.flag_count,
        "correct_flag_count": challenge.correct_flag_count,
        "container_status": challenge.container_status,
        "container_addr": list(challenge.container_addr),
    }


def _request_backend(action: str, params: dict) -> dict:
    if _ctx.client is None:
        return _request_bridge(action, params)
    try:
        return _request_tsecbench(action, params)
    except (TaskNotFound, InvalidState) as exc:
        # ToolRunner 将异常格式化成文本，但任务终止必须穿透到
        # Agent/Scheduler，不能被当成普通 bash/submit 失败继续重跑。
        text = " ".join(
            str(value).lower()
            for value in (exc, getattr(exc, "message", ""), getattr(exc, "detail", ""))
        )
        hint_completed = action == "challenge_get_hint" and any(
            marker in text for marker in ("completed", "complete", "通关", "已完成")
        )
        capacity = (
            "max active" in text
            or ("active" in text and "limit" in text)
            or "上限" in text
            or "最大活跃" in text
        )
        if isinstance(exc, TaskNotFound) or (isinstance(exc, InvalidState) and not hint_completed and not capacity):
            _ctx.terminal_error = exc
        raise


def _challenge_dir() -> str:
    d = getattr(_ctx, "challenge_dir", "") or ""
    if not d or d == "/workspace":
        return ""
    return d


def submit_flag(args: dict) -> str:
    flag = args.get("flag", "").strip()
    writeup = args.get("writeup", "")

    def submit_once() -> dict:
        try:
            return _request_backend(
                "challenge_submit_flag", {"flag": flag, "writeup": writeup}
            )
        except DuplicateSubmit:
            # A duplicate means this flag index was previously accepted.  The
            # duplicate response has no score/progress metadata, so reconcile
            # current completion state before updating the local store.
            duplicate = {"correct": True, "duplicate": True}
            try:
                state = _request_backend(
                    "challenge_get_state", {"unique_code": _current_unique_code()}
                )
                duplicate.update({
                    "correct_flag_count": state.get("correct_flag_count", 0),
                    "total_flag_count": state.get("flag_count", 0),
                    "is_completed": state.get("is_completed", False),
                })
            except (TaskNotFound, InvalidState):
                raise
            except Exception:
                # The duplicate itself is still authoritative; a transient
                # snapshot failure must not turn it into a wrong submission.
                pass
            return duplicate

    challenge_dir = _challenge_dir()
    if challenge_dir:
        outcome = SubmissionStore(challenge_dir).submit(flag, submit_once)
    else:
        data = submit_once()
        outcome = SubmissionOutcome(
            status="correct" if data.get("correct") else "wrong",
            response=data,
            duplicate=False,
            wrong_count=0 if data.get("correct") else 1,
        )

    persistence_warning = (
        f"\n[警告] 平台响应已生效，但本地提交状态未完整持久化：{outcome.persistence_error}"
        if outcome.persistence_error else ""
    )

    if outcome.duplicate:
        if outcome.status == "correct":
            return f"[重复] Flag 已提交且正确：{flag}{persistence_warning}"
        return f"[重复] 该 flag 之前已提交且判定错误：{flag}。禁止重复提交同一 flag，请换方向重新分析。{persistence_warning}"

    if outcome.status == "limited":
        return (
            f"[拦截] 本题已累计提交 {outcome.wrong_count} 个错误 flag，"
            "禁止继续猜。请回到题目逻辑重新分析，找到确定证据后再提交。"
        )

    data = outcome.response or {}
    if data.get("duplicate"):
        correct = data.get("correct_flag_count", "?")
        total = data.get("total_flag_count", "?")
        progress = f"（进度 {correct}/{total}）"
        if data.get("is_completed"):
            return (
                f"[重复] Flag 已经正确提交并计分：{flag}{progress} "
                f"🎉 全部 Flag 已找到，题目完成！{persistence_warning}"
            )
        return f"[重复] Flag 已经正确提交并计分：{flag}{progress}{persistence_warning}"
    if data.get("correct"):
        score = data.get("awarded")
        correct = data.get("correct_flag_count", "?")
        total = data.get("total_flag_count", "?")
        completed = data.get("is_completed", False)
        suffix = f"，本次得分 {score}" if score is not None else ""
        progress = f"（进度 {correct}/{total}）"
        if completed:
            return f"[✓] Flag 提交正确：{flag}{suffix}{progress} 🎉 全部 Flag 已找到，题目完成！{persistence_warning}"
        else:
            return f"[✓] Flag 提交正确：{flag}{suffix}{progress} 还有剩余 Flag，请继续寻找！{persistence_warning}"
    else:
        wrong = outcome.wrong_count
        warn = ""
        if wrong >= 3:
            warn = (
                f"\n⚠️ 已累计提交 {wrong} 个错误 flag。"
                "立即停止猜 flag，回到题目逻辑重新分析，找到确定证据后再提交。"
            )
        return f"[✗] Flag 提交错误：{flag}，请继续寻找{warn}{persistence_warning}"


def get_state(args: dict) -> str:
    data = _request_backend("challenge_get_state", args)
    if data.get("challenges"):
        return "[题目列表]\n" + "\n".join(
            f"- {item.get('unique_code')}: {item.get('correct_flag_count', 0)}/{item.get('flag_count', 0)}，"
            f"状态={item.get('container_status')}，完成={item.get('is_completed')}"
            for item in data["challenges"]
        )
    lines = [
        f"题目：{data.get('name')} ({data.get('category')} / {data.get('difficulty')})",
        f"URL：{data.get('url')}",
        f"描述：{data.get('description')}",
        f"已完成：{'是' if data.get('is_completed') else '否'}",
    ]
    correct_flags = data.get("correct_flags", [])
    if correct_flags:
        lines.append(f"已找到的 Flag：{', '.join(correct_flags)}")
    return "\n".join(lines)


def get_hint(args: dict) -> str:
    # 提示扣分按题目一次性计算；跨 Agent/重跑时允许重看，但直接返回
    # 题目级缓存，避免 Multi-Solver 重复请求平台和重复消耗时间。
    challenge_dir = _challenge_dir()

    def fetch() -> list[str]:
        data = _request_backend("challenge_get_hint", args)
        return [str(value) for value in data.get("hints", []) if value]

    if challenge_dir:
        hints, cached = ChallengeLedger(challenge_dir).get_or_fetch_hints(fetch)
    else:
        hints, cached = fetch(), False
    if not hints:
        suffix = "（本地缓存）" if cached else ""
        return f"[提示]{suffix} 暂无提示"
    source = "本地缓存，未重复请求平台" if cached else "首次获取并已缓存"
    return (
        f"[提示]（{source}；本题提示扣分不重复叠加）\n"
        + "\n".join(f"- {hint}" for hint in hints)
    )


def start_challenge(args: dict) -> str:
    data = _request_backend("challenge_start", args)
    return f"[启动] {data.get('unique_code')}：{', '.join(data.get('container_addr', []))}"


def close_challenge(args: dict) -> str:
    data = _request_backend("challenge_close", args)
    return f"[关闭] {data.get('unique_code')}：{'成功' if data.get('closed') else '未关闭'}"
