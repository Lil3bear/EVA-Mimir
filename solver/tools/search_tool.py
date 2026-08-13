"""
安全知识搜索工具。

使用独立的 LLM 接口做安全知识搜索，与 Solver 主模型分开配置。
支持三种搜索后端（按优先级）：

1. Kimi（moonshot-v1-auto）— 原生联网搜索，能获取真实 writeup
2. DeepSeek（deepseek-chat）— 用模型训练知识回答，无联网
3. 任意 OpenAI 兼容 API — 通过 settings.search_llm 配置

配置方式：
  settings.json 中添加 search_llm 节（可选，不配则复用 llm 节）：
  {
    "search_llm": {
      "base_url": "https://api.moonshot.cn/v1",
      "api_key": "sk-xxx",
      "model": "moonshot-v1-auto"
    }
  }

  或环境变量：
    SEARCH_LLM_BASE_URL, SEARCH_LLM_API_KEY, SEARCH_LLM_MODEL
"""

import os
from typing import Optional

from openai import OpenAI

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

# 搜索专用 LLM 客户端（与 Solver 主模型独立）
_search_client: Optional[OpenAI] = None
_search_model: str = ""
_search_source: str = ""  # 标记搜索来源（kimi/deepseek/custom）


def init(settings: dict) -> None:
    global _search_client, _search_model, _search_source

    # 优先使用独立的 search_llm 配置
    search_cfg = settings.get("search_llm", {})

    if search_cfg.get("base_url") or os.environ.get("SEARCH_LLM_BASE_URL"):
        # 有独立搜索 LLM 配置
        base_url = search_cfg.get("base_url") or os.environ.get("SEARCH_LLM_BASE_URL", "")
        api_key = search_cfg.get("api_key") or os.environ.get("SEARCH_LLM_API_KEY", "")
        _search_model = search_cfg.get("model") or os.environ.get("SEARCH_LLM_MODEL", "moonshot-v1-auto")
        _search_client = OpenAI(base_url=base_url, api_key=api_key)

        # 判断来源
        if "moonshot" in base_url or "kimi" in base_url:
            _search_source = "kimi"
        elif "deepseek" in base_url:
            _search_source = "deepseek"
        else:
            _search_source = "custom"
    else:
        # fallback：复用 Solver 主 LLM 配置
        llm_cfg = settings.get("llm", {})
        base_url = llm_cfg.get("base_url") or os.environ.get("LLM_BASE_URL", "")
        api_key = llm_cfg.get("api_key") or os.environ.get("LLM_API_KEY", "")
        _search_model = (
            llm_cfg.get("search_model")
            or llm_cfg.get("default_model")
            or os.environ.get("LLM_MODEL", "deepseek-chat")
        )
        _search_client = OpenAI(base_url=base_url, api_key=api_key)
        _search_source = "deepseek" if "deepseek" in base_url else "fallback"


def search(args: dict) -> str:
    query = args.get("query", "").strip()
    if not query:
        return "[错误] query 不能为空"
    if _search_client is None:
        return "[错误] search_tool 未初始化，请先调用 init(settings)"

    # Kimi 支持联网搜索（通过 tool_choice 触发内置 web_search）
    # DeepSeek/其他模型走纯知识查询
    try:
        messages = [
            {"role": "system", "content": _SEARCH_SYSTEM},
            {"role": "user", "content": query},
        ]

        extra_kwargs = {}
        if _search_source == "kimi":
            extra_kwargs["tools"] = [{
                "type": "builtin_function",
                "function": {"name": "$web_search"},
            }]

        resp = _search_client.chat.completions.create(
            model=_search_model,
            messages=messages,
            max_tokens=800,
            **extra_kwargs,
        )

        msg = resp.choices[0].message

        # Kimi 联网搜索是两步：
        # 第一轮返回 tool_calls（搜索结果），需要塞回去让 Kimi 生成最终回答
        if msg.tool_calls and _search_source == "kimi":
            messages.append(msg.model_dump(exclude_none=True))
            for tc in msg.tool_calls:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.function.name,
                    "content": tc.function.arguments,
                })
            resp2 = _search_client.chat.completions.create(
                model=_search_model,
                messages=messages,
                max_tokens=800,
                **extra_kwargs,
            )
            content = resp2.choices[0].message.content or "（无结果）"
        else:
            content = msg.content or "（无结果）"

        # 标记搜索来源，让 Solver 知道数据可信度
        if _search_source == "kimi":
            prefix = "[Kimi 联网搜索结果]"
        elif _search_source == "deepseek":
            prefix = "[DeepSeek 知识查询结果（非实时搜索）]"
        else:
            prefix = f"[{_search_source} 搜索结果]"

        return f"{prefix}\n{content}"

    except Exception as e:
        return f"[错误] 搜索失败：{e}"
