"""
多题并行调度器：从 Tsecbench 平台拉取题目列表，并行启动多道题同时解题。

生命周期：
  1. check_vpn -> 确认 VPN 连通
  2. list_challenges -> 筛选未完成题目
  3. 按难度排序（easy -> medium -> hard）
  4. ThreadPoolExecutor(max_workers=3) 并行：start -> SolverAgent.run -> close
  5. 平台限制同时最多 3 道题，通过 max_workers 控制并发度

每个 worker 线程拥有独立的 thread-local 上下文（WorkerContext），
避免跨题目的状态污染。
"""

import json
import os
import sys
import time
import threading
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import logging

logger = logging.getLogger(__name__)

from solver.ctfplatform.tsecbench_client import (
    Challenge,
    ChallengeNotFound,
    DuplicateSubmit,
    InvalidState,
    ResourceUnavailable,
    TsecbenchClient,
    TsecbenchConnectionError,
    TsecbenchError,
    VpnCheckError,
)
from solver.tools import bridge_tools
from solver.worker_context import ctx as _ctx
from solver.ctfplatform.scoreboard import Scoreboard


DIFFICULTY_ORDER = {
    "easy": 0,
    "medium": 1,
    "hard": 2,
    "difficult": 2,
}

DEFAULT_MAX_PARALLEL = 3

# start_challenge 失败后的重试参数
_START_RETRY_MAX = 5
_START_RETRY_INTERVAL = 30  # 秒

# close_challenge 失败后的重试参数
_CLOSE_RETRY_MAX = 3
_CLOSE_RETRY_INTERVAL = 5  # 秒

# 靶场健康检查参数
_HEALTH_CHECK_MAX = 3       # 最多检查次数（从 5 降到 3，减少等待）
_HEALTH_CHECK_INTERVAL = 5   # 每次间隔（秒，从 10 降到 5）
_HEALTH_CHECK_TIMEOUT = 8    # 单次连接超时（秒，从 10 降到 8）

# 环境不可用的重试参数
_ENV_RETRY_INTERVAL = 300  # 5 分钟后重试


@dataclass
class SchedulerResult:
    """单题解题结果"""
    unique_code: str
    success: bool
    correct_flag_count: int = 0
    total_flag_count: int = 0
    error: str = ""
    rounds: int = 0


@dataclass
class SchedulerReport:
    """调度器最终报告"""
    total_challenges: int = 0
    attempted: int = 0
    solved: int = 0
    partial: int = 0
    failed: int = 0
    skipped: int = 0
    cumulative_score: int = 0
    results: list[SchedulerResult] = field(default_factory=list)


_emit_lock = threading.Lock()


def _emit(event_type: str, data: Any = None) -> None:
    from shared.jsonl import serialize
    msg = {"type": event_type, "data": data}
    with _emit_lock:
        sys.stdout.write(serialize(msg))
        sys.stdout.flush()


def _sort_challenges(challenges: list[Challenge]) -> list[Challenge]:
    """
    按优先级评分降序排列。
    考虑：难度权重 + 题目类型权重 + 部分进展加分 + 未尝试加分。
    """
    def _score(c: Challenge) -> float:
        score = 0.0

        # 难度权重（easy 先做）
        score += {"easy": 30, "medium": 20, "hard": 10, "difficult": 10}.get(
            c.difficulty.lower(), 10
        )

        # 题目类型权重（Agent 擅长的优先做）
        code_lower = c.unique_code.lower()
        if code_lower.startswith('a-') or code_lower.startswith('c-'):
            score += 15   # Web/杂项，LLM 最擅长
        elif code_lower.startswith('d-'):
            score += 12   # 漏洞利用
        elif code_lower.startswith('f1'):
            score += 12   # 对抗规避-1，正确率高
        elif code_lower.startswith('e2') or code_lower.startswith('e3'):
            score += 8    # 二进制 2/3，正确率较高
        elif code_lower.startswith('e1'):
            score += 5    # 二进制-1
        elif code_lower.startswith('f2'):
            score += 0    # 对抗规避-2，最难
        elif code_lower.startswith('b-'):
            score += 5    # 多阶段渗透，难但分值高

        # 部分进展加分（已经有 flag 的优先继续）
        if c.correct_flag_count > 0:
            score += 20

        return score

    return sorted(challenges, key=_score, reverse=True)


