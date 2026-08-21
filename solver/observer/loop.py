import hashlib
import os
import re
import threading
from pathlib import Path

from solver.worker_context import ctx as _ctx
from shared.jsonl import write_line


# 攻击向量关键词映射：命中任意关键词→向量名
_ATTACK_VECTOR_PATTERNS: list[tuple[str, list[str]]] = [
    ("LFI", ["..%2f", "..%252f", "....//", "../", "..\\\\\\\\" ,"php://filter", "php://input",
             "file://", "data://", "expect://", "%00", "null byte",
             "include", "path traversal", "lfi", "\u6587\u4ef6\u5305\u542b"]),
    ("SQLi", ["union select", "' or ", "1=1", "sqlmap", "order by", "group_concat",
             "information_schema", "load_file", "into outfile", "sleep(",
             "benchmark(", "sqli", "sql\u6ce8\u5165", "\u6ce8\u5165\u70b9"]),
    ("XSS", ["<script", "javascript:", "onerror", "onload", "alert(", "xss"]),
    ("SSRF", ["127.0.0.1", "localhost", "0.0.0.0", "169.254", "ssrf",
              "\u670d\u52a1\u7aef\u8bf7\u6c42\u4f2a\u9020", "gopher://", "dict://"]),
    ("RCE", ["system(", "exec(", "passthru", "shell_exec", "popen",
             "eval(", "assert(", ";id", ";whoami", "|id", "|whoami",
             "reverse shell", "\u53cd\u5f39shell"]),
    ("brute-force", ["wordlist", "ffuf", "gobuster", "dirsearch", "dirb",
                     "hydra", "\u7206\u7834", "\u5b57\u5178", "rockyou", "burp intruder"]),
    ("deserialization", ["unserialize", "\u53cd\u5e8f\u5217\u5316", "pickle", "ysoserial",
                         "__wakeup", "__destruct", "gadget chain"]),
    ("JWT", ["jwt", "json web token", "hs256", "rs256", "\u7b7e\u540d", "jku", "jwk"]),
    ("upload", [".php", ".jsp", ".asp", "\u4e0a\u4f20", "webshell", "\u6728\u9a6c",
                "multipart", "content-type", "\u6587\u4ef6\u4e0a\u4f20"]),
]


# Webshell 通道白名单：通过 webshell 执行不同命令是正常的 RCE 通道使用，
# 不应被视为循环。URL path 固定但命令内容完全不同。
_WEBSHELL_URL_PATTERNS = re.compile(
    r'(?:shell|cmd|s|c|backdoor|webshell|hack|x|1)\.(php|jsp|asp|aspx|phtml)'
    r'[?&](?:c|cmd|x|command|exec|1)=',
    re.IGNORECASE,
)


def _is_webshell_command(cmd: str) -> bool:
    """检测命令是否是通过 webshell 执行的操作（curl shell.php?c=xxx）。"""
    return bool(_WEBSHELL_URL_PATTERNS.search(cmd))


def _classify_attack_vector(cmd: str) -> str | None:
    """从 bash 命令中提取攻击向量类型。返回匹配关键词最多的向量，或 None。

    webshell 通道命令会被标记为 'webshell_channel'（特殊白名单类型），
    不会触发循环检测。
    """
    cmd_lower = cmd.lower()
    # webshell 通道白名单：不同命令通过同一 webshell 执行不算循环
    if _is_webshell_command(cmd_lower):
        return "webshell_channel"
    best_vector = None
    best_hits = 0
    for vector_name, keywords in _ATTACK_VECTOR_PATTERNS:
        hits = sum(1 for kw in keywords if kw.lower() in cmd_lower)
        if hits > best_hits:
            best_hits = hits
            best_vector = vector_name
    return best_vector if best_hits > 0 else None


