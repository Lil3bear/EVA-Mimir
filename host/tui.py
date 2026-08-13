import threading
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from shared.bridge_types import SolverEvent
from shared.data import memory as mem_store, ideas as idea_store


MAX_LOG_LINES = 100
REFRESH_RATE = 4  # 每秒刷新次数


class TUI:
    def __init__(self, challenge_name: str, workspace_dir: Path, challenge_id: str):
        self.challenge_name = challenge_name
        self.challenge_dir = workspace_dir / challenge_id
        self._lock = threading.Lock()
        self._logs: list[tuple[str, str]] = []  # (timestamp, message)
        self._status = "启动中..."
        self._round = 0
        self._correct_flags: list[str] = []
        self._live: Live | None = None

    # ── 事件接收 ──────────────────────────────────────────────

    def handle_event(self, event: SolverEvent) -> None:
        t = event.type
        d = event.data or {}

        if t == "agent_start":
            self._set_status("运行中")
            self._log("[Agent]", "开始解题", style="bold green")

        elif t == "round_start":
            self._round = d.get("round", self._round)
            self._set_status(f"运行中 — 第 {self._round} 轮")

        elif t == "tool_call":
            tool = d.get("tool", "")
            args = d.get("args", {})
            # 只显示最关键的参数
            if tool == "bash":
                detail = d.get("args", {}).get("cmd", "")[:80]
            elif tool in ("read_file", "write_file", "grep"):
                detail = args.get("path", args.get("pattern", ""))[:80]
            elif tool in ("memory_add", "idea_add"):
                detail = args.get("content", "")[:80]
            elif tool == "challenge_submit_flag":
                detail = args.get("flag", "")
            else:
                detail = ""
            self._log(f"[{tool}]", detail, style="cyan")

        elif t == "tool_result":
            tool = d.get("tool", "")
            result = d.get("result", "")
            if tool == "challenge_submit_flag":
                if "正确" in result:
                    flag = result.split("：")[-1].strip()
                    with self._lock:
                        self._correct_flags.append(flag)
                    self._log("[Flag ✓]", flag, style="bold green")
                else:
                    self._log("[Flag ✗]", result[:80], style="bold red")

        elif t == "message":
            content = d.get("content", "")
            if content:
                self._log("[Solver]", content[:120], style="white")

        elif t == "observer_tool":
            tool = d.get("tool", "")
            result = d.get("result", "")[:60]
            self._log(f"[Observer/{tool}]", result, style="dim yellow")

        elif t == "observer_correction":
            msg = d.get("message", "")
            self._log("[Observer→纠偏]", msg[:100], style="bold yellow")

        elif t == "observer_end":
            summary = d.get("summary", "")
            if summary and summary != "NO_CHANGE":
                self._log("[Observer]", summary[:100], style="yellow")

        elif t == "agent_end":
            reason = d.get("reason", "")
            rounds = d.get("rounds", self._round)
            self._set_status(f"已结束（{reason}，共 {rounds} 轮）")
            self._log("[Agent]", f"结束，原因：{reason}，共 {rounds} 轮", style="bold")

        elif t == "error":
            msg = d.get("msg", str(d))
            self._log("[错误]", msg[:120], style="bold red")

    def _log(self, prefix: str, message: str, style: str = "white") -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        # 转义方括号，防止 rich 把 [bash]、[memory_list] 等当成 markup 标签
        safe_prefix = str(prefix).replace("[", r"\[")
        safe_message = str(message).replace("[", r"\[")
        with self._lock:
            self._logs.append((ts, f"[{style}]{safe_prefix}[/{style}] {safe_message}"))
            if len(self._logs) > MAX_LOG_LINES:
                self._logs.pop(0)

    def _set_status(self, status: str) -> None:
        with self._lock:
            self._status = status

    # ── 渲染 ──────────────────────────────────────────────────

    def _render_header(self) -> Panel:
        with self._lock:
            status = self._status
            round_num = self._round
        text = Text()
        text.append("CTF Agent  ", style="bold cyan")
        text.append(f"{self.challenge_name}  ", style="bold white")
        text.append(f"轮次: {round_num}  ", style="dim")
        text.append(status, style="green" if "运行" in status else "yellow")
        return Panel(text, box=box.HORIZONTALS, padding=(0, 1))

    def _render_log(self) -> Panel:
        with self._lock:
            logs = list(self._logs)
        text = Text()
        for ts, line in logs[-40:]:
            text.append(f"{ts} ", style="dim")
            text.append_text(Text.from_markup(line))
            text.append("\n")
        return Panel(text, title="[bold]Solver 日志[/bold]",
                     box=box.ROUNDED, padding=(0, 1))

    def _render_memory(self) -> Panel:
        table = Table(box=box.SIMPLE, show_header=True,
                      header_style="bold", expand=True)
        table.add_column("类型", width=8)
        table.add_column("内容")

        try:
            entries = mem_store.list_memory(self.challenge_dir, limit=12)
            for e in entries:
                style = {
                    "fact": "white",
                    "evidence": "green",
                    "failure": "red",
                    "note": "dim",
                }.get(e.kind, "white")
                table.add_row(e.kind, e.content[:60], style=style)
        except Exception:
            table.add_row("—", "读取失败")

        return Panel(table, title="[bold]Memory[/bold]", box=box.ROUNDED)

    def _render_ideas(self) -> Panel:
        table = Table(box=box.SIMPLE, show_header=True,
                      header_style="bold", expand=True)
        table.add_column("状态", width=9)
        table.add_column("假设")

        try:
            ideas = idea_store.list_ideas(self.challenge_dir, limit=8)
            for i in ideas:
                style = {
                    "pending": "white",
                    "testing": "cyan",
                    "verified": "bold green",
                    "failed": "dim red",
                }.get(i.status, "white")
                table.add_row(i.status, i.content[:60], style=style)
        except Exception:
            table.add_row("—", "读取失败")

        return Panel(table, title="[bold]Ideas[/bold]", box=box.ROUNDED)

    def _render_flags(self) -> Panel:
        with self._lock:
            flags = list(self._correct_flags)
        if flags:
            text = Text("\n".join(f"✓ {f}" for f in flags), style="bold green")
        else:
            text = Text("暂无", style="dim")
        return Panel(text, title="[bold green]已找到 Flag[/bold green]", box=box.ROUNDED)

    def _build_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(self._render_header(), name="header", size=3),
            Layout(name="body"),
        )
        layout["body"].split_row(
            Layout(self._render_log(), name="log", ratio=3),
            Layout(name="right", ratio=2),
        )
        layout["right"].split_column(
            Layout(self._render_memory(), name="memory", ratio=2),
            Layout(self._render_ideas(), name="ideas", ratio=2),
            Layout(self._render_flags(), name="flags", size=5),
        )
        return layout

    # ── 启动/停止 ─────────────────────────────────────────────

    def start(self) -> None:
        console = Console()
        self._live = Live(
            self._build_layout(),
            console=console,
            refresh_per_second=REFRESH_RATE,
            screen=True,
        )
        self._live.start()

    def update(self) -> None:
        if self._live:
            self._live.update(self._build_layout())

    def stop(self) -> None:
        if self._live:
            self._live.stop()

    def run_update_loop(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            self.update()
            stop_event.wait(timeout=1.0 / REFRESH_RATE)
        self.update()
