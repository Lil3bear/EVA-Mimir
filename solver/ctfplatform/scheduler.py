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
import random
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
    TaskNotFound,
    TsecbenchClient,
    TsecbenchConnectionError,
    TsecbenchError,
    VpnCheckError,
)
from solver.tools import bridge_tools
from solver.runtime.challenge_ledger import ChallengeLedger
from solver.runtime.contracts import SubtaskContract, write_contract
from solver.runtime.submission_store import (
    prepare_challenge_state,
    score_belongs_to_current_task,
)
from solver.worker_context import RunContext, ctx as _ctx
from solver.runtime.portfolio import (
    PortfolioBudget,
    build_portfolio,
    challenge_memory_scope,
)

DEFAULT_MAX_PARALLEL = 3

# start_challenge 失败后的重试参数
_START_RETRY_MAX = 5
_START_RETRY_INTERVAL = 5  # 秒；指数退避后封顶 60 秒

# close_challenge 失败后的重试参数
_CLOSE_RETRY_MAX = 3
_CLOSE_RETRY_INTERVAL = 5  # 秒


@dataclass
class SchedulerResult:
    """单题解题结果及本次 attempt 的实际增量。"""
    unique_code: str
    success: bool
    correct_flag_count: int = 0
    total_flag_count: int = 0
    error: str = ""
    rounds: int = 0
    initial_correct_flag_count: int = 0
    material_progress_count: int = 0
    difficulty: str = ""

    @property
    def new_flag_count(self) -> int:
        return max(0, self.correct_flag_count - self.initial_correct_flag_count)

    @property
    def made_progress(self) -> bool:
        return bool(self.success or self.new_flag_count > 0 or self.material_progress_count > 0)


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


def _deadline_reached(deadline: float) -> bool:
    return bool(deadline and time.time() >= deadline)


def _sleep_retry(seconds: float, deadline: float = 0.0) -> None:
    """Sleep for a retry interval without crossing the run deadline."""
    seconds = max(0.0, float(seconds or 0.0))
    if not seconds:
        return
    if deadline:
        seconds = min(seconds, max(0.0, deadline - time.time()))
    if seconds:
        time.sleep(seconds)


def _retry_delay(base: float, attempt: int, *, cap: float = 60.0) -> float:
    """Exponential retry delay with jitter to avoid synchronized workers."""
    base = max(0.0, float(base or 0.0))
    if not base:
        return 0.0
    delay = min(float(cap), base * (2 ** max(0, attempt - 1)))
    return delay * random.uniform(0.85, 1.15)


def _is_capacity_invalid_state(error: InvalidState) -> bool:
    """Only the platform's max-active variant is retryable."""
    text = " ".join(
        str(value).lower()
        for value in (
            error,
            getattr(error, "message", ""),
            getattr(error, "detail", ""),
        )
    )
    return (
        "max active" in text
        or "maximum active" in text
        or "上限" in text
        or "最大活跃" in text
        or ("同时" in text and "容器" in text)
        or ("active" in text and "limit" in text)
    )


def _actual_cumulative_score(challenges: list[Challenge], workspace_dir: str) -> int:
    """
    优先用 submit 回传落盘的 cumulative_score（含 hint 扣分后的实际累计分）；
    找不到记录时回退到题目满分（未看过 hint 的题等价于满分）。
    """
    total = 0
    for c in challenges:
        challenge_dir = os.path.join(workspace_dir, c.unique_code)
        score_file = os.path.join(challenge_dir, ".cumulative_score")
        try:
            # 部分完成题也可能已经获得分数，不能只统计 is_completed。
            if not score_belongs_to_current_task(challenge_dir):
                continue
            with open(score_file, "r", encoding="utf-8") as f:
                total += max(0, int(f.read().strip()))
        except (OSError, ValueError):
            # 只有 API 明确报告通关时才可安全回退到满分；未通关题
            # 的本地 score 文件缺失只能按 0 处理。
            if c.is_completed:
                total += c.total_score
    return total