class ObserverLoop:
    """
    挂在 SolverAgent 上的旁路触发器。
    每 REVIEW_EVERY_ROUNDS 轮触发一次异步审查，不阻塞 Solver 推进。
    """

    REVIEW_EVERY_ROUNDS = 6
    NO_PROGRESS_THRESHOLD = 1  # 连续几个审查周期无进展才触发强干预

    def __init__(self, settings: dict, on_correction: callable = None):
        self.settings = settings
        self.on_correction = on_correction
        self.enabled = settings.get("solver", {}).get("observer_enabled", True)
        self._round_logs: list[dict] = []
        self._current_round: dict | None = None
        self._lock = threading.Lock()
        self._review_thread: threading.Thread | None = None
        self.review_every = settings.get("solver", {}).get("observer_every_rounds", 6)
        # 内容指纹去重：相同方向的纠偏只发一次，不限轮次
        self._sent_correction_fps: set[str] = set()
        # 无进展检测：记录上次审查时 ideas 的 active 状态快照
        self._last_active_idea_ids: set[str] = set()
        self._no_progress_periods: int = 0
        # 攻击向量级循环检测
        self._recent_vectors: list[str | None] = []  # 每轮的主要攻击向量
        self._vector_cycle_warned: set[str] = set()  # 已警告过的向量
        self._VECTOR_CYCLE_THRESHOLD = 4  # 第 4 轮前强制切换已连续失败的方向
        self._run_context = _ctx.snapshot()
        self._client = _ctx.client

    def trigger_now(self, reason: str = "", extra_context: str = "") -> None:
        """立即触发一次 Observer 审查（不等周期）。"""
        if not self.enabled:
            return
        with self._lock:
            rounds_to_review = list(self._round_logs)
            self._round_logs = []

        challenge_dir = self._get_challenge_dir()
        attempt_dir = self._get_attempt_dir()

        if self._review_thread and self._review_thread.is_alive():
            self._review_thread.join(timeout=10)
            if self._review_thread.is_alive():
                # Keep the evidence for the next review rather than starting two
                # observers that concurrently mutate the same blackboard.
                with self._lock:
                    self._round_logs = rounds_to_review + self._round_logs
                return

        self._review_thread = threading.Thread(
            target=self._run_review,
            args=(rounds_to_review, challenge_dir, attempt_dir),
            daemon=True,
        )
        self._review_thread.start()

    def on_round_start(self, round_num: int) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._current_round = {"round": round_num, "tool_calls": []}

    def on_tool_call(self, tool: str, args: dict, result: str) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._current_round is not None:
                # Preserve both response identity and final diagnostics.
                result_excerpt = result
                if len(result_excerpt) > 1200:
                    result_excerpt = (
                        result_excerpt[:400]
                        + "\n...[observer excerpt]...\n"
                        + result_excerpt[-800:]
                    )
                self._current_round["tool_calls"].append({
                    "tool": tool,
                    "args": args,
                    "result": result_excerpt,
                })
                # 攻击向量分类（只对 bash 命令）
                if tool == "bash":
                    vector = _classify_attack_vector(str(args.get("cmd", "")))
                    if vector:
                        self._current_round["_attack_vector"] = vector

    def on_round_end(self, round_num: int) -> None:
        if not self.enabled:
            return
        with self._lock:
            current = self._current_round
            if current:
                self._round_logs.append(current)
                self._current_round = None
                # 记录本轮的攻击向量
                vector = current.get("_attack_vector")
                self._recent_vectors.append(vector)
                if len(self._recent_vectors) > 20:
                    self._recent_vectors = self._recent_vectors[-20:]

        # 攻击向量级循环检测
        self._check_vector_cycle(round_num)

        if round_num % self.review_every == 0:
            self._trigger_review()

    def _check_vector_cycle(self, round_num: int) -> None:
        """
        检测是否连续 N 轮都在同一攻击向量上。
        触发时立即调起 Observer 审查，并附上向量循环上下文。
        """
        threshold = self._VECTOR_CYCLE_THRESHOLD
        if len(self._recent_vectors) < threshold:
            return

        # 取最近 threshold 轮
        tail = self._recent_vectors[-threshold:]
        # 过滤掉 None（非 bash 或无法分类的轮）
        non_none = [v for v in tail if v is not None]
        if len(non_none) < threshold - 1:  # 允许 1 轮空白
            return

        # 检查是否全部相同
        dominant = non_none[0]
        if not all(v == dominant for v in non_none):
            return

        # webshell 通道白名单：通过 webshell 执行不同命令是正常操作，不触发循环警告
        if dominant == "webshell_channel":
            return

        # 已警告过这个向量则不重复
        if dominant in self._vector_cycle_warned:
            return
        self._vector_cycle_warned.add(dominant)

        # 直接发纠偏（不等 Observer，确定性规则）
        message = (
            f"[向量循环检测] 连续 {len(non_none)} 轮都在尝试 {dominant}，"
            f"且未取得突破。\n"
            f"当前 {dominant} 方向已经耗尽合理尝试次数，必须立即切换到其他攻击向量。\n"
            f"请执行：\n"
            f"1. idea_list 查看未探索的方向\n"
            f"2. memory_list 查看是否有未利用的凭据/发现\n"
            f"3. security_search 搜索该题目类型的其他常见漏洞"
        )

        if self.on_correction:
            if self._should_send_correction(message, round_num):
                self.on_correction(message, round_num)

        # 同时触发 Observer 审查，让它结合 Memory/Ideas 做更智能的纠偏
        self.trigger_now(reason=f"vector_cycle:{dominant}")

    def on_agent_end(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            has_unreviewed = bool(self._round_logs)

        if has_unreviewed:
            self._trigger_review(force=True)

        if self._review_thread and self._review_thread.is_alive():
            self._review_thread.join(timeout=60)

    def _trigger_review(self, force: bool = False) -> None:
        if self._review_thread and self._review_thread.is_alive():
            return

        with self._lock:
            rounds_to_review = list(self._round_logs)
            self._round_logs = []

        if not rounds_to_review and not force:
            return

        challenge_dir = self._get_challenge_dir()
        attempt_dir = self._get_attempt_dir()

        self._review_thread = threading.Thread(
            target=self._run_review,
            args=(rounds_to_review, challenge_dir, attempt_dir),
            daemon=True,
        )
        self._review_thread.start()

    @staticmethod
    def _get_challenge_dir() -> Path:
        """从 thread-local 上下文获取 challenge_dir（并行安全）。"""
        if _ctx.challenge_dir and _ctx.challenge_dir != "/workspace":
            return Path(_ctx.challenge_dir)
        return Path(os.environ.get("CTF_WORKSPACE", "/workspace"))

    @staticmethod
    def _get_attempt_dir() -> Path:
        if _ctx.attempt_dir and _ctx.attempt_dir != "/workspace":
            return Path(_ctx.attempt_dir)
        return ObserverLoop._get_challenge_dir()

    def _should_send_correction(self, content: str, current_round: int) -> bool:
        # 只做内容指纹去重，不限轮次 cooldown
        # 相同方向的纠偏只发一次，不同方向不管多近都允许发
        fp = hashlib.md5(content.encode()).hexdigest()[:8]
        if fp in self._sent_correction_fps:
            return False
        self._sent_correction_fps.add(fp)
        return True

    def _check_progress(self, challenge_dir: Path, current_round: int) -> None:
        """
        审查结束后检测是否有进展：
        - 若所有 ideas 均为 failed 且 Memory 无新 evidence，立即触发强干预（不等周期）
        - 若连续 NO_PROGRESS_THRESHOLD 个周期没有任何 idea 推进到 testing/verified，触发强干预
        """
        try:
            from shared.data import ideas as idea_store, memory as mem_store
            all_ideas = idea_store.list_ideas(challenge_dir)
            all_memories = mem_store.list_memory(challenge_dir)
        except Exception:
            return

        # 快速路径：所有 idea 均 failed → 立即触发，不等周期计数
        non_failed = [i for i in all_ideas if i.status != "failed"]
        if all_ideas and not non_failed:
            evidence = [m for m in all_memories if m.kind == "evidence"]
            self._send_no_progress_intervention(all_ideas, current_round, fast_path=True)
            return

        # 常规路径：tracking testing/verified 推进
        active_ids = {
            i.id for i in all_ideas
            if i.status in ("testing", "verified")
        }

        if active_ids == self._last_active_idea_ids:
            self._no_progress_periods += 1
        else:
            self._no_progress_periods = 0
            self._last_active_idea_ids = active_ids

        if self._no_progress_periods >= self.NO_PROGRESS_THRESHOLD:
            self._no_progress_periods = 0
            self._send_no_progress_intervention(all_ideas, current_round)

    def _send_no_progress_intervention(self, all_ideas, current_round: int, fast_path: bool = False) -> None:
        """连续无进展时发送强干预：列出所有 failed 路线，要求从未尝试方向出发。"""
        failed = [i for i in all_ideas if i.status == "failed"]
        pending = [i for i in all_ideas if i.status == "pending"]

        trigger_reason = "所有攻击方向均已失败" if fast_path else "已连续多个周期没有新进展"
        lines = [
            f"[OBSERVER][强干预] {trigger_reason}。",
            "",
        ]
        if failed:
            lines.append("以下方向已确认失败，不要再尝试：")
            for i in failed:
                result_str = f"（{i.result}）" if i.result else ""
                lines.append(f"  - {i.content}{result_str}")
            lines.append("")
        if pending:
            lines.append("以下是尚未探索的方向，请从中选一个开始：")
            for i in pending:
                lines.append(f"  - {i.content}")
            lines.append("")
        lines.append(
            "必须立即切换到一个未尝试过的全新方向。"
            "如果 idea 列表已空，调用 security_search 搜索该题目类型的其他常见漏洞或 writeup。"
        )

        message = "\n".join(lines)
        if self._should_send_correction(message, current_round):
            if self.on_correction:
                self.on_correction(message, current_round)

    def _run_review(
        self, rounds: list[dict], challenge_dir: Path, attempt_dir: Path
    ) -> None:
        current_round = rounds[-1]["round"] if rounds else 0

        def guarded_correction(content: str) -> None:
            if self._should_send_correction(content, current_round):
                if self.on_correction:
                    self.on_correction(content, current_round)
            else:
                write_line({
                    "type": "observer_correction_suppressed",
                    "data": {"reason": "cooldown_or_duplicate", "round": current_round},
                })

        try:
            from solver.observer.agent import ObserverAgent
            with _ctx.bind(self._run_context, self._client):
                observer = ObserverAgent(settings=self.settings)
                observer.review(
                    recent_rounds=rounds,
                    challenge_dir=challenge_dir,
                    attempt_dir=attempt_dir,
                    on_correction=guarded_correction,
                )
        except Exception as e:
            write_line({"type": "observer_error", "data": {"msg": str(e)}})

        # 审查结束后做无进展检测
        self._check_progress(challenge_dir, current_round)
