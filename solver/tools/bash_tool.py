import subprocess
import os
import re
import hashlib
import shlex
from collections import Counter
from urllib.parse import urlsplit

from solver.worker_context import ctx as _ctx
from solver.tools import knowledge_router

# 常量
_DEDUP_WINDOW = 10
_DEDUP_WARN_THRESHOLD = 3
_APPROACH_WARN_THRESHOLD = 3
_APPROACH_BLOCK_THRESHOLD = 3
_HOST_FAIL_WARN_THRESHOLD = 3


def register_observer_trigger(callback) -> None:
    """agent.py 启动时注册，approach 循环首次触发时调用（thread-local）。"""
    _ctx.observer_trigger_callback = callback


def _cmd_fingerprint(cmd: str) -> str:
    """取命令前 80 字符的 md5，忽略细节差异只关注大致意图。"""
    return hashlib.md5(cmd[:80].encode()).hexdigest()[:8]


def _extract_url_pattern(cmd: str) -> str | None:
    """
    从命令里提取 URL + 参数名结构（忽略具体值），作为 approach 指纹。
    支持两类命令：
    1. curl 命令：直接从 URL 提取
    2. Python inline 脚本（python3 -c '...'）：从代码字符串内提取 URL

    例：curl ... 'http://host/leve2.php?a=QNKCDZO&b=240610708' -d 'c=...'
    → 'http://host/leve2.php?a=&b= POST:c='
    """
    search_target = cmd

    # 对 Python inline 脚本，从代码字符串内提取
    py_inline = re.search(r'python3?\s+-c\s+[\'"](.+?)[\'"](?:\s|$)', cmd, re.DOTALL)
    if py_inline:
        search_target = py_inline.group(1)

    m = re.search(r'https?://[^\s\'"]+', search_target)
    if not m:
        # Python 脚本里也可能用变量拼 URL，尝试提取 host:port 结构
        host_m = re.search(r'[\'"]https?://([^\s\'"/?]+)', search_target)
        if not host_m:
            return None
        # 只有 host，不含路径/参数，作为粗粒度 approach 指纹
        return f"python:{host_m.group(1)}"

    raw_url = m.group()
    # SQL/命令执行端点白名单：同一 endpoint 执行不同 SQL/命令是正常操作，
    # 需要将 POST body 中的关键内容也纳入指纹（而非只看 URL path）
    _SQL_EXEC_ENDPOINTS = (
        'EntitySQLProcessor', 'ProgramExport', 'phpmyadmin',
        'sql.php', 'query', 'sqlconsole', 'script', 'scriptText',
        'groovy', '/eval', '/exec',
    )
    if any(ep.lower() in raw_url.lower() for ep in _SQL_EXEC_ENDPOINTS):
        # 对 SQL/脚本执行端点，将 POST body 的具体内容（如 sqlCommand/groovyProgram 的值）
        # 也作为指纹的一部分。--data-urlencode 的值不同 = 不同 approach
        # 匹配带引号和不带引号两种格式
        data_values = re.findall(r'(?:-d|--data|--data-urlencode)[=\s]+[\'"]([^\'"]+)[\'"]', cmd)
        if not data_values:
            data_values = re.findall(r'(?:-d|--data|--data-urlencode)[=\s]+([^\s\'"]+)', cmd)
        data_hash = hashlib.md5('|'.join(data_values).encode()).hexdigest()[:6] if data_values else 'nodata'
        return f"{raw_url} DATA:{data_hash}"
    # Path traversal 检测：如果 URL 参数值包含 ../ 或绝对路径，保留目标文件名作为指纹的一部分
    # 这样 download.php?id=../config.php 和 download.php?id=../../../etc/passwd 是不同 approach
    path_part = raw_url
    if re.search(r'=\.\.[\\/]|=/etc/|=/proc/', raw_url):
        # 保留参数名和目标文件名（去掉中间的 ../ 层数差异）
        # download.php?id=../config.php → download.php?id=TRAVERSAL:config.php
        # download.php?id=../../../etc/passwd → download.php?id=TRAVERSAL:/etc/passwd
        def _normalize_traversal(match):
            val = match.group()
            # val 形如 '=../config.php' 或 '=../../../etc/passwd'
            # 去掉开头的 '=' 和所有 '../' 序列，保留目标路径
            target = re.sub(r'^=(\.\./)*', '', val)
            if not target:
                target = 'unknown'
            return f'=TRAVERSAL:{target}'
        path_part = re.sub(r'=[^&\s\'"]*\.\.[\\/][^&\s\'"]*', _normalize_traversal, raw_url)
    else:
        # 非路径穿越的普通参数：只保留参数名，去掉参数值
        path_part = re.sub(r'=[^&\s\'"]*', '=', raw_url)
    # 提取 -d / --data 的参数名（去掉值）
    post_params = re.findall(r'(?:-d|--data)[=\s]+[\'"]?([^\'"\s]+)', cmd)
    post_keys = ""
    if post_params:
        keys = "&".join(re.sub(r'=[^&]*', '=', p) for p in post_params)
        post_keys = f" POST:{keys}"
    return path_part + post_keys


