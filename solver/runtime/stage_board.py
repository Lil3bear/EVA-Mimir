"""Durable stage board for multi-flag / pentest challenges.

Long solves (b-01/b-02) lose hosts and credentials when bash output is
truncated. This module force-lands deterministic facts onto ArtifactBus
(auto-approved) so later rounds read a stable board instead of history.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from solver.runtime.artifacts import ArtifactBus

_NORMALIZE_RE = re.compile(r"\s+")


def _normalize(value: str) -> str:
    return _NORMALIZE_RE.sub(" ", str(value or "").strip().lower())


def _known_values(bus: ArtifactBus, artifact_type: str) -> set[str]:
    known: set[str] = set()
    for item in bus.list(limit=2000):
        if item.get("artifact_type") != artifact_type:
            continue
        if item.get("status") == "rejected":
            continue
        known.add(_normalize(item.get("value", "")))
    return known


def land_fact(
    challenge_dir: str | Path,
    *,
    artifact_type: str,
    value: str,
    producer_attempt: str = "primary",
    proof_ref: str = "",
    confidence: float = 0.95,
    metadata: dict[str, Any] | None = None,
    auto_approve: bool = True,
) -> dict[str, Any] | None:
    """Publish (and optionally auto-approve) a short durable fact. Deduped."""
    text = str(value or "").strip()
    if not text or not challenge_dir:
        return None
    try:
        from solver.runtime.observer_policy import content_has_truncation

        if content_has_truncation(text):
            return None
    except Exception:
        pass
    kind = str(artifact_type or "fact").strip() or "fact"
    bus = ArtifactBus(challenge_dir)
    if _normalize(text) in _known_values(bus, kind):
        return None
    meta = {"auto_landed": True, **(metadata or {})}
    artifact = bus.publish(
        artifact_type=kind,
        value=text,
        producer_attempt=producer_attempt or "primary",
        proof_ref=proof_ref,
        confidence=confidence,
        metadata=meta,
    )
    if auto_approve:
        approved = bus.approve(artifact["artifact_id"], reviewer="stage_board")
        return approved or artifact
    return artifact


def land_credentials(
    challenge_dir: str | Path,
    values: list[str],
    *,
    producer_attempt: str = "primary",
    proof_ref: str = "bash_auto_extract",
) -> list[dict[str, Any]]:
    landed: list[dict[str, Any]] = []
    for raw in values or []:
        item = land_fact(
            challenge_dir,
            artifact_type="credential",
            value=f"credential={raw}",
            producer_attempt=producer_attempt,
            proof_ref=proof_ref,
            metadata={"raw": str(raw)},
        )
        if item:
            landed.append(item)
    return landed


def land_hosts(
    challenge_dir: str | Path,
    ips: list[str],
    *,
    producer_attempt: str = "primary",
    proof_ref: str = "bash_auto_extract",
) -> list[dict[str, Any]]:
    landed: list[dict[str, Any]] = []
    for ip in ips or []:
        item = land_fact(
            challenge_dir,
            artifact_type="host",
            value=f"host={ip}",
            producer_attempt=producer_attempt,
            proof_ref=proof_ref,
            metadata={"ip": str(ip)},
        )
        if item:
            landed.append(item)
    return landed


def land_flag_progress(
    challenge_dir: str | Path,
    *,
    correct: int,
    total: int,
    matched_index: Any = None,
    producer_attempt: str = "primary",
) -> dict[str, Any] | None:
    idx = matched_index if matched_index is not None else "?"
    value = f"flag_progress {correct}/{total} index={idx}"
    return land_fact(
        challenge_dir,
        artifact_type="flag_stage",
        value=value,
        producer_attempt=producer_attempt,
        proof_ref="challenge_submit_flag",
        confidence=1.0,
        metadata={"correct": int(correct), "total": int(total), "index": idx},
    )


def land_foothold(
    challenge_dir: str | Path,
    *,
    summary: str,
    producer_attempt: str = "primary",
    proof_ref: str = "phase_transition",
) -> dict[str, Any] | None:
    text = str(summary or "").strip()
    if not text:
        return None
    return land_fact(
        challenge_dir,
        artifact_type="foothold",
        value=text[:240],
        producer_attempt=producer_attempt,
        proof_ref=proof_ref,
        confidence=0.9,
    )


def approved_board(challenge_dir: str | Path, *, limit: int = 40) -> dict[str, list[dict[str, Any]]]:
    """Group latest approved artifacts by type for injection."""
    if not challenge_dir:
        return {}
    bus = ArtifactBus(challenge_dir)
    items = bus.list(status="approved", limit=max(20, int(limit or 40)))
    # Keep last occurrence per normalized value within type.
    by_type: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str]] = set()
    for item in reversed(items):
        kind = str(item.get("artifact_type") or "fact")
        key = (kind, _normalize(item.get("value", "")))
        if key in seen:
            continue
        seen.add(key)
        by_type.setdefault(kind, []).append(item)
    for kind in by_type:
        by_type[kind].reverse()
    return by_type


def board_snapshot(challenge_dir: str | Path, *, limit_per_type: int = 8) -> str:
    """Human-readable board for Solver injection. Empty string if nothing landed."""
    board = approved_board(challenge_dir)
    if not board:
        return ""
    order = ("flag_stage", "foothold", "credential", "host", "service")
    labels = {
        "flag_stage": "🏁 Flag 阶段",
        "foothold": "🐚 立足点",
        "credential": "🔑 凭据",
        "host": "🌐 内网主机",
        "service": "📡 服务",
    }
    lines = [
        "[阶段看板] 已落地共享证据（截断上下文不可靠，下一跳必须从这里出发，禁止对已知 host 全盘重扫）："
    ]
    shown = 0
    for kind in order:
        items = board.get(kind) or []
        if not items:
            continue
        lines.append(f"{labels.get(kind, kind)}（{len(items)}）：")
        for item in items[-limit_per_type:]:
            lines.append(f"  - {item.get('value')}")
            shown += 1
    for kind, items in board.items():
        if kind in order or not items:
            continue
        lines.append(f"{kind}（{len(items)}）：")
        for item in items[-limit_per_type:]:
            lines.append(f"  - {item.get('value')}")
            shown += 1
    if shown == 0:
        return ""
    lines.append("优先：用已有凭据访问已记录 host；artifact_list 可复查。")
    return "\n".join(lines)


def known_host_ips(challenge_dir: str | Path) -> set[str]:
    ips: set[str] = set()
    for item in approved_board(challenge_dir).get("host") or []:
        value = str(item.get("value") or "")
        meta_ip = (item.get("metadata") or {}).get("ip")
        if meta_ip:
            ips.add(str(meta_ip))
        for match in re.findall(
            r"(?:(?:172\.(?:1[6-9]|2\d|3[01]))|(?:10\.\d{1,3})|(?:192\.168))"
            r"\.\d{1,3}\.\d{1,3}",
            value,
        ):
            ips.add(match)
    return ips


def rescan_warning(challenge_dir: str | Path, cmd: str) -> str:
    """Soft warn when broad recon repeats after hosts/creds are already landed."""
    hosts = known_host_ips(challenge_dir)
    board = approved_board(challenge_dir)
    if not hosts and not board.get("credential") and not board.get("flag_stage"):
        return ""
    cmd_l = str(cmd or "").lower()
    broad = any(
        token in cmd_l
        for token in (
            "nmap ",
            "masscan",
            "gobuster",
            "ffuf ",
            "dirsearch",
            "nikto",
            "for p in ",
            "seq 1 65535",
            "/.git/",
            "common files",
        )
    )
    if not broad:
        return ""
    host_preview = ", ".join(sorted(hosts)[:5]) if hosts else "（见看板凭据/阶段）"
    return (
        f"\n⚠️ [阶段看板] 已有落地证据（hosts={host_preview}）。"
        "禁止对已知拓扑全盘重扫；用已记录凭据对未验证 host 做精确下一跳，"
        "或 `find/cat` 抢当前机 flag。完整看板见状态快照 / artifact_list。\n"
    )
