"""Small reliability wrapper for OpenAI-compatible completion calls."""

from __future__ import annotations

import copy
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import CancelledError
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)


_RETRYABLE_ERRORS = (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)

DEEPSEEK_V4_CONTEXT_TOKENS = 1_000_000
DEEPSEEK_V4_MAX_OUTPUT_TOKENS = 8_192
DEEPSEEK_V4_COMPACTION_RESERVE_TOKENS = 32_768

# Per-request transport timeout caps (seconds).
_DEFAULT_REQUEST_TIMEOUT = 120.0
_MIN_REQUEST_TIMEOUT = 20.0


def _llm_limit() -> int:
    try:
        return max(1, int(os.environ.get("LLM_MAX_CONCURRENCY", "4")))
    except ValueError:
        return 4


def llm_concurrency_limit() -> int:
    """The process-wide LLM slot count (``LLM_MAX_CONCURRENCY``).

    The scheduler sizes its lane budget against this so the number of running
    solver lanes never exceeds the number of LLM slots (extra lanes past the
    gate would only queue and slow every lane down).
    """
    return _llm_limit()


class AdaptiveLLMGate:
    """Process-wide LLM slot gate with latency/rate-limit backpressure.

    Healthy: all ``limit`` slots available.
    Degraded (recent timeouts / 429 / high latency): hold half the permits so
    each in-flight request has more gateway headroom — slows total throughput
    to protect per-request quality under API instability.
    """

    def __init__(self, limit: int):
        self.limit = max(1, int(limit))
        self._sem = threading.BoundedSemaphore(self.limit)
        self._lock = threading.Lock()
        self._held = 0  # permits reserved for backpressure
        self._latencies: deque[float] = deque(maxlen=24)
        self._fail_streak = 0
        self._degraded_until = 0.0
        self._last_emit_state = "healthy"

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "limit": self.limit,
                "held": self._held,
                "effective": max(1, self.limit - self._held),
                "fail_streak": self._fail_streak,
                "degraded": time.time() < self._degraded_until,
                "p50_latency_s": _percentile(list(self._latencies), 0.5),
            }

    def note_success(self, latency_s: float) -> None:
        with self._lock:
            self._latencies.append(max(0.0, float(latency_s)))
            self._fail_streak = 0
            # One healthy reply ends degradation; backpressure releases next reconcile.
            self._degraded_until = min(self._degraded_until, time.time())
            self._reconcile_locked()

    def note_failure(self, exc: BaseException, latency_s: float = 0.0) -> None:
        rate_limited = isinstance(exc, RateLimitError)
        timed_out = isinstance(exc, APITimeoutError)
        server_err = isinstance(exc, (InternalServerError, APIConnectionError)) or (
            isinstance(exc, APIStatusError) and int(getattr(exc, "status_code", 0) or 0) >= 500
        )
        if not (rate_limited or timed_out or server_err):
            return
        with self._lock:
            if latency_s > 0:
                self._latencies.append(max(0.0, float(latency_s)))
            self._fail_streak += 1
            # Escalate degradation window with streak; cap at 90s.
            window = min(90.0, 15.0 * self._fail_streak)
            if rate_limited:
                window = max(window, 45.0)
            self._degraded_until = max(self._degraded_until, time.time() + window)
            self._reconcile_locked()

    def _target_held_locked(self) -> int:
        if time.time() >= self._degraded_until:
            return 0
        # Keep at least 1 slot free so a single challenge can still progress.
        return max(0, self.limit // 2)

    def _reconcile_locked(self) -> None:
        target = self._target_held_locked()
        # Release excess held permits when recovering.
        while self._held > target:
            self._sem.release()
            self._held -= 1
        # Acquire and hold permits when degrading (non-blocking; best-effort).
        while self._held < target:
            if not self._sem.acquire(blocking=False):
                break
            self._held += 1
        state = "degraded" if self._held else "healthy"
        if state != self._last_emit_state:
            self._last_emit_state = state
            # Lazy emit: callers that care listen to llm_backpressure via agent.

    def acquire(self, deadline: float, cancel_event: threading.Event | None) -> None:
        """Acquire one working slot without waiting past cancellation/deadline."""
        while True:
            _ensure_request_active(deadline, cancel_event)
            if deadline:
                remaining = max(0.0, deadline - time.time())
                wait = min(remaining, 0.2) if cancel_event is not None else remaining
                acquired = self._sem.acquire(timeout=wait)
            elif cancel_event is not None:
                acquired = self._sem.acquire(timeout=0.2)
            else:
                self._sem.acquire()
                acquired = True
            if acquired:
                try:
                    _ensure_request_active(deadline, cancel_event)
                except Exception:
                    self._sem.release()
                    raise
                return

    def release(self) -> None:
        self._sem.release()


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return float(ordered[idx])


# Process-wide gate: 3 challenges × portfolio must not overwhelm the gateway.
_LLM_GATE = AdaptiveLLMGate(_llm_limit())
# Backward-compatible alias used by older tests that patch the semaphore.
_LLM_SEMAPHORE = _LLM_GATE._sem


def llm_health_snapshot() -> dict[str, Any]:
    return _LLM_GATE.snapshot()


def note_llm_success(latency_s: float) -> None:
    _LLM_GATE.note_success(latency_s)


def note_llm_failure(exc: BaseException, latency_s: float = 0.0) -> None:
    _LLM_GATE.note_failure(exc, latency_s)


def budget_aware_timeout(
    deadline: float = 0.0,
    *,
    default: float = _DEFAULT_REQUEST_TIMEOUT,
    floor: float = _MIN_REQUEST_TIMEOUT,
) -> float:
    """Tighten per-request timeout when the benchmark clock is short.

    Prevents one slow API call from burning ~3×120s of wall clock when the
    remaining budget can no longer afford full retries.
    """
    default = float(default or _DEFAULT_REQUEST_TIMEOUT)
    floor = float(floor or _MIN_REQUEST_TIMEOUT)
    deadline = float(deadline or 0.0)
    if not deadline:
        return default
    remaining = deadline - time.time()
    if remaining <= 0:
        return max(0.1, min(floor, default))
    if remaining > 360:
        return default
    if remaining > 180:
        return min(default, 90.0)
    if remaining > 90:
        return min(default, 60.0)
    # Leave room for one retry + tool execution.
    return max(floor, min(default, remaining / 3.0))


def budget_aware_attempts(
    deadline: float = 0.0,
    *,
    default: int = 3,
) -> int:
    """Reduce retry count when remaining wall clock is tight."""
    default = max(1, int(default or 3))
    deadline = float(deadline or 0.0)
    if not deadline:
        return default
    remaining = deadline - time.time()
    if remaining < 90:
        return 1
    if remaining < 180:
        return min(default, 2)
    return default


def is_deepseek_v4(model: str) -> bool:
    return model.lower().startswith("deepseek-v4")


def is_glm_model(model: str) -> bool:
    """智谱 GLM（tokenhub：glm-5.3 / glm-5.3-flash 等）。"""
    return model.lower().startswith("glm-")


def _glm_reasoning_effort(effort: str) -> str:
    """Map our medium/high scale onto GLM's low/high/max."""
    token = (effort or "medium").strip().lower()
    return {
        "low": "low",
        "medium": "high",
        "high": "max",
        "max": "max",
    }.get(token, "high")


def completion_kwargs(
    *,
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_choice: str | None = None,
    max_tokens: int | None = None,
    reasoning_effort: str = "medium",
    thinking_enabled: bool = True,
    reasoning_effort_cap: str | None = None,
) -> dict[str, Any]:
    """Build one OpenAI-compatible request with per-family thinking/tool semantics."""
    effort = reasoning_effort
    if reasoning_effort_cap:
        effort = reasoning_effort_cap
    kwargs: dict[str, Any] = {"model": model, "messages": messages}
    if tools is not None:
        kwargs["tools"] = tools
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    if is_deepseek_v4(model):
        # DeepSeek V4 thinking rejects tool_choice. reasoning_effort 必须是
        # 顶层字段（放进 extra_body 时 tokenhub 不生效，导致每轮都按
        # 默认 high 读满 reasoning）。
        kwargs["extra_body"] = {
            "thinking": {"type": "enabled" if thinking_enabled else "disabled"},
        }
        if thinking_enabled:
            kwargs["reasoning_effort"] = effort
    elif is_glm_model(model):
        # GLM-5.3 / Flash（TokenHub）：
        # - thinking 默认开启；5.3 传入 disabled 会失败 → 只发 enabled
        # - Function Calling 走标准 tools；结构调用用 tool_choice=auto
        #   （required 在部分 GLM 端不稳/不支持）
        # - reasoning_effort：low / high / max
        kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        kwargs["reasoning_effort"] = _glm_reasoning_effort(effort)
        if tool_choice is not None:
            kwargs["tool_choice"] = "auto" if tool_choice == "required" else tool_choice
    elif tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    return kwargs


def assistant_message_dict(message: Any) -> dict[str, Any]:
    """Serialize an assistant message for reliable multi-turn tool replay."""
    data = message.model_dump(exclude_none=True)
    extra = getattr(message, "model_extra", {}) or {}
    reasoning = getattr(message, "reasoning_content", None) or extra.get("reasoning_content")
    if reasoning:
        data["reasoning_content"] = reasoning
    if data.get("tool_calls"):
        data["content"] = data.get("content") or ""
    return data


def _ensure_request_active(
    deadline: float,
    cancel_event: threading.Event | None,
) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise CancelledError("LLM request cancelled")
    if deadline and time.time() >= deadline:
        raise TimeoutError("LLM request exceeded benchmark deadline")


def _acquire_llm_slot(
    deadline: float,
    cancel_event: threading.Event | None,
) -> None:
    """Acquire the global slot without waiting past cancellation/deadline."""
    # Tests may patch ``_LLM_SEMAPHORE``; use AdaptiveLLMGate only when live.
    if _LLM_SEMAPHORE is _LLM_GATE._sem:
        _LLM_GATE.acquire(deadline, cancel_event)
        return
    while True:
        _ensure_request_active(deadline, cancel_event)
        if deadline:
            remaining = max(0.0, deadline - time.time())
            wait = min(remaining, 0.2) if cancel_event is not None else remaining
            acquired = _LLM_SEMAPHORE.acquire(timeout=wait)
        elif cancel_event is not None:
            acquired = _LLM_SEMAPHORE.acquire(timeout=0.2)
        else:
            _LLM_SEMAPHORE.acquire()
            acquired = True
        if acquired:
            try:
                _ensure_request_active(deadline, cancel_event)
            except Exception:
                _LLM_SEMAPHORE.release()
                raise
            return


def _release_llm_slot() -> None:
    if _LLM_SEMAPHORE is _LLM_GATE._sem:
        _LLM_GATE.release()
    else:
        _LLM_SEMAPHORE.release()


def create_with_retry(
    create: Callable[..., Any],
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    on_retry: Callable[[int, Exception, float], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    deadline: float = 0.0,
    cancel_event: threading.Event | None = None,
    **kwargs: Any,
) -> Any:
    """Call a completion endpoint with bounded concurrency and retries.

    ``create`` is invoked once per attempt, after acquiring the process-wide
    slot.  Callers that need a transport timeout derived from the remaining
    budget should pass a small wrapper which computes that timeout when it is
    invoked rather than binding the client before entering this function.
    """
    attempts = max(1, max_attempts)
    request_snapshot = copy.deepcopy(kwargs)
    deadline = float(deadline or 0.0)
    for attempt in range(1, attempts + 1):
        _acquire_llm_slot(deadline, cancel_event)
        started = time.time()
        try:
            result = create(**copy.deepcopy(request_snapshot))
            note_llm_success(time.time() - started)
            return result
        except Exception as exc:
            latency = time.time() - started
            retryable = isinstance(exc, _RETRYABLE_ERRORS) or (
                isinstance(exc, APIStatusError) and exc.status_code >= 500
            )
            if retryable:
                note_llm_failure(exc, latency)
            if not retryable or attempt == attempts:
                raise
            delay = max(0.0, min(base_delay * (2 ** (attempt - 1)), 8.0))
            if deadline:
                delay = min(delay, max(0.0, deadline - time.time()))
            if on_retry:
                on_retry(attempt, exc, delay)
        finally:
            _release_llm_slot()

        _ensure_request_active(deadline, cancel_event)
        if cancel_event is not None:
            if cancel_event.wait(delay):
                raise CancelledError("LLM request cancelled during retry backoff")
        else:
            sleep(delay)
        _ensure_request_active(deadline, cancel_event)

    raise RuntimeError("unreachable")