def _extract_host(cmd: str) -> str | None:
    """从命令中提取 host:port，用于连接失败计数。"""
    m = re.search(r'https?://([^\s\'"/?]+)', cmd)
    return m.group(1) if m else None


def _target_hostname(target_url: str | None = None) -> str:
    """Return the configured target host without doing DNS resolution."""
    value = (target_url if target_url is not None else _ctx.target_url).strip()
    if not value:
        return ""
    try:
        return urlsplit(value if "://" in value else f"//{value}").hostname or ""
    except ValueError:
        return ""


def _inline_http_variant_count(cmd: str) -> int:
    """Count values in a shell ``for ... in ...`` loop that drives HTTP calls."""
    if "curl" not in cmd.lower() or not re.search(r'https?://', cmd, re.IGNORECASE):
        return 1
    match = re.search(
        r'\bfor\s+[A-Za-z_]\w*\s+in\s+(.+?);\s*do\b', cmd, re.DOTALL
    )
    if not match:
        return 1
    try:
        return max(1, len(shlex.split(match.group(1))))
    except ValueError:
        return 1


def _is_connection_refused(output: str) -> bool:
    """判断 bash 输出是否表明目标不可达（Connection Refused / timeout）。"""
    patterns = [
        'Connection refused',
        'connect: Connection refused',
        'Failed to connect',
        'curl: (7)',   # curl 连接失败
        'curl: (28)',  # curl 超时
        'Network unreachable',
        'No route to host',
    ]
    return any(p.lower() in output.lower() for p in patterns)


TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": (
            "在容器内执行 shell 命令。适用于网络探测、漏洞利用、文件操作等一切需要"
            "在系统层面执行的操作。命令在当前题目的专属目录下执行（/workspace/<题目ID>/），"
            "禁止 cd /root/workspace，所有文件操作都在当前目录进行。"
            "输出超长时会截断，截断提示里会给出完整结果的绝对路径，可用 grep/cat 查询。"
            "对于耗时较长的求解脚本（python3/sage），可设置 timeout 参数（最大 600 秒）。"
            "同一 HTTP 请求结构最多执行 3 个变体；批量 shell 循环按循环值逐个计数，超限会被阻止。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cmd": {
                    "type": "string",
                    "description": "要执行的 shell 命令",
                },
                "timeout": {
                    "type": "integer",
                    "description": "命令超时时间（秒），默认 120，求解脚本可设置为 300-600",
                },
            },
            "required": ["cmd"],
        },
    },
}

MAX_OUTPUT = 8000
_DEFAULT_TIMEOUT = 120
_MAX_TIMEOUT = 600


def _get_timeout(cmd: str, requested: int | None = None) -> int:
    """根据命令类型和用户请求确定超时时间。"""
    if requested is not None:
        return max(10, min(requested, _MAX_TIMEOUT))
    # 求解类脚本需要更长超时
    if cmd.lstrip().startswith(("python", "sage", "z3")):
        return 300
    # 编译也可能慢
    if any(kw in cmd for kw in ("gcc", "g++", "make", "cargo")):
        return 180
    return _DEFAULT_TIMEOUT


