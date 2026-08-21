"""
安全知识搜索工具。

使用独立的 LLM 接口做安全知识搜索，与 Solver 主模型分开配置。
支持三种搜索后端（按优先级）：

1. Tavily — 真实搜索 API，CTF 友好，能提取代码块和 writeup
2. Kimi（moonshot-v1-auto）— 原生联网搜索，能获取真实 writeup
3. DeepSeek（deepseek-v4-flash）— 用模型训练知识回答，无联网

配置方式：
  settings.json 中添加：
  {
    "tavily_api_key": "tvly-xxx",                    // Tavily API key（优先）
    "search_llm": {                                   // Kimi/DeepSeek fallback
      "base_url": "https://api.moonshot.cn/v1",
      "api_key": "sk-xxx",
      "model": "moonshot-v1-auto"
    }
  }

  或环境变量：
    TAVILY_API_KEY, SEARCH_LLM_BASE_URL, SEARCH_LLM_API_KEY, SEARCH_LLM_MODEL
"""

import os
from typing import Optional

from openai import OpenAI

from solver.runtime.llm import create_with_retry, is_deepseek_v4

def _msg_content(msg) -> str:
    """只返回最终答案；reasoning_content 不能冒充搜索结果。"""
    c = getattr(msg, "content", None)
    return c or ""


TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "security_search",
        "description": (
            "搜索安全知识库和互联网。适用于需要了解特定 CVE、框架漏洞、绕过技术、CTF writeup 时，"
            "例如 'PHP 7.3 md5 array bypass'、'JWT none algorithm attack'、'pydash prototype pollution CTF'。"
            "返回相关的技术要点和利用方法。"
            "⚠️ 搜索结果可能来自 AI 知识或互联网搜索，具体 payload 使用前必须用 bash 工具验证。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，支持中英文，尽量具体（如加 'CTF writeup' 或 'exploit payload'）",
                }
            },
            "required": ["query"],
        },
    },
}

_SEARCH_SYSTEM = (
    "你是一名顶尖 CTF 安全专家。用户会给你一个安全技术关键词或漏洞名称，"
    "请搜索互联网并用简洁的中文回答：\n"
    "1. 该技术/漏洞的原理（1-2 句）\n"
    "2. 利用条件和前提\n"
    "3. 具体可用的 payload 或命令（直接给出可复制执行的）\n"
    "4. 常见绕过姿势或变体\n"
    "回答控制在 500 字以内，优先给出可操作的信息。"
    "如果能找到 CTF writeup，优先参考 writeup 中的解法。"
)

_MODEL_KNOWLEDGE_SYSTEM = (
    _SEARCH_SYSTEM
    + "\n你当前没有联网或检索能力，只能提供模型已有知识。"
    "不得声称已经搜索互联网，不得根据题号、标题或零散词语猜测特定题目的解法。"
    "如果没有高置信度的直接知识，只回答“无可靠本地知识”，不要给通用漏洞清单。"
)

# 搜索专用 LLM 客户端（与 Solver 主模型独立）
_search_client: Optional[OpenAI] = None
_search_model: str = ""
_search_source: str = ""  # 标记搜索来源

# Tavily 客户端
_tavily_api_key: str = ""
_tavily_client = None


def init(settings: dict) -> None:
    global _search_client, _search_model, _search_source, _tavily_api_key, _tavily_client

    # --- Tavily 配置 ---
    _tavily_api_key = (
        settings.get("tavily_api_key", "")
        or os.environ.get("TAVILY_API_KEY", "")
    )
    if _tavily_api_key:
        try:
            from tavily import TavilyClient
            _tavily_client = TavilyClient(api_key=_tavily_api_key)
        except Exception:
            _tavily_client = None

    # --- Fallback: Kimi / DeepSeek ---
    search_cfg = settings.get("search_llm", {})

    if search_cfg.get("base_url") or os.environ.get("SEARCH_LLM_BASE_URL"):
        base_url = search_cfg.get("base_url") or os.environ.get("SEARCH_LLM_BASE_URL", "")
        api_key = search_cfg.get("api_key") or os.environ.get("SEARCH_LLM_API_KEY", "")
        _search_model = search_cfg.get("model") or os.environ.get("SEARCH_LLM_MODEL", "moonshot-v1-auto")
        _search_client = OpenAI(base_url=base_url, api_key=api_key)

        if "moonshot" in base_url or "kimi" in base_url:
            _search_source = "kimi"
        elif "deepseek" in base_url:
            _search_source = "deepseek"
        else:
            _search_source = "custom"
    else:
        llm_cfg = settings.get("llm", {})
        base_url = llm_cfg.get("base_url") or os.environ.get("LLM_BASE_URL", "")
        api_key = llm_cfg.get("api_key") or os.environ.get("LLM_API_KEY", "")
        _search_model = (
            llm_cfg.get("search_model")
            or llm_cfg.get("default_model")
            or os.environ.get("LLM_MODEL", "deepseek-v4-flash")
        )
        _search_client = OpenAI(base_url=base_url, api_key=api_key)
        _search_source = "deepseek" if "deepseek" in base_url else "fallback"


