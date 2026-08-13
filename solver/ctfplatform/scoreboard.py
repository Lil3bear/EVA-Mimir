"""
实时看板：workspace/scoreboard.md

每完成/开始一道题就更新文件，你随时打开就能看到全局进度。
线程安全（多 worker 并行写入）。
"""

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ChallengeRow:
    """看板中的一行"""
    unique_code: str
    difficulty: str
    total_score: int
    flag_count: int
    status: str = "⏳ 排队"       # ⏳ 排队 / 🔄 进行 / ✅ 解出 / ◐ 部分 / ❌ 失败 / ⏭ 跳过
    correct_flags: int = 0
    rounds: int = 0
    elapsed_sec: float = 0.0
    note: str = ""
    started_at: float = 0.0       # time.time()，内部用，不显示


class Scoreboard:
    """
    维护一份 Markdown 看板，每次变更后原子写入 workspace/scoreboard.md。
    """

    def __init__(self, workspace_dir: str, total_score: int = 0) -> None:
        self._path = Path(workspace_dir) / "scoreboard.md"
        self._lock = threading.Lock()
        self._rows: dict[str, ChallengeRow] = {}          # unique_code → row
        self._order: list[str] = []                        # 保持插入顺序
        self._total_score = total_score
        self._started_at = time.time()

    # ── 公开接口 ──────────────────────────────────────────

    def register(self, unique_code: str, difficulty: str,
                 total_score: int, flag_count: int) -> None:
        """注册一道题（排队状态）。"""
        with self._lock:
            if unique_code not in self._rows:
                self._rows[unique_code] = ChallengeRow(
                    unique_code=unique_code,
                    difficulty=difficulty,
                    total_score=total_score,
                    flag_count=flag_count,
                )
                self._order.append(unique_code)
            self._flush()

    def mark_running(self, unique_code: str) -> None:
        """标记为正在解题。"""
        with self._lock:
            row = self._rows.get(unique_code)
            if row:
                row.status = "🔄 进行"
                row.started_at = time.time()
            self._flush()

    def mark_done(
        self,
        unique_code: str,
        *,
        success: bool,
        correct_flags: int = 0,
        total_flags: int = 0,
        rounds: int = 0,
        note: str = "",
    ) -> None:
        """标记为完成（解出/部分/失败）。"""
        with self._lock:
            row = self._rows.get(unique_code)
            if not row:
                return
            if success:
                row.status = "✅ 解出"
            elif correct_flags > 0:
                row.status = f"◐ 部分({correct_flags}/{total_flags})"
            else:
                row.status = "❌ 失败"
            row.correct_flags = correct_flags
            row.rounds = rounds
            row.note = note
            if row.started_at > 0:
                row.elapsed_sec = time.time() - row.started_at
            self._flush()

    def mark_skipped(self, unique_code: str, reason: str = "") -> None:
        """标记为跳过。"""
        with self._lock:
            row = self._rows.get(unique_code)
            if row:
                row.status = "⏭ 跳过"
                row.note = reason
            self._flush()

    # ── 内部 ──────────────────────────────────────────────

    def _flush(self) -> None:
        """生成 Markdown 并原子写入文件。调用方须持有 self._lock。"""
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        elapsed_total = time.time() - self._started_at
        elapsed_str = self._fmt_time(elapsed_total)

        solved = sum(1 for r in self._rows.values() if r.status.startswith("✅"))
        partial = sum(1 for r in self._rows.values() if r.status.startswith("◐"))
        failed = sum(1 for r in self._rows.values() if r.status.startswith("❌"))
        running = sum(1 for r in self._rows.values() if r.status.startswith("🔄"))
        queued = sum(1 for r in self._rows.values() if r.status.startswith("⏳"))

        earned = sum(
            r.total_score for r in self._rows.values() if r.status.startswith("✅")
        )

        # 正在运行的题目列表
        running_codes = [c for c in self._order if self._rows[c].status.startswith("🔄")]
        running_str = ", ".join(running_codes) if running_codes else "无"

        lines = [
            f"# 📊 CTF Agent 实时看板",
            f"",
            f"> 更新: {now} | 已运行: {elapsed_str}",
            f"",
            f"**已解: {solved}/{len(self._rows)}** | "
            f"得分: **{earned}/{self._total_score}** | "
            f"部分: {partial} | 失败: {failed} | "
            f"进行中: {running} | 排队: {queued}",
            f"",
            f"正在解: {running_str}",
            f"",
            f"| 题目 | 难度 | 分值 | 状态 | Flag | 轮次 | 耗时 | 备注 |",
            f"|------|------|------|------|------|------|------|------|",
        ]

        for code in self._order:
            r = self._rows[code]
            flag_str = f"{r.correct_flags}/{r.flag_count}" if r.rounds > 0 or r.correct_flags > 0 else f"0/{r.flag_count}"
            rounds_str = str(r.rounds) if r.rounds > 0 else "-"
            time_str = self._fmt_time(r.elapsed_sec) if r.elapsed_sec > 0 else "-"
            # 截断备注避免表格太宽
            note = r.note[:60] + "…" if len(r.note) > 60 else r.note
            lines.append(
                f"| {code} | {r.difficulty} | {r.total_score} | {r.status} | "
                f"{flag_str} | {rounds_str} | {time_str} | {note} |"
            )

        lines.append("")  # trailing newline

        content = "\n".join(lines)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(self._path)
        except Exception:
            # 写入失败不应影响解题流程
            try:
                self._path.write_text(content, encoding="utf-8")
            except Exception:
                pass

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}s"
        m, s = divmod(int(seconds), 60)
        if m < 60:
            return f"{m}m{s:02d}s"
        h, m = divmod(m, 60)
        return f"{h}h{m:02d}m"
