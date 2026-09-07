"""Post-run workspace analyzer for RSI local iteration."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from solver.runtime.retry_ledger import RetryLedger
from solver.runtime.submission_store import score_belongs_to_current_task

# Known failure patterns from docs/PROBLEMS.md — suggest next skill/router layer.
_KNOWN_FAILURE_HINTS: dict[str, str] = {
    "a-03": "login 报 500/密码错误先试 SQLi UNION 注入拿 session，再枚举 /admin/* 隐藏路由",
    "c-08": "Langflow：validate/code 默认参数求值 payload（§6.10），禁止跨 IP :80",
    "c-05": "Gradio 4.x /file= 白名单：product-playbooks §6.8，验证 bypass 而非路径枚举",
    "c-02": "ComfyUI §6.5：weak+use_uv=False → setup.py sdist → pip 裸文本 → reboot → /view type=input；卡安装看 pip --log",
    "a-18": "JWT kid：优先 kid=../css/reset.css 伪造，再 php-fpm FastCGI；勿盲猜 kid / php_code",
    "a-13": "PyDash：Cookie \\073 + POST /admin 污染 __file__；单 agent（勿开 multi-solver）",
    "e3-04": "Injection /check：精确计数 bypass≥0.6（触发≤2），逐 token 测规则",
    "c-03": "React2Shell：复用 §6.6 手动 payload，勿下载 scanner",
    "c-06": "HugeGraph：cve-cheatsheet + graph-db skill",
    "b-02": "多flag：flag1在DB；其余从解题容器 sshpass/paramiko 直连内网SSH（勿在web容器找ssh）",
    "f2-05": "VM公式被删成putc('.')：过门禁后停手推op，pip install angr 符号解 flag{",
}


@dataclass
class ChallengeSnapshot:
    code: str
    score: int = 0
    completed: bool = False
    difficulty: str = ""
    category: str = ""
    abandoned: bool = False
    fail_streak: int = 0
    hint: str = ""


@dataclass
class RSIReport:
    generated_at: float
    pack: str = ""
    expected_codes: list[str] = field(default_factory=list)
    total_expected: int = 0
    solved: int = 0
    partial: int = 0
    zero_score: int = 0
    missing: list[str] = field(default_factory=list)
    challenges: list[ChallengeSnapshot] = field(default_factory=list)
    next_actions: list[dict[str, str]] = field(default_factory=list)
    pass_regression: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_int(path: Path) -> int:
    try:
        return max(0, int(path.read_text(encoding="utf-8").strip()))
    except (OSError, ValueError):
        return 0


def _read_challenge_meta(challenge_dir: Path) -> tuple[str, str]:
    config_path = challenge_dir / "challenge.json"
    if not config_path.is_file():
        return "", ""
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return str(data.get("difficulty", "")), str(data.get("category", ""))
    except (OSError, json.JSONDecodeError):
        return "", ""


def _snapshot_challenge(
    challenge_dir: Path,
    *,
    abandoned: set[str],
    fail_streak: dict[str, int],
) -> ChallengeSnapshot | None:
    if not score_belongs_to_current_task(challenge_dir):
        return None
    code = challenge_dir.name
    score = _read_int(challenge_dir / ".cumulative_score")
    completed = (challenge_dir / ".completed").is_file()
    difficulty, category = _read_challenge_meta(challenge_dir)
    hint = _KNOWN_FAILURE_HINTS.get(code, "")
    return ChallengeSnapshot(
        code=code,
        score=score,
        completed=completed,
        difficulty=difficulty,
        category=category,
        abandoned=code in abandoned,
        fail_streak=int(fail_streak.get(code, 0)),
        hint=hint,
    )


def analyze_workspace(
    workspace_dir: str | Path,
    *,
    expected_codes: Sequence[str] | None = None,
    pack: str = "",
    retry_ledger: RetryLedger | None = None,
) -> RSIReport:
    workspace = Path(workspace_dir)
    ledger = retry_ledger or RetryLedger(workspace)
    state = ledger.snapshot()
    abandoned = set(state.get("abandoned") or [])
    fail_streak = dict(state.get("fail_streak") or {})

    expected = [str(c).strip() for c in (expected_codes or []) if str(c).strip()]
    expected_set = set(expected)

    snapshots: list[ChallengeSnapshot] = []
    if workspace.is_dir():
        for child in sorted(workspace.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            snap = _snapshot_challenge(
                child, abandoned=abandoned, fail_streak=fail_streak
            )
            if snap is not None:
                snapshots.append(snap)

    if expected_set:
        relevant = [s for s in snapshots if s.code in expected_set]
        seen = {s.code for s in relevant}
        missing = sorted(expected_set - seen)
    else:
        relevant = snapshots
        missing = []

    partial = sum(1 for s in relevant if s.score > 0 and not s.completed)
    zero_score = sum(1 for s in relevant if s.score == 0)

    next_actions: list[dict[str, str]] = []
    for s in relevant:
        if s.completed:
            continue
        if s.score == 0 or s.abandoned:
            action = {
                "code": s.code,
                "layer": "skill" if s.hint else "router",
                "hint": s.hint or "检查 session 日志，更新 PROBLEMS.md 与对应 skill",
            }
            next_actions.append(action)

    pass_regression = bool(expected_set) and zero_score == 0 and not missing

    return RSIReport(
        generated_at=time.time(),
        pack=pack,
        expected_codes=sorted(expected_set),
        total_expected=len(expected_set) if expected_set else len(relevant),
        solved=sum(1 for s in relevant if s.completed),
        partial=partial,
        zero_score=zero_score,
        missing=missing,
        challenges=relevant,
        next_actions=next_actions,
        pass_regression=pass_regression,
    )


def write_report(report: RSIReport, workspace_dir: str | Path) -> tuple[Path, Path]:
    """Write JSON + Markdown reports under workspace."""
    workspace = Path(workspace_dir)
    workspace.mkdir(parents=True, exist_ok=True)
    json_path = workspace / "rsi-report.json"
    md_path = workspace / "rsi-report.md"

    payload = report.to_dict()
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# RSI 回归报告",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(report.generated_at))}",
        f"- Pack：`{report.pack or '(all)'}`",
        f"- 期望题数：{report.total_expected} | 解出：{report.solved} | 部分：{report.partial} | 0 分：{report.zero_score}",
        f"- 回归通过：{'✅' if report.pass_regression else '❌'}",
        "",
    ]
    if report.missing:
        lines.append("## 未尝试（工作区无目录）")
        lines.append("")
        for code in report.missing:
            lines.append(f"- `{code}`")
        lines.append("")

    if report.next_actions:
        lines.append("## 建议下一层改动（一次只改 skill 或 router 或 scheduler）")
        lines.append("")
        for item in report.next_actions:
            lines.append(f"- **{item['code']}** [{item['layer']}]: {item['hint']}")
        lines.append("")

    lines.append("## 题目明细")
    lines.append("")
    lines.append("| 题号 | 得分 | 状态 | 难度 | 放弃 | 提示 |")
    lines.append("|---|---:|---|---|---|---|")
    for s in report.challenges:
        status = "✅" if s.completed else ("◐" if s.score > 0 else "❌")
        lines.append(
            f"| {s.code} | {s.score} | {status} | {s.difficulty} | "
            f"{'是' if s.abandoned else '否'} | {s.hint or '-'} |"
        )
    lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def analyze_and_emit(
    workspace_dir: str | Path,
    *,
    pack: str = "",
    expected_codes: Sequence[str] | None = None,
    emit=None,
) -> RSIReport:
    """Analyze workspace, write reports, optionally emit JSONL event."""
    report = analyze_workspace(
        workspace_dir,
        expected_codes=expected_codes,
        pack=pack,
    )
    json_path, md_path = write_report(report, workspace_dir)
    if emit is not None:
        emit(
            "rsi_report",
            {
                "pack": pack,
                "pass_regression": report.pass_regression,
                "solved": report.solved,
                "zero_score": report.zero_score,
                "missing": report.missing,
                "json_path": str(json_path),
                "md_path": str(md_path),
                "next_actions": report.next_actions,
            },
        )
    return report
