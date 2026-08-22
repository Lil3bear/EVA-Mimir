import json
import os
import sys
import time
import threading
import uuid
from pathlib import Path

from shared.jsonl import deserialize, write_line
from shared.bridge_types import SolverInitPayload
from solver.runtime.settings import (
    apply_llm_gateway as _apply_llm_gateway,
    load_settings as _load_settings_from_env,
)
from solver.tools import bridge_tools
from solver.runtime.submission_store import score_belongs_to_current_task


def _emit(event_type: str, data=None) -> None:
    write_line({"type": event_type, "data": data})


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"环境变量 {name} 必须是整数，实际为 {raw!r}") from exc
    if value < minimum:
        raise ValueError(f"环境变量 {name} 必须大于等于 {minimum}，实际为 {value}")
    return value


def _read_stdin_loop(agent) -> None:
    """持续监听 stdin，处理 Host 发来的指令和 Bridge 响应。"""
    buffer = ""
    while True:
        chunk = sys.stdin.read(1)
        if not chunk:
            break
        buffer += chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                msg = deserialize(line)
                _handle_host_msg(msg, agent)
            except Exception as e:
                _emit("error", {"msg": f"解析 Host 消息失败：{e}"})


def _handle_host_msg(msg: dict, agent) -> None:
    msg_type = msg.get("type", "")

    # Host Bridge 响应 → 交给 bridge_tools 解锁等待中的请求
    if msg_type == "host_bridge_response":
        request_id = msg.get("request_id", "")
        bridge_tools.register_response(request_id, msg)
        return

    # Observer 纠偏消息 → 注入到 Agent 对话
    if msg_type == "steer" or msg_type == "follow_up":
        message = msg.get("message", "")
        if message and agent:
            agent.inject_message(message)
        return

    # 中止指令
    if msg_type == "abort":
        _emit("agent_end", {"reason": "aborted"})
        sys.exit(0)