def _ensure_target_ready(url: str) -> bool:
    """
    靶场健康检查：start_challenge 成功后探测目标是否可达。
    最多重试 _HEALTH_CHECK_MAX 次，每次间隔 _HEALTH_CHECK_INTERVAL 秒。
    返回 True 可达，False 不可达。
    """
    import subprocess
    import time as _time
    for attempt in range(1, _HEALTH_CHECK_MAX + 1):
        _t_curl = _time.time()
        try:
            result = subprocess.run(
                ["curl", "-sf", "--max-time", str(_HEALTH_CHECK_TIMEOUT),
                 "-o", "/dev/null", "-w", "%{http_code}", url],
                capture_output=True, text=True, timeout=_HEALTH_CHECK_TIMEOUT + 5,
            )
            status = result.stdout.strip()
            if status and int(status) < 500:
                _emit("health_check_ok", {"url": url, "attempt": attempt, "status": status, "curl_elapsed_s": round(_time.time() - _t_curl, 2)})
                return True
        except Exception:
            pass

        if attempt < _HEALTH_CHECK_MAX:
            _emit("health_check_retry", {
                "url": url, "attempt": attempt,
                "wait": _HEALTH_CHECK_INTERVAL,
                "curl_elapsed_s": round(_time.time() - _t_curl, 2),
            })
            time.sleep(_HEALTH_CHECK_INTERVAL)

    _emit("health_check_failed", {"url": url, "attempts": _HEALTH_CHECK_MAX})
    return False


# 题目编号前缀 → 类型推断
_CODE_PREFIX_TO_TYPE = {
    'a-': ('→ Web 漏洞', '/skills/web/SKILL.md'),
    'b-': ('→ 多阶段渗透（多 flag）', '/skills/pentest/SKILL.md'),
    'c-': ('→ 综合/杂项', '/skills/web/SKILL.md'),
    'd-': ('→ 漏洞利用', '/skills/pwn/SKILL.md'),
    'e1': ('→ 二进制/逆向-1', '/skills/reverse/SKILL.md'),
    'e2': ('→ 二进制/逆向-2', '/skills/reverse/SKILL.md'),
    'e3': ('→ 二进制/逆向-3', '/skills/reverse/SKILL.md'),
    'f1': ('→ 对抗规避-1', '/skills/evasion/SKILL.md'),
    'f2': ('→ 对抗规避-2（深度逆向/patch）', '/skills/evasion/SKILL.md'),
}


def _infer_challenge_type(unique_code: str) -> tuple[str, str]:
    """根据 unique_code 前缀推断题目类型和建议读取的 SKILL 文件。"""
    code_lower = unique_code.lower()
    for prefix, (type_name, skill_path) in _CODE_PREFIX_TO_TYPE.items():
        if code_lower.startswith(prefix):
            return type_name, skill_path
    return '→ 未知类型', '/skills/web/SKILL.md'


_ATTACK_PLAN_PROMPT = (
    "你是一名顶尖 CTF 安全专家。根据以下题目信息，生成 3-5 条按优先级排序的攻击步骤。"
    "每条步骤 1-2 句话，简洁可执行。考虑题目类型（Web题 vs 多阶段渗透题计划完全不同）。"
    "输出格式：每行一条，以 '1. ' '2. ' 开头，不要多余解释。"
)


def _generate_attack_plan(challenge, container_addr: tuple[str, ...], settings: dict) -> str:
    """生成题目专属攻击计划。一次 LLM 调用，不参与运行时循环。"""
    if not container_addr:
        return ""
    addr = container_addr[0]
    url = addr if addr.startswith("http") else f"http://{addr}"

    type_name, _ = _infer_challenge_type(challenge.unique_code)

    prompt = (
        f"题目编号：{challenge.unique_code}\n"
        f"类型：{type_name}\n"
        f"难度：{challenge.difficulty}\n"
        f"Flag 数量：{challenge.flag_count}\n"
        f"目标地址：{url}\n"
        f"描述：{challenge.description or '无'}\n"
        f"\n生成 3-5 条攻击步骤："
    )

    try:
        from openai import OpenAI
        import httpx2 as httpx
        llm_cfg = settings.get("llm", {})
        client = OpenAI(
            base_url=llm_cfg.get("base_url") or os.environ.get("LLM_BASE_URL", ""),
            api_key=llm_cfg.get("api_key") or os.environ.get("LLM_API_KEY", ""),
            timeout=httpx.Timeout(15.0, connect=10.0),
        )
        model = llm_cfg.get("default_model") or os.environ.get("LLM_MODEL", "deepseek-chat")
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _ATTACK_PLAN_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=300,
            temperature=0.3,
        )
        msg = resp.choices[0].message
        plan = getattr(msg, "content", None) or getattr(msg, "model_extra", {}).get("reasoning_content", "") or ""
        return plan.strip()
    except Exception:
        return ""


# ━━ 跨题经验注入：攻击链存储与匹配 ━━
_CHAIN_STORE_FILE = ".attack-chains.json"


