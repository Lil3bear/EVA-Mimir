"""Runtime tiered model routing for one Solver.

The Solver historically bound a single ``model`` for its entire lifetime, so a
heavy reasoning model (e.g. ``deepseek-v4-pro``) spent its long thinking budget
on every turn — including cheap verification and summarization steps.  That
starves the solve loop of wall-clock time and process slots.

``ModelRouter`` makes the acting model a per-turn decision:

- a *light* tier drives the default loop, verification, summaries and the
  Observer, keeping latency low;
- a *heavy* tier is engaged only when the run is genuinely stuck, then
  automatically falls back after a bounded window so pro budget and time are
  not burned continuously.

Each tier may live on its own provider (base_url + api_key), so mixing e.g.
Kimi on Tencent tokenhub with DeepSeek on deepseek.com is a configuration
concern, not a code change.  Clients are cached per (base_url, api_key).

The router is deliberately free of any OpenAI import at module import time: a
``client_factory`` is injected so tests can exercise selection logic without a
network or credentials.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class ModelPurpose(str, Enum):
    """Why the caller needs a model this turn."""

    MAIN = "main"          # the Solver's acting/reasoning turn
    SUMMARY = "summary"    # context compaction summary
    OBSERVER = "observer"  # bypass review control plane


DEFAULT_TIER_LIGHT = "light"
DEFAULT_TIER_HEAVY = "heavy"

# Conservative defaults: light everywhere, heavy only when stuck, and a short
# escalation window so the heavy model does not linger.
DEFAULT_ROUTING: dict[str, Any] = {
    "main_tier": DEFAULT_TIER_LIGHT,
    "summary_tier": DEFAULT_TIER_LIGHT,
    "observer_tier": DEFAULT_TIER_LIGHT,
    "deep_lane_default_tier": DEFAULT_TIER_LIGHT,
    "fast_lane_tier": DEFAULT_TIER_LIGHT,
    # hard / stuck 均保持 light：评测表明 reasoning_effort=high 只增加延迟与占槽，
    # 不能替代 skill/payload（run-13844：hard 四题 0 分 + 6×10^5 reasoning token）。
    "hard_tier": DEFAULT_TIER_LIGHT,
    "stuck_escalate_tier": DEFAULT_TIER_LIGHT,
    "escalate_rounds": 0,
    # A stuck signal that keeps firing should not extend heavy usage forever.
    "escalate_max_consecutive": 12,
    # Thresholds the Solver uses to compute the stuck signal it feeds back in.
    "stuck_no_progress_rounds": 8,
    "stuck_wrong_submit_streak": 2,
    "stuck_repeat_action_streak": 4,
}


def _is_deepseek_v4(model: str) -> bool:
    return model.lower().startswith("deepseek-v4")


def _is_glm_model(model: str) -> bool:
    return model.lower().startswith("glm-")


def _default_thinking_enabled(model: str) -> bool:
    # DeepSeek V4 / GLM-5.3 都走思考链；GLM 不能 disabled。
    return _is_deepseek_v4(model) or _is_glm_model(model)


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"1", "true", "yes", "on"}:
            return True
        if token in {"0", "false", "no", "off"}:
            return False
    return default


@dataclass(frozen=True)
class Provider:
    """One OpenAI-compatible endpoint (base_url + api_key)."""

    key: str
    base_url: str
    api_key: str

    def client_id(self) -> tuple[str, str]:
        return (self.base_url, self.api_key)


@dataclass(frozen=True)
class ModelSpec:
    """A concrete model resolved to a provider and thinking semantics."""

    name: str
    tier: str
    provider: Provider
    reasoning_effort: str = "medium"
    thinking_enabled: bool = True
    max_output_tokens: int = 8192

    @property
    def is_deepseek_v4(self) -> bool:
        return _is_deepseek_v4(self.name)


@dataclass(frozen=True)
class ModelSelection:
    """The router's decision for one call, plus why it was made."""

    spec: ModelSpec
    purpose: ModelPurpose
    reason: str

    @property
    def model(self) -> str:
        return self.spec.name

    @property
    def tier(self) -> str:
        return self.spec.tier


