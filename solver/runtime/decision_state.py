"""Typed decision state for adaptive challenge control.

The solver's durable memory stores facts and ideas, while this module stores
small, deterministic control signals: action fingerprints, evidence novelty,
strategy mode and hypothesis ownership.  It deliberately does not contain
challenge-specific answers or payloads.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class StrategyMode(str, Enum):
    MAP = "MAP"
    EXPLORE = "EXPLORE"
    EXPLOIT = "EXPLOIT"
    ALTERNATE = "ALTERNATE"
    VERIFY = "VERIFY"
    RECOVER = "RECOVER"


class ActionOutcomeKind(str, Enum):
    NOVEL_EVIDENCE = "novel_evidence"
    NEGATIVE_BOUNDARY = "negative_boundary"
    DUPLICATE = "duplicate"
    TIMEOUT = "timeout"
    ERROR = "error"
    BLOCKED = "blocked"
    SUBMISSION = "submission"
    NONE = "none"


class HypothesisStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    TESTING = "testing"
    SUPPORTED = "supported"
    DISPROVED = "disproved"
    BLOCKED = "blocked"
    EXPIRED = "expired"


@dataclass(frozen=True)
class ActionOutcome:
    """Deterministic classification of one completed tool action."""

    kind: str
    tool_name: str
    action_fingerprint: str
    vector: str
    soft_progress: bool = False
    novel_progress: bool = False
    positive_progress: bool = False
    evidence_fingerprints: tuple[str, ...] = ()
    reason: str = ""
    round_num: int = 0
    attempt_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "tool_name": self.tool_name,
            "action_fingerprint": self.action_fingerprint,
            "vector": self.vector,
            "soft_progress": self.soft_progress,
            "novel_progress": self.novel_progress,
            "positive_progress": self.positive_progress,
            "evidence_fingerprints": list(self.evidence_fingerprints),
            "reason": self.reason,
            "round_num": self.round_num,
            "attempt_id": self.attempt_id,
        }


@dataclass
class Hypothesis:
    id: str
    description: str
    domain: str = ""
    status: str = HypothesisStatus.PENDING.value
    confidence: float = 0.5
    owner: str = ""
    lease_until: int = 0
    expected_evidence: str = ""
    attempts: int = 0
    last_round: int = 0
    last_result: str = ""
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "domain": self.domain,
            "status": self.status,
            "confidence": self.confidence,
            "owner": self.owner,
            "lease_until": self.lease_until,
            "expected_evidence": self.expected_evidence,
            "attempts": self.attempts,
            "last_round": self.last_round,
            "last_result": self.last_result,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Hypothesis":
        return cls(
            id=str(data.get("id", "")),
            description=str(data.get("description", "")),
            domain=str(data.get("domain", "")),
            status=str(data.get("status", HypothesisStatus.PENDING.value)),
            confidence=_bounded_confidence(data.get("confidence", 0.5)),
            owner=str(data.get("owner", "")),
            lease_until=_safe_int(data.get("lease_until", 0)),
            expected_evidence=str(data.get("expected_evidence", "")),
            attempts=_safe_int(data.get("attempts", 0)),
            last_round=_safe_int(data.get("last_round", 0)),
            last_result=str(data.get("last_result", "")),
            updated_at=_safe_float(data.get("updated_at", 0.0)),
        )


@dataclass
class DecisionState:
    """Small, versioned state snapshot shared by attempts for one challenge."""

    schema_version: int = 1
    state_version: int = 0
    challenge_id: str = ""
    strategy_mode: str = StrategyMode.EXPLORE.value
    stage: str = "CLASSIFY"
    last_round: int = 0
    last_soft_progress_round: int = 0
    last_novel_progress_round: int = 0
    last_positive_progress_round: int = 0
    last_action_fingerprint: str = ""
    same_action_streak: int = 0
    last_vector: str = ""
    same_vector_streak: int = 0
    switch_count: int = 0
    last_switch_round: int = 0
    total_actions: int = 0
    last_outcome: str = ActionOutcomeKind.NONE.value
    last_reason: str = ""
    evidence_fingerprints: list[str] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)

    @classmethod
    def empty(cls, challenge_id: str = "") -> "DecisionState":
        return cls(challenge_id=challenge_id)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "DecisionState":
        data = data or {}
        raw_hypotheses = data.get("hypotheses") or []
        hypotheses = []
        if isinstance(raw_hypotheses, list):
            for item in raw_hypotheses:
                if isinstance(item, Mapping):
                    hypothesis = Hypothesis.from_dict(item)
                    if hypothesis.id and hypothesis.description:
                        hypotheses.append(hypothesis)
        raw_fps = data.get("evidence_fingerprints") or []
        fingerprints = [str(value) for value in raw_fps if value][:2048]
        return cls(
            schema_version=_safe_int(data.get("schema_version", 1)) or 1,
            state_version=_safe_int(data.get("state_version", 0)),
            challenge_id=str(data.get("challenge_id", "")),
            strategy_mode=str(data.get("strategy_mode", StrategyMode.EXPLORE.value)),
            stage=str(data.get("stage", "CLASSIFY")),
            last_round=_safe_int(data.get("last_round", 0)),
            last_soft_progress_round=_safe_int(data.get("last_soft_progress_round", 0)),
            last_novel_progress_round=_safe_int(data.get("last_novel_progress_round", 0)),
            last_positive_progress_round=_safe_int(data.get("last_positive_progress_round", 0)),
            last_action_fingerprint=str(data.get("last_action_fingerprint", "")),
            same_action_streak=_safe_int(data.get("same_action_streak", 0)),
            last_vector=str(data.get("last_vector", "")),
            same_vector_streak=_safe_int(data.get("same_vector_streak", 0)),
            switch_count=_safe_int(data.get("switch_count", 0)),
            last_switch_round=_safe_int(data.get("last_switch_round", 0)),
            total_actions=_safe_int(data.get("total_actions", 0)),
            last_outcome=str(data.get("last_outcome", ActionOutcomeKind.NONE.value)),
            last_reason=str(data.get("last_reason", "")),
            evidence_fingerprints=fingerprints,
            hypotheses=hypotheses,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state_version": self.state_version,
            "challenge_id": self.challenge_id,
            "strategy_mode": self.strategy_mode,
            "stage": self.stage,
            "last_round": self.last_round,
            "last_soft_progress_round": self.last_soft_progress_round,
            "last_novel_progress_round": self.last_novel_progress_round,
            "last_positive_progress_round": self.last_positive_progress_round,
            "last_action_fingerprint": self.last_action_fingerprint,
            "same_action_streak": self.same_action_streak,
            "last_vector": self.last_vector,
            "same_vector_streak": self.same_vector_streak,
            "switch_count": self.switch_count,
            "last_switch_round": self.last_switch_round,
            "total_actions": self.total_actions,
            "last_outcome": self.last_outcome,
            "last_reason": self.last_reason,
            "evidence_fingerprints": list(self.evidence_fingerprints[-2048:]),
            "hypotheses": [item.to_dict() for item in self.hypotheses[-128:]],
        }

    def summary(self) -> dict[str, Any]:
        """Return a small prompt-safe summary, not the full evidence store."""
        return {
            "state_version": self.state_version,
            "strategy_mode": self.strategy_mode,
            "stage": self.stage,
            "last_round": self.last_round,
            "same_action_streak": self.same_action_streak,
            "same_vector_streak": self.same_vector_streak,
            "last_novel_progress_round": self.last_novel_progress_round,
            "last_positive_progress_round": self.last_positive_progress_round,
            "switch_count": self.switch_count,
            "active_hypotheses": sum(
                item.status in {
                    HypothesisStatus.PENDING.value,
                    HypothesisStatus.ACTIVE.value,
                    HypothesisStatus.TESTING.value,
                }
                for item in self.hypotheses
            ),
            "last_outcome": self.last_outcome,
        }


def stable_action_fingerprint(tool_name: str, tool_args: Mapping[str, Any] | None) -> str:
    """Hash a canonical action so different attempts share repeat detection."""
    tool = str(tool_name or "").strip().lower()
    args = dict(tool_args or {})
    if tool == "bash" and "cmd" in args:
        # Collapse shell whitespace but preserve argument order and values.
        args["cmd"] = re.sub(r"\s+", " ", str(args["cmd"]).strip())
    payload = json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(f"{tool}\0{payload}".encode("utf-8")).hexdigest()[:20]


def classify_vector(tool_name: str, tool_args: Mapping[str, Any] | None) -> str:
    tool = str(tool_name or "").lower()
    if tool in {"skill_load", "skill_list"}:
        return "skill"
    if tool in {"memory_add", "memory_list", "idea_list"}:
        return "blackboard"
    if tool in {"challenge_get_hint", "challenge_get_state"}:
        return "platform_state"
    if tool == "challenge_submit_flag":
        return "verification"
    text = json.dumps(dict(tool_args or {}), ensure_ascii=False).lower()
    groups = (
        ("web", ("curl", "http", "api", "endpoint", "request")),
        ("network", ("nmap", "nc ", "netcat", "port", "socket", "ssh")),
        ("auth", ("login", "jwt", "token", "cookie", "password", "passwd")),
        ("file", ("read_file", "grep", "find", "/etc/", "config", "source")),
        ("binary", ("gdb", "objdump", "readelf", "strings", "elf")),
        ("crypto", ("openssl", "decrypt", "xor", "aes", "rsa", "hash")),
        ("code", ("python", "php", "java", "node", "serialize", "eval")),
    )
    for name, keywords in groups:
        if any(keyword in text for keyword in keywords):
            return name
    return tool or "unknown"


def extract_evidence_fingerprints(tool_name: str, result: str) -> tuple[str, ...]:
    """Extract hashed, non-secret evidence markers from a tool result."""
    text = str(result or "").strip()
    if not text:
        return ()
    lowered = text.lower()
    if lowered.startswith(("[错误]", "[停止]", "[拒绝]", "[拦截]", "[阻止]")):
        return ()

    markers: list[tuple[str, str]] = []
    patterns = (
        ("flag", r"[A-Za-z0-9_:-]+\{[^}\s]{4,120}\}"),
        ("ip", r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
        ("http", r"HTTP/[0-9.]+\s+\d{3}"),
        ("identity", r"(?:uid=\d+|gid=\d+|www-data|root)"),
        ("path", r"(?<![\w])/[A-Za-z0-9._~!$&()*+,;=:@%/-]{4,}"),
        ("positive", r"(?:success|successful|found|exists|vulnerable|成功|发现)"),
    )
    for kind, pattern in patterns:
        for value in re.findall(pattern, text, re.IGNORECASE):
            normalized = re.sub(r"\s+", " ", str(value).strip().lower())
            markers.append((kind, normalized))

    # File/source output often contains useful novel facts without one of the
    # markers above.  Keep only a bounded normalized digest, never raw content.
    if not markers and tool_name in {"bash", "read_file", "grep", "challenge_get_state"}:
        normalized = re.sub(r"\s+", " ", text)
        normalized = re.sub(r"\b\d{6,}\b", "<number>", normalized)
        if len(normalized) >= 12:
            markers.append(("output", normalized[:800]))

    fingerprints = []
    for kind, value in markers:
        fingerprints.append(
            hashlib.sha1(f"{kind}\0{value}".encode("utf-8")).hexdigest()[:24]
        )
    return tuple(dict.fromkeys(fingerprints))


def classify_action(
    tool_name: str,
    tool_args: Mapping[str, Any] | None,
    result: str,
    *,
    known_evidence: set[str] | None = None,
    round_num: int = 0,
    attempt_id: str = "",
) -> ActionOutcome:
    """Classify an action without asking the LLM to judge its own progress."""
    tool = str(tool_name or "")
    text = str(result or "").strip()
    lowered = text.lower()
    action_fp = stable_action_fingerprint(tool, tool_args)
    vector = classify_vector(tool, tool_args)
    known = known_evidence or set()

    if lowered.startswith("[停止]") or "超时" in lowered or "timeout" in lowered:
        return ActionOutcome(
            ActionOutcomeKind.TIMEOUT.value,
            tool,
            action_fp,
            vector,
            reason="tool_timeout_or_deadline",
            round_num=round_num,
            attempt_id=attempt_id,
        )
    if lowered.startswith(("[拒绝]", "[拦截]", "[阻止]")):
        return ActionOutcome(
            ActionOutcomeKind.BLOCKED.value,
            tool,
            action_fp,
            vector,
            reason="tool_gate_blocked",
            round_num=round_num,
            attempt_id=attempt_id,
        )
    if lowered.startswith("[错误]") or "执行失败" in lowered:
        return ActionOutcome(
            ActionOutcomeKind.ERROR.value,
            tool,
            action_fp,
            vector,
            reason="tool_error",
            round_num=round_num,
            attempt_id=attempt_id,
        )

    if tool in {"challenge_get_hint", "skill_load", "skill_list", "memory_list", "idea_list"}:
        return ActionOutcome(
            ActionOutcomeKind.NONE.value,
            tool,
            action_fp,
            vector,
            reason="control_input_not_target_progress",
            round_num=round_num,
            attempt_id=attempt_id,
        )

    fingerprints = extract_evidence_fingerprints(tool, text)
    fresh = tuple(value for value in fingerprints if value not in known)
    negative = bool(
        re.search(r"HTTP/[0-9.]+\s+[45]\d\d", text, re.IGNORECASE)
        or re.search(
            r"(?:not found|forbidden|denied|invalid|failed|wrong|incorrect|"
            r"不存在|拒绝|失败|错误)",
            text,
            re.IGNORECASE,
        )
    )
    positive = bool(
        not negative
        and re.search(
            r"(?:\{[^}\s]{4,120}\}|HTTP/[0-9.]+\s+2\d\d|uid=\d+|root|www-data|"
            r"\bsuccess(?:ful)?\b|\bfound\b|\bexists\b|\bvulnerable\b|成功|发现)",
            text,
            re.IGNORECASE,
        )
    )

    if tool == "challenge_submit_flag":
        kind = ActionOutcomeKind.SUBMISSION.value
        positive = bool(
            re.search(r"(?:✓|正确|accepted|全部)", text, re.IGNORECASE)
        )
    elif fresh and negative:
        kind = ActionOutcomeKind.NEGATIVE_BOUNDARY.value
    elif fresh:
        kind = ActionOutcomeKind.NOVEL_EVIDENCE.value
    elif fingerprints:
        kind = ActionOutcomeKind.DUPLICATE.value
    else:
        kind = ActionOutcomeKind.NONE.value

    return ActionOutcome(
        kind=kind,
        tool_name=tool,
        action_fingerprint=action_fp,
        vector=vector,
        soft_progress=bool(fingerprints),
        novel_progress=bool(fresh),
        positive_progress=bool(positive and fresh),
        evidence_fingerprints=fingerprints,
        reason="new_evidence" if fresh else ("duplicate_evidence" if fingerprints else "no_structured_evidence"),
        round_num=round_num,
        attempt_id=attempt_id,
    )


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _bounded_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.5
