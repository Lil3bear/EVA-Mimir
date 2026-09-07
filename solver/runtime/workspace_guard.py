"""Prevent parallel runs from reading or writing sibling challenge workspaces."""

from __future__ import annotations

import os
import re
from pathlib import Path

from solver.worker_context import ctx as _ctx

# Platform challenge codes: a-03, c-08, e3-04, f2-01, ...
_CHALLENGE_CODE_RE = re.compile(r"^[a-z][a-z0-9]*-\d+$", re.IGNORECASE)

# Absolute paths like /workspace/c-08/ or $PWD/../b-01/
_ABS_WORKSPACE_RE = re.compile(
    r"(?:^|[\s'\"=(])(?:/workspace|~?/workspace)/([a-z][a-z0-9]*-\d+)(?:/|\b)",
    re.IGNORECASE,
)
# cd ../other-code, cd /workspace/other-code
_CD_FOREIGN_RE = re.compile(
    r"\bcd\s+(?:/workspace/)?([a-z][a-z0-9]*-\d+)\b",
    re.IGNORECASE,
)


def _current_challenge_code() -> str:
    return (getattr(_ctx, "unique_code", "") or getattr(_ctx, "challenge_id", "") or "").strip()


def _is_challenge_code(name: str) -> bool:
    return bool(_CHALLENGE_CODE_RE.match((name or "").strip()))


def foreign_challenge_codes(text: str) -> list[str]:
    """Return challenge codes referenced in a shell command or path."""
    if not text:
        return []
    current = _current_challenge_code().lower()
    found: list[str] = []
    for pattern in (_ABS_WORKSPACE_RE, _CD_FOREIGN_RE):
        for match in pattern.finditer(text):
            code = match.group(1).strip()
            if not _is_challenge_code(code):
                continue
            lowered = code.lower()
            if current and lowered == current:
                continue
            if lowered not in found:
                found.append(lowered)
    return found


def _foreign_block_message(foreign: list[str], *, action: str = "访问") -> str:
    if not foreign:
        return ""
    current = _current_challenge_code() or "本题"
    joined = ", ".join(foreign[:3])
    base = getattr(_ctx, "challenge_dir", "") or ""
    hint = f"本题目录：{base}" if base else f"本题编号：{current}"
    return (
        f"[拒绝] 禁止{action}其他题目的工作目录（{joined}）。"
        f"并行评测时各题 workspace 互相隔离；{hint}。"
        "脚本与输出只能落在本题目录下。"
    )


def block_foreign_workspace(text: str, *, action: str = "访问") -> str:
    """Return a user-facing error when *text* references another challenge dir."""
    return _foreign_block_message(foreign_challenge_codes(text), action=action)


def assert_path_allowed(path: str) -> str:
    """Return error message when an absolute path crosses into another challenge."""
    if not path:
        return ""
    foreign = foreign_challenge_codes(path)
    if foreign:
        return block_foreign_workspace(path, action="读取")
    current = _current_challenge_code().lower()
    if current:
        for part in Path(path).parts:
            if _is_challenge_code(part) and part.lower() != current:
                return _foreign_block_message([part.lower()], action="读取")
    resolved = Path(path)
    workspace = (getattr(_ctx, "workspace", "") or "").strip()
    challenge_dir = (getattr(_ctx, "challenge_dir", "") or "").strip()
    if workspace and challenge_dir and workspace not in {"/workspace", "/"}:
        try:
            ws = Path(workspace).resolve()
            mine = Path(challenge_dir).resolve()
            resolved = resolved.resolve()
            if resolved.is_relative_to(ws) and not resolved.is_relative_to(mine):
                rel = resolved.relative_to(ws)
                if rel.parts and _is_challenge_code(rel.parts[0]):
                    return _foreign_block_message([rel.parts[0].lower()], action="读取")
        except (ValueError, OSError):
            pass
    return ""


def tool_results_dir() -> str:
    """Directory for large bash outputs; always scoped to the active attempt."""
    attempt = (getattr(_ctx, "attempt_dir", "") or "").strip()
    challenge = (getattr(_ctx, "challenge_dir", "") or "").strip()
    code = _current_challenge_code()
    workspace = (getattr(_ctx, "workspace", "") or "").strip()

    base = attempt or challenge
    if not base or base in {"/workspace", "/"}:
        if workspace and code:
            base = os.path.join(workspace, code)
        else:
            base = challenge or "/workspace"
    return os.path.join(base, ".tool-results")