def execute(args: dict) -> str:
    cmd = args.get("cmd", "").strip()
    if not cmd:
        return "[错误] 命令不能为空"

    requested_timeout = args.get("timeout")
    timeout = _get_timeout(cmd, requested_timeout)

    # 重复操作检测（命令级）
    fp = _cmd_fingerprint(cmd)
    _ctx.recent_fingerprints.append(fp)
    if len(_ctx.recent_fingerprints) > _DEDUP_WINDOW:
        _ctx.recent_fingerprints = _ctx.recent_fingerprints[-_DEDUP_WINDOW:]
    repeat_count = Counter(_ctx.recent_fingerprints)[fp]
    repeat_warn = ""
    if repeat_count >= _DEDUP_WARN_THRESHOLD:
        repeat_warn = (
            f"\n⚠️ [重复操作警告] 近似命令已执行 {repeat_count} 次，"
            f"当前方向可能陷入死路，建议换方向或查看 idea_list 寻找新思路。\n"
        )

    # approach-level 计数（URL 模式级）
    approach_warn = ""
    url_pattern = _extract_url_pattern(cmd)
    if url_pattern:
        variant_count = _inline_http_variant_count(cmd)
        previous_count = _ctx.approach_counter[url_pattern]
        approach_count = previous_count + variant_count
        if approach_count > _APPROACH_BLOCK_THRESHOLD:
            _ctx.approach_counter[url_pattern] = _APPROACH_BLOCK_THRESHOLD + 1
            if previous_count <= _APPROACH_BLOCK_THRESHOLD and _ctx.observer_trigger_callback:
                _ctx.observer_trigger_callback(reason=f"approach_blocked:{url_pattern[:60]}")
            return (
                f"[阻止] 同一 HTTP 请求结构本次包含 {variant_count} 个变体，"
                f"累计将达到 {approach_count} 个，超过 {_APPROACH_BLOCK_THRESHOLD} 个的验证预算。"
                "请记录失败边界并切换方向；不要把更多猜测藏进 shell 循环。"
            )
        _ctx.approach_counter[url_pattern] = approach_count
        if approach_count >= _APPROACH_WARN_THRESHOLD:
            approach_warn = (
                f"\n⚠️ [方向循环警告] 同一请求结构已尝试 {approach_count} 次（{url_pattern[:80]}），"
                f"换传参方式或换攻击方向，不要再用相同结构重试。\n"
            )
            # 首次达到阈值时立即触发 Observer 强制审查
            if approach_count == _APPROACH_WARN_THRESHOLD and _ctx.observer_trigger_callback:
                _ctx.observer_trigger_callback(reason=f"approach_loop:{url_pattern[:60]}")

    # 每题独立的工作目录（并行安全）
    cwd = _ctx.attempt_dir if (_ctx.attempt_dir and _ctx.attempt_dir != "/workspace") else "/root/workspace"
    os.makedirs(cwd, exist_ok=True)

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env={**os.environ, "TERM": "dumb"},
        )
        output = result.stdout + result.stderr
        if not output:
            output = f"[命令执行完毕，退出码 {result.returncode}，无输出]"
    except subprocess.TimeoutExpired:
        output = f"[错误] 命令执行超时（{timeout}秒）。如果是求解脚本，可用 timeout 参数增加超时（最大 600秒）"
    except Exception as e:
        output = f"[错误] 执行失败：{e}"

    if len(output) > MAX_OUTPUT:
        saved_path = _save_full_output(cmd, output)
        tail = output[-3000:]
        head = output[:500]
        output = (
            f"[输出过长（{len(output)} 字节），已截断]\n"
            f"[完整结果已保存至：{saved_path}，可用 bash 工具执行 grep/cat 查询]\n"
            f"[开头 500 字节]\n{head}\n"
            f"... (省略中间部分) ...\n"
            f"[末尾 3000 字节]\n{tail}"
        )

    # 连接失败检测：同一 host 连续失败 >= 阈值时警告
    conn_warn = ""
    host = _extract_host(cmd)
    if host and _is_connection_refused(output):
        _ctx.host_fail_counter[host] += 1
        fail_count = _ctx.host_fail_counter[host]
        if fail_count >= _HOST_FAIL_WARN_THRESHOLD:
            conn_warn = (
                f"\n⚠️ [目标不可达] {host} 已连续 {fail_count} 次 Connection Refused。"
                f"目标实例可能已下线。请调用 challenge_get_state 确认题目 URL 是否变化，"
                f"不要继续猜端口或换节点重试。\n"
            )
    elif host and not _is_connection_refused(output):
        # 连接成功，重置该 host 的失败计数
        _ctx.host_fail_counter[host] = 0

    return repeat_warn + approach_warn + conn_warn + _auto_extract(output, cmd) + output


