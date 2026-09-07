"""Observer interference policy.

Default posture is advisory: keep Memory hygiene, suppress directional
corrections unless the deterministic decision plane shows thrashing.
Truncated / mangled evidence must never be written into Memory.
"""

from __future__ import annotations

from typing import Any

# Markers that mean the Observer (or Solver) only saw a partial dump.
TRUNCATION_MARKERS: tuple[str, ...] = (
    "[历史输出过长，仅保留末尾",
    "[文件过长，只显示最后",
    "...[observer excerpt]...",
    " ...[省略]... ",
    "...[省略]...",
    "... (省略中间部分) ...",
    "[截断]",
    "[输出过长",
    "...[已截断",
    "...[内容过长已截断]",
    "...[tool output truncated for summary]...",
)

# Soft pollution heuristics: pasted playbooks / long dumps masquerading as facts.
_POLLUTION_SNIPPETS: tuple[str, ...] = (
    "## 步骤",
    "### Step",
    "playbook",
    "skill_load(name=",
    "必须先 skill_load",
    "[历史输出过长",
    "[输出过长",
    "❌ 死路",
    "绝对死路",
)

_DEFAULT_ACTION_STREAK = 4
_DEFAULT_VECTOR_STREAK = 6
_MAX_TRUSTED_MEMORY_CHARS = 1200


def normalize_observer_mode(raw: Any) -> str:
    mode = str(raw or "advisory").strip().lower()
    if mode in {"off", "disabled", "false", "0"}:
        return "off"
    if mode in {"full", "aggressive", "legacy"}:
        return "full"
    return "advisory"


def content_has_truncation(content: str) -> bool:
    text = str(content or "")
    return any(marker in text for marker in TRUNCATION_MARKERS)


def memory_write_allowed(content: str, *, kind: str = "note") -> tuple[bool, str]:
    """Gate Memory writes that would pollute the board from partial evidence."""
    text = str(content or "").strip()
    if not text:
        return False, "empty"
    if content_has_truncation(text):
        return False, "truncated_evidence"
    if len(text) > _MAX_TRUSTED_MEMORY_CHARS and kind != "evidence":
        return False, "oversized_non_evidence"
    lower = text.lower()
    polluted = any(s.lower() in lower for s in _POLLUTION_SNIPPETS)
    # note/failure: block mid-size playbook dumps; fact: only block large dumps
    # so short skill-route pins (skill_load(...)) remain allowed.
    if polluted and kind in {"note", "failure"} and len(text) >= 240:
        return False, "playbook_dump"
    if polluted and kind == "fact" and len(text) >= 400:
        return False, "playbook_dump"
    return True, "ok"


def is_untrusted_memory(content: str) -> bool:
    allowed, _ = memory_write_allowed(content, kind="note")
    return not allowed


def correction_allowed(
    *,
    mode: str,
    decision: dict[str, Any] | None = None,
    skill_chain_open: bool = False,
    strong_intervention: bool = False,
    action_streak_threshold: int = _DEFAULT_ACTION_STREAK,
    vector_streak_threshold: int = _DEFAULT_VECTOR_STREAK,
) -> tuple[bool, str]:
    """Whether Observer may inject a directional correction into the Solver."""
    mode = normalize_observer_mode(mode)
    if mode == "off":
        return False, "mode_off"
    if mode == "full":
        return True, "mode_full"

    # advisory
    if skill_chain_open:
        return False, "skill_chain_open"

    decision = decision or {}
    try:
        action_streak = int(decision.get("same_action_streak") or 0)
    except (TypeError, ValueError):
        action_streak = 0
    try:
        vector_streak = int(decision.get("same_vector_streak") or 0)
    except (TypeError, ValueError):
        vector_streak = 0

    if action_streak >= action_streak_threshold:
        return True, "same_action_streak"
    if vector_streak >= vector_streak_threshold:
        return True, "same_vector_streak"

    # Deterministic "no progress" / vector-cycle interventions also need a
    # thrashing signal under advisory; otherwise they interrupt long solves.
    if strong_intervention and (
        action_streak >= max(2, action_streak_threshold - 1)
        or vector_streak >= max(3, vector_streak_threshold - 2)
    ):
        return True, "strong_with_streak"

    return False, "quiet_default"