def _save_attack_chain(challenge_workspace: str, unique_code: str, success: bool) -> None:
    """解完一道题后，保存攻击链摘要到共享存储，供同类题注入。"""
    if not success:
        return
    ws = Path(challenge_workspace)
    chain = _extract_chain_from_workspace(ws)
    if not chain:
        return

    # 类型前缀
    prefix = unique_code.split("-")[0] + "-" if "-" in unique_code else unique_code[:2]

    chain_entry = {
        "code": unique_code,
        "prefix": prefix,
        "summary": chain,
        "time": __import__("time").time(),
    }

    # 读取/更新共享存储
    store_path = Path(os.environ.get("CTF_WORKSPACE", "/workspace")) / _CHAIN_STORE_FILE
    store = {}
    if store_path.exists():
        try:
            store = json.loads(store_path.read_text(encoding="utf-8"))
        except Exception:
            store = {}

    chains = store.setdefault("chains", {})
    prefix_chains = chains.setdefault(prefix, [])
    # 避免重复
    if not any(c.get("code") == unique_code for c in prefix_chains):
        prefix_chains.append(chain_entry)
        # 每个类型只保留最近 3 条
        prefix_chains[:] = prefix_chains[-3:]

    try:
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(json.dumps(store, ensure_ascii=False, indent=2))
    except Exception:
        pass


def _extract_chain_from_workspace(ws: Path) -> str:
    """从题目工作目录的 Ideas/Memory 中提取攻击链摘要。"""
    parts = []

    # 从 verified ideas 提取
    ideas_file = ws / "ideas" / "index.json"
    if ideas_file.exists():
        try:
            ideas = json.loads(ideas_file.read_text(encoding="utf-8"))
            verified = [i["content"] for i in ideas if i.get("status") == "verified"]
            if verified:
                # 取最长的（通常包含完整攻击链）
                best = max(verified, key=len)
                parts.append(best[:200])
        except Exception:
            pass

    # 从 evidence memories 提取关键步骤
    mem_dir = ws / "memory" / "entries"
    if mem_dir.exists():
        try:
            import json as _json
            evidences = []
            for f in sorted(mem_dir.glob("*.json")):
                data = _json.loads(f.read_text(encoding="utf-8"))
                if data.get("kind") == "evidence":
                    c = data.get("content", "")
                    if len(c) > 30:  # 只取有实质内容的
                        evidences.append(c[:150])
            if evidences:
                parts.append(" | ".join(evidences[:2]))
        except Exception:
            pass

    return " → ".join(parts) if parts else ""


def _load_recent_chain(unique_code: str) -> str:
    """加载最近一道同类题的攻击链，用于注入到新题 task。"""
    prefix = unique_code.split("-")[0] + "-" if "-" in unique_code else unique_code[:2]

    store_path = Path(os.environ.get("CTF_WORKSPACE", "/workspace")) / _CHAIN_STORE_FILE
    if not store_path.exists():
        return ""

    try:
        store = json.loads(store_path.read_text(encoding="utf-8"))
        chains = store.get("chains", {})
        prefix_chains = chains.get(prefix, [])
        if prefix_chains:
            # 返回最近一条（排除自身）
            others = [c for c in prefix_chains if c.get("code") != unique_code]
            if others:
                latest = others[-1]
                return (
                    f"\n\n## 同类题经验（来自 {latest['code']} 的解法）\n"
                    f"最近解出的同类题攻击链：{latest['summary']}\n"
                    f"参考此攻击链，优先尝试类似路径。"
                )
    except Exception:
        pass

    return ""


def _build_task_from_challenge(challenge: Challenge, container_addr: tuple[str, ...]) -> str:
    """从平台 Challenge 数据构建 SolverAgent 的 task 文本。"""
    if container_addr:
        addr = container_addr[0]
        url = addr if addr.startswith("http") else f"http://{addr}"
    else:
        url = "（未返回靶场地址）"

    type_name, skill_path = _infer_challenge_type(challenge.unique_code)

    lines = [
        f"# CTF 题目：{challenge.unique_code}",
        f"- 类型：{type_name}",
        f"- 建议先读：`read_file(\"{skill_path}\")`",
        f"- 难度：{challenge.difficulty}",
        f"- 目标地址：{url}",
        f"- Flag 格式：flag{{...}}",
    ]

    if challenge.description:
        lines.append(f"- 描述：{challenge.description}")

    if challenge.flag_count > 1:
        remaining = challenge.flag_count - challenge.correct_flag_count
        lines.append(f"- ⚠️ 本题包含 {challenge.flag_count} 个 Flag（多阶段渗透题），已找到 {challenge.correct_flag_count} 个，还剩 {remaining} 个")
        lines.append(f"- ❗ 每找到一个 flag 就立即提交，然后继续渗透下一阶段（提权/横向移动/内网），直到全部找到")

    if challenge.correct_flag_count > 0:
        lines.append(f"\n## 已找到 {challenge.correct_flag_count} 个 Flag（继续寻找剩余的）")
        lines.append(f"\n⚠️ **这是重跑轮次**。上一轮发现的内网 IP 和端口可能已变化，必须重新扫描确认。")
        lines.append(f"不要直接使用 memory 中的旧 IP 地址，先重新执行 `ip addr` + `cat /proc/net/arp` + 端口探测。")
        lines.append(f"\n💡 **优先重建已有解法**：如果 memory 中已记录了完整的攻击链（如「error.log 投毒 RCE」「admin/Admin@123 登录」），")
        lines.append(f"直接按记忆中的步骤快速重建立足点，不要从零重新探测。重建优先级：先重建 RCE → 再验证内网拓扑 → 再用新 IP 执行横向移动。")

    lines.append(f"\n请开始解题，找到 flag 后调用 challenge_submit_flag 工具提交。")

    return "\n".join(lines)


