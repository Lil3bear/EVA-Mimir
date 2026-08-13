import argparse
import json
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

from shared.types import ChallengeConfig
from shared.bridge_types import SolverInitPayload
from shared.data import store
from shared.jsonl import serialize


def load_settings(project_root: Path) -> dict:
    # settings.local.json 优先（不进版本控制，含 API key）
    for name in ["settings.local.json", "settings.json"]:
        path = project_root / name
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return {}


def load_challenge(challenge_path: Path) -> ChallengeConfig:
    data = json.loads(challenge_path.read_text(encoding="utf-8"))
    return ChallengeConfig(**data)


def main():
    parser = argparse.ArgumentParser(description="CTF Agent - Host 主进程")
    parser.add_argument("--challenge", required=True, help="challenge.json 路径")
    parser.add_argument("--build", action="store_true", help="强制重新构建 Docker 镜像")
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent
    settings = load_settings(project_root)

    challenge_path = Path(args.challenge)
    if not challenge_path.exists():
        print(f"[错误] 找不到题目配置文件：{challenge_path}")
        sys.exit(1)

    config = load_challenge(challenge_path)
    workspace_dir = Path(settings.get("docker", {}).get("workspace_dir", "./workspace")).resolve()
    skills_dir = project_root / "skills"
    image_name = settings.get("docker", {}).get("image_name", "ctf-agent-solver")

    # 初始化题目工作目录
    challenge_dir = workspace_dir / config.id
    challenge_dir.mkdir(parents=True, exist_ok=True)
    store.save_challenge_config(workspace_dir, config)

    print(f"[CTF Agent] 题目：{config.name} ({config.category} / {config.difficulty})")
    print(f"[CTF Agent] 目标：{config.url}")
    print(f"[CTF Agent] 工作目录：{challenge_dir}")

    # 构建 Docker 镜像
    from host.docker_manager import DockerManager
    docker = DockerManager(image_name=image_name, settings=settings.get("docker", {}))

    if args.build:
        docker.build_image(project_root)
    else:
        # 检查镜像是否存在
        result = subprocess.run(
            ["docker", "image", "inspect", image_name],
            capture_output=True,
        )
        if result.returncode != 0:
            print(f"[Docker] 镜像 {image_name} 不存在，开始构建...")
            docker.build_image(project_root)

    # 初始化 Bridge Handler
    solver_id = f"solver_{uuid.uuid4().hex[:8]}"
    from host.bridge_handler import BridgeHandler
    from host.tui import TUI
    bridge = BridgeHandler(config=config, workspace_dir=workspace_dir, solver_id=solver_id)
    docker.set_bridge_handler(bridge.handle)

    # 初始化日志文件（UTF-8，带时间戳）
    log_path = project_root / f"run_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    log_file = open(log_path, "w", encoding="utf-8", buffering=1)
    print(f"[CTF Agent] 日志文件：{log_path}")

    def _log_event(event):
        log_file.write(serialize({"type": event.type, "data": event.data}))

    # 初始化 TUI
    tui = TUI(challenge_name=config.name, workspace_dir=workspace_dir, challenge_id=config.id)
    docker.on_event(tui.handle_event)
    docker.on_event(_log_event)

    # 组装初始任务
    solver_settings = settings.get("solver", {})
    task = _build_task(config, workspace_dir, solver_settings)

    init_payload = SolverInitPayload(
        solver_id=solver_id,
        challenge_id=config.id,
        task=task,
        workspace_dir="/workspace",
        skills_dir="/skills",
        settings={
            "llm": settings.get("llm", {}),
            "solver": solver_settings,
        },
    )

    # 启动容器
    print(f"\n[Docker] 启动 Solver 容器 (solver_id={solver_id})...")
    docker.launch(init_payload, workspace_dir, skills_dir, project_root)

    # 启动 TUI
    stop_event = threading.Event()
    tui.start()
    tui_thread = threading.Thread(
        target=tui.run_update_loop, args=(stop_event,), daemon=True
    )
    tui_thread.start()

    # 等待容器结束
    exit_code = docker.wait()
    stop_event.set()
    tui_thread.join(timeout=2)
    tui.stop()
    log_file.close()

    # 输出最终结果
    print(f"\n[Docker] 容器退出，退出码：{exit_code}")

    # 输出最终结果
    submissions = store.list_submissions(workspace_dir, config.id)
    correct = [s for s in submissions if s.correct]
    # 去重（同一 flag 可能被提交多次）
    seen = set()
    unique_correct = []
    for s in correct:
        if s.flag not in seen:
            seen.add(s.flag)
            unique_correct.append(s)
    if unique_correct:
        print(f"\n[✓] 解题成功！共找到 {len(unique_correct)} 个正确 flag：")
        for s in unique_correct:
            print(f"    {s.flag}")
    else:
        print(f"\n[✗] 未找到正确 flag")


def _build_task(config: ChallengeConfig, workspace_dir: Path, solver_settings: dict) -> str:
    from shared.data import memory as mem_store, ideas as idea_store

    challenge_dir = workspace_dir / config.id
    memory_limit = solver_settings.get("memory_limit", 10)
    idea_limit = solver_settings.get("idea_limit", 8)

    memories = mem_store.list_memory(challenge_dir, limit=memory_limit)
    ideas = idea_store.list_ideas(challenge_dir, limit=idea_limit)
    submissions = store.list_submissions(workspace_dir, config.id)
    correct_flags = [s.flag for s in submissions if s.correct]

    lines = [
        f"# CTF 题目：{config.name}",
        f"- 类型：{config.category}",
        f"- 难度：{config.difficulty}",
        f"- 目标地址：{config.url}",
        f"- Flag 格式：{config.flag_format}",
        f"- 描述：{config.description}",
    ]

    if config.hints:
        lines.append(f"- 提示：{'; '.join(config.hints)}")

    if config.difficulty and config.difficulty.lower() in ("hard", "difficult", "medium"):
        lines.append(
            f"\n⚠️ 难度等级：{config.difficulty}。"
            f"按解题流程第3步要求，第 3 轮前必须调用 security_search 搜索本题 writeup，"
            f"关键词：\"{config.name} writeup\" 或 \"{config.name} CTF solution\"。"
        )

    if correct_flags:
        lines.append(f"\n## 已找到的 Flag（不要重复寻找）")
        for f in correct_flags:
            lines.append(f"- {f}")

    if memories:
        lines.append(f"\n## 历史记忆（最近 {len(memories)} 条）")
        for m in memories:
            lines.append(f"- [{m.kind}] {m.content}")

    failed_ideas = [i for i in ideas if i.status == "failed"]
    active_ideas = [i for i in ideas if i.status != "failed"]

    if failed_ideas:
        lines.append(f"\n## ⛔ 已确认失败的攻击方向（禁止重复，直接跳过）")
        for i in failed_ideas:
            result_str = f"（{i.result}）" if i.result else ""
            lines.append(f"- {i.content}{result_str}")

    if active_ideas:
        lines.append(f"\n## 待探索的攻击方向")
        for i in active_ideas:
            lines.append(f"- [{i.status}] {i.content}")

    lines.append(f"\n请开始解题，找到 flag 后调用 challenge_submit_flag 工具提交。")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
