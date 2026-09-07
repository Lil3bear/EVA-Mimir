"""Mandatory skill-load chains: description/fingerprint → playbook → gate wrong tools.

Closes the unstable6 knowledge loop: banners alone are ignored too often;
this module blocks security_search / off-chain bash until the right reference
is loaded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Chain definitions (generic vulnerability families, not per-code hacks)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SkillChain:
    chain_id: str
    skill: str
    resource: str
    label: str
    description_keywords: tuple[str, ...] = ()
    blocks_search: bool = True
    block_bash_patterns: tuple[str, ...] = ()


_CHAINS: tuple[SkillChain, ...] = (
    SkillChain(
        "flask-session",
        "web",
        "common-vulnerabilities.md",
        "Flask session 伪造（/login 500 + gunicorn）",
        ("资产管理系统", "flask session", "flask-unsign", "gunicorn"),
        block_bash_patterns=(
            r"\bffuf\b",
            r"\bgobuster\b",
            r"\bdirb\b",
            r"\bdirsearch\b",
            r"wordlist",
            r"路径扫描|目录扫描",
        ),
    ),
    SkillChain(
        "jwt-kid",
        "web",
        "jwt-attacks.md",
        "JWT kid 伪造（静态文件作密钥）+ php-fpm FastCGI",
        ("jwt", "cloudfunc", "云函数", "kid", "prod.key"),
        # 只拦明确盲猜；允许读 /css、扫 9000 等活路探测。
        block_bash_patterns=(
            r"kid[=:\s]+['\"]?(none|admin|test|key)['\"]?",
            r"alg[=:\s]*none",
        ),
    ),
    SkillChain(
        "pydash",
        "web",
        "prototype-pollution-pydash.md",
        "PyDash 原型链污染 + cookie/路径绕过",
        ("pydash", "原型链", "parse_path", "八进制"),
        block_bash_patterns=(
            r"\bffuf\b",
            r"\bgobuster\b",
            r"\.git/HEAD",
            r"/static/\.\./",
        ),
    ),
    SkillChain(
        "comfyui",
        "web",
        "product-playbooks.md",
        "ComfyUI：config.ini + 标准 sdist + pip install（禁 git_url /view 遍历）",
        ("comfyui", "8188", "智算模型"),
        block_bash_patterns=(
            # 遍历才拦；type=input 读回 flag 是成功链最后一步
            r"/view\?[^\"'\s]*filename=\.\.",
            r"/view\?[^\"'\s]*\.\./",
            r"filename=.*\.(png|jpg|safetensors)",
            r"install/git_url",
            r"customnode/install/git",
            r"git_url",
        ),
    ),
    SkillChain(
        "langflow",
        "web",
        "product-playbooks.md",
        "Langflow 7860 协议 + CVE 链",
        ("langflow", "智能编排", "编排调度"),
        block_bash_patterns=(
            r":80/login",
            r":80/api",
            r"10\.\d+\.\d+\.\d+:80",
        ),
    ),
    SkillChain(
        "gradio",
        "web",
        "product-playbooks.md",
        "Gradio 7860 /file= 白名单链",
        ("gradio", "7860"),
        block_bash_patterns=(
            r"/file=/flag",
            r"/file=/etc/passwd",
        ),
    ),
    SkillChain(
        "evasion-check",
        "evasion",
        "process-injection-bypass.md",
        "检测对抗 /check 逐条消规则",
        ("检测对抗", "注入检测", "免杀", "绕过检测", "对抗评估"),
        block_bash_patterns=(),
    ),
    SkillChain(
        "pentest-lateral",
        "pentest",
        "initial-access.md",
        "多阶段渗透：入口登录卡住→数据查询SSRF/内网→泛微OA SSH 默认凭证爆破",
        ("多阶段", "渗透", "APT", "内网", "横向", "企业遭遇"),
        # 只拦批量爆破工具；不要拦 playbook 里的单次登录表单（username=admin 等）。
        block_bash_patterns=(
            r"\bhydra\b",
            r"\bmedusa\b",
            r"\bncrack\b",
            r"-P\s+\S*(pass|wordlist|rockyou)",
        ),
    ),
    SkillChain(
        "reverse-vm",
        "reverse",
        "vm-and-firmware.md",
        "VM/字节码：门禁→停手推已删公式→angr/符号执行",
        ("虚拟机", "字节码", "bytecode", "自制指令", "自制虚拟机", "vm 解释器"),
        # 强制先 load playbook；不硬拦 bash（angr/objdump 脚本需自由跑）
        block_bash_patterns=(),
    ),
)

_CHAIN_BY_ID = {c.chain_id: c for c in _CHAINS}

# Bash / banner fingerprints → chain_id (same families as skill_router)
_FINGERPRINT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "flask-session",
        (
            r"gunicorn",
            r"/login",
            r"500",
        ),
    ),
    (
        "jwt-kid",
        (
            r'kid["\']?\s*[:=]\s*["\']?prod\.key',
            r"prod\.key.*kid",
        ),
    ),
    (
        "pydash",
        (
            r"pydash",
            r"pydash pollution",
            r"parse_path",
            r"sanic_session",
        ),
    ),
    (
        "comfyui",
        (
            r":8188",
            r"/api/manager",
            r"comfyui",
        ),
    ),
    (
        "langflow",
        (
            r"langflow",
            r"/api/v1/validate/code",
            r"/api/v1/webhook",
        ),
    ),
    (
        "gradio",
        (
            r"gradio",
            r"allowed_paths",
            r"file not allowed",
        ),
    ),
    (
        "evasion-check",
        (
            r"/check",
            r"triggered.*rule",
            r"bypass_score",
        ),
    ),
    (
        "reverse-vm",
        (
            r"\bbytecode\b",
            r"handler\[\d+\]",
            r"VM_KEY",
            r"自制.*虚拟机|虚拟机.*指令",
            r"跳转表|dispatch.*table",
        ),
    ),
)


def _ref_key(skill: str, resource: str) -> str:
    return f"{skill.strip().lower()}/{resource.strip().lower()}"


def chains_from_description(text: str) -> set[str]:
    lowered = (text or "").lower()
    found: set[str] = set()
    for chain in _CHAINS:
        if any(kw in lowered for kw in chain.description_keywords):
            found.add(chain.chain_id)
    # CloudFunc + JWT: both jwt-kid and serverless may appear; jwt takes priority.
    if any(k in lowered for k in ("cloudfunc", "serverless", "云函数")) and any(
        k in lowered for k in ("jwt", "token", "kid", "认证")
    ):
        found.add("jwt-kid")
    return found


def chains_from_task(task: str) -> set[str]:
    """Seed pending chains from the task banner (description + 📚 hints)."""
    parts: list[str] = []
    for line in (task or "").splitlines():
        if line.startswith("- 描述："):
            parts.append(line.split("：", 1)[-1])
        elif "📚" in line:
            parts.append(line)
    return chains_from_description("\n".join(parts))


def chains_from_bash(output: str, context: str = "") -> set[str]:
    combined = f"{output or ''}\n{context or ''}"
    found: set[str] = set()
    lower = combined.lower()

    for chain_id, patterns in _FINGERPRINT_RULES:
        if chain_id == "flask-session":
            if (
                "/login" in lower
                and "500" in lower
                and ("gunicorn" in lower or "session=" in lower or "set-cookie: session" in lower)
            ):
                found.add(chain_id)
            continue
        if chain_id == "langflow":
            langflow_hit = any(p in lower for p in ("langflow", "/api/v1/flows", "/api/v1/validate/code"))
            gradio_hit = "gradio" in lower or "gr-" in lower
            if langflow_hit or (":7860" in lower and "/api/v1/" in lower and not gradio_hit):
                found.add(chain_id)
            continue
        if chain_id == "gradio":
            if "gradio" in lower and ":7860" in lower:
                found.add(chain_id)
            continue
        for pat in patterns:
            if re.search(pat, combined, re.I):
                found.add(chain_id)
                break
    return found


@dataclass
class SkillChainTracker:
    """Per-attempt state: pending → active → satisfied."""

    pending: set[str] = field(default_factory=set)
    active: set[str] = field(default_factory=set)
    loaded: set[str] = field(default_factory=set)

    @classmethod
    def from_task(cls, task: str) -> SkillChainTracker:
        return cls(pending=chains_from_task(task))

    def observe_bash(self, output: str, context: str = "") -> None:
        for chain_id in chains_from_bash(output, context):
            self.active.add(chain_id)
            if chain_id in self.pending:
                self.pending.discard(chain_id)

    def mark_loaded(self, skill: str, resource: str) -> None:
        key = _ref_key(skill, resource)
        self.loaded.add(key)
        for chain in _CHAINS:
            if _ref_key(chain.skill, chain.resource) == key:
                self.active.discard(chain.chain_id)
                self.pending.discard(chain.chain_id)

    def unsatisfied(self) -> list[SkillChain]:
        need = self.pending | self.active
        out: list[SkillChain] = []
        for chain_id in sorted(need):
            chain = _CHAIN_BY_ID.get(chain_id)
            if chain is None:
                continue
            if _ref_key(chain.skill, chain.resource) in self.loaded:
                continue
            out.append(chain)
        return out

    def gate(self, tool_name: str, tool_args: dict) -> str:
        chains = self.unsatisfied()
        if not chains:
            return ""

        if tool_name == "security_search":
            blocked = [c for c in chains if c.blocks_search]
            if blocked:
                c = blocked[0]
                return (
                    f"[拒绝] 知识链未闭合：{c.label}。"
                    f"必须先 skill_load(name=\"{c.skill}\", resource=\"{c.resource}\") "
                    f"并按 playbook 逐步验证，禁止 security_search（离线幻觉）。"
                )

        if tool_name == "bash":
            cmd = str((tool_args or {}).get("cmd", "") or "")
            if not cmd.strip():
                return ""
            for chain in chains:
                for pat in chain.block_bash_patterns:
                    if re.search(pat, cmd, re.I):
                        return (
                            f"[拒绝] 知识链未闭合：{chain.label}。"
                            f"当前命令命中禁止模式（{pat}）。"
                            f"先 skill_load(name=\"{chain.skill}\", resource=\"{chain.resource}\") "
                            f"再按 § 步骤执行。"
                        )
        return ""

    def status_note(self) -> str:
        chains = self.unsatisfied()
        if not chains:
            return ""
        lines = ["⭐ [知识链] 以下 playbook 尚未加载，优先闭合："]
        for c in chains[:4]:
            lines.append(
                f"  - {c.label} → skill_load(name=\"{c.skill}\", resource=\"{c.resource}\")"
            )
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Banner text (single source with fingerprints above). skill_router calls this.
# ---------------------------------------------------------------------------

_ROUTE_BANNERS: dict[str, str] = {
    "flask-session": (
        "⭐ [Skill 路由 · Flask 资产管理系统] 拿 session 多路径："
        "已有 cookie → flask-unsign；/login 报 500/密码错误 → 先试 SQLi UNION 注入拿 session。"
        "拿到 session 后系统枚举 /admin/*、/api/* 隐藏路由（flag 常在这）。"
        "下一步：`skill_load(web, common-vulnerabilities.md)` §2 Flask session。\n"
    ),
    "jwt-kid": (
        "⭐ [Skill 路由 · JWT kid] 响应/解码里出现 `kid`→`prod.key`。"
        "下一步必须：`skill_load(name=\"web\", resource=\"jwt-attacks.md\")` "
        "→ §5：优先 `kid=../css/reset.css`（密钥=静态文件全文）伪造 admin；"
        "拿到 JWT 后转 php-fpm:9000 FastCGI，禁止盲猜 kid / 死磕 php_code.execute。"
        "（CloudFunc 题也先走 jwt-attacks，不要只 load serverless.md。）\n"
    ),
    "pydash": (
        "⭐ [Skill 路由 · PyDash] 指纹命中 pydash 原型链污染题。"
        "下一步：`skill_load(name=\"web\", resource=\"prototype-pollution-pydash.md\")` "
        "→ Cookie 八进制登录 + /admin path 污染，禁止目录爆破与 security_search。\n"
    ),
    "comfyui": (
        "⭐ [Skill 路由 · ComfyUI] 指纹命中 ComfyUI/8188。"
        "下一步：`skill_load(name=\"web\", resource=\"product-playbooks.md\")` "
        "→ §6.5：config.ini（weak + use_uv=False）→ `python setup.py sdist` 标准包 "
        "→ install/pip 裸文本 body → /manager/reboot → /view?type=input 读回；"
        "卡安装先 `--log` 读真实错误（手写 tar 常缺 setup.py）；"
        "git_url /view 遍历各试≤1次后转回本链（非绝对死路）。\n"
    ),
    "langflow": (
        "⭐ [Skill 路由 · Langflow] 7860 端口 + /api/v1/ 指纹 → Langflow（非 Gradio）。"
        "下一步：`skill_load(name=\"web\", resource=\"product-playbooks.md\")` "
        "→ §6.9 协议探测 + §6.10 默认参数求值 RCE；锁定目标 IP:7860，禁止漂到同网段 :80。\n"
    ),
    "gradio": (
        "⭐ [Skill 路由 · Gradio] 指纹命中 Gradio/7860。"
        "下一步：`skill_load(name=\"web\", resource=\"product-playbooks.md\")` "
        "→ §6.7/§6.8；若 `/file=` 返回 File not allowed，走白名单链。\n"
    ),
    "evasion-check": (
        "⭐ [Skill 路由 · 检测对抗] 命中 /check 评估端点。"
        "下一步：`skill_load(name=\"evasion\", resource=\"process-injection-bypass.md\")`；"
        "每改一版 POST /check 看触发条数，逐条消规则，勿盲改 shellcode。\n"
    ),
    "pentest-lateral": (
        "⭐ [Skill 路由 · 多阶段渗透] 入口登录卡住时**不要死磕登录页**（b-02 教训）。"
        "优先：1) 数据查询/搜索测 SSRF/SQLi 探内网；"
        "2) **从解题容器** sshpass/paramiko 直连内网 :22（靶机 web 无 ssh ≠ 无解）；"
        "3) 已拿部分 flag 时继续下一服务，勿重开全端口扫描。"
        "下一步：`skill_load(name=\"pentest\", resource=\"initial-access.md\")` + `ssh-operations.md`。\n"
    ),
    "reverse-vm": (
        "⭐ [Skill 路由 · VM/字节码] 命中自制 VM / 字节码解释器题。"
        "下一步：`skill_load(name=\"reverse\", resource=\"vm-and-firmware.md\")`；"
        "过门禁后若 putc 只吐点/公式被删 → 停手推 xor/add，"
        "`pip install angr` 符号约束 `flag{` 一次解满长。\n"
    ),
}


def lookup_route_banners(output: str, context: str = "") -> str:
    """Build skill-route banners from the same fingerprints as the hard gate."""
    found = chains_from_bash(output, context)
    # Prefer Langflow over Gradio when both could fire on :7860.
    if "langflow" in found and "gradio" in found:
        found.discard("gradio")
    lines: list[str] = []
    for chain_id in sorted(found):
        banner = _ROUTE_BANNERS.get(chain_id)
        if banner:
            lines.append(banner.rstrip())
    if not lines:
        return ""
    return "\n".join(lines) + "\n\n"
