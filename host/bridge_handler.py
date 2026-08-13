import time
import requests
from pathlib import Path
from typing import Any

from shared.data import store, memory, ideas
from shared.types import ChallengeConfig


class BridgeHandler:
    def __init__(self, config: ChallengeConfig, workspace_dir: Path, solver_id: str):
        self.config = config
        self.workspace_dir = workspace_dir
        self.solver_id = solver_id
        self._challenge_dir = workspace_dir / config.id

    def handle(self, msg: dict) -> dict:
        request_id = msg.get("request_id", "")
        action = msg.get("action", "")
        params = msg.get("params", {})

        try:
            if action == "challenge_submit_flag":
                data = self._submit_flag(params)
            elif action == "challenge_get_state":
                data = self._get_state()
            elif action == "challenge_get_hint":
                data = self._get_hint()
            elif action == "challenge_is_completed":
                data = self._is_completed()
            else:
                raise ValueError(f"未知 action: {action}")

            return {
                "type": "host_bridge_response",
                "request_id": request_id,
                "success": True,
                "data": data,
            }
        except Exception as e:
            return {
                "type": "host_bridge_response",
                "request_id": request_id,
                "success": False,
                "error": str(e),
            }

    def _submit_flag(self, params: dict) -> dict:
        flag = params.get("flag", "").strip()
        writeup = params.get("writeup", "")

        if not flag:
            raise ValueError("flag 不能为空")

        # 检查是否已经提交过同一个 flag
        existing = store.list_submissions(self.workspace_dir, self.config.id)
        for s in existing:
            if s.flag == flag:
                return {"correct": s.correct, "flag": flag, "duplicate": True}

        correct = False

        # 有 submit_url 则调 CTFd API
        if self.config.submit_url and self.config.api_key:
            correct = self._submit_to_ctfd(flag)
        else:
            # 无平台配置，只打印到终端，人工判断
            print(f"\n[Flag] Solver 提交了 flag：{flag}")
            print(f"[Flag] Writeup：{writeup}")
            correct = True  # 无法验证时视为正确，让 Solver 继续

        # 记录提交
        store.append_submission(
            self.workspace_dir, self.config.id,
            flag=flag, correct=correct,
            writeup=writeup, solver_id=self.solver_id,
        )

        if correct:
            print(f"\n[✓] Flag 正确：{flag}")
        else:
            print(f"\n[✗] Flag 错误：{flag}")

        return {"correct": correct, "flag": flag}

    def _submit_to_ctfd(self, flag: str) -> bool:
        headers = {
            "Authorization": f"Token {self.config.api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(
                self.config.submit_url,
                json={"submission": flag},
                headers=headers,
                timeout=10,
            )
            data = resp.json()
            return data.get("data", {}).get("status") == "correct"
        except Exception as e:
            raise RuntimeError(f"CTFd 提交失败：{e}")

    def _get_state(self) -> dict:
        submissions = store.list_submissions(self.workspace_dir, self.config.id)
        correct_flags = [s.flag for s in submissions if s.correct]
        return {
            "challenge_id": self.config.id,
            "name": self.config.name,
            "category": self.config.category,
            "difficulty": self.config.difficulty,
            "url": self.config.url,
            "flag_format": self.config.flag_format,
            "description": self.config.description,
            "hints": self.config.hints,
            "correct_flags": correct_flags,
            "is_completed": len(correct_flags) > 0,
        }

    def _get_hint(self) -> dict:
        return {"hints": self.config.hints}

    def _is_completed(self) -> dict:
        completed = store.is_solved(self.workspace_dir, self.config.id)
        return {"completed": completed}
