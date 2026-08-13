import subprocess
import threading
import json
import time
import uuid
from pathlib import Path
from typing import Callable, Any

from shared.jsonl import serialize, deserialize
from shared.bridge_types import SolverInitPayload, SolverEvent


class DockerManager:
    def __init__(self, image_name: str, settings: dict):
        self.image_name = image_name
        self.settings = settings
        self._proc: subprocess.Popen | None = None
        self._solver_id: str = ""
        self._event_handlers: list[Callable[[SolverEvent], None]] = []
        self._bridge_handler: Callable[[dict], Any] | None = None
        self._lock = threading.Lock()
        self._pending: dict[str, threading.Event] = {}
        self._responses: dict[str, dict] = {}

    def on_event(self, handler: Callable[[SolverEvent], None]) -> None:
        self._event_handlers.append(handler)

    def set_bridge_handler(self, handler: Callable[[dict], Any]) -> None:
        self._bridge_handler = handler

    def build_image(self, project_root: Path) -> None:
        fastcoll_path = project_root / "docker" / "fastcoll"
        if not fastcoll_path.is_file():
            raise RuntimeError(
                f"缺少 Docker 构建依赖：{fastcoll_path}。"
                "请先放置可执行的 linux/amd64 fastcoll，再构建镜像。"
            )
        print(f"[Docker] 构建镜像 {self.image_name} ...")
        result = subprocess.run(
            ["docker", "build", "-t", self.image_name,
             "-f", str(project_root / "docker" / "Dockerfile"),
             str(project_root)],
            capture_output=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"镜像构建失败，退出码 {result.returncode}")
        print(f"[Docker] 镜像构建完成")

    def launch(self, init_payload: SolverInitPayload,
               workspace_dir: Path, skills_dir: Path,
               project_root: Path) -> str:
        self._solver_id = init_payload.solver_id
        challenge_workspace = workspace_dir / init_payload.challenge_id

        # 把 init payload 写到 workspace，容器从文件读而不是从 stdin 读
        # 避免 Windows Docker Desktop 的 stdin pipe 时序问题
        init_file = challenge_workspace / ".init_payload.json"
        init_file.write_text(
            json.dumps(init_payload.__dict__, ensure_ascii=False),
            encoding="utf-8",
        )

        cmd = [
            "docker", "run", "--rm", "--interactive",
            "--platform", "linux/amd64",
            "--network", self.settings.get("network_mode", "host"),
            "--name", f"ctf-agent-{self._solver_id}",
            "-v", f"{project_root / 'shared'}:/opt/ctf-agent/shared:ro",
            "-v", f"{project_root / 'solver'}:/opt/ctf-agent/solver:ro",
            "-v", f"{project_root / 'prompts'}:/opt/ctf-agent/prompts:ro",
            "-v", f"{challenge_workspace}:/workspace:rw",
            "-v", f"{skills_dir}:/skills:ro",
            "-e", f"CTF_SOLVER_ID={self._solver_id}",
            "-e", f"CTF_WORKSPACE=/workspace",
            "-e", f"CTF_SKILLS_DIR=/skills",
            "-e", f"CTF_INIT_FILE=/workspace/.init_payload.json",
            self.image_name,
        ]

        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )

        # 启动读取线程
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

        return self._solver_id

    def _write(self, obj: dict) -> None:
        with self._lock:
            if self._proc and self._proc.stdin:
                self._proc.stdin.write(serialize(obj))
                self._proc.stdin.flush()

    def _read_stdout(self) -> None:
        buffer = ""
        while self._proc and self._proc.stdout:
            chunk = self._proc.stdout.read(1)
            if not chunk:
                break
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if line:
                    try:
                        msg = deserialize(line)
                        self._dispatch(msg)
                    except Exception as e:
                        print(f"[Docker] 解析消息失败: {e} | 原始: {line}")

    def _read_stderr(self) -> None:
        while self._proc and self._proc.stderr:
            line = self._proc.stderr.readline()
            if not line:
                break
            print(f"[容器stderr] {line.rstrip()}")

    def _dispatch(self, msg: dict) -> None:
        msg_type = msg.get("type", "")

        # Host Bridge 请求
        if msg_type == "host_bridge_request":
            if self._bridge_handler:
                response = self._bridge_handler(msg)
                self._write(response)
            return

        # 挂起的 send_command 响应
        if msg_type == "rpc_response":
            req_id = msg.get("request_id", "")
            self._responses[req_id] = msg
            event = self._pending.pop(req_id, None)
            if event:
                event.set()
            return

        # 普通事件，广播给 TUI 等监听者
        event = SolverEvent(
            solver_id=self._solver_id,
            type=msg_type,
            data=msg.get("data"),
        )
        for handler in self._event_handlers:
            handler(event)

    def send_command(self, cmd_type: str, message: str = "",
                     timeout: float = 10.0) -> dict | None:
        req_id = uuid.uuid4().hex[:8]
        done = threading.Event()
        self._pending[req_id] = done
        self._write({"type": cmd_type, "message": message, "request_id": req_id})
        done.wait(timeout=timeout)
        return self._responses.pop(req_id, None)

    def stop(self) -> None:
        if self._proc:
            solver_name = f"ctf-agent-{self._solver_id}"
            subprocess.run(["docker", "stop", solver_name],
                           capture_output=True, timeout=15)

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def wait(self) -> int:
        if self._proc:
            return self._proc.wait()
        return -1
