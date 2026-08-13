import os
import subprocess


MAX_OUTPUT = 8000

READ_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "读取文件内容。适用于查看源码、配置文件、附件等。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "offset": {"type": "integer", "description": "从第几行开始读（可选）"},
                "limit": {"type": "integer", "description": "最多读多少行（可选）"},
            },
            "required": ["path"],
        },
    },
}

WRITE_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "写入文件内容。适用于创建 exploit 脚本、保存中间结果等。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "写入的内容"},
            },
            "required": ["path", "content"],
        },
    },
}

GREP_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "grep",
        "description": "在文件或目录中搜索内容，支持正则表达式。",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "搜索的正则表达式"},
                "path": {"type": "string", "description": "搜索的文件或目录"},
                "recursive": {"type": "boolean", "description": "是否递归搜索目录"},
            },
            "required": ["pattern", "path"],
        },
    },
}


def read_file(args: dict) -> str:
    path = args.get("path", "")
    offset = args.get("offset", 0)
    limit = args.get("limit", None)

    if not os.path.exists(path):
        return f"[错误] 文件不存在：{path}"

    try:
        with open(path, "r", errors="replace") as f:
            lines = f.readlines()

        if offset:
            lines = lines[offset:]
        if limit:
            lines = lines[:limit]

        content = "".join(lines)
        if len(content) > MAX_OUTPUT:
            content = content[:MAX_OUTPUT] + f"\n...[已截断，共 {len(lines)} 行]"
        return content
    except Exception as e:
        return f"[错误] 读取失败：{e}"


def write_file(args: dict) -> str:
    path = args.get("path", "")
    content = args.get("content", "")

    if not path:
        return "[错误] 路径不能为空"

    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return f"[成功] 已写入 {path}（{len(content)} 字节）"
    except Exception as e:
        return f"[错误] 写入失败：{e}"


def grep(args: dict) -> str:
    pattern = args.get("pattern", "")
    path = args.get("path", "")
    recursive = args.get("recursive", False)

    cmd = ["grep", "-n", "--color=never"]
    if recursive:
        cmd.append("-r")
    cmd += [pattern, path]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = result.stdout or result.stderr or "[无匹配结果]"
        if len(output) > MAX_OUTPUT:
            output = output[:MAX_OUTPUT] + "\n...[已截断]"
        return output
    except subprocess.TimeoutExpired:
        return "[错误] 搜索超时"
    except Exception as e:
        return f"[错误] 搜索失败：{e}"