def _run_tsecbench_mode() -> None:
    """
    Tsecbench 比赛模式：检测到 BENCHMARK_TOKEN 和 BENCHMARK_BASE_URL 时自动进入。
    使用调度器遍历所有题目，逐题解题。
    支持多轮重跑：第一遍跑全部 63 题，后续轮次只跑失败题，
    连续两轮都失败的题放弃。
    """
    from solver.ctfplatform.tsecbench_client import (
        InvalidState,
        TaskNotFound,
        TsecbenchClient,
        VpnCheckError,
    )
    from solver.ctfplatform.scheduler import Scheduler

    _emit("mode", {"mode": "tsecbench"})
    # Deadline covers preflight, LLM probe, retries and solver work—not only
    # the first challenge attempt.
    run_start_time = time.time()

    # 从环境变量读取 LLM 配置（比赛环境下可能通过环境变量传入）
    try:
        settings = _load_settings_from_env()
    except ValueError as exc:
        _emit("error", {"msg": f"配置加载失败：{exc}"})
        sys.exit(1)

    # 强制前置 VPN 健康检查：任何 LLM 探测或挑战 API 之前，先确认
    # http://10.0.100.58 返回 status=ok。Scheduler 会再次检查以覆盖
    # 长时间运行期间 VPN 断线的情况。
    try:
        client = TsecbenchClient.from_env()
        vpn = client.check_vpn()
        _emit("vpn_preflight_ok", {
            "client_ip": vpn.client_ip,
            "time": vpn.time,
        })
    except VpnCheckError as exc:
        _emit("error", {"msg": "VPN检测未通过,请检查靶场VPN网络配置", "detail": str(exc)})
        if "client" in locals():
            client.close()
        sys.exit(1)
    except ValueError as exc:
        _emit("error", {"msg": f"Tsecbench 客户端初始化失败：{exc}"})
        sys.exit(1)

    # 验证 LLM 配置
    llm_cfg = settings.get("llm", {})
    llm_url = llm_cfg.get("base_url") or os.environ.get("LLM_BASE_URL", "")
    llm_key = llm_cfg.get("api_key") or os.environ.get("LLM_API_KEY", "")

    # 托管模式只能访问平台网关。即使旧的 settings.local.json 中残留
    # 公网 URL，也要在进入 Solver 前强制改写，避免托管沙箱访问公网。
    if not llm_url:
        llm_url = "http://api.deepseek.com.tsecbench.gw/v1"
    else:
        # Always normalize hosted URLs, including a manually suffixed
        # https://...tsecbench.gw value.
        llm_url = _apply_llm_gateway(llm_url, {"LLM_GATEWAY": "1"})
    llm_cfg["base_url"] = llm_url

    if not llm_key:
        _emit("error", {"msg": (
            "LLM_API_KEY 未配置。请在平台运行时环境变量中添加：\n"
            "  LLM_API_KEY=<你的大模型 API Key>\n"
            "可选：LLM_MODEL=deepseek-v4-flash（默认已是）、LLM_GATEWAY=1（自动改写网关）。"
        )})
        sys.exit(1)
    _emit("llm_config", {"base_url": llm_url, "model": llm_cfg.get("default_model", "deepseek-v4-flash")})

    # ━━ LLM 连通性测试 ━━
    _emit("llm_probe", {"status": "testing", "url": llm_url})
    try:
        import httpx
        from openai import OpenAI
        probe_client = OpenAI(
            base_url=llm_url,
            api_key=llm_key,
            timeout=httpx.Timeout(10.0, connect=8.0),
        )
        probe_model = llm_cfg.get("default_model") or os.environ.get("LLM_MODEL", "deepseek-v4-flash")
        probe_resp = probe_client.chat.completions.create(
            model=probe_model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=4,
        )
        probe_content = getattr(probe_resp.choices[0].message, "content", None) or getattr(probe_resp.choices[0].message, "model_extra", {}).get("reasoning_content", "")
        _emit("llm_probe_ok", {"model": probe_model, "response": (probe_content or "")[:50]})
    except Exception as e:
        _emit("llm_probe_fail", {"url": llm_url, "error": str(e), "type": type(e).__name__})

    workspace_dir = os.environ.get("CTF_WORKSPACE", "/workspace")
    skills_dir = os.environ.get("CTF_SKILLS_DIR", "/skills")
    os.environ.setdefault("CTF_WORKSPACE", workspace_dir)
    os.environ.setdefault("CTF_SKILLS_DIR", skills_dir)

    # 并行度：settings.solver.max_parallel 或环境变量 SOLVER_MAX_PARALLEL（默认 3）
    max_parallel = settings.get('solver', {}).get('max_parallel', 3)
    try:
        if os.environ.get('SOLVER_MAX_PARALLEL'):
            max_parallel = _env_int('SOLVER_MAX_PARALLEL', 3, minimum=1)
        else:
            max_parallel = int(max_parallel)
    except (TypeError, ValueError) as exc:
        _emit("error", {"msg": str(exc)})
        client.close()
        sys.exit(1)
    # 平台上限是 3；调度器也会再次限幅，入口处先规范化日志和配置。
    max_parallel = min(3, max(1, max_parallel))

    # 前缀过滤：只跑指定前缀的题目（如 SOLVER_PREFIX_FILTER=b- 只跑多阶段渗透）
    prefix_filter = os.environ.get('SOLVER_PREFIX_FILTER', '').strip() or None

    # 多轮重跑参数
    try:
        total_timeout_min = _env_int('SOLVER_TOTAL_TIMEOUT', 350, minimum=0)
        max_retry_rounds = _env_int('SOLVER_MAX_RETRY_ROUNDS', 5, minimum=0)
    except ValueError as exc:
        _emit("error", {"msg": str(exc)})
        client.close()
        sys.exit(1)
    start_time = run_start_time
    # 同一进程内的重跑共享 run_id；SubmissionStore 用它清理旧 run 的
    # 错误猜测，同时保留本次 run 已经正确提交的 flag。
    os.environ.setdefault("CTF_RUN_ID", uuid.uuid4().hex)
    deadline = start_time + max(0, total_timeout_min) * 60

    # 连续 MAX_FAIL_STREAK 轮都失败（0 correct）的题 → 放弃
    fail_streak: dict[str, int] = {}  # 每题连续失败轮数
    abandoned_codes: set[str] = set()
    MAX_FAIL_STREAK = 4
    cumulative_report: dict = {}
    # Only report a total count that came from a successful platform snapshot;
    # never hard-code a presumed benchmark size after a terminal error.
    known_total_count = 0
    round_idx = 0
    terminal_error_code = ""

    for round_idx in range(1, max_retry_rounds + 1):
        elapsed_min = (time.time() - start_time) / 60
        remaining_min = total_timeout_min - elapsed_min
        if remaining_min < 5:
            _emit("retry_stop", {"reason": "time_up", "remaining_min": round(remaining_min, 1)})
            break

        _emit("retry_round_start", {
            "round": round_idx,
            "elapsed_min": round(elapsed_min, 1),
            "remaining_min": round(remaining_min, 1),
            "abandoned": len(abandoned_codes),
        })

        # 剩余时间 < 20% 时，跳过未尝试过的 hard 题（不值得开新坑）
        time_ratio = remaining_min / total_timeout_min if total_timeout_min > 0 else 1.0
        skip_hard_new = set()
        if time_ratio < 0.2 and round_idx > 1:
            try:
                all_ch = client.list_challenges()
                known_total_count = len(all_ch)
                for c in all_ch:
                    if (c.difficulty.lower() in ("hard", "difficult")
                            and not c.is_completed
                            and c.correct_flag_count == 0
                            and c.unique_code not in abandoned_codes):
                        skip_hard_new.add(c.unique_code)
                if skip_hard_new:
                    _emit("skip_hard_time_pressure", {
                        "codes": sorted(skip_hard_new),
                        "time_ratio": round(time_ratio, 2),
                    })
            except (TaskNotFound, InvalidState) as exc:
                _emit("terminal_error", {
                    "phase": "time_pressure_list_challenges",
                    "code": getattr(exc, "code", ""),
                    "message": str(exc),
                })
                break
            except Exception as exc:
                _emit("warning", {
                    "phase": "time_pressure_list_challenges",
                    "message": str(exc),
                })

        scheduler = Scheduler(
            client=client,
            settings=settings,
            skills_dir=skills_dir,
            workspace_dir=workspace_dir,
            max_parallel=max_parallel,
            deadline=deadline,
            skip_completed=True,
            skip_codes=abandoned_codes | skip_hard_new,
            prefix_filter=prefix_filter,
        )

        try:
            report = scheduler.run_all()
            known_total_count = max(known_total_count, report.total_challenges)
        except (TaskNotFound, InvalidState) as e:
            terminal_error_code = getattr(e, "code", "") or type(e).__name__
            _emit("terminal_error", {
                "code": terminal_error_code,
                "message": str(e),
            })
            scheduler.close_all_active()
            break
        except KeyboardInterrupt:
            _emit("scheduler_interrupted", {})
            scheduler.close_all_active()
            sys.exit(130)
        except Exception as e:
            import traceback
            _emit("error", {"msg": f"调度器异常：{e}", "traceback": traceback.format_exc()})
            scheduler.close_all_active()
            break

        # 统计本轮失败的题目
        this_round_failed: set[str] = set()
        this_round_solved = 0
        for r in report.results:
            if r.success:
                this_round_solved += 1
                fail_streak.pop(r.unique_code, None)
            elif r.correct_flag_count == 0:
                this_round_failed.add(r.unique_code)
            else:
                # 部分解出（correct > 0），重置失败计数
                fail_streak.pop(r.unique_code, None)

        _emit("retry_round_end", {
            "round": round_idx,
            "attempted": report.attempted,
            "solved": this_round_solved,
            "failed": len(this_round_failed),
        })

        # 更新连续失败计数
        for code in this_round_failed:
            fail_streak[code] = fail_streak.get(code, 0) + 1

        # 连续 MAX_FAIL_STREAK 轮失败 → 放弃
        newly_abandoned = {code for code, streak in fail_streak.items() if streak >= MAX_FAIL_STREAK}
        abandoned_codes |= newly_abandoned
        for code in newly_abandoned:
            fail_streak.pop(code, None)
        if newly_abandoned:
            _emit("retry_abandoned", {
                "codes": sorted(newly_abandoned),
                "total_abandoned": len(abandoned_codes),
            })

        # 检查是否还有未完成的题
        try:
            remaining_challenges = client.list_challenges()
            known_total_count = len(remaining_challenges)
            undone = [
                c for c in remaining_challenges
                if not c.is_completed and c.unique_code not in abandoned_codes
            ]
            if not undone:
                _emit("retry_stop", {"reason": "all_completed"})
                break
        except (TaskNotFound, InvalidState) as exc:
            _emit("terminal_error", {
                "phase": "retry_list_challenges",
                "code": getattr(exc, "code", ""),
                "message": str(exc),
            })
            break
        except Exception as exc:
            _emit("warning", {
                "phase": "retry_list_challenges",
                "message": str(exc),
            })

    # 最终报告
    try:
        final_challenges = client.list_challenges()
        total_score = 0
        for c in final_challenges:
            challenge_dir = Path(workspace_dir) / c.unique_code
            score_file = challenge_dir / ".cumulative_score"
            try:
                if not score_belongs_to_current_task(challenge_dir):
                    continue
                total_score += max(0, int(score_file.read_text(encoding="utf-8").strip()))
            except (OSError, ValueError):
                if c.is_completed:
                    total_score += c.total_score
        total_solved = sum(1 for c in final_challenges if c.is_completed)
        total_count = len(final_challenges)
    except (TaskNotFound, InvalidState) as exc:
        # 任务结束后 list 接口可能返回 invalid_state；token 无效则是
        # task_not_found。两者都要进入终态报告，不能伪装成普通网络异常。
        if not terminal_error_code:
            terminal_error_code = getattr(exc, "code", "") or type(exc).__name__
        _emit("terminal_error", {
            "phase": "final_list_challenges",
            "code": terminal_error_code,
            "message": str(exc),
        })
        total_score = 0
        total_solved = 0
        total_count = known_total_count
        # Preserve scores already acknowledged by submit responses even when
        # the final snapshot is rejected because the benchmark ended.
        try:
            base = Path(workspace_dir)
            if base.is_dir():
                for score_file in base.glob("*/.cumulative_score"):
                    if not score_belongs_to_current_task(score_file.parent):
                        continue
                    try:
                        total_score += max(0, int(score_file.read_text(encoding="utf-8").strip()))
                    except (OSError, ValueError):
                        continue
                    if score_file.with_name(".completed").exists():
                        total_solved += 1
        except Exception:
            pass
    except Exception:
        # 其它最终快照失败也改为从工作区落盘的实际得分统计；如果此时
        # 已知 token/task 终止状态，保持终态计数语义。
        total_score = 0
        total_solved = 0
        total_count = known_total_count
        try:
            base = Path(workspace_dir)
            if base.is_dir():
                for score_file in base.glob("*/.cumulative_score"):
                    try:
                        if not score_belongs_to_current_task(score_file.parent):
                            continue
                        total_score += max(0, int(score_file.read_text(encoding="utf-8").strip()))
                    except (OSError, ValueError):
                        continue
                    # .completed 由 SubmissionStore 在 API 明确报告全部
                    # flag 完成时写入；仅有累计分不能推断通关。
                    if score_file.with_name(".completed").exists():
                        total_solved += 1
        except Exception:
            pass
    finally:
        client.close()

    _emit("final_report", {
        "total": total_count,
        "solved": total_solved,
        "cumulative_score": total_score,
        "retry_rounds": round_idx,
        "abandoned": len(abandoned_codes),
        "terminal_error": terminal_error_code,
    })

    print(f"\n{'='*60}")
    print(f"  Tsecbench 比赛结束")
    print(f"  总题数：{total_count}")
    print(f"  解出：{total_solved} | 累计得分：{total_score}")
    print(f"  重跑轮数：{round_idx} | 放弃题数：{len(abandoned_codes)}")
    print(f"{'='*60}\n")

    # total_count == 0 只代表没有可信的题目列表（例如 token 无效），
    # 不能被误报为成功；终态错误必须返回非零让托管平台识别失败。
    success = (
        not terminal_error_code
        and total_count > 0
        and total_solved == total_count
    )
    sys.exit(0 if success else 1)