@dataclass
class ModelRouter:
    """Selects a model per purpose/turn and caches per-provider clients."""

    tiers: dict[str, ModelSpec]
    routing: dict[str, Any]
    client_factory: Callable[..., Any]
    default_tier: str = DEFAULT_TIER_LIGHT
    timeout_factory: Callable[[], Any] | None = None
    _clients: dict[tuple[str, str], Any] = field(default_factory=dict)
    # Round (inclusive) up to which MAIN keeps using the escalated tier.
    _escalated_until_round: int = 0
    _escalate_started_round: int = 0

    # ---- construction -------------------------------------------------

    @classmethod
    def from_settings(
        cls,
        settings: Mapping[str, Any],
        environ: Mapping[str, str] | None = None,
        *,
        client_factory: Callable[..., Any] | None = None,
        timeout_factory: Callable[[], Any] | None = None,
    ) -> "ModelRouter":
        env = os.environ if environ is None else environ
        llm = dict(settings.get("llm", {}) or {})

        providers = _build_providers(llm, env)
        default_provider = providers["__default__"]

        tiers = _build_tiers(llm, providers, default_provider, env)

        routing = dict(DEFAULT_ROUTING)
        configured = llm.get("routing", {})
        if isinstance(configured, Mapping):
            routing.update(configured)
        # Validate tier references so a typo fails loudly instead of silently
        # falling back to the acting model mid-run.
        for key in (
            "main_tier", "summary_tier", "observer_tier",
            "deep_lane_default_tier", "fast_lane_tier", "hard_tier",
            "stuck_escalate_tier",
        ):
            tier_name = routing.get(key)
            if tier_name and tier_name not in tiers:
                raise ValueError(
                    f"llm.routing.{key} 引用了未定义的层 {tier_name!r}；"
                    f"可用层：{sorted(tiers)}"
                )

        factory = client_factory
        if factory is None:  # pragma: no cover - exercised only with real SDK
            from openai import OpenAI as factory  # type: ignore

        return cls(
            tiers=tiers,
            routing=routing,
            client_factory=factory,
            default_tier=DEFAULT_TIER_LIGHT if DEFAULT_TIER_LIGHT in tiers else next(iter(tiers)),
            timeout_factory=timeout_factory,
        )

    # ---- selection ----------------------------------------------------

    def resolve(
        self,
        purpose: ModelPurpose | str,
        *,
        round_num: int = 0,
        lane: str = "deep",
        stuck: bool = False,
        difficulty: str = "",
    ) -> ModelSelection:
        purpose = ModelPurpose(purpose)
        if purpose is ModelPurpose.SUMMARY:
            tier = self.routing.get("summary_tier", self.default_tier)
            return self._select(tier, purpose, "summary always uses the fast tier")
        if purpose is ModelPurpose.OBSERVER:
            tier = self.routing.get("observer_tier", self.default_tier)
            return self._select(tier, purpose, "observer control plane stays light")
        return self._resolve_main(
            round_num=round_num, lane=lane, stuck=stuck, difficulty=difficulty
        )

    def _resolve_main(
        self, *, round_num: int, lane: str, stuck: bool, difficulty: str = ""
    ) -> ModelSelection:
        lane = (lane or "deep").lower()
        diff = (difficulty or "").lower()
        escalate_rounds = max(0, int(self.routing.get("escalate_rounds", 0)))
        max_consecutive = max(0, int(self.routing.get("escalate_max_consecutive", 12)))
        escalate_tier = self.routing.get("stuck_escalate_tier", DEFAULT_TIER_LIGHT)

        # hard/difficult 与 easy/medium 同走 light；深度思考不能替代 skill/payload。
        if diff in ("hard", "difficult"):
            hard_tier = self.routing.get("hard_tier", DEFAULT_TIER_LIGHT)
            if hard_tier in self.tiers:
                return self._select(
                    hard_tier, ModelPurpose.MAIN,
                    f"{diff} difficulty uses configured tier ({hard_tier})",
                )

        # Fast Lane never escalates: simple challenges must stay fast.
        if lane == "fast":
            self._escalated_until_round = 0
            self._escalate_started_round = 0
            tier = self.routing.get("fast_lane_tier", self.default_tier)
            return self._select(tier, ModelPurpose.MAIN, "fast lane keeps the light tier")

        # The escalation anchor tracks one continuous stuck episode.  It is
        # cleared only when the stuck signal actually clears, so a run that
        # stays stuck cannot keep re-opening the window past the cap.
        if not stuck:
            self._escalate_started_round = 0

        # Stuck escalation is optional; escalate_rounds=0 or stuck_escalate_tier=light
        # disables burning a heavier reasoning budget on repeated failures.
        if (
            stuck
            and escalate_tier in self.tiers
            and escalate_rounds > 0
            and escalate_tier != self.routing.get("deep_lane_default_tier", self.default_tier)
        ):
            if self._escalate_started_round == 0:
                self._escalate_started_round = round_num
            within_cap = (
                max_consecutive == 0
                or round_num - self._escalate_started_round < max_consecutive
            )
            if within_cap:
                self._escalated_until_round = max(
                    self._escalated_until_round, round_num + escalate_rounds
                )

        if self._escalated_until_round and round_num <= self._escalated_until_round:
            if escalate_tier in self.tiers:
                return self._select(
                    escalate_tier, ModelPurpose.MAIN,
                    f"stuck: escalated through round {self._escalated_until_round}",
                )

        tier = self.routing.get("deep_lane_default_tier", self.default_tier)
        return self._select(tier, ModelPurpose.MAIN, "deep lane default tier")

    def _select(self, tier: str, purpose: ModelPurpose, reason: str) -> ModelSelection:
        spec = self.tiers.get(tier) or self.tiers[self.default_tier]
        return ModelSelection(spec=spec, purpose=purpose, reason=reason)

    # ---- clients ------------------------------------------------------

    def client_for(self, spec: ModelSpec) -> Any:
        """Return a cached client for the spec's provider."""
        key = spec.provider.client_id()
        client = self._clients.get(key)
        if client is None:
            kwargs: dict[str, Any] = {
                "base_url": spec.provider.base_url,
                "api_key": spec.provider.api_key,
            }
            if self.timeout_factory is not None:
                kwargs["timeout"] = self.timeout_factory()
            client = self.client_factory(**kwargs)
            self._clients[key] = client
        return client

    def describe(self) -> dict[str, Any]:
        """Compact view for telemetry/emit."""
        return {
            "tiers": {
                name: {
                    "model": spec.name,
                    "provider": spec.provider.key,
                    "base_url": spec.provider.base_url,
                }
                for name, spec in self.tiers.items()
            },
            "routing": dict(self.routing),
        }