def _save_full_output(cmd: str, output: str) -> str:
    import time, hashlib
    # 每题独立的 tool-results 目录（并行安全）
    base_dir = _ctx.attempt_dir if (_ctx.attempt_dir and _ctx.attempt_dir != "/workspace") else "/root/workspace"
    results_dir = os.path.join(base_dir, ".tool-results")
    os.makedirs(results_dir, exist_ok=True)
    ts = int(time.time() * 1000)
    slug = hashlib.md5(cmd.encode()).hexdigest()[:8]
    path = f"{results_dir}/{ts}-bash-{slug}.txt"
    with open(path, "w") as f:
        f.write(f"# CMD: {cmd}\n\n{output}")
    return path


# 已知中间件关键词（用于自动提示 Solver 搜索 CVE）
_MIDDLEWARE_KEYWORDS = [
    "geoserver", "gradio", "spring", "struts", "log4j", "tomcat",
    "jenkins", "confluence", "gitlab", "nacos", "fastjson",
    "thinkphp", "laravel", "next.js", "nextjs", "flask", "django",
    "wordpress", "phpmyadmin", "redis", "elasticsearch", "minio",
    "weblogic", "jboss", "wildfly", "drupal", "shiro",
    "1panel", "comfyui", "comfyui-manager", "ofbiz",
]


def _auto_extract(output: str, command: str = "") -> str:
    """
    对 bash 输出做确定性后处理：用正则提取 flag、凭据、内网 IP、中间件名。
    结果作为醒目前缀追加到输出开头，确保模型不会遗漏关键信息。
    纯正则，不用 LLM。
    """
    if output.startswith("[错误]") or output.startswith("[命令执行完毕"):
        return ""

    findings: list[str] = []

    # 1. flag 格式字符串
    flags = re.findall(r'[A-Za-z0-9_]+\{[^}]{4,80}\}', output)
    if flags:
        # 去重
        unique_flags = list(dict.fromkeys(flags))
        findings.append(f"⚡ 发现疑似 flag：{unique_flags[:3]}，立即用 challenge_submit_flag 提交！")

    # 2. 凭据（password/token/secret/key = xxx）
    cred_patterns = re.findall(
        r'(?:password|passwd|pwd|token|secret|api_key|apikey|db_pass|mysql_pwd)'
        r'\s*[=:]\s*[\'"]?([^\s\'"<>]{3,60})',
        output, re.IGNORECASE
    )
    if cred_patterns:
        unique_creds = list(dict.fromkeys(cred_patterns))[:5]
        findings.append(f"🔑 发现疑似凭据：{unique_creds}，立即尝试用这些凭据登录/连接！")

    # 3. 内网 IP
    internal_ips = re.findall(
        r'(?:(?:172\.(?:1[6-9]|2\d|3[01]))|(?:10\.\d{1,3})|(?:192\.168))\.\d{1,3}\.\d{1,3}',
        output
    )
    if internal_ips:
        # 去重 + 排除常见无关 IP
        target_host = _target_hostname()
        unique_ips = [ip for ip in dict.fromkeys(internal_ips)
                      if not ip.startswith('10.0.100.')  # VPN 网关
                      and ip != '172.17.0.1'  # Docker 网关
                      and ip != target_host]
        if unique_ips:
            findings.append(f"🌐 发现内网 IP：{unique_ips[:5]}，可能需要横向移动！")

    # 4. 中间件/框架识别 → 确定性 CVE 路由（本地表命中直接注入，不靠模型回忆）
    cve_hint = knowledge_router.lookup(output, context=command)
    if cve_hint:
        findings.append(cve_hint)
    else:
        output_lower = output.lower()
        detected_mw = [mw for mw in _MIDDLEWARE_KEYWORDS if mw in output_lower]
        if detected_mw:
            findings.append(
                f"🔍 识别到中间件：{detected_mw[:3]}"
                f"（本地 CVE 表未命中，可用 security_search 补充，结果必须 bash 验证）"
            )

    if not findings:
        return ""

    return "\n" + "\n".join(findings) + "\n\n"
