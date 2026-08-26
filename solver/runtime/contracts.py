"""Explicit Planner -> Solver contracts.

A contract is the boundary of one attempt.  It gives a Solver one hypothesis,
one scope and observable success/stop conditions instead of a vague strategy
prompt.  Contracts are durable artifacts under the attempt directory.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SubtaskContract:
    task_id: str
    challenge_id: str
    attempt_id: str
    objective: str
    hypothesis: str = ""
    allowed_scope: str = "current_challenge"
    success_condition: str = ""
    stop_condition: str = ""
    parent_id: str = ""
    contract_id: str = field(default_factory=lambda: f"contract_{uuid.uuid4().hex}")
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def prompt_text(self) -> str:
        return (
            "## 当前 Subtask Contract（只约束本 attempt）\n"
            f"- contract_id: {self.contract_id}\n"
            f"- challenge_id: {self.challenge_id}\n"
            f"- attempt_id: {self.attempt_id}\n"
            f"- objective: {self.objective}\n"
            f"- hypothesis: {self.hypothesis or '未指定'}\n"
            f"- allowed_scope: {self.allowed_scope}\n"
            f"- success_condition: {self.success_condition or '获得可验证新证据或 flag'}\n"
            f"- stop_condition: {self.stop_condition or '重复无新证据时记录边界并换方向'}\n"
            "不要读取其他 attempt 的原始 Memory/Ideas；需要协作时提交结构化 evidence proposal。"
        )


def write_contract(attempt_dir: str | Path, contract: SubtaskContract) -> Path:
    path = Path(attempt_dir) / "subtask-contract.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(contract.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_contract(attempt_dir: str | Path) -> SubtaskContract | None:
    path = Path(attempt_dir) / "subtask-contract.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return SubtaskContract(**data)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
