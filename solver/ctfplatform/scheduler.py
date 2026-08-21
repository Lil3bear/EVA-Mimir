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
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from solver.ctfplatform.policy import sort_challenges as _sort_challenges
from solver.ctfplatform.scoreboard import Scoreboard
from solver.ctfplatform.task_builder import (
    TaskBuilder,
    build_task_from_challenge as _build_task_from_challenge,
)
from solver.ctfplatform.tsecbench_client import (
    Challenge,
    InvalidState,
    ResourceUnavailable,
    TsecbenchClient,
    TsecbenchConnectionError,
    TsecbenchError,
    VpnCheckError,
)
from solver.tools import bridge_tools
from solver.worker_context import RunContext, ctx as _ctx
from solver.runtime.portfolio import build_portfolio

DEFAULT_MAX_PARALLEL = 3

# start_challenge 失败后的重试参数
_START_RETRY_MAX = 5
_START_RETRY_INTERVAL = 30  # 秒

# close_challenge 失败后的重试参数
_CLOSE_RETRY_MAX = 3
_CLOSE_RETRY_INTERVAL = 5  # 秒


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


def _emit(event_type: str, data: Any = None) -> None:
    from shared.jsonl import write_line
    write_line({"type": event_type, "data": data})


def _actual_cumulative_score(challenges: list[Challenge], workspace_dir: str) -> int:
    """
    优先用 submit 回传落盘的 cumulative_score（含 hint 扣分后的实际累计分）；
    找不到记录时回退到题目满分（未看过 hint 的题等价于满分）。
    """
    total = 0
    for c in challenges:
        if not c.is_completed:
            continue
        score_file = os.path.join(workspace_dir, c.unique_code, ".cumulative_score")
        try:
            with open(score_file, "r", encoding="utf-8") as f:
                total += int(f.read().strip())
        except Exception:
            total += c.total_score
    return total


# ━━ 跨题经验注入：攻击链存储与匹配 ━━
_CHAIN_STORE_FILE = ".attack-chains.json"
# 跨 run 持久化的种子文件：随镜像打包（skills/ 进镜像），实现"本题历史解法"跨比赛复用
_CHAIN_SEED_FILE = "experiences/references/attack-chains.json"

_FLAG_PATTERN = re.compile(r"[A-Za-z0-9_]+\{[^}]{4,80}\}")
_IPV4_PATTERN = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")


def _sanitize_chain_text(text: str) -> str:
    """持久化/注入攻击链前剥离 flag 与 IP。

    合规与鲁棒性双重要求：
    - 只沉淀"解法方法"，不沉淀 flag 答案本身（flag 可能每实例轮换，且直接带答案不合规）
    - 每次 run 靶场实例 IP 都会变，旧 IP 注入只会误导
    """
    text = _FLAG_PATTERN.sub("<flag>", text or "")
    text = _IPV4_PATTERN.sub("<IP>", text)
    return text


def _chain_seed_path(skills_dir: str = "") -> Path:
    base = skills_dir or os.environ.get("CTF_SKILLS_DIR", "/skills")
    return Path(base) / _CHAIN_SEED_FILE


def _load_chain_seed(skills_dir: str = "") -> dict:
    try:
        path = _chain_seed_path(skills_dir)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_attack_chain(challenge_workspace: str, unique_code: str, success: bool) -> None:
    """解完一道题后，保存攻击链摘要到共享存储，供同类题注入。"""
    if not success:
        return
    ws = Path(challenge_workspace)
    chain = _extract_chain_from_workspace(ws)
    if not chain:
        return
    chain = _sanitize_chain_text(chain)

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

    # 按题号精确索引（跨 run 导出后供"本题历史解法"精确注入）
    by_code = store.setdefault("by_code", {})
    by_code[unique_code] = chain_entry

    try:
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text(json.dumps(store, ensure_ascii=False, indent=2))
    except Exception:
        pass

    # 发事件到 stdout 日志，run 结束后可用 harvest_attack_chains.py 沉淀进镜像 seed
    _emit("attack_chain", {"code": unique_code, "prefix": prefix, "summary": chain})


def _extract_chain_from_workspace(ws: Path) -> str:
    """从题目工作目录的 Ideas/Memory/执行日志中提取攻击链摘要。"""
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

    # 从执行日志提取成功提交的 writeup（solver 自己总结的解法，是最精确的攻击链）
    # 单 solver：ws/.execution-journal.jsonl；multi-solver：ws/<attempt>/.execution-journal.jsonl
    writeups = _extract_successful_writeups(ws)
    if writeups:
        parts.append("writeup: " + " | ".join(writeups[:2]))

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


