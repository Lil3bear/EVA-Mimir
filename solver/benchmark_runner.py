"""Tsecbench 多题调度器。

调度器运行在 Solver 进程内，负责题目生命周期；工具层只处理当前题目的
API 调用。这样每次 SolverAgent 运行都只绑定一个 unique_code。
"""

from dataclasses import dataclass
from typing import Callable

from solver.agent import SolverAgent
from solver.ctfplatform.tsecbench_client import Challenge, TsecbenchClient
from solver.tools import bridge_tools


@dataclass(frozen=True)
class ChallengeRun:
    unique_code: str
    completed: bool
    rounds: int = 0


def _difficulty_key(value: str) -> tuple[int, str]:
    names = {"easy": 1, "medium": 2, "hard": 3, "expert": 4}
    normalized = value.strip().lower()
    return names.get(normalized, 99), normalized


class BenchmarkRunner:
    def __init__(
        self,
        client: TsecbenchClient,
        *,
        settings: dict,
        skills_dir: str,
        agent_factory: Callable[..., SolverAgent] = SolverAgent,
        max_agent_runs_per_challenge: int = 20,
    ) -> None:
        self.client = client
        self.settings = settings
        self.skills_dir = skills_dir
        self.agent_factory = agent_factory
        self.max_agent_runs_per_challenge = max_agent_runs_per_challenge

    def run(self) -> list[ChallengeRun]:
        self.client.check_vpn()
        runs: list[ChallengeRun] = []
        for challenge in self._pending_challenges(self.client.list_challenges()):
            runs.append(self._run_challenge(challenge))
        bridge_tools.clear_tsecbench()
        return runs

    @staticmethod
    def _pending_challenges(challenges: list[Challenge]) -> list[Challenge]:
        return sorted(
            (item for item in challenges if not item.is_completed),
            key=lambda item: (item.level, _difficulty_key(item.difficulty), item.unique_code),
        )

    def _run_challenge(self, challenge: Challenge) -> ChallengeRun:
        code = challenge.unique_code
        started = False
        rounds = 0
        try:
            start = self.client.start_challenge(code)
            started = True
            bridge_tools.configure_tsecbench(self.client, code)
            addresses = ", ".join(start.container_addr)
            task = self._build_task(challenge, addresses)

            # 一个 Agent 实例以一个 flag 为终点；刷新状态后继续同题剩余 flag。
            for _ in range(self.max_agent_runs_per_challenge):
                agent = self.agent_factory(task=task, settings=self.settings, skills_dir=self.skills_dir)
                agent.run()
                rounds += getattr(agent, "round", 0)
                current = self._find_current(self.client.list_challenges(), code)
                if current is None or current.is_completed:
                    return ChallengeRun(code, True, rounds)
                task = self._build_task(current, ", ".join(current.container_addr or start.container_addr))
            current = self._find_current(self.client.list_challenges(), code)
            return ChallengeRun(code, bool(current and current.is_completed), rounds)
        finally:
            bridge_tools.clear_tsecbench()
            if started:
                self.client.close_challenge(code)

    @staticmethod
    def _find_current(challenges: list[Challenge], code: str) -> Challenge | None:
        return next((item for item in challenges if item.unique_code == code), None)

    @staticmethod
    def _build_task(challenge: Challenge, addresses: str) -> str:
        return (
            f"题目编号：{challenge.unique_code}\n"
            f"目标地址：{addresses}\n"
            f"题目难度：{challenge.difficulty}（等级 {challenge.level}）\n"
            f"题目描述：{challenge.description or '暂无描述'}\n"
            f"当前进度：{challenge.correct_flag_count}/{challenge.flag_count} 个 flag\n"
            "请分析并解决当前题目，找到 flag 后立即调用 challenge_submit_flag。"
        )
