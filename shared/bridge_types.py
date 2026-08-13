from dataclasses import dataclass
from typing import Any, Literal


# Solver 容器 → Host 的请求
@dataclass
class HostBridgeRequest:
    request_id: str
    action: Literal["challenge_submit_flag", "challenge_get_state", "challenge_get_hint", "challenge_is_completed"]
    params: dict[str, Any]


# Host → Solver 容器的响应
@dataclass
class HostBridgeResponse:
    request_id: str
    success: bool
    data: Any = None
    error: str = ""


# Host → Solver 容器的指令（运行时控制）
@dataclass
class RpcCommand:
    type: Literal["steer", "follow_up", "abort"]
    message: str = ""


# Solver 容器 → Host 的事件（转发给 TUI）
@dataclass
class SolverEvent:
    solver_id: str
    type: str
    data: Any = None


# Solver 容器启动时 Host 发的第一条消息
@dataclass
class SolverInitPayload:
    solver_id: str
    challenge_id: str
    task: str
    workspace_dir: str
    skills_dir: str
    settings: dict[str, Any]
