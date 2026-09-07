"""Late-game salvage: cut long/hard slots, reconcentrate on recoverable simple scores."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
    # 仅类型注解用；运行时导入会触发 ctfplatform.__init__ → scheduler →
    # salvage 的循环导入，故延迟到类型检查期。
    from solver.ctfplatform.tsecbench_client import Challenge


def _policy_imports():
    """延迟导入 policy，打破 salvage ↔ scheduler 的循环导入。

    policy → ctfplatform.__init__ → scheduler → salvage；若 salvage 在顶层导
    policy，会在 scheduler 导入 salvage 时触发未初始化模块错误。
    """
    from solver.ctfplatform.policy import _DEFERRED_PREFIXES, _roi, _tier
    return _DEFERRED_PREFIXES, _roi, _tier

# TSecBench 全量赛程基准（6h）。尾段阈值按此墙钟定义，再按实际 SOLVER_TOTAL_TIMEOUT 等比缩放。
BENCHMARK_MINUTES_DEFAULT = 360
# 剩 140min → 进入 salvage（360 - 220 = 140）
SALVAGE_REMAINING_AT_360 = 140
# 剩 72min  → critical（360 的 20%）
CRITICAL_REMAINING_AT_360 = 72
# 剩 36min  → final，只捞 easy/salvage focus
FINAL_REMAINING_AT_360 = 36

_TRANSIENT_TOKENS = (
    "connection error",
    "apiconnectionerror",
    "connection",
    "timeout",
    "rate limit",
    "连接",
    "超时",
    "timed out",
)

_WASTED_MIN_ROUNDS = 8


@dataclass(frozen=True)
class SalvagePhasePlan:
    """Benchmark-aware salvage tier for one retry round."""

    phase: str  # normal | salvage | critical | final
    benchmark_minutes: int
    benchmark_remaining_min: float
    run_remaining_min: float
    late_game_mode: bool = False
    cut_long_hard: bool = False
    salvage_enabled: bool = False
    skip_hard_new: bool = False
    clear_easy_cooldown: bool = False
    salvage_only: bool = False
    min_retry_round: int = 2

    def to_emit(self) -> dict:
        return {
            "phase": self.phase,
            "benchmark_minutes": self.benchmark_minutes,
            "benchmark_remaining_min": round(self.benchmark_remaining_min, 1),
            "run_remaining_min": round(self.run_remaining_min, 1),
            "late_game_mode": self.late_game_mode,
            "cut_long_hard": self.cut_long_hard,
            "salvage_enabled": self.salvage_enabled,
            "skip_hard_new": self.skip_hard_new,
            "salvage_only": self.salvage_only,
        }


def _positive_int(value: object, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _positive_float(value: object, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def load_salvage_config(
    settings: dict | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, float | int]:
    """Merge settings + env into benchmark-relative salvage thresholds."""
    settings = settings or {}
    env = os.environ if environ is None else environ
    solver = settings.get("solver") or {}
    salvage_cfg = solver.get("salvage") if isinstance(solver.get("salvage"), dict) else {}

    benchmark = _positive_int(
        env.get("SOLVER_BENCHMARK_MINUTES")
        or salvage_cfg.get("benchmark_minutes")
        or solver.get("benchmark_minutes"),
        BENCHMARK_MINUTES_DEFAULT,
    )
    return {
        "benchmark_minutes": benchmark,
        "salvage_remaining_min": _positive_float(
            env.get("SOLVER_SALVAGE_REMAINING_MIN")
            or salvage_cfg.get("salvage_remaining_min"),
            float(SALVAGE_REMAINING_AT_360),
        ),
        "critical_remaining_min": _positive_float(
            env.get("SOLVER_CRITICAL_REMAINING_MIN")
            or salvage_cfg.get("critical_remaining_min"),
            float(CRITICAL_REMAINING_AT_360),
        ),
        "final_remaining_min": _positive_float(
            env.get("SOLVER_FINAL_REMAINING_MIN")
            or salvage_cfg.get("final_remaining_min"),
            float(FINAL_REMAINING_AT_360),
        ),
        "min_retry_round": _positive_int(
            env.get("SOLVER_SALVAGE_MIN_ROUND")
            or salvage_cfg.get("min_retry_round"),
            2,
        ),
    }


def _scale_threshold(
    base_at_360: float,
    *,
    total_timeout_min: int,
    benchmark_minutes: int,
) -> float:
    """Map a 360-min benchmark boundary onto the configured run timeout."""
    if benchmark_minutes <= 0:
        return base_at_360
    if total_timeout_min <= 0:
        return base_at_360
    return base_at_360 * (total_timeout_min / benchmark_minutes)


def resolve_salvage_phase(
    *,
    elapsed_min: float,
    remaining_min: float,
    total_timeout_min: int,
    round_idx: int,
    settings: dict | None = None,
    environ: Mapping[str, str] | None = None,
) -> SalvagePhasePlan:
    """Resolve salvage tier from 360-min benchmark clock + run deadline.

    Triggers when **either** benchmark wall (360 - elapsed) **or** scaled run
    remaining crosses a threshold — whichever is stricter (earlier salvage).
    """
    cfg = load_salvage_config(settings, environ)
    benchmark_min = int(cfg["benchmark_minutes"])
    benchmark_remaining = float(benchmark_min) - float(elapsed_min)
    run_remaining = float(remaining_min)

    salvage_at = _scale_threshold(
        float(cfg["salvage_remaining_min"]),
        total_timeout_min=total_timeout_min,
        benchmark_minutes=benchmark_min,
    )
    critical_at = _scale_threshold(
        float(cfg["critical_remaining_min"]),
        total_timeout_min=total_timeout_min,
        benchmark_minutes=benchmark_min,
    )
    final_at = _scale_threshold(
        float(cfg["final_remaining_min"]),
        total_timeout_min=total_timeout_min,
        benchmark_minutes=benchmark_min,
    )
    min_round = int(cfg["min_retry_round"])

    def _reached(threshold: float, benchmark_floor: float) -> bool:
        return run_remaining <= threshold or benchmark_remaining <= benchmark_floor

    if round_idx < min_round or not _reached(salvage_at, float(cfg["salvage_remaining_min"])):
        return SalvagePhasePlan(
            phase="normal",
            benchmark_minutes=benchmark_min,
            benchmark_remaining_min=benchmark_remaining,
            run_remaining_min=run_remaining,
            min_retry_round=min_round,
        )

    if _reached(final_at, float(cfg["final_remaining_min"])):
        return SalvagePhasePlan(
            phase="final",
            benchmark_minutes=benchmark_min,
            benchmark_remaining_min=benchmark_remaining,
            run_remaining_min=run_remaining,
            late_game_mode=True,
            cut_long_hard=True,
            salvage_enabled=True,
            skip_hard_new=True,
            clear_easy_cooldown=True,
            salvage_only=True,
            min_retry_round=min_round,
        )

    if _reached(critical_at, float(cfg["critical_remaining_min"])):
        return SalvagePhasePlan(
            phase="critical",
            benchmark_minutes=benchmark_min,
            benchmark_remaining_min=benchmark_remaining,
            run_remaining_min=run_remaining,
            late_game_mode=True,
            cut_long_hard=True,
            salvage_enabled=True,
            skip_hard_new=True,
            clear_easy_cooldown=True,
            min_retry_round=min_round,
        )

    return SalvagePhasePlan(
        phase="salvage",
        benchmark_minutes=benchmark_min,
        benchmark_remaining_min=benchmark_remaining,
        run_remaining_min=run_remaining,
        late_game_mode=True,
        cut_long_hard=True,
        salvage_enabled=True,
        skip_hard_new=True,
        clear_easy_cooldown=True,
        min_retry_round=min_round,
    )


def filter_challenges_for_phase(
    challenges: list[Challenge],
    *,
    salvage_only: bool,
    salvage_focus: set[str],
) -> list[Challenge]:
    """Final phase: only salvage focus + untouched easy/medium."""
    if not salvage_only:
        return challenges
    keep: list[Challenge] = []
    for ch in challenges:
        if ch.is_completed:
            continue
        code = ch.unique_code
        if code in salvage_focus:
            keep.append(ch)
            continue
        if is_simple_challenge(ch) and ch.correct_flag_count == 0:
            keep.append(ch)
    return keep


def is_long_hard_challenge(challenge: Challenge) -> bool:
    """耗时家族 / 多 flag / hard：尾段直接停开，把 slot 让给简单捞分。"""
    if challenge.is_completed:
        return False
    diff = (challenge.difficulty or "").lower()
    if diff in ("hard", "difficult"):
        return True
    code = (challenge.unique_code or "").lower()
    _DEFERRED_PREFIXES, _, _ = _policy_imports()
    if code.startswith(_DEFERRED_PREFIXES):
        return True
    if challenge.flag_count >= 4:
        return True
    return False


def is_simple_challenge(challenge: Challenge) -> bool:
    diff = (challenge.difficulty or "").lower()
    return diff in ("easy", "medium") and not is_long_hard_challenge(challenge)


def long_hard_skip_codes(challenges: list[Challenge]) -> set[str]:
    return {c.unique_code for c in challenges if is_long_hard_challenge(c)}


_DEFAULT_LASTMILE_CODES = ("a-03", "f2-05", "b-02")


def long_hard_cut_codes(
    challenges: list[Challenge],
    *,
    phase: str = "salvage",
    settings: dict | None = None,
) -> set[str]:
    """Salvage 阶段真正标记 abandon 的 long-hard 集合。

    - 有部分 flag（correct_flag_count>0）永不砍，避免 b-02 2/6 被尾段丢掉
    - ``solver.lastmile_codes``（默认 a-03/f2-05/b-02）仅在 ``final`` 阶段才砍，
      给能力边界题留到最后一刻的干净重试窗口
    """
    solver = (settings or {}).get("solver") or {}
    raw = solver.get("lastmile_codes")
    if raw is None:
        lastmile = set(_DEFAULT_LASTMILE_CODES)
    elif isinstance(raw, str):
        lastmile = {c.strip() for c in raw.split(",") if c.strip()}
    else:
        lastmile = {str(c).strip() for c in raw if str(c).strip()}

    cut: set[str] = set()
    for ch in challenges:
        if not is_long_hard_challenge(ch):
            continue
        if int(getattr(ch, "correct_flag_count", 0) or 0) > 0:
            continue
        code = ch.unique_code
        if code in lastmile and str(phase) != "final":
            continue
        cut.add(code)
    return cut


def _read_ledger_attempts(workspace_dir: Path, code: str) -> list[dict]:
    path = workspace_dir / code / ".challenge-ledger.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        attempts = data.get("attempts") or []
        return [a for a in attempts if isinstance(a, dict)]
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []


def challenge_salvage_signals(workspace_dir: Path, code: str) -> dict:
    """Detect transient LLM jitter vs wasted rounds (wrong direction)."""
    attempts = _read_ledger_attempts(workspace_dir, code)
    if not attempts:
        return {
            "attempts": 0,
            "transient": False,
            "wasted_attempt": False,
        }
    last = attempts[-1]
    err = str(last.get("error") or "").lower()
    rounds = int(last.get("rounds") or 0)
    new_flags = int(last.get("new_flags") or 0)
    transient = any(token in err for token in _TRANSIENT_TOKENS)
    wasted = (
        not last.get("success")
        and new_flags == 0
        and (rounds >= _WASTED_MIN_ROUNDS or (rounds <= 3 and bool(err)))
    )
    return {
        "attempts": len(attempts),
        "transient": transient,
        "wasted_attempt": wasted and not transient,
        "last_rounds": rounds,
        "last_error": err[:120],
    }


def salvage_abandoned_codes(
    abandoned: set[str] | list[str],
    challenges: list[Challenge],
) -> set[str]:
    """Recover abandoned easy/medium or partial-score challenges."""
    abandoned_set = {str(code).strip() for code in (abandoned or []) if str(code).strip()}
    if not abandoned_set:
        return set()
    by_code = {c.unique_code: c for c in challenges}
    salvaged: set[str] = set()
    for code in abandoned_set:
        ch = by_code.get(code)
        if ch is None or ch.is_completed:
            continue
        if is_simple_challenge(ch):
            salvaged.add(code)
        elif ch.correct_flag_count > 0:
            salvaged.add(code)
    return salvaged


def collect_salvage_targets(
    challenges: list[Challenge],
    *,
    abandoned: set[str],
    fail_streak: dict[str, int],
    workspace_dir: str | Path,
) -> set[str]:
    """Simple challenges worth a concentrated late-game retry pass."""
    ws = Path(workspace_dir)
    targets: set[str] = set()
    for ch in challenges:
        if ch.is_completed or not is_simple_challenge(ch):
            continue
        code = ch.unique_code
        signals = challenge_salvage_signals(ws, code)
        if code in abandoned:
            targets.add(code)
            continue
        if int(fail_streak.get(code, 0)) >= 1:
            targets.add(code)
            continue
        if signals.get("transient") or signals.get("wasted_attempt"):
            targets.add(code)
            continue
        if signals.get("attempts", 0) >= 1 and ch.correct_flag_count == 0:
            targets.add(code)
    return targets


def sort_challenges_salvage(
    challenges: list[Challenge],
    workspace_dir: str | Path,
    *,
    salvage_focus: set[str] | None = None,
) -> list[Challenge]:
    """Order for late-game scoring: salvage focus (transient first) → easy → rest."""
    ws = Path(workspace_dir)
    focus = salvage_focus or set()

    _DEFERRED_PREFIXES, _roi, _tier = _policy_imports()

    def _key(c: Challenge) -> tuple:
        code = c.unique_code
        diff = (c.difficulty or "").lower()
        if is_long_hard_challenge(c):
            return (9, 0, 0, code.lower())
        signals = challenge_salvage_signals(ws, code) if code in focus else {}
        if code in focus and signals.get("transient"):
            return (0, 0 if diff == "easy" else 1, -_roi(c), code.lower())
        if code in focus:
            return (1, 0 if diff == "easy" else 1, -_roi(c), code.lower())
        if diff == "easy":
            return (2, 0, -_roi(c), code.lower())
        if diff == "medium":
            return (3, 0, -_roi(c), code.lower())
        partial = c.correct_flag_count > 0 and not c.is_completed
        if partial:
            remaining = max(0, c.flag_count - c.correct_flag_count)
            return (4, remaining, -_roi(c), code.lower())
        return (5, _tier(c), -_roi(c), code.lower())

    return sorted(challenges, key=_key)


def salvage_task_banner(code: str, workspace_dir: str | Path) -> str:
    """Inject into agent task when code is in salvage focus."""
    signals = challenge_salvage_signals(Path(workspace_dir), code)
    lines = ["\n## 尾段捞分（优先快速拿分）"]
    if signals.get("transient"):
        lines.append(
            "- 上一轮因 **LLM/连接抖动** 中断；从 memory / execution-journal "
            "复用已验证 exploit，不要从零枚举。"
        )
    elif signals.get("wasted_attempt"):
        lines.append(
            "- 上一轮 **方向可能有误**（多轮无新 flag）；换正交攻击面，"
            "禁止重复同一 payload/路径。"
        )
    else:
        lines.append(
            "- 尾段集中重试；优先复用 workspace 已验证事实，走最短 skill 链。"
        )
    lines.append("- 禁止 security_search / hint（除非工具门控已允许）。")
    return "\n".join(lines)
