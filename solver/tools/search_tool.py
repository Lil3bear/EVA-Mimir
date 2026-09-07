"""安全知识查询工具（纯模型知识，不联网）。

使用 LLM 的内置训练知识回答安全技术问题，与 Solver 主模型分开配置。
不联网：无法查询最新 CVE / writeup，结果可能过时，payload 必须用 bash 验证。

配置方式：
  settings.json 可选 search_llm 独立配置（未配置时回退到主 llm 配置）：
  {
    "search_llm": {
      "base_url": "https://tokenhub.tencentmaas.com/v1",
      "api_key": "sk-xxx",
      "model": "deepseek-v4-flash-202605"
    }
  }
"""

import os
from typing import Optional

from openai import OpenAI

from solver.runtime.llm import create_with_retry, is_deepseek_v4
from solver.worker_context import ctx as _ctx


def _search_completion(**request_kwargs):
    """Create one search completion using the current remaining deadline."""
    if _search_client is None:
        raise RuntimeError("search_tool 未初始化")
    client = _search_client
    deadline = float(getattr(_ctx, "deadline", 0.0) or 0.0)
    if deadline:
        remaining = deadline - __import__("time").time()
        if remaining <= 0:
            raise TimeoutError("search deadline exceeded")
        with_options = getattr(client, "with_options", None)
        if callable(with_options):
            client = with_options(timeout=max(0.1, min(60.0, remaining)))
    return client.chat.completions.create(**request_kwargs)


def _msg_content(msg) -> str:
    """只返回最终答案；reasoning_content 不能冒充搜索结果。"""
    c = getattr(msg, "content", None)
    return c or ""


TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "security_search",
        "description": (
            "查询安全知识（模型内置知识，不联网）。适用于需要了解特定 CVE、框架漏洞、绕过技术时，"
            "例如 'PHP md5 array bypass'、'JWT none algorithm attack'。"
            "⚠️ 结果是模型训练知识，可能过时或不完整，具体 payload 使用前必须用 bash 工具验证。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，支持中英文，尽量具体",
                }
            },
            "required": ["query"],
        },
    },
}

_MODEL_KNOWLEDGE_SYSTEM = (
    "你是一名顶尖 CTF 安全专家。用户会给你一个安全技术关键词或漏洞名称，"
    "请用简洁的中文回答：\n"
    "1. 该技术/漏洞的原理（1-2 句）\n"
    "2. 利用条件和前提\n"
    "3. 具体可用的 payload 或命令（直接给出可复制执行的）\n"
    "4. 常见绕过姿势或变体\n"
    "回答控制在 500 字以内，优先给出可操作的信息。"
    "你当前没有联网或检索能力，只能提供模型已有知识。"
    "不得声称已经搜索互联网，不得根据题号、标题或零散词语猜测特定题目的解法。"
    "如果没有高置信度的直接知识，只回答“无可靠本地知识”，不要给通用漏洞清单。"
)

# 搜索专用 LLM 客户端（与 Solver 主模型独立，纯知识查询）
_search_client: Optional[OpenAI] = None
_search_model: str = ""


def init(settings: dict) -> None:
    """从 settings 初始化纯知识查询客户端（不联网）。"""
    global _search_client, _search_model

    search_cfg = settings.get("search_llm", {}) or {}
    llm_cfg = settings.get("llm", {}) or {}

    base_url = (
        search_cfg.get("base_url")
        or os.environ.get("SEARCH_LLM_BASE_URL", "")
        or llm_cfg.get("base_url")
        or os.environ.get("LLM_BASE_URL", "")
    )
    api_key = (
        search_cfg.get("api_key")
        or os.environ.get("SEARCH_LLM_API_KEY", "")
        or llm_cfg.get("api_key")
        or os.environ.get("LLM_API_KEY", "")
    )
    _search_model = (
        search_cfg.get("model")
        or os.environ.get("SEARCH_LLM_MODEL", "")
        or llm_cfg.get("search_model")
        or llm_cfg.get("default_model")
        or os.environ.get("LLM_MODEL", "deepseek-v4-flash")
    )
    _search_client = OpenAI(base_url=base_url, api_key=api_key)


def _search_llm(query: str) -> str:
    """纯模型知识查询（不联网）。"""
    if _search_client is None:
        return "[错误] search_tool 未初始化"

    messages = [
        {"role": "system", "content": _MODEL_KNOWLEDGE_SYSTEM},
        {"role": "user", "content": query},
    ]

    request = {
        "model": _search_model,
        "messages": messages,
        "max_tokens": 1200,
    }
    if is_deepseek_v4(_search_model):
        # 短知识查询不需要思考模式；避免预算全部消耗在 reasoning_content。
        request["extra_body"] = {"thinking": {"type": "disabled"}}

    resp = create_with_retry(
        _search_completion,
        **request,
        deadline=float(getattr(_ctx, "deadline", 0.0) or 0.0),
    )

    choice = resp.choices[0]
    content = _msg_content(choice.message).strip()
    if not content:
        reason = getattr(choice, "finish_reason", "") or "unknown"
        return (
            f"[错误] 模型知识查询未生成最终答案（finish_reason={reason}）。"
            "已丢弃 reasoning_content，禁止把模型推理草稿当作搜索结果。"
        )

    return f"[模型知识（未联网、未验证，使用前必须用 bash 验证）]\n{content}"


def search(args: dict) -> str:
    query = args.get("query", "").strip()
    if not query:
        return "[错误] query 不能为空"

    if _search_client is not None:
        try:
            return _search_llm(query)
        except Exception as e:
            return f"[错误] 搜索失败：{e}"

    return "[错误] search_tool 未初始化，请先调用 init(settings)"
