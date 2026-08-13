import json
import os
import sys
import time
import threading
from pathlib import Path

from shared.jsonl import serialize, deserialize
from shared.bridge_types import SolverInitPayload
from solver.tools import bridge_tools


def _emit(event_type: str, data=None) -> None:
    msg = {"type": event_type, "data": data}
    sys.stdout.write(serialize(msg))
    sys.stdout.flush()


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
    from solver.ctfplatform.tsecbench_client import TsecbenchClient
    from solver.ctfplatform.scheduler import Scheduler

    _emit("mode", {"mode": "tsecbench"})

    # 从环境变量读取 LLM 配置（比赛环境下可能通过环境变量传入）
    settings = _load_settings_from_env()

    # 验证 LLM 配置
    llm_cfg = settings.get("llm", {})
    llm_url = llm_cfg.get("base_url") or os.environ.get("LLM_BASE_URL", "")
    llm_key = llm_cfg.get("api_key") or os.environ.get("LLM_API_KEY", "")
    if not llm_url or not llm_key:
        _emit("error", {"msg": (
            "LLM 配置缺失。请设置环境变量 LLM_BASE_URL 和 LLM_API_KEY。"
            " 比赛环境网关地址示例：LLM_BASE_URL=http://api.deepseek.com.tsecbench.gw"
        )})
        sys.exit(1)
    _emit("llm_config", {"base_url": llm_url, "model": llm_cfg.get("default_model", "deepseek-chat")})

    workspace_dir = os.environ.get("CTF_WORKSPACE", "/workspace")
    skills_dir = os.environ.get("CTF_SKILLS_DIR", "/skills")
    os.environ.setdefault("CTF_WORKSPACE", workspace_dir)
    os.environ.setdefault("CTF_SKILLS_DIR", skills_dir)

    # 创建 Tsecbench 客户端
    try:
        client = TsecbenchClient.from_env()
    except ValueError as e:
        _emit("error", {"msg": f"Tsecbench 客户端初始化失败：{e}"})
        sys.exit(1)

    # 并行度：settings.solver.max_parallel 或环境变量 SOLVER_MAX_PARALLEL（默认 3）
    max_parallel = settings.get('solver', {}).get('max_parallel', 3)
    if os.environ.get('SOLVER_MAX_PARALLEL'):
        max_parallel = int(os.environ['SOLVER_MAX_PARALLEL'])

    # 多轮重跑参数
    total_timeout_min = int(os.environ.get('SOLVER_TOTAL_TIMEOUT', '350'))
    max_retry_rounds = int(os.environ.get('SOLVER_MAX_RETRY_ROUNDS', '5'))
    start_time = time.time()

    # 连续 MAX_FAIL_STREAK 轮都失败（0 correct）的题 → 放弃
    fail_streak: dict[str, int] = {}  # 每题连续失败轮数
    abandoned_codes: set[str] = set()
    MAX_FAIL_STREAK = 4
    cumulative_report: dict = {}

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
            except Exception:
                pass

        scheduler = Scheduler(
            client=client,
            settings=settings,
            skills_dir=skills_dir,
            workspace_dir=workspace_dir,
            max_parallel=max_parallel,
            skip_completed=True,
            skip_codes=abandoned_codes | skip_hard_new,
        )

        try:
            report = scheduler.run_all()
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
            undone = [
                c for c in remaining_challenges
                if not c.is_completed and c.unique_code not in abandoned_codes
            ]
            if not undone:
                _emit("retry_stop", {"reason": "all_completed"})
                break
        except Exception:
            pass

    # 最终报告
    try:
        final_challenges = client.list_challenges()
        total_score = sum(c.total_score for c in final_challenges if c.is_completed)
        total_solved = sum(1 for c in final_challenges if c.is_completed)
        total_count = len(final_challenges)
    except Exception:
        total_score = 0
        total_solved = 0
        total_count = 63
    finally:
        client.close()

    _emit("final_report", {
        "total": total_count,
        "solved": total_solved,
        "cumulative_score": total_score,
        "retry_rounds": round_idx,
        "abandoned": len(abandoned_codes),
    })

    print(f"\n{'='*60}")
    print(f"  Tsecbench 比赛结束")
    print(f"  总题数：{total_count}")
    print(f"  解出：{total_solved} | 累计得分：{total_score}")
    print(f"  重跑轮数：{round_idx} | 放弃题数：{len(abandoned_codes)}")
    print(f"{'='*60}\n")

    sys.exit(0 if total_solved == total_count else 1)


def _load_settings_from_env() -> dict:
    """
    从环境变量加载 settings（比赛环境下不走 settings.json）。
    支持的环境变量：
      LLM_BASE_URL, LLM_API_KEY, LLM_MODEL    → settings.llm
      SOLVER_MAX_ROUNDS, SOLVER_OBSERVER_EVERY → settings.solver
    也尝试从 /workspace/settings.json 或当前目录 settings.json 读取。
    """
    settings: dict = {}

    # 优先从文件加载（settings.local.json 优先，不进版本控制）
    for candidate in ["/workspace/settings.local.json", "/workspace/settings.json",
                      "settings.local.json", "settings.json"]:
        try:
            settings = json.loads(Path(candidate).read_text(encoding="utf-8"))
            break
        except Exception:
            continue

    # 环境变量覆盖
    llm = settings.setdefault("llm", {})
    if os.environ.get("LLM_BASE_URL"):
        llm["base_url"] = os.environ["LLM_BASE_URL"]
    if os.environ.get("LLM_API_KEY"):
        llm["api_key"] = os.environ["LLM_API_KEY"]
    if os.environ.get("LLM_MODEL"):
        llm["default_model"] = os.environ["LLM_MODEL"]

    solver = settings.setdefault("solver", {})
    if os.environ.get("SOLVER_MAX_ROUNDS"):
        solver["max_rounds"] = int(os.environ["SOLVER_MAX_ROUNDS"])
    if os.environ.get("SOLVER_OBSERVER_EVERY"):
        solver["observer_every_rounds"] = int(os.environ["SOLVER_OBSERVER_EVERY"])

    return settings


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