def _extract_successful_writeups(ws: Path, limit: int = 2) -> list[str]:
    """从执行日志中提取提交成功的 writeup（判定正确的 flag 提交所附的解法说明）。"""
    journals = list(ws.glob(".execution-journal.jsonl")) + list(ws.glob("*/.execution-journal.jsonl"))
    writeups: list[str] = []
    for journal_path in journals:
        try:
            prepared: dict[tuple, dict] = {}
            correct_ids: set[tuple] = set()
            for line in journal_path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                key = (event.get("run_id"), event.get("call_id"))
                if event.get("type") == "prepared" and event.get("tool") == "challenge_submit_flag":
                    prepared[key] = event.get("args") or {}
                elif event.get("type") == "completed" and event.get("tool") == "challenge_submit_flag":
                    if "提交正确" in str(event.get("result", "")):
                        correct_ids.add(key)
            for key in correct_ids:
                writeup = str(prepared.get(key, {}).get("writeup", "")).strip()
                if writeup and writeup != "auto-submit from tool output":
                    writeups.append(writeup[:200])
        except Exception:
            continue
    # 去重保序
    return list(dict.fromkeys(writeups))[:limit] if writeups else []


def _load_recent_chain(unique_code: str, skills_dir: str = "") -> str:
    """加载攻击链经验注入到新题 task。

    优先级：
    1. 本题历史解法（跨 run seed 中同题号的已验证攻击链）—— 最精确，直接重建
    2. 本次 run 内同类题攻击链（runtime store，随容器生命周期）
    3. 跨 run seed 中同类题攻击链
    """
    prefix = unique_code.split("-")[0] + "-" if "-" in unique_code else unique_code[:2]
    seed = _load_chain_seed(skills_dir)

    # 1. 同题精确匹配（跨 run 沉淀，最高优先级）
    exact = (seed.get("by_code") or {}).get(unique_code)
    if exact and exact.get("summary"):
        return (
            f"\n\n## 本题历史解法（此前比赛已解出，优先按此重建）\n"
            f"已验证攻击链：{exact['summary']}\n"
            f"注意：其中的 <IP> 占位代表上次实例地址，本次必须先用当前目标地址重新确认；"
            f"flag 已剥离，需按攻击链从目标重新获取。"
        )

    # 2. 本次 run 内同类题（runtime store）
    store_path = Path(os.environ.get("CTF_WORKSPACE", "/workspace")) / _CHAIN_STORE_FILE
    if store_path.exists():
        try:
            store = json.loads(store_path.read_text(encoding="utf-8"))
            prefix_chains = (store.get("chains") or {}).get(prefix, [])
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

    # 3. 跨 run seed 同类题
    try:
        prefix_chains = (seed.get("chains") or {}).get(prefix, [])
        others = [c for c in prefix_chains if c.get("code") != unique_code and c.get("summary")]
        if others:
            latest = others[-1]
            return (
                f"\n\n## 同类题经验（来自历史比赛 {latest['code']} 的解法）\n"
                f"已验证同类题攻击链：{latest['summary']}\n"
                f"参考此攻击链，优先尝试类似路径；其中 <IP> 需用当前目标重新确认。"
            )
    except Exception:
        pass

    return ""


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
        self._platform_state_lock = threading.RLock()
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
            all_challenges = self._list_challenges()
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
            final_challenges = self._list_challenges()
            report.cumulative_score = _actual_cumulative_score(
                final_challenges, self.workspace_dir
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
        """并行运行题目；每个 attempt 返回前都会关闭容器。"""
        results: list[SchedulerResult] = []

        _emit("scheduler_phase", {
            "phase": "parallel_start",
            "max_parallel": self.max_parallel,
            "total_todo": len(todo),
        })

        with ThreadPoolExecutor(
            max_workers=self.max_parallel, thread_name_prefix="solver"
        ) as executor:
            futures = {
                executor.submit(self._attempt_challenge, challenge): challenge
                for challenge in todo
            }
            for future in as_completed(futures):
                challenge = futures[future]
                try:
                    result = future.result()
                except Exception as e:
                    result = SchedulerResult(
                        unique_code=challenge.unique_code,
                        success=False,
                        error=f"Worker exception: {e}",
                        total_flag_count=challenge.flag_count,
                    )
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

    @staticmethod
    def _should_multi_solve(challenge) -> bool:
        """判断是否对该题启用 Multi-Solver（并行两个不同策略的 Solver）。"""
        return len(build_portfolio(challenge)) > 1

    def _build_agent_task(
        self,
        challenge: Challenge,
        container_addr: tuple[str, ...],
        challenge_workspace: str,
        *,
        strategy_name: str = "",
        strategy_hint: str = "",
        attempt_context: RunContext | None = None,
    ) -> str:
        return TaskBuilder(
            skills_dir=self.skills_dir,
            load_experience=_load_recent_chain,
        ).build(
            challenge,
            container_addr,
            challenge_workspace,
            strategy_name=strategy_name,
            strategy_hint=strategy_hint,
            attempt_context=attempt_context,
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

        base_context = RunContext(
            unique_code=code,
            challenge_id=code,
            challenge_dir=challenge_workspace,
            target_url=url,
        )

        portfolio = build_portfolio(challenge)
        observer_leader = portfolio[0].name

        def _run_one(spec):
            """运行一个 Solver 实例。"""
            try:
                attempt_context = base_context.for_attempt(spec.name)
                with _ctx.bind(attempt_context, self.client):
                    return _run_bound_attempt(spec, attempt_context)
            except Exception as e:
                import traceback
                _emit("solver_error", {
                    "unique_code": code,
                    "strategy": spec.name,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                })

        def _run_bound_attempt(
            spec,
            attempt_context: RunContext,
        ) -> None:
            bridge_tools.configure_tsecbench(self.client, code)

            task = self._build_agent_task(
                challenge,
                container_addr,
                challenge_workspace,
                strategy_name=spec.name,
                strategy_hint=spec.strategy_hint,
                attempt_context=attempt_context,
            )

            strategy_settings = dict(self.settings)
            solver_cfg = dict(strategy_settings.get("solver", {}))
            # One challenge gets one control plane. Multiple Observers racing on
            # the shared Memory/Ideas board produced stale and conflicting edits.
            solver_cfg["observer_enabled"] = spec.name == observer_leader
            strategy_settings["solver"] = solver_cfg

            agent = self._agent_factory(
                task=task,
                settings=strategy_settings,
                skills_dir=self.skills_dir,
            )
            agent._stop_event = stop_event

            agent.run()

            # 记录结果
            with result_lock:
                if agent.solved:
                    stop_event.set()  # 通知另一个停止
                    best_result.success = True
                    best_result.rounds = agent.round
                    best_result.correct_flag_count = challenge.flag_count

        # 两个 Solver 只用 prompt 区分策略，共用同一套预算与一个 Observer。
        threads = [
            threading.Thread(
                target=_run_one,
                args=(spec,),
                name=f"multi-{code}-{spec.name}",
                daemon=True,
            )
            for spec in portfolio
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        return best_result

    def _attempt_challenge(self, challenge: Challenge) -> SchedulerResult:
        """Run one challenge and close any resource left by an unexpected exit."""
        code = challenge.unique_code
        try:
            return self._attempt_challenge_inner(challenge)
        finally:
            with self._active_lock:
                still_active = code in self._active_codes
            if still_active:
                for attempt in range(1, self.close_retry_max + 1):
                    try:
                        self.client.close_challenge(code)
                        with self._active_lock:
                            self._active_codes.discard(code)
                        _emit("challenge_closed", {
                            "unique_code": code,
                            "recovered_by": "attempt_finally",
                        })
                        break
                    except Exception as e:
                        _emit("challenge_close_retry", {
                            "unique_code": code,
                            "attempt": attempt,
                            "error": str(e),
                            "recovered_by": "attempt_finally",
                        })
                        if attempt < self.close_retry_max:
                            time.sleep(self.close_retry_interval)
            bridge_tools.clear_tsecbench()
            _ctx.reset()

    def _attempt_challenge_inner(self, challenge: Challenge) -> SchedulerResult:
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

        # 每题独立的工作目录（并行安全）
        challenge_workspace = os.path.join(self.workspace_dir, code)
        os.makedirs(challenge_workspace, exist_ok=True)

        target = container_addr[0] if container_addr else ""

        run_context = RunContext(
            unique_code=code,
            challenge_id=code,
            challenge_dir=challenge_workspace,
            target_url=target,
        )
        _ctx.reset()
        _ctx.configure(run_context, self.client)

        # 单线程模式下还是设置环境变量（向后兼容）
        if self.max_parallel <= 1:
            os.environ["CTF_CHALLENGE_ID"] = code
            os.environ["CTF_WORKSPACE"] = challenge_workspace
            if container_addr:
                os.environ["CTF_TARGET_URL"] = target

        # ━━ Multi-Solver：hard 题启动两个不同策略的 Solver ━━
        if self._should_multi_solve(challenge):
            _emit("multi_solver_start", {"unique_code": code, "reason": "hard_challenge"})
            result = self._attempt_multi_solver(
                challenge, container_addr, challenge_workspace, code, target
            )
            # 更新平台状态
            try:
                updated = self._list_challenges()
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

        task = self._build_agent_task(
            challenge,
            container_addr,
            challenge_workspace,
        )

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

        # 刷新一次平台状态，同时用于结果统计和攻击链归档。
        try:
            updated = self._list_challenges()
            current = next((c for c in updated if c.unique_code == code), None)
            if current:
                result.correct_flag_count = current.correct_flag_count
                result.total_flag_count = current.flag_count
                result.success = current.is_completed
                if result.success:
                    _save_attack_chain(challenge_workspace, code, True)
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

    def _list_challenges(self) -> list[Challenge]:
        """Serialize state snapshots so parallel attempts see a coherent platform view."""
        with self._platform_state_lock:
            return self.client.list_challenges()

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