# 历史题目攻击链注入已按评测合规要求移除。只允许把抽象原则写入
# skills/experiences/references/case-notes.md；TaskBuilder 保留兼容回调。
def _load_recent_chain(unique_code: str, skills_dir: str = "") -> str:
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
        skip_completed: bool = True,
        skip_codes: set[str] | None = None,
        prefix_filter: str | None = None,
        only_codes: set[str] | None = None,
        max_parallel: int = DEFAULT_MAX_PARALLEL,
        agent_factory=None,
        start_retry_max: int = _START_RETRY_MAX,
        start_retry_interval: float = _START_RETRY_INTERVAL,
        close_retry_max: int = _CLOSE_RETRY_MAX,
        close_retry_interval: float = _CLOSE_RETRY_INTERVAL,
        deadline: float | None = None,
    ) -> None:
        self.client = client
        self.settings = settings
        self.skills_dir = skills_dir
        self.workspace_dir = workspace_dir
        self.skip_completed = skip_completed
        self.skip_codes = skip_codes or set()
        self.prefix_filter = prefix_filter.strip() if prefix_filter else None
        self.only_codes = only_codes or set()
        # 平台最多同时运行 3 个容器；额外的 worker 只会制造
        # max-active 重试和 LLM 争抢，因此在调度器边界强制限幅。
        self.max_parallel = min(3, max(1, int(max_parallel)))
        self._agent_factory = agent_factory or _default_agent_factory
        self._active_codes: set[str] = set()
        self._active_lock = threading.Lock()
        self._platform_state_lock = threading.RLock()
        self._scoreboard = Scoreboard(workspace_dir)
        self.start_retry_max = start_retry_max
        self.start_retry_interval = start_retry_interval
        self.close_retry_max = close_retry_max
        self.close_retry_interval = close_retry_interval
        self.deadline = float(deadline or 0.0)
        self._terminal_error: Exception | None = None
        self._abort_event = threading.Event()

    def run_all(self) -> SchedulerReport:
        """主调度循环：VPN 检测 -> 列题 -> 并行攻破。"""
        report = SchedulerReport()
        if _deadline_reached(self.deadline):
            _emit("scheduler_done", {"reason": "deadline_exceeded"})
            return report
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
        except (TaskNotFound, InvalidState) as e:
            # token 无效或任务已结束不是普通题目失败，必须立即终止
            # 整个跑分流程，不能进入下一轮重试。
            _emit("scheduler_terminal_error", {
                "phase": "list_challenges",
                "code": getattr(e, "code", ""),
                "error": str(e),
            })
            raise
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

        # 精确题号过滤：只跑指定题号（用于专项研究能力瓶颈题）
        if self.only_codes:
            todo = [c for c in todo if c.unique_code in self.only_codes]
            _emit("only_codes", {"codes": sorted(self.only_codes), "matched": len(todo)})

        # 跳过被暂停的题目（跨重跑连续无新增 flag/实质证据）
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
        if _deadline_reached(self.deadline):
            _emit("scheduler_done", {"reason": "deadline_exceeded"})
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
        except (TaskNotFound, InvalidState) as e:
            _emit("scheduler_terminal_error", {
                "phase": "final_list_challenges",
                "code": getattr(e, "code", ""),
                "error": str(e),
            })
            raise
        except Exception:
            # A transient final snapshot failure does not erase per-submit
            # scores already persisted in the workspace.
            report.cumulative_score = _actual_cumulative_score(
                all_challenges, self.workspace_dir
            )

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
                "new_flags": result.new_flag_count,
                "material_progress": result.material_progress_count,
                "rounds": result.rounds,
                "error": result.error,
            })
        return results

    def _run_parallel(self, todo: list[Challenge]) -> list[SchedulerResult]:
        """并行运行题目；每个 attempt 返回前都会关闭容器。"""
        results: list[SchedulerResult] = []
        self._abort_event.clear()

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
                except (TaskNotFound, InvalidState) as e:
                    self._terminal_error = e
                    self._abort_event.set()
                    self.close_all_active()
                    raise
                except Exception as e:
                    result = SchedulerResult(
                        unique_code=challenge.unique_code,
                        success=False,
                        error=f"Worker exception: {e}",
                        correct_flag_count=challenge.correct_flag_count,
                        total_flag_count=challenge.flag_count,
                        initial_correct_flag_count=challenge.correct_flag_count,
                        difficulty=challenge.difficulty,
                    )
                results.append(result)
                _emit("challenge_result", {
                    "unique_code": result.unique_code,
                    "success": result.success,
                    "correct": result.correct_flag_count,
                    "total": result.total_flag_count,
                    "new_flags": result.new_flag_count,
                    "material_progress": result.material_progress_count,
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
        role: str = "executor",
        objective: str = "完成当前题目并验证提交结果",
        success_condition: str = "获得可重复验证的 flag 或明确记录终止边界",
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
            role=role,
            objective=objective,
            success_condition=success_condition,
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
        terminal_error: list[Exception] = []
        best_result = SchedulerResult(
            unique_code=code,
            success=False,
            total_flag_count=challenge.flag_count,
            correct_flag_count=challenge.correct_flag_count,
            initial_correct_flag_count=challenge.correct_flag_count,
            difficulty=challenge.difficulty,
        )

        base_context = RunContext(
            unique_code=code,
            challenge_id=code,
            challenge_dir=challenge_workspace,
            target_url=url,
            deadline=self.deadline,
            run_id=os.environ.get("CTF_RUN_ID", ""),
        )

        portfolio = build_portfolio(challenge)
        memory_scope = challenge_memory_scope(challenge)
        observer_leader = portfolio[0].name
        portfolio_budget = PortfolioBudget(expected_attempts=len(portfolio))
        _emit("multi_solver_memory_scope", {
            "unique_code": code,
            "memory_scope": memory_scope,
            "attempts": [spec.name for spec in portfolio],
        })

        def _run_one(spec):
            """运行一个 Solver 实例。"""
            try:
                attempt_context = base_context.for_attempt(
                    spec.name, memory_scope=memory_scope
                )
                with _ctx.bind(attempt_context, self.client):
                    return _run_bound_attempt(spec, attempt_context)
            except (TaskNotFound, InvalidState) as e:
                # A benchmark task ending is process-wide, not a failed
                # strategy.  Preserve it so the outer scheduler can stop
                # instead of silently starting another Solver.
                with result_lock:
                    if not terminal_error:
                        terminal_error.append(e)
                    stop_event.set()
                    self._abort_event.set()
                _emit("scheduler_terminal_error", {
                    "unique_code": code,
                    "strategy": spec.name,
                    "code": getattr(e, "code", ""),
                    "error": str(e),
                })
            except Exception as e:
                import traceback
                _emit("solver_error", {
                    "unique_code": code,
                    "strategy": spec.name,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                })
            finally:
                portfolio_budget.mark_done(spec.name)

        def _run_bound_attempt(
            spec,
            attempt_context: RunContext,
        ) -> None:
            bridge_tools.configure_tsecbench(self.client, code)

            contract = SubtaskContract(
                task_id=attempt_context.run_id,
                challenge_id=code,
                attempt_id=spec.name,
                objective=spec.objective,
                hypothesis=spec.hypothesis,
                allowed_scope=spec.allowed_scope,
                success_condition=spec.success_condition,
                stop_condition=spec.stop_condition,
            )
            write_contract(attempt_context.attempt_dir, contract)
            _emit("subtask_assigned", {
                "unique_code": code,
                "attempt_id": spec.name,
                "contract": contract.to_dict(),
            })
            task = self._build_agent_task(
                challenge,
                container_addr,
                challenge_workspace,
                strategy_name=spec.name,
                strategy_hint=spec.strategy_hint,
                role=spec.role,
                objective=spec.objective,
                success_condition=spec.success_condition,
                attempt_context=attempt_context,
            ) + "\n\n" + contract.prompt_text()

            strategy_settings = dict(self.settings)
            solver_cfg = dict(strategy_settings.get("solver", {}))
            # One challenge gets one control plane. Multiple Observers racing on
            # the shared Memory/Ideas board produced stale and conflicting edits.
            solver_cfg["observer_enabled"] = spec.name == observer_leader
            strategy_settings["solver"] = solver_cfg

            # 每个 attempt 可指定独立模型：spec.model="pro" → llm.pro_model
            # （默认 deepseek-v4-pro，用于 hard 竞争假设攻坚）。
            # solver.pro_enabled=false 或 LLM_PRO_MODEL 可覆盖全局开关/模型名，
            # 避免重跑时误烧 pro 额度或指向不存在的模型。
            llm_cfg = dict(strategy_settings.get("llm", {}))
            if spec.model:
                pro_enabled = str(solver_cfg.get("pro_enabled", True)).strip().lower() not in {
                    "0", "false", "no", "off",
                }
                if spec.model == "pro" and pro_enabled:
                    llm_cfg["default_model"] = (
                        llm_cfg.get("pro_model")
                        or os.environ.get("LLM_PRO_MODEL", "").strip()
                        or "deepseek-v4-pro"
                    )
                elif spec.model != "pro":
                    llm_cfg["default_model"] = spec.model
            strategy_settings["llm"] = llm_cfg
            _emit("attempt_model", {
                "unique_code": code,
                "attempt_id": spec.name,
                "model": llm_cfg.get("default_model", ""),
                "spec_model": spec.model or "",
            })

            agent = self._agent_factory(
                task=task,
                settings=strategy_settings,
                skills_dir=self.skills_dir,
            )
            # Register before run so all parallel attempts share one aggregate
            # budget.  A peer that exits early releases its unused quota.
            try:
                quota = int(agent.max_rounds)
            except (TypeError, ValueError):
                quota = 100
            quota = quota if quota > 0 else 100
            portfolio_budget.register(spec.name, quota)
            portfolio_budget.wait_until_ready(timeout=2.0)
            try:
                agent.max_rounds = max(quota, portfolio_budget.total_quota)
            except Exception:
                pass
            agent._portfolio_budget = portfolio_budget
            agent._portfolio_attempt_id = spec.name
            agent._stop_event = stop_event

            agent.run()

            # 记录结果。rounds 使用两个策略的总消耗，使题目级预算看到
            # Multi-Solver 的真实成本，而不是只记录获胜策略。
            with result_lock:
                best_result.rounds += agent.round
                best_result.material_progress_count += int(
                    getattr(agent, "_material_progress_count", 0) or 0
                )
                if agent.solved:
                    stop_event.set()  # 通知另一个停止
                    best_result.success = True
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
            if self.deadline:
                remaining = max(0.0, self.deadline - time.time())
                # 给正在收尾的 Solver 少量宽限时间；bash 层会把新命令
                # 的 timeout 截到同一个 deadline，不会无限挂住调度器。
                thread.join(timeout=remaining + 5.0)
            else:
                thread.join()
            if thread.is_alive():
                stop_event.set()
                _emit("multi_solver_timeout", {
                    "unique_code": code,
                    "strategy": thread.name,
                })

        if terminal_error:
            raise terminal_error[0]
        _emit("multi_solver_budget", {
            "unique_code": code,
            **portfolio_budget.snapshot(),
        })
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
                        closed = self.client.close_challenge(code)
                        if hasattr(closed, "closed") and not closed.closed:
                            raise RuntimeError("平台未确认容器已关闭")
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
                            _sleep_retry(self.close_retry_interval, self.deadline)
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
            initial_correct_flag_count=challenge.correct_flag_count,
            difficulty=challenge.difficulty,
        )

        # A terminal platform error in another worker aborts queued work too;
        # otherwise ThreadPoolExecutor would start every remaining challenge
        # before the outer loop gets a chance to propagate the error.
        if self._abort_event.is_set():
            result.error = "scheduler_aborted"
            self._scoreboard.mark_skipped(code, result.error)
            return result

        # start_challenge 带重试：平台可能暂时认为容器数已满（close 延迟释放）
        container_addr: tuple[str, ...] = ()
        import time as _time
        _t_start_begin = _time.time()
        for attempt in range(1, self.start_retry_max + 1):
            if _deadline_reached(self.deadline):
                result.error = "deadline_exceeded"
                self._scoreboard.mark_skipped(code, result.error)
                return result
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
            except InvalidState as e:
                if not _is_capacity_invalid_state(e):
                    _emit("scheduler_terminal_error", {
                        "unique_code": code,
                        "code": getattr(e, "code", "invalid_state"),
                        "error": str(e),
                    })
                    raise
                wait = _retry_delay(self.start_retry_interval, attempt)
                _emit("challenge_start_retry", {
                    "unique_code": code,
                    "attempt": attempt,
                    "reason": str(e),
                    "wait": round(wait, 2),
                    "elapsed_so_far_s": round(_time.time() - _t_start_begin, 2),
                })
                if attempt < self.start_retry_max:
                    _sleep_retry(wait, self.deadline)
                else:
                    _emit("challenge_skip", {"unique_code": code, "reason": str(e)})
                    result.error = str(e)
                    self._scoreboard.mark_skipped(code, str(e))
                    return result
            except ResourceUnavailable as e:
                wait = _retry_delay(self.start_retry_interval, attempt)
                _emit("challenge_start_retry", {
                    "unique_code": code,
                    "attempt": attempt,
                    "reason": str(e),
                    "wait": round(wait, 2),
                    "elapsed_so_far_s": round(_time.time() - _t_start_begin, 2),
                })
                if attempt < self.start_retry_max:
                    _sleep_retry(wait, self.deadline)
                else:
                    _emit("challenge_skip", {"unique_code": code, "reason": str(e)})
                    result.error = str(e)
                    self._scoreboard.mark_skipped(code, str(e))
                    return result
            except TsecbenchConnectionError as e:
                # 连接超时：服务端可能已启动容器但客户端没收到响应
                # 尝试 close 释放可能占用的槽位，然后重试
                wait = _retry_delay(self.start_retry_interval, attempt)
                _emit("challenge_start_retry", {
                    "unique_code": code,
                    "attempt": attempt,
                    "reason": f"connection_error: {e}",
                    "wait": round(wait, 2),
                    "elapsed_so_far_s": round(_time.time() - _t_start_begin, 2),
                })
                # 尝试 close（可能服务端已启动）
                try:
                    self.client.close_challenge(code)
                except Exception:
                    pass
                if attempt < self.start_retry_max:
                    _sleep_retry(wait, self.deadline)
                else:
                    _emit("challenge_skip", {"unique_code": code, "reason": str(e)})
                    result.error = str(e)
                    self._scoreboard.mark_skipped(code, str(e))
                    return result
            except TaskNotFound:
                # A token/task failure is process-wide, never a per-challenge
                # start failure.
                raise
            except TsecbenchError as e:
                _emit("challenge_error", {"unique_code": code, "error": str(e)})
                result.error = str(e)
                self._scoreboard.mark_skipped(code, str(e))
                return result

        # 每题独立的工作目录（并行安全）
        challenge_workspace = os.path.join(self.workspace_dir, code)
        os.makedirs(challenge_workspace, exist_ok=True)
        # Reset persistent Memory/Ideas/journals when this mounted workspace
        # belongs to another benchmark task before any Solver sees it.
        if prepare_challenge_state(challenge_workspace):
            _emit("challenge_state_reset", {"unique_code": code})

        target = container_addr[0] if container_addr else ""

        run_context = RunContext(
            unique_code=code,
            challenge_id=code,
            challenge_dir=challenge_workspace,
            target_url=target,
            deadline=self.deadline,
            run_id=os.environ.get("CTF_RUN_ID", ""),
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
            except (TaskNotFound, InvalidState):
                raise
            except Exception:
                pass
            self._record_attempt_outcome(challenge_workspace, result)
            # close; retain the active marker on failure so the outer
            # finally/close_all_active path can retry rather than leaking a
            # container slot silently.
            close_ok = False
            for attempt in range(1, self.close_retry_max + 1):
                try:
                    closed = self.client.close_challenge(code)
                    if hasattr(closed, "closed") and not closed.closed:
                        raise RuntimeError("平台未确认容器已关闭")
                    close_ok = True
                    break
                except Exception:
                    if attempt < self.close_retry_max:
                        _sleep_retry(self.close_retry_interval, self.deadline)
            if close_ok:
                with self._active_lock:
                    self._active_codes.discard(code)
            else:
                _emit("challenge_close_error", {
                    "unique_code": code,
                    "error": "multi-solver close failed",
                })
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

        contract = SubtaskContract(
            task_id=run_context.run_id,
            challenge_id=code,
            attempt_id="primary",
            objective="完成当前题目并验证提交结果",
            hypothesis="选择一个有证据支持的最短解法并验证提交",
            success_condition="获得可重复验证的 flag 或明确记录终止边界",
            stop_condition="无新证据时停止重复并记录失败边界",
        )
        write_contract(run_context.attempt_dir, contract)
        _emit("subtask_assigned", {
            "unique_code": code,
            "attempt_id": "primary",
            "contract": contract.to_dict(),
        })
        task = self._build_agent_task(
            challenge,
            container_addr,
            challenge_workspace,
            attempt_context=run_context,
        ) + "\n\n" + contract.prompt_text()

        try:
            agent = self._agent_factory(
                task=task,
                settings=self.settings,
                skills_dir=self.skills_dir,
            )
            if self.max_parallel > 1:
                # A terminal platform error in one worker asks other workers
                # to stop at their next round boundary instead of consuming a
                # full budget after the task has already ended.
                agent._stop_event = self._abort_event
            _emit("timing_agent_start", {
                "unique_code": code,
                "elapsed_since_attempt_begin": round(_time.time() - _t_start_begin, 2),
            })
            agent.run()
            result.rounds = agent.round
            result.material_progress_count = int(
                getattr(agent, "_material_progress_count", 0) or 0
            )
            _emit("timing_agent_done", {
                "unique_code": code,
                "rounds": agent.round,
                "elapsed_since_attempt_begin": round(_time.time() - _t_start_begin, 2),
            })
        except (TaskNotFound, InvalidState):
            # Platform terminal states must not be downgraded to an ordinary
            # solver failure or trigger another challenge/retry round.
            raise
        except Exception as e:
            import traceback
            _emit("solver_error", {
                "unique_code": code,
                "error": str(e),
                "traceback": traceback.format_exc(),
            })
            result.error = str(e)

        # 刷新一次平台状态，同时用于结果统计。
        try:
            updated = self._list_challenges()
            current = next((c for c in updated if c.unique_code == code), None)
            if current:
                result.correct_flag_count = current.correct_flag_count
                result.total_flag_count = current.flag_count
                result.success = current.is_completed
        except (TaskNotFound, InvalidState):
            raise
        except Exception:
            pass

        self._record_attempt_outcome(challenge_workspace, result)

        # close_challenge 带重试：确保平台侧容器被释放，防止槽位泄漏
        close_ok = False
        for attempt in range(1, self.close_retry_max + 1):
            try:
                closed = self.client.close_challenge(code)
                if hasattr(closed, "closed") and not closed.closed:
                    raise RuntimeError("平台未确认容器已关闭")
                close_ok = True
                break
            except Exception as e:
                _emit("challenge_close_retry", {
                    "unique_code": code,
                    "attempt": attempt,
                    "error": str(e),
                })
                if attempt < self.close_retry_max:
                    _sleep_retry(self.close_retry_interval, self.deadline)

        if close_ok:
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
                    closed = self.client.close_challenge(code)
                    if hasattr(closed, "closed") and not closed.closed:
                        raise RuntimeError("平台未确认容器已关闭")
                    with self._active_lock:
                        self._active_codes.discard(code)
                    break
                except Exception:
                    if attempt < self.close_retry_max - 1:
                        _sleep_retry(self.close_retry_interval, self.deadline)

    def _list_challenges(self) -> list[Challenge]:
        """Serialize state snapshots so parallel attempts see a coherent platform view."""
        with self._platform_state_lock:
            return self.client.list_challenges()

    @staticmethod
    def _record_attempt_outcome(
        challenge_workspace: str,
        result: SchedulerResult,
    ) -> None:
        try:
            ChallengeLedger(challenge_workspace).record_attempt({
                "initial_correct_flags": result.initial_correct_flag_count,
                "final_correct_flags": result.correct_flag_count,
                "new_flags": result.new_flag_count,
                "material_progress": result.material_progress_count,
                "rounds": result.rounds,
                "success": result.success,
                "error": result.error[:300],
            })
        except Exception as exc:
            _emit("challenge_ledger_error", {
                "unique_code": result.unique_code,
                "phase": "record_attempt",
                "error": str(exc),
            })

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