def _search_tavily(query: str) -> Optional[str]:
    """使用 Tavily 真实搜索，返回格式化结果。失败返回 None。"""
    if _tavily_client is None:
        return None
    try:
        result = _tavily_client.search(
            query,
            search_depth="advanced",
            include_raw_content=True,
            max_results=5,
        )
        return _format_tavily_results(result)
    except Exception:
        return None


def _format_tavily_results(result: dict) -> str:
    """把 Tavily 搜索结果格式化为 Solver 可用的文本。"""
    parts = ["[Tavily 真实搜索]"]

    answer = result.get("answer")
    if answer:
        parts.append(f"AI 摘要：{answer}")

    results = result.get("results", [])
    if results:
        parts.append(f"\n搜索到 {len(results)} 个相关结果：")
        for i, r in enumerate(results[:5], 1):
            title = r.get("title", "无标题")
            url = r.get("url", "")
            content = r.get("content", "")
            # 截断过长内容
            if len(content) > 400:
                content = content[:400] + "..."
            parts.append(f"\n[{i}] {title}")
            if url:
                parts.append(f"    URL: {url}")
            parts.append(f"    {content}")

    return "\n".join(parts)


def _search_kimi(query: str) -> str:
    """使用 Kimi 联网搜索（两步：tool_calls → 最终回答）。"""
    if _search_client is None:
        return "[错误] search_tool 未初始化"

    messages = [
        {"role": "system", "content": _SEARCH_SYSTEM},
        {"role": "user", "content": query},
    ]
    extra_kwargs = {
        "tools": [{
            "type": "builtin_function",
            "function": {"name": "$web_search"},
        }]
    }

    resp = create_with_retry(
        _search_client.chat.completions.create,
        model=_search_model,
        messages=messages,
        max_tokens=800,
        **extra_kwargs,
    )

    msg = resp.choices[0].message

    if msg.tool_calls:
        messages.append(msg.model_dump(exclude_none=True))
        for tc in msg.tool_calls:
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tc.function.name,
                "content": tc.function.arguments,
            })
        resp2 = create_with_retry(
            _search_client.chat.completions.create,
            model=_search_model,
            messages=messages,
            max_tokens=800,
            **extra_kwargs,
        )
        content = _msg_content(resp2.choices[0].message) or "（无结果）"
    else:
        content = _msg_content(msg) or "（无结果）"

    return f"[Kimi 联网搜索结果]\n{content}"


def _search_llm(query: str) -> str:
    """使用 DeepSeek / 其他 LLM 纯知识查询。"""
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
        _search_client.chat.completions.create,
        **request,
    )

    choice = resp.choices[0]
    content = _msg_content(choice.message).strip()
    if not content:
        reason = getattr(choice, "finish_reason", "") or "unknown"
        return (
            f"[错误] 模型知识查询未生成最终答案（finish_reason={reason}）。"
            "已丢弃 reasoning_content，禁止把模型推理草稿当作搜索结果。"
        )

    if _search_source == "deepseek":
        prefix = "[DeepSeek 模型知识（非联网、未验证，使用前必须用 bash 验证）]"
    else:
        prefix = f"[{_search_source} 搜索结果]"

    return f"{prefix}\n{content}"


def search(args: dict) -> str:
    query = args.get("query", "").strip()
    if not query:
        return "[错误] query 不能为空"

    # 优先级 1: Tavily 真实搜索
    if _tavily_client is not None:
        tavily_result = _search_tavily(query)
        if tavily_result is not None:
            return tavily_result

    # 优先级 2: Kimi 联网搜索
    if _search_client is not None and _search_source == "kimi":
        try:
            return _search_kimi(query)
        except Exception as e:
            pass  # fall through to next

    # 优先级 3: DeepSeek / 其他 LLM 知识查询
    if _search_client is not None:
        try:
            return _search_llm(query)
        except Exception as e:
            return f"[错误] 搜索失败：{e}"

    return "[错误] search_tool 未初始化，请先调用 init(settings)"