def _default_agent_factory(task: str, settings: dict, skills_dir: str):
    """默认的 SolverAgent 工厂，延迟导入避免循环依赖。"""
    from solver.agent import SolverAgent
    return SolverAgent(task=task, settings=settings, skills_dir=skills_dir)


class Scheduler:
    def __init__(
        self,
        client: TsecbenchClient,
        settings: dict,
        *,
        skills_dir: str = "/skills",
        workspace_dir: str = "/workspace",
        max_retries_per_challenge: int = 1,
        skip_completed: bool = True,
        skip_codes: set[str] | None = None,
        prefix_filter: str | None = None,
        max_parallel: int = DEFAULT_MAX_PARALLEL,
        agent_factory=None,
        start_retry_max: int = _START_RETRY_MAX,
        start_retry_interval: float = _START_RETRY_INTERVAL,
        close_retry_max: int = _CLOSE_RETRY_MAX,
        close_retry_interval: float = _CLOSE_RETRY_INTERVAL,
    ) -> None:
        self.client = client
        self.settings = settings
        self.skills_dir = skills_dir
        self.workspace_dir = workspace_dir
        self.max_retries = max_retries_per_challenge
        self.skip_completed = skip_completed
        self.skip_codes = skip_codes or set()
        self.prefix_filter = prefix_filter.strip() if prefix_filter else None
        self.max_parallel = max(1, max_parallel)
        self._agent_factory = agent_factory or _default_agent_factory
        self._active_codes: set[str] = set()
        self._active_lock = threading.Lock()
        self._scoreboard = Scoreboard(workspace_dir)
        self.start_retry_max = start_retry_max
        self.start_retry_interval = start_retry_interval
        self.close_retry_max = close_retry_max
        self.close_retry_interval = close_retry_interval

    def run_all(self) -> SchedulerReport:
        """主调度循环：VPN 检测 -> 列题 -> 并行攻破。"""
        report = SchedulerReport()
        import time as _time
        _t_total_start = _time.time()

        _emit("scheduler_phase", {"phase": "vpn_check"})
        _t0 = _time.time()
        try:
            vpn = self.client.check_vpn()
            _emit("vpn_ok", {"client_ip": vpn.client_ip, "elapsed_s": round(_time.time() - _t0, 2)})
        except VpnCheckError as e:
            _emit("scheduler_error", {"phase": "vpn_check", "error": str(e), "elapsed_s": round(_time.time() - _t0, 2)})
            report.failed = -1
            return report

        _emit("scheduler_phase", {"phase": "list_challenges"})
        _t0 = _time.time()
        try:
            all_challenges = self.client.list_challenges()
            _emit("timing_list_challenges", {"elapsed_s": round(_time.time() - _t0, 2)})
        except TsecbenchError as e:
            _emit("scheduler_error", {"phase": "list_challenges", "error": str(e), "elapsed_s": round(_time.time() - _t0, 2)})
            return report

        _emit("timing_setup_done", {"total_elapsed_s": round(_time.time() - _t_total_start, 2)})

        report.total_challenges = len(all_challenges)
        self._scoreboard._total_score = sum(c.total_score for c in all_challenges)
        _emit("challenges_listed", {
            "total": len(all_challenges),
            "completed": sum(1 for c in all_challenges if c.is_completed),
        })

        if self.skip_completed:
            todo = [c for c in all_challenges if not c.is_completed]
        else:
            todo = list(all_challenges)

        # 前缀过滤：只保留指定前缀的题目（如 b- 只跑多阶段渗透）
        if self.prefix_filter:
            todo = [c for c in todo if c.unique_code.lower().startswith(self.prefix_filter.lower())]
            _emit("prefix_filter", {"prefix": self.prefix_filter, "matched": len(todo)})

        # 跳过被放弃的题目（多轮重跑时连续两轮失败的题）
        if self.skip_codes:
            todo = [c for c in todo if c.unique_code not in self.skip_codes]

        todo = _sort_challenges(todo)
        report.skipped = report.total_challenges - len(todo)

        # 注册所有待解题目到看板
        for c in todo:
            self._scoreboard.register(c.unique_code, c.difficulty, c.total_score, c.flag_count)

        if not todo:
            _emit("scheduler_done", {"reason": "all_completed"})
            return report

        if self.max_parallel <= 1:
            results = self._run_sequential(todo)
        else:
            results = self._run_parallel(todo)

        for result in results:
            report.results.append(result)
            report.attempted += 1
            if result.success:
                report.solved += 1
            elif result.correct_flag_count > 0:
                report.partial += 1
            else:
                report.failed += 1

        try:
            final_challenges = self.client.list_challenges()
            report.cumulative_score = sum(
                c.total_score for c in final_challenges if c.is_completed
            )
        except Exception:
            pass

        _emit("scheduler_done", {
            "attempted": report.attempted,
            "solved": report.solved,
            "partial": report.partial,
            "failed": report.failed,
            "skipped": report.skipped,
            "cumulative_score": report.cumulative_score,
            "mode": "parallel" if self.max_parallel > 1 else "sequential",
            "max_parallel": self.max_parallel,
        })

        return report

    def _run_sequential(self, todo: list[Challenge]) -> list[SchedulerResult]:
        results = []
        for challenge in todo:
            result = self._attempt_challenge(challenge)
            results.append(result)
            _emit("challenge_result", {
                "unique_code": result.unique_code,
                "success": result.success,
                "correct": result.correct_flag_count,
                "total": result.total_flag_count,
                "rounds": result.rounds,
                "error": result.error,
            })
        return results

    def _run_parallel(self, todo: list[Challenge]) -> list[SchedulerResult]:
        """生产者-消费者队列模式：N 个 worker 从队列取题，
        每个 worker close 当前题后才取下一题，
        保证平台活跃实例数永远 ≤ max_parallel。
        环境不可用的题放入重试队列，5 分钟后重新尝试。"""
        results: list[SchedulerResult] = []
        results_lock = threading.Lock()

        _emit("scheduler_phase", {
            "phase": "parallel_start",
            "max_parallel": self.max_parallel,
            "total_todo": len(todo),
        })

        work_queue: queue.Queue[Challenge | None] = queue.Queue()
        for c in todo:
            work_queue.put(c)

        # 环境不可用重试队列：(retry_after_time, challenge)
        env_retry_queue: list[tuple[float, Challenge]] = []
        env_retry_lock = threading.Lock()
        # 停止标志
        stop_event = threading.Event()

        def _env_retry_feeder() -> None:
            """守护线程：定期检查环境不可用的题，到期后放回工作队列。"""
            while not stop_event.is_set():
                now = time.time()
                with env_retry_lock:
                    ready = [item for item in env_retry_queue if now >= item[0]]
                    for item in ready:
                        env_retry_queue.remove(item)
                for _, challenge in ready:
                    _emit("env_retry_requeue", {"unique_code": challenge.unique_code})
                    work_queue.put(challenge)
                stop_event.wait(timeout=30)  # 每 30s 检查一次

        feeder_thread = threading.Thread(target=_env_retry_feeder, daemon=True)
        feeder_thread.start()

        # 用计数器跟踪“未完成的任务数”，而不是固定毒丸
        pending_count = len(todo)
        pending_lock = threading.Lock()

        def _worker() -> None:
            nonlocal pending_count
            while True:
                try:
                    item = work_queue.get(timeout=60)
                except queue.Empty:
                    # 检查是否还有待重试的题
                    with env_retry_lock:
                        has_retry = len(env_retry_queue) > 0
                    with pending_lock:
                        has_pending = pending_count > 0
                    if not has_retry and not has_pending:
                        break
                    continue

                if item is None:
                    break
                challenge = item
                try:
                    result = self._attempt_challenge(challenge)
                except Exception as e:
                    result = SchedulerResult(
                        unique_code=challenge.unique_code,
                        success=False,
                        error=f"Worker exception: {e}",
                        total_flag_count=challenge.flag_count,
                    )

                # 检查是否是环境不可用，如果是则放入重试队列而非直接失败
                if result.error and "environment_issue" in result.error:
                    with env_retry_lock:
                        retry_at = time.time() + _ENV_RETRY_INTERVAL
                        env_retry_queue.append((retry_at, challenge))
                    _emit("env_retry_scheduled", {
                        "unique_code": challenge.unique_code,
                        "retry_in_sec": _ENV_RETRY_INTERVAL,
                    })
                    continue  # 不记录结果，等重试

                with pending_lock:
                    pending_count -= 1

                with results_lock:
                    results.append(result)

                _emit("challenge_result", {
                    "unique_code": result.unique_code,
                    "success": result.success,
                    "correct": result.correct_flag_count,
                    "total": result.total_flag_count,
                    "rounds": result.rounds,
                    "error": result.error,
                })

        threads = []
        for i in range(self.max_parallel):
            t = threading.Thread(target=_worker, name=f"solver-{i}", daemon=True)
            t.start()
            threads.append(t)

        # 等待所有普通任务完成后放毒丸
        # 先等待 pending_count 归 0 和 env_retry_queue 清空
        while True:
            with pending_lock:
                done = pending_count <= 0
            with env_retry_lock:
                no_retry = len(env_retry_queue) == 0
            if done and no_retry:
                break
            time.sleep(5)

        # 放毒丸让 worker 退出
        for _ in range(self.max_parallel):
            work_queue.put(None)
        stop_event.set()

        for t in threads:
            t.join(timeout=30)

        return results

    @staticmethod
    def _should_multi_solve(challenge) -> bool:
        """判断是否对该题启用 Multi-Solver（并行两个不同策略的 Solver）。"""
        return (
            challenge.flag_count >= 4
            or challenge.difficulty.lower() in ("hard", "difficult")
        )

    def _attempt_multi_solver(
        self, challenge: Challenge, container_addr: tuple[str, ...],
        challenge_workspace: str, code: str, url: str
    ) -> SchedulerResult:
        """对 hard 题启动两个 Solver 实例，不同策略，先解出者胜。"""
        import threading

        stop_event = threading.Event()
        result_lock = threading.Lock()
        best_result = SchedulerResult(
            unique_code=code,
            success=False,
            total_flag_count=challenge.flag_count,
            correct_flag_count=challenge.correct_flag_count,
        )

        def _run_one(strategy_name: str, extra_rounds: int, observer_every: int):
            """运行一个 Solver 实例。"""
            try:
                # 线程内重新配置 Tsecbench 客户端（thread-local 不继承主线程）
                bridge_tools.configure_tsecbench(self.client, code)

                # 构建独立 task（含策略提示）
                task = _build_task_from_challenge(challenge, container_addr)
                task += f"\n\n## 策略：{strategy_name}（本策略为 Multi-Solver 并行模式，另一策略也在同时解题）"

                # 注入跨题经验
                recent_chain = _load_recent_chain(challenge.unique_code)
                if recent_chain:
                    task += recent_chain

                # 生成攻击计划
                attack_plan = _generate_attack_plan(challenge, container_addr, self.settings)
                if attack_plan:
                    task += f"\n\n## 本题攻击计划（自动生成，按优先级执行）\n{attack_plan}"
                    plan_path = os.path.join(challenge_workspace, f".attack-plan-{strategy_name}.json")
                    try:
                        import json
                        plan_steps = [
                            s.strip() for s in attack_plan.split("\n")
                            if s.strip() and (s.strip()[0].isdigit() or s.strip().startswith("-"))
                        ]
                        with open(plan_path, "w", encoding="utf-8") as f:
                            json.dump({"steps": plan_steps, "raw": attack_plan}, f, ensure_ascii=False)
                    except Exception:
                        pass

                # 策略差异化：max_rounds 和 observer 频率
                strategy_settings = dict(self.settings)
                solver_cfg = dict(strategy_settings.get("solver", {}))
                solver_cfg["observer_every_rounds"] = observer_every
                strategy_settings["solver"] = solver_cfg

                from solver.agent import SolverAgent
                agent = SolverAgent(
                    task=task,
                    settings=strategy_settings,
                    skills_dir=self.skills_dir,
                )
                if extra_rounds > 0:
                    agent.max_rounds += extra_rounds
                agent._stop_event = stop_event

                agent.run()

                # 记录结果
                with result_lock:
                    if agent.solved:
                        stop_event.set()  # 通知另一个停止
                        best_result.success = True
                        best_result.rounds = agent.round
                        best_result.correct_flag_count = challenge.flag_count
            except Exception as e:
                import traceback
                _emit("solver_error", {
                    "unique_code": code,
                    "strategy": strategy_name,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                })

        # 启动两个 Solver 线程
        # 策略 A：激进型 — 更多轮次，更频繁 Observer
        # 策略 B：稳健型 — 默认配置
        t1 = threading.Thread(
            target=_run_one, args=("aggressive", 30, 4),
            name=f"multi-{code}-aggressive", daemon=True
        )
        t2 = threading.Thread(
            target=_run_one, args=("steady", 0, 8),
            name=f"multi-{code}-steady", daemon=True
        )

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        return best_result

    def _attempt_challenge(self, challenge: Challenge) -> SchedulerResult:
        code = challenge.unique_code
        _emit("challenge_start", {"unique_code": code, "difficulty": challenge.difficulty})
        self._scoreboard.mark_running(code)

        result = SchedulerResult(
            unique_code=code,
            success=False,
            total_flag_count=challenge.flag_count,
            correct_flag_count=challenge.correct_flag_count,
        )

        # start_challenge 带重试：平台可能暂时认为容器数已满（close 延迟释放）
        container_addr: tuple[str, ...] = ()
        import time as _time
        _t_start_begin = _time.time()
        for attempt in range(1, self.start_retry_max + 1):
            try:
                _t_attempt = _time.time()
                start = self.client.start_challenge(code)
                container_addr = start.container_addr
                with self._active_lock:
                    self._active_codes.add(code)
                _emit("challenge_started", {
                    "unique_code": code,
                    "container_addr": list(container_addr),
                    "attempt": attempt,
                    "attempt_elapsed_s": round(_time.time() - _t_attempt, 2),
                    "total_elapsed_s": round(_time.time() - _t_start_begin, 2),
                })
                break
            except (InvalidState, ResourceUnavailable) as e:
                _emit("challenge_start_retry", {
                    "unique_code": code,
                    "attempt": attempt,
                    "reason": str(e),
                    "wait": self.start_retry_interval,
                    "elapsed_so_far_s": round(_time.time() - _t_start_begin, 2),
                })
                if attempt < self.start_retry_max:
                    time.sleep(self.start_retry_interval)
                else:
                    _emit("challenge_skip", {"unique_code": code, "reason": str(e)})
                    result.error = str(e)
                    self._scoreboard.mark_skipped(code, str(e))
                    return result
            except TsecbenchConnectionError as e:
                # 连接超时：服务端可能已启动容器但客户端没收到响应
                # 尝试 close 释放可能占用的槽位，然后重试
                _emit("challenge_start_retry", {
                    "unique_code": code,
                    "attempt": attempt,
                    "reason": f"connection_error: {e}",
                    "wait": self.start_retry_interval,
                    "elapsed_so_far_s": round(_time.time() - _t_start_begin, 2),
                })
                # 尝试 close（可能服务端已启动）
                try:
                    self.client.close_challenge(code)
                except Exception:
                    pass
                if attempt < self.start_retry_max:
                    time.sleep(self.start_retry_interval)
                else:
                    _emit("challenge_skip", {"unique_code": code, "reason": str(e)})
                    result.error = str(e)
                    self._scoreboard.mark_skipped(code, str(e))
                    return result
            except TsecbenchError as e:
                _emit("challenge_error", {"unique_code": code, "error": str(e)})
                result.error = str(e)
                self._scoreboard.mark_skipped(code, str(e))
                return result

        _ctx.reset()
        bridge_tools.configure_tsecbench(self.client, code)
        _ctx.challenge_id = code

        # 每题独立的工作目录（并行安全）
        challenge_workspace = os.path.join(self.workspace_dir, code)
        os.makedirs(challenge_workspace, exist_ok=True)
        _ctx.challenge_dir = challenge_workspace

        if container_addr:
            addr = container_addr[0]
            url = addr if addr.startswith("http") else f"http://{addr}"
            _ctx.target_url = url

            # ━━ 靶场健康检查 ━━
            # start 成功后探测目标是否可达，不可达则标记 environment_issue
            # 由调度器放入重试队列，5 分钟后重新尝试
            _t_health = _time.time()
            _health_ok = _ensure_target_ready(url)
            _emit("timing_health_check", {"unique_code": code, "elapsed_s": round(_time.time() - _t_health, 2), "ok": _health_ok})
            if not _health_ok:
                _emit("challenge_env_issue", {"unique_code": code, "url": url})
                # close 释放槽位
                try:
                    self.client.close_challenge(code)
                except Exception:
                    pass
                with self._active_lock:
                    self._active_codes.discard(code)
                bridge_tools.clear_tsecbench()
                _ctx.reset()
                result.error = "environment_issue: target unreachable"
                self._scoreboard.mark_skipped(code, "靶场不可达")
                return result

        # 单线程模式下还是设置环境变量（向后兼容）
        if self.max_parallel <= 1:
            os.environ["CTF_CHALLENGE_ID"] = code
            os.environ["CTF_WORKSPACE"] = challenge_workspace
            if container_addr:
                os.environ["CTF_TARGET_URL"] = url

        # ━━ Multi-Solver：hard 题启动两个不同策略的 Solver ━━
        if self._should_multi_solve(challenge):
            _emit("multi_solver_start", {"unique_code": code, "reason": "hard_challenge"})
            result = self._attempt_multi_solver(
                challenge, container_addr, challenge_workspace, code, url
            )
            # 更新平台状态
            try:
                updated = self.client.list_challenges()
                current = next((c for c in updated if c.unique_code == code), None)
                if current:
                    result.correct_flag_count = current.correct_flag_count
                    result.total_flag_count = current.flag_count
                    result.success = current.is_completed
                if result.success:
                    _save_attack_chain(challenge_workspace, code, True)
            except Exception:
                pass
            # close
            for attempt in range(1, self.close_retry_max + 1):
                try:
                    self.client.close_challenge(code)
                    break
                except Exception:
                    if attempt < self.close_retry_max:
                        time.sleep(self.close_retry_interval)
            with self._active_lock:
                self._active_codes.discard(code)
            bridge_tools.clear_tsecbench()
            self._scoreboard.mark_done(
                code, success=result.success,
                correct_flags=result.correct_flag_count,
                total_flags=result.total_flag_count,
                rounds=result.rounds,
                note="" if result.success else (self._collect_failure_note(challenge_workspace)),
            )
            _ctx.reset()
            return result

        task = _build_task_from_challenge(challenge, container_addr)

        # ━━ 跨题经验注入（同类题已解攻击链）━━
        recent_chain = _load_recent_chain(challenge.unique_code)
        if recent_chain:
            task += recent_chain

        # ━━ 攻击计划生成（一次性 LLM 调用，不参与运行时循环）━━
        attack_plan = _generate_attack_plan(challenge, container_addr, self.settings)
        if attack_plan:
            task += f"\n\n## 本题攻击计划（自动生成，按优先级执行）\n{attack_plan}"
            # 写入 .attack-plan.json 供 Observer 对照
            plan_path = os.path.join(challenge_workspace, ".attack-plan.json")
            try:
                import json
                plan_steps = [
                    s.strip() for s in attack_plan.split("\n")
                    if s.strip() and (s.strip()[0].isdigit() or s.strip().startswith("-"))
                ]
                with open(plan_path, "w", encoding="utf-8") as f:
                    json.dump({"steps": plan_steps, "raw": attack_plan}, f, ensure_ascii=False)
            except Exception:
                pass

        try:
            agent = self._agent_factory(
                task=task,
                settings=self.settings,
                skills_dir=self.skills_dir,
            )
            _emit("timing_agent_start", {
                "unique_code": code,
                "elapsed_since_attempt_begin": round(_time.time() - _t_start_begin, 2),
            })
            agent.run()
            result.rounds = agent.round
            _emit("timing_agent_done", {
                "unique_code": code,
                "rounds": agent.round,
                "elapsed_since_attempt_begin": round(_time.time() - _t_start_begin, 2),
            })
        except Exception as e:
            import traceback
            _emit("solver_error", {
                "unique_code": code,
                "error": str(e),
                "traceback": traceback.format_exc(),
            })
            result.error = str(e)

        # ━━ 跨题经验：解出后保存攻击链 ━━
        try:
            updated = self.client.list_challenges()
            current = next((c for c in updated if c.unique_code == code), None)
            if current and current.is_completed:
                _save_attack_chain(challenge_workspace, code, True)
        except Exception:
            pass

        try:
            updated = self.client.list_challenges()
            current = next((c for c in updated if c.unique_code == code), None)
            if current:
                result.correct_flag_count = current.correct_flag_count
                result.total_flag_count = current.flag_count
                result.success = current.is_completed
        except Exception:
            pass

        # close_challenge 带重试：确保平台侧容器被释放，防止槽位泄漏
        close_ok = False
        for attempt in range(1, self.close_retry_max + 1):
            try:
                self.client.close_challenge(code)
                close_ok = True
                break
            except Exception as e:
                _emit("challenge_close_retry", {
                    "unique_code": code,
                    "attempt": attempt,
                    "error": str(e),
                })
                if attempt < self.close_retry_max:
                    time.sleep(self.close_retry_interval)

        with self._active_lock:
            self._active_codes.discard(code)
        if close_ok:
            _emit("challenge_closed", {"unique_code": code})
        else:
            _emit("challenge_close_error", {
                "unique_code": code,
                "error": f"close failed after {_CLOSE_RETRY_MAX} attempts",
            })

        bridge_tools.clear_tsecbench()

        # 更新看板：采集失败原因
        note = self._collect_failure_note(challenge_workspace) if not result.success else ""
        self._scoreboard.mark_done(
            code,
            success=result.success,
            correct_flags=result.correct_flag_count,
            total_flags=result.total_flag_count,
            rounds=result.rounds,
            note=note or result.error,
        )

        _ctx.reset()

        return result

    def close_all_active(self) -> None:
        with self._active_lock:
            codes = list(self._active_codes)
        for code in codes:
            for attempt in range(self.close_retry_max):
                try:
                    self.client.close_challenge(code)
                    with self._active_lock:
                        self._active_codes.discard(code)
                    break
                except Exception:
                    if attempt < self.close_retry_max - 1:
                        time.sleep(self.close_retry_interval)

    @staticmethod
    def _collect_failure_note(challenge_workspace: str) -> str:
        """
        从题目工作目录的 Memory/Ideas 中提取失败原因摘要。
        返回一句话的失败原因，写入看板的“备注”列。
        """
        import json
        ws = Path(challenge_workspace)
        parts: list[str] = []

        # 1. 从 Ideas 中找已失败的路线
        ideas_file = ws / "ideas" / "index.json"
        if ideas_file.exists():
            try:
                ideas = json.loads(ideas_file.read_text(encoding="utf-8"))
                failed = [i["content"] for i in ideas if i.get("status") == "failed"]
                if failed:
                    parts.append("失败路线: " + "; ".join(failed[:3]))
            except Exception:
                pass

        # 2. 从 Memory 中找 failure 类型记录
        mem_dir = ws / "memory" / "entries"
        if mem_dir.exists():
            try:
                failures = []
                for f in sorted(mem_dir.glob("*.json"), key=lambda x: x.name)[-5:]:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    if data.get("kind") == "failure":
                        failures.append(data["content"])
                if failures:
                    parts.append("失败记录: " + "; ".join(failures[:2]))
            except Exception:
                pass

        return " | ".join(parts) if parts else ""
