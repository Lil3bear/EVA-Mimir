"""Skill 知识库专用工具。

与通用 read_file 分离：read_file 只用于附件/源码，Skill 知识检索走这里。

设计目标：
- skill_list()  只暴露 name + description + 可用 reference，模型不用读大文件就能选。
- skill_load()  加载 SKILL.md 入口（路由/决策），不返回整本 payload 库。
- skill_load(name, resource) 一次调用完整返回某个 reference（有明确边界）。

前端 YAML frontmatter 约定：
    ---
    name: web
    description: 处理 HTTP/Web 入口的 CTF 题。
    ---
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from solver.worker_context import ctx as _ctx

# 单次 skill_load 返回上限：覆盖仓库内当前最大的 reference，保持一次读全。
MAX_BODY = 40000
# skill_load(name) 入口文档的返回上限（入口应 < 200 行）。
MAX_ENTRY = 12000


def _skills_root() -> str:
    return os.environ.get("CTF_SKILLS_DIR", "/skills")


def _safe_name(name: str) -> str:
    """只允许字母/数字/连字符，防路径穿越。"""
    name = (name or "").strip().lower()
    if not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in name):
        raise ValueError(f"非法 skill 名称：{name!r}")
    return name


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析文件开头的 --- frontmatter。返回 (meta, body)。"""
    meta: dict[str, Any] = {}
    body = text
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is not None:
            fm_lines = lines[1:end]
            for line in fm_lines:
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip()
            body = "\n".join(lines[end + 1:])
    return meta, body


def _first_description(body: str) -> str:
    """无 frontmatter 时从正文第一段派生描述。"""
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("#"):
            continue
        if len(line) >= 8:
            return line[:120]
    return ""


def _list_skills(root: str | None = None) -> list[dict]:
    root = root or _skills_root()
    root_path = Path(root)
    result: list[dict] = []
    if not root_path.exists():
        return result
    for d in sorted(root_path.iterdir()):
        if not d.is_dir():
            continue
        skill_md = d / "SKILL.md"
        if not skill_md.exists():
            continue
        try:
            text = skill_md.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        meta, body = _parse_frontmatter(text)
        name = meta.get("name") or d.name
        description = meta.get("description") or _first_description(body)
        references: list[str] = []
        ref_dir = d / "references"
        if ref_dir.is_dir():
            references = sorted(
                p.name for p in ref_dir.glob("*.md")
            )
        result.append({
            "name": name,
            "description": description,
            "references": references,
        })
    return result


def _resolve_resource(name: str, resource: str | None) -> Path:
    root = Path(_skills_root())
    skill_dir = root / name
    if resource:
        resource = resource.strip().lstrip("/")
        if resource.startswith("..") or os.path.isabs(resource):
            raise ValueError(f"非法资源路径：{resource!r}")
        path = (skill_dir / "references" / resource).resolve()
    else:
        path = (skill_dir / "SKILL.md").resolve()
    # 必须仍位于 skill 目录内
    skill_dir_resolved = skill_dir.resolve()
    if not str(path).startswith(str(skill_dir_resolved) + os.sep) and path != skill_dir_resolved / "SKILL.md":
        raise ValueError(f"资源越界：{resource!r}")
    return path


def _format_loaded(name: str, resource: str | None, content: str, truncated: bool) -> str:
    header = f"[Skill: {name}" + (f"/references/{resource}" if resource else "") + "]"
    tail = "\n...[内容过长已截断]" if truncated else ""
    return f"{header}\n\n{content}{tail}"


def skill_list(args: dict) -> str:
    """列出可用 Skill：名称、用途、可用 reference。"""
    skills = _list_skills()
    if not skills:
        return "[Skills] 未找到任何 Skill。"
    lines = ["[Skills 目录]（用 skill_load 按需加载，不要 read_file 整本读）"]
    for s in skills:
        refs = ", ".join(s["references"]) if s["references"] else "（无）"
        lines.append(f"- {s['name']}: {s['description']}")
        lines.append(f"  references: {refs}")
    return "\n".join(lines)


def skill_load(args: dict) -> str:
    """加载 Skill 入口或某个 reference。"""
    name = _safe_name(args.get("name", ""))
    resource = args.get("resource", "").strip() or None
    path = _resolve_resource(name, resource)

    if not path.exists():
        return f"[错误] Skill 资源不存在：{name}" + (f"/{resource}" if resource else "")

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"[错误] 读取失败：{e}"

    limit = MAX_BODY if resource else MAX_ENTRY
    truncated = False
    if len(text) > limit:
        # 入口文档截断时，提示用 skill_load(name, resource) 加载具体 reference
        text = text[:limit]
        truncated = True
        if not resource:
            text += "\n\n...[入口已截断，请用 skill_list 查看 references，再 skill_load(name, resource) 精确加载]"

    return _format_loaded(name, resource, text, truncated)


TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "skill_list",
            "description": (
                "列出可用的 CTF 知识 Skill（名称、用途、可加载的 reference）。"
                "解题前先调用它确定该加载哪个 Skill。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill_load",
            "description": (
                "加载指定 Skill 的入口文档或某个 reference 章节。"
                "参数 name 必填（如 web/pwn/reverse/pentest/cloud/crypto/evasion）；"
                "resource 可选，填 skill_list 返回的 references 文件名（如 product-playbooks.md）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Skill 名称"},
                    "resource": {"type": "string", "description": "reference 文件名（可选）"},
                },
                "required": ["name"],
            },
        },
    },
]