def _build_providers(
    llm: Mapping[str, Any], env: Mapping[str, str]
) -> dict[str, Provider]:
    """Named providers plus a synthesized ``__default__`` from top-level llm."""
    default_base = str(llm.get("base_url") or env.get("LLM_BASE_URL", "") or "")
    default_key = str(llm.get("api_key") or env.get("LLM_API_KEY", "") or "")
    providers: dict[str, Provider] = {
        "__default__": Provider("__default__", default_base, default_key),
    }
    configured = llm.get("providers", {})
    if isinstance(configured, Mapping):
        for name, spec in configured.items():
            if not isinstance(spec, Mapping):
                raise ValueError(f"llm.providers.{name} 必须是 JSON object")
            base = str(spec.get("base_url") or default_base or "")
            key = str(spec.get("api_key") or "")
            # Allow env-based key wiring: providers.<name>.api_key_env
            env_name = spec.get("api_key_env")
            if not key and env_name:
                key = str(env.get(str(env_name), "") or "")
            # A provider sharing the top-level endpoint inherits its key, so
            # committed settings can name providers with an empty key and let
            # the local (gitignored) top-level api_key supply the secret.
            if not key and base == default_base:
                key = default_key
            providers[str(name)] = Provider(str(name), base, key)
    return providers


def _build_tiers(
    llm: Mapping[str, Any],
    providers: Mapping[str, Provider],
    default_provider: Provider,
    env: Mapping[str, str],
) -> dict[str, ModelSpec]:
    """Explicit ``llm.tiers`` if present, else derive light/heavy from legacy keys."""
    default_effort = str(llm.get("reasoning_effort", "medium"))
    default_max_out = int(llm.get("max_output_tokens", 8192))

    def resolve_provider(name: Any) -> Provider:
        if not name:
            return default_provider
        provider = providers.get(str(name))
        if provider is None:
            raise ValueError(
                f"tier 引用了未定义的 provider {name!r}；"
                f"可用：{[k for k in providers if k != '__default__']}"
            )
        return provider

    configured = llm.get("tiers")
    tiers: dict[str, ModelSpec] = {}
    if isinstance(configured, Mapping) and configured:
        for name, spec in configured.items():
            if not isinstance(spec, Mapping):
                raise ValueError(f"llm.tiers.{name} 必须是 JSON object")
            model = str(spec.get("model") or "").strip()
            if not model:
                raise ValueError(f"llm.tiers.{name} 缺少 model")
            provider = resolve_provider(spec.get("provider"))
            tiers[str(name)] = ModelSpec(
                name=model,
                tier=str(name),
                provider=provider,
                reasoning_effort=str(spec.get("reasoning_effort", default_effort)),
                thinking_enabled=_as_bool(
                    spec.get("thinking_enabled"),
                    default=_default_thinking_enabled(model),
                ),
                max_output_tokens=int(spec.get("max_output_tokens", default_max_out)),
            )
        return tiers

    # Legacy fallback: build light/heavy from default_model / pro_model so
    # existing deployments keep working with zero config changes.
    light_model = str(
        llm.get("default_model") or env.get("LLM_MODEL", "deepseek-v4-flash")
    )
    heavy_model = str(llm.get("pro_model") or "").strip() or light_model
    tiers[DEFAULT_TIER_LIGHT] = ModelSpec(
        name=light_model,
        tier=DEFAULT_TIER_LIGHT,
        provider=default_provider,
        reasoning_effort=default_effort,
        thinking_enabled=_default_thinking_enabled(light_model),
        max_output_tokens=default_max_out,
    )
    tiers[DEFAULT_TIER_HEAVY] = ModelSpec(
        name=heavy_model,
        tier=DEFAULT_TIER_HEAVY,
        provider=default_provider,
        reasoning_effort=default_effort,
        thinking_enabled=_default_thinking_enabled(heavy_model),
        max_output_tokens=default_max_out,
    )
    return tiers
