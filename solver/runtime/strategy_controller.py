"""Durable, deterministic strategy control for one challenge.

This is intentionally a small control plane rather than another LLM.  It
records normalized actions and evidence novelty across portfolio attempts,
then emits a bounded strategy-switch advice when the current direction is
repeating without useful progress.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from solver.runtime.decision_state import (
    ActionOutcome,
    ActionOutcomeKind,
    DecisionState,
    Hypothesis,
    HypothesisStatus,
    StrategyMode,
    classify_action,
)

if sys.platform != "win32":
    import fcntl


@dataclass(frozen=True)
class ControlAdvice:
    """A structured recommendation; the Solver decides how to present it."""

    action: str
    mode: str
    reason: str
    state_version: int
    round_num: int
    attempt_id: str = ""
    expires_after_rounds: int = 4
    outcome: ActionOutcome | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "mode": self.mode,
            "reason": self.reason,
            "state_version": self.state_version,
            "round_num": self.round_num,
            "attempt_id": self.attempt_id,
            "expires_after_rounds": self.expires_after_rounds,
            "outcome": self.outcome.to_dict() if self.outcome else None,
        }


class DecisionStateStore:
    """Atomic JSON state store shared by attempts of one challenge."""

    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(self, challenge_dir: str | Path):
        self.challenge_dir = Path(challenge_dir)
        self.path = self.challenge_dir / ".decision-state.json"
        self.lock_path = self.challenge_dir / "locks" / "decision-state.lock"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        key = str(self.lock_path.resolve())
        with self._locks_guard:
            lock = self._locks.setdefault(key, threading.RLock())
        with lock:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = self.lock_path.open("a+")
            try:
                if sys.platform != "win32":
                    fcntl.flock(handle, fcntl.LOCK_EX)
                yield
            finally:
                if sys.platform != "win32":
                    fcntl.flock(handle, fcntl.LOCK_UN)
                handle.close()

    def load(self) -> DecisionState:
        with self._locked():
            return self._load_unlocked()

    def update(self, mutator: Callable[[DecisionState], Any]) -> Any:
        """Load, mutate and atomically save one state version."""
        with self._locked():
            state = self._load_unlocked()
            result = mutator(state)
            state.state_version += 1
            self._write_unlocked(state)
            return result

    def _load_unlocked(self) -> DecisionState:
        if not self.path.exists():
            return DecisionState.empty(self.challenge_dir.name)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("decision state root is not an object")
            state = DecisionState.from_dict(data)
            if not state.challenge_id:
                state.challenge_id = self.challenge_dir.name
            return state
        except (OSError, json.JSONDecodeError, UnicodeError, TypeError, ValueError):
            quarantine = self.path.with_name(
                f"{self.path.name}.corrupt.{time.time_ns()}"
            )
            try:
                os.replace(self.path, quarantine)
            except OSError:
                pass
            return DecisionState.empty(self.challenge_dir.name)

    def _write_unlocked(self, state: DecisionState) -> None:
        self.challenge_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
        )
        try:
            tmp.write_text(
                json.dumps(state.to_dict(), ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)


class StrategyController:
    """Challenge-scoped adaptive controller with conservative defaults."""

    _MODE_AFTER_SWITCH = {
        StrategyMode.MAP.value: StrategyMode.EXPLORE.value,
        StrategyMode.EXPLORE.value: StrategyMode.ALTERNATE.value,
        StrategyMode.EXPLOIT.value: StrategyMode.ALTERNATE.value,
        StrategyMode.ALTERNATE.value: StrategyMode.VERIFY.value,
        StrategyMode.VERIFY.value: StrategyMode.EXPLORE.value,
        StrategyMode.RECOVER.value: StrategyMode.ALTERNATE.value,
    }

    def __init__(
        self,
        challenge_dir: str | Path,
        *,
        attempt_id: str = "primary",
        difficulty: str = "",
        switch_after: int = 12,
        stop_after: int = 30,
        action_repeat_threshold: int = 4,
        vector_repeat_threshold: int = 4,
        enabled: bool = True,
    ):
        self.challenge_dir = Path(challenge_dir)
        self.attempt_id = str(attempt_id or "primary")
        self.difficulty = str(difficulty or "")
        self.switch_after = _positive_int(switch_after, 12)
        self.stop_after = max(self.switch_after + 1, _positive_int(stop_after, 30))
        self.action_repeat_threshold = max(2, _positive_int(action_repeat_threshold, 4))
        self.vector_repeat_threshold = max(2, _positive_int(vector_repeat_threshold, 4))
        self.enabled = bool(enabled)
        self.store = DecisionStateStore(self.challenge_dir)

    def snapshot(self) -> DecisionState:
        return self.store.load()

    def summary(self) -> dict[str, Any]:
        return self.snapshot().summary()

    def observe(
        self,
        tool_name: str,
        tool_args: Mapping[str, Any] | None,
        result: str,
        round_num: int,
        *,
        allow_switch: bool = True,
    ) -> ControlAdvice | None:
        """Record one result and optionally emit a bounded strategy failure.

        Fast Lane passes ``allow_switch=False`` so evidence is still durable,
        but merely observing repeated actions cannot mutate the strategy mode
        or consume a switch before Deep Lane actually starts.
        """
        if not self.enabled:
            return None

        def mutate(state: DecisionState) -> ControlAdvice | None:
            outcome = classify_action(
                tool_name,
                tool_args,
                result,
                known_evidence=set(state.evidence_fingerprints),
                round_num=round_num,
                attempt_id=self.attempt_id,
            )
            state.last_round = max(state.last_round, int(round_num))
            state.total_actions += 1
            state.last_outcome = outcome.kind
            state.last_reason = outcome.reason

            if outcome.action_fingerprint == state.last_action_fingerprint:
                state.same_action_streak += 1
            else:
                state.same_action_streak = 1
            state.last_action_fingerprint = outcome.action_fingerprint

            if outcome.vector == state.last_vector:
                state.same_vector_streak += 1
            else:
                state.same_vector_streak = 1
            state.last_vector = outcome.vector

            if outcome.soft_progress:
                state.last_soft_progress_round = max(
                    state.last_soft_progress_round, int(round_num)
                )
            if outcome.novel_progress:
                state.last_novel_progress_round = max(
                    state.last_novel_progress_round, int(round_num)
                )
            if outcome.positive_progress:
                state.last_positive_progress_round = max(
                    state.last_positive_progress_round, int(round_num)
                )
            if outcome.evidence_fingerprints:
                existing = set(state.evidence_fingerprints)
                for fingerprint in outcome.evidence_fingerprints:
                    if fingerprint not in existing:
                        state.evidence_fingerprints.append(fingerprint)
                        existing.add(fingerprint)
                state.evidence_fingerprints = state.evidence_fingerprints[-2048:]

            # Control-only calls (skill/hint/blackboard) do not make the
            # current target direction look healthy.  They still count as
            # actions, so repeated control calls can eventually trigger a
            # strategy change through the idle condition below.
            idle_novel = max(0, int(round_num) - state.last_novel_progress_round)
            idle_positive = max(0, int(round_num) - state.last_positive_progress_round)
            cooldown = max(4, self.switch_after // 2)
            in_cooldown = (
                state.last_switch_round > 0
                and int(round_num) - state.last_switch_round < cooldown
            )

            repeat_reason = ""
            if (
                not outcome.novel_progress
                and state.same_action_streak >= self.action_repeat_threshold
            ):
                repeat_reason = "same_action_without_novel_evidence"
            elif (
                state.same_vector_streak >= self.vector_repeat_threshold
                and idle_positive >= max(3, self.switch_after // 2)
            ):
                repeat_reason = "same_strategy_without_positive_progress"
            elif idle_novel >= self.switch_after and not outcome.novel_progress:
                repeat_reason = "no_novel_progress"

            if not repeat_reason or in_cooldown or not allow_switch:
                return None

            next_mode = self._MODE_AFTER_SWITCH.get(
                state.strategy_mode, StrategyMode.ALTERNATE.value
            )
            state.strategy_mode = next_mode
            state.switch_count += 1
            state.last_switch_round = int(round_num)
            state.last_reason = repeat_reason
            return ControlAdvice(
                action="switch_strategy",
                mode=next_mode,
                reason=repeat_reason,
                state_version=state.state_version + 1,
                round_num=int(round_num),
                attempt_id=self.attempt_id,
                expires_after_rounds=max(4, self.switch_after // 2),
                outcome=outcome,
            )

        return self.store.update(mutate)

    def register_hypothesis(
        self,
        description: str,
        *,
        domain: str = "",
        expected_evidence: str = "",
        confidence: float = 0.5,
    ) -> Hypothesis:
        """Create or return a deduplicated hypothesis contract."""
        normalized = " ".join(str(description or "").split()).lower()
        if not normalized:
            raise ValueError("hypothesis description cannot be empty")

        def mutate(state: DecisionState) -> Hypothesis:
            for item in state.hypotheses:
                if " ".join(item.description.split()).lower() == normalized:
                    return item
            digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
            identifier = f"h_{len(state.hypotheses) + 1:03d}_{digest}"
            item = Hypothesis(
                id=identifier,
                description=str(description).strip(),
                domain=str(domain or ""),
                confidence=max(0.0, min(1.0, float(confidence))),
                expected_evidence=str(expected_evidence or ""),
                updated_at=time.time(),
            )
            state.hypotheses.append(item)
            return item

        return self.store.update(mutate)

    def claim_hypothesis(
        self,
        hypothesis_id: str,
        *,
        owner: str | None = None,
        round_num: int = 0,
        lease_rounds: int = 8,
    ) -> bool:
        """Atomically claim a hypothesis so portfolio attempts do not duplicate it."""
        owner = str(owner or self.attempt_id)
        lease_rounds = max(1, int(lease_rounds or 8))

        def mutate(state: DecisionState) -> bool:
            for item in state.hypotheses:
                if item.id != hypothesis_id and not item.id.startswith(hypothesis_id):
                    continue
                active_lease = bool(item.owner and item.lease_until > int(round_num))
                if active_lease and item.owner != owner:
                    return False
                item.owner = owner
                item.lease_until = int(round_num) + lease_rounds
                item.status = HypothesisStatus.TESTING.value
                item.attempts += 1
                item.last_round = int(round_num)
                item.updated_at = time.time()
                return True
            return False

        return bool(self.store.update(mutate))

    def release_hypothesis(
        self,
        hypothesis_id: str,
        *,
        owner: str | None = None,
        status: str | None = None,
        result: str = "",
        confidence: float | None = None,
    ) -> bool:
        owner = str(owner or self.attempt_id)

        def mutate(state: DecisionState) -> bool:
            for item in state.hypotheses:
                if item.id != hypothesis_id and not item.id.startswith(hypothesis_id):
                    continue
                if item.owner and item.owner != owner:
                    return False
                item.owner = ""
                item.lease_until = 0
                if status:
                    item.status = str(status)
                if result:
                    item.last_result = str(result)[:1000]
                if confidence is not None:
                    item.confidence = max(0.0, min(1.0, float(confidence)))
                item.updated_at = time.time()
                return True
            return False

        return bool(self.store.update(mutate))


def load_decision_summary(challenge_dir: str | Path) -> dict[str, Any]:
    """Best-effort summary helper for Observer and diagnostics."""
    try:
        return DecisionStateStore(challenge_dir).load().summary()
    except Exception:
        return {}


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 0
    return parsed if parsed > 0 else default