def _run_bridge_mode() -> None:
    """
    本地 Host Bridge 模式：通过 Docker stdin/stdout 与 Host 通信。
    这是现有的单题模式，由 host/main.py 启动。
    """
    _emit("mode", {"mode": "bridge"})

    # 优先从文件读取初始化载荷（避免 Windows Docker stdin pipe 时序问题）
    init_file_value = os.environ.get("CTF_INIT_FILE", "").strip()
    init_file = Path(init_file_value) if init_file_value else None
    init_data = None

    if init_file is not None and init_file.is_file():
        try:
            init_data = json.loads(init_file.read_text(encoding="utf-8"))
        except Exception as e:
            _emit("error", {"msg": f"读取初始化文件失败：{e}"})
            sys.exit(1)
    else:
        # fallback：从 stdin 读第一行
        init_line = ""
        buffer = ""
        while True:
            chunk = sys.stdin.read(1)
            if not chunk:
                break
            buffer += chunk
            if "\n" in buffer:
                init_line, _ = buffer.split("\n", 1)
                break

        if not init_line.strip():
            _emit("error", {"msg": "未收到初始化消息"})
            sys.exit(1)

        try:
            init_data = deserialize(init_line)
        except Exception as e:
            _emit("error", {"msg": f"初始化消息解析失败：{e}"})
            sys.exit(1)

    # 解析初始化载荷
    solver_id = init_data.get("solver_id", "")
    challenge_id = init_data.get("challenge_id", "")
    task = init_data.get("task", "")
    workspace_dir = init_data.get("workspace_dir", "/workspace")
    skills_dir = init_data.get("skills_dir", "/skills")
    settings = init_data.get("settings", {})

    # 设置环境变量供工具使用
    os.environ["CTF_SOLVER_ID"] = solver_id
    os.environ["CTF_CHALLENGE_ID"] = challenge_id
    os.environ["CTF_WORKSPACE"] = workspace_dir
    os.environ["CTF_SKILLS_DIR"] = skills_dir

    from solver.worker_context import RunContext, ctx
    ctx.configure(
        RunContext.create(
            workspace_dir,
            challenge_id,
            target_url=os.environ.get("CTF_TARGET_URL", ""),
        )
    )

    _emit("init_success", {"solver_id": solver_id, "challenge_id": challenge_id})

    # 创建 Agent
    try:
        from solver.agent import SolverAgent
        agent = SolverAgent(task=task, settings=settings, skills_dir=skills_dir)
    except Exception as e:
        import traceback
        _emit("error", {"msg": f"Agent 初始化异常：{e}", "traceback": traceback.format_exc()})
        sys.exit(1)

    # 启动 stdin 监听线程（处理 Host 消息）
    stdin_thread = threading.Thread(
        target=_read_stdin_loop, args=(agent,), daemon=True
    )
    stdin_thread.start()

    # 运行 Agent 主循环（阻塞直到结束）
    try:
        agent.run()
    except Exception as e:
        import traceback
        _emit("error", {"msg": f"Agent 运行异常：{e}", "traceback": traceback.format_exc()})
        sys.exit(1)


def main():
    """
    入口：自动检测运行模式。
    - 存在 BENCHMARK_TOKEN + BENCHMARK_BASE_URL → Tsecbench 比赛模式
    - 否则 → 本地 Host Bridge 模式
    """
    from solver.ctfplatform.tsecbench_client import TsecbenchClient

    if TsecbenchClient.is_configured():
        _run_tsecbench_mode()
    else:
        _run_bridge_mode()


if __name__ == "__main__":
    main()
