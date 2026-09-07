"""Deterministic skill routing from bash output (non-CVE fingerprints).

Knowledge injection layers (keep them distinct):
  * knowledge_router — product/CVE cheatsheet injection
  * skill_chain — fingerprint → mandatory playbook + hard tool gate (source of truth)
  * skill_router — advisory banners + IP-drift / URL-bug notes (delegates chain
    banners to skill_chain so playbooks cannot drift apart)

Memory pin in agent.py is a durability aid, not a fourth fingerprint table.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from solver.tools import skill_chain
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


def _extract_hosts(context: str) -> set[str]:
    hosts: set[str] = set()
    for m in re.finditer(r"(?:https?://|//)(\d{1,3}(?:\.\d{1,3}){3})", context):
        hosts.add(m.group(1))
    for m in _IP_RE.findall(context):
        hosts.add(m)
    return hosts


def _target_drift_note(context: str) -> str:
    """Warn when bash hits a same-/24 but different host than the configured target."""
    target = _current_target_host()
    if not target:
        return ""
    tparts = target.split(".")
    if len(tparts) != 4:
        return ""
    tprefix = ".".join(tparts[:3])
    for host in _extract_hosts(context):
        if host == target:
            continue
        parts = host.split(".")
        if len(parts) == 4 and ".".join(parts[:3]) == tprefix and parts[3] != tparts[3]:
            return (
                f"🎯 [目标 IP 锁定] 本题目标是 **{target}**，命令里出现了 **{host}**（同网段旧实例）。"
                f"禁止把 .{parts[3]} 上的结论搬到 .{tparts[3]}；所有探测必须指向 {target}，"
                f"Memory 里旧 IP 的事实需重新验证。\n"
            )
    return ""


def _url_glue_bug_note(output: str) -> str:
    if any(x in (output or "") for x in ("NameResolutionError", "InvalidURL", "Failed to establish a new connection")):
        if re.search(r"http://\d+\.\d+\.\d+\.\d+[a-z/]", output or "", re.I):
            return (
                "⚠️ [脚本 URL 错误] 检测到 `http://IP路径` 拼接 bug（缺 `:` 端口或 `/`）。"
                "应写 `http://IP:80/path` 或 `base='http://IP:80'; base+path`，修脚本后再跑。\n"
            )
    return ""


def _engineering_error_oracle(output: str) -> str:
    """Map concrete tool errors → next action (generic, not per-code).

    Lesson from c-02: wrong hypotheses burn hours; real stderr fixes in minutes.
    """
    text = output or ""
    low = text.lower()
    if (
        "neither 'setup.py' nor 'pyproject.toml'" in low
        or "does not appear to be a python project" in low
    ):
        return (
            "⚠️ [工程错误 · sdist] pip 找不到 setup.py/pyproject.toml。"
            "不要猜路径 bug：用 `python setup.py sdist --formats=gztar` 重打标准包"
            "（顶层必须 `pkg-1.0/` + PKG-INFO），安装时加 `--log` 核对。\n"
        )
    if "no-build-isolation" in low and ("uv" in low or "unrecognized" in low or "unknown option" in low):
        return (
            "⚠️ [工程错误 · uv] `--no-build-isolation` 不被支持。"
            "config.ini 设 `use_uv = False` 后 reboot，再用 pip 安装本地 sdist。\n"
        )
    if re.search(r"/api/manager/reboot.*(405|method not allowed)", low) or (
        "405" in text and "manager/reboot" in low and "/api/manager/reboot" in low
    ):
        return (
            "⚠️ [工程错误 · 端点] `/api/manager/reboot` = 405。"
            "改用 `/manager/reboot`（无 `/api` 前缀）。\n"
        )
    return ""


def _protocol_probe_note(output: str, context: str) -> str:
    combined = f"{output or ''}\n{context or ''}".lower()
    if (
        any(f":{p}" in combined for p in ("7860", "7861", "9090"))
        and any(x in combined for x in (
            "connection reset", "reset by peer", "empty reply", "recv failure",
            "timed out", "无输出", "no bytes", "timeout",
        ))
        and "http/1" not in combined[:800]
    ):
        return (
            "⭐ [Skill 路由 · 协议探测] 端口可连但 HTTP 无有效响应。"
            "HTTP 最多再试 1 次后必须：`nc` 静默读 banner → 发 `\\r\\n`/二进制握手；"
            "禁止扫同网段其它 IP 的 :80 FastAPI、禁止用端口弱信号当 Gradio CVE 依据。\n"
        )
    return ""


def _ssrf_note(output: str, context: str) -> str:
    combined = f"{output or ''}\n{context or ''}".lower()
    if any(x in combined for x in (
        "169.254.169.254", "metadata.google", "ssrf",
        "127.0.0.1", "localhost", "内网", "file://",
    )) and any(x in combined for x in ("curl", "wget", "requests.", "http://", "fetch(")):
        return (
            "⭐ [Skill 路由 · SSRF] 出现内网/metadata 请求痕迹。"
            "下一步：`skill_load(name=\"web\", resource=\"ssrf.md\")`；"
            "从题目允许的 URL 参数打到内网服务，勿盲扫全 /24。\n"
        )
    return ""


def _multistage_note(output: str, context: str) -> str:
    combined = f"{output or ''}\n{context or ''}".lower()
    if any(x in combined for x in ("correct_flag", "已找到", "1/4", "2/4", "3/4", "stage")):
        if "提权" in combined or "横向" in combined or "内网" in combined:
            return (
                "⭐ [Skill 路由 · 多阶段] 已有部分 flag/内网线索。"
                "用 memory_add 记 stage_ledger；下一跳从当前 shell/凭据出发，"
                "勿重复全端口 nmap 或已失败的 exploit 链。\n"
            )
    return ""


def lookup(output: str, context: str = "") -> str:
    """Return a skill-route banner to prepend to bash output, or empty string."""
    lines: list[str] = []

    drift = _target_drift_note(f"{output or ''}\n{context or ''}")
    if drift:
        lines.append(drift.rstrip())

    url_bug = _url_glue_bug_note(output or "")
    if url_bug:
        lines.append(url_bug.rstrip())

    eng = _engineering_error_oracle(output or "")
    if eng:
        lines.append(eng.rstrip())

    # Chain playbooks: single fingerprint table lives in skill_chain.
    chain_banners = skill_chain.lookup_route_banners(output, context)
    if chain_banners:
        for block in chain_banners.strip().split("\n\n"):
            block = block.strip()
            if block:
                lines.append(block)

    proto = _protocol_probe_note(output or "", context or "")
    if proto:
        lines.append(proto.rstrip())

    ssrf = _ssrf_note(output or "", context or "")
    if ssrf:
        lines.append(ssrf.rstrip())

    multi = _multistage_note(output or "", context or "")
    if multi:
        lines.append(multi.rstrip())

    if not lines:
        return ""
    return "\n".join(lines) + "\n\n"
