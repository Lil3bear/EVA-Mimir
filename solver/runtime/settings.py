"""Single settings loader for local and benchmark runtimes."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import urlparse, urlunparse


DEFAULT_SETTINGS_PATHS = (
    "/workspace/settings.local.json",
    "/workspace/settings.json",
    "settings.local.json",
    "settings.json",
)


def apply_llm_gateway(url: str, environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    if env.get("LLM_GATEWAY", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return url
    url = (url or "").strip()
    if not url:
        return url
    parsed = urlparse(url)
    host = (parsed.hostname or "").strip().rstrip(".")
    if not parsed.scheme or not host:
        return url
    # Gateway requests are always plain HTTP.  This also normalizes a URL
    # that was already manually suffixed with .tsecbench.gw but still used
    # the original https scheme.
    if not host.endswith(".tsecbench.gw"):
        host = f"{host}.tsecbench.gw"
    port = f":{parsed.port}" if parsed.port else ""
    return urlunparse(parsed._replace(scheme="http", netloc=f"{host}{port}"))


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge overlay onto base (overlay wins on conflicts)."""
    merged = dict(base)
    for key, value in overlay.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(
    paths: Sequence[str | Path] = DEFAULT_SETTINGS_PATHS,
    environ: Mapping[str, str] | None = None,
) -> dict:
    env = os.environ if environ is None else environ
    # Merge all existing files: later paths in DEFAULT_SETTINGS_PATHS win
    # (settings.json base → settings.local.json overlay).
    existing = [Path(p) for p in paths if Path(p).is_file()]
    settings: dict = {}
    for candidate in reversed(existing):
        try:
            loaded = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"无法加载配置文件 {candidate}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ValueError(f"配置文件 {candidate} 的根节点必须是 JSON object")
        settings = _deep_merge(settings, loaded)

    llm = _section(settings, "llm")
    _apply_env(llm, env, {
        "LLM_BASE_URL": "base_url",
        "LLM_API_KEY": "api_key",
        "LLM_MODEL": "default_model",
        "LLM_PRO_MODEL": "pro_model",
    })
    if llm.get("base_url"):
        llm["base_url"] = apply_llm_gateway(str(llm["base_url"]), env)
    # providers 的 base_url 同样走网关改写，否则 tiers 指向的 provider
    # 会绕过 .tsecbench.gw 直连，在托管沙箱里必然超时。
    providers = llm.get("providers")
    if isinstance(providers, dict):
        for spec in providers.values():
            if isinstance(spec, dict) and spec.get("base_url"):
                spec["base_url"] = apply_llm_gateway(str(spec["base_url"]), env)

    search_llm = _section(settings, "search_llm")
    _apply_env(search_llm, env, {
        "SEARCH_LLM_BASE_URL": "base_url",
        "SEARCH_LLM_API_KEY": "api_key",
        "SEARCH_LLM_MODEL": "model",
    })
    if search_llm.get("base_url"):
        search_llm["base_url"] = apply_llm_gateway(str(search_llm["base_url"]), env)

    solver = _section(settings, "solver")
    _apply_int_env(solver, env, "SOLVER_MAX_ROUNDS", "max_rounds")
    _apply_int_env(solver, env, "SOLVER_OBSERVER_EVERY", "observer_every_rounds")

    rsi = _section(settings, "rsi")
    if env.get("SOLVER_RSI_PACK"):
        rsi["active_pack"] = env["SOLVER_RSI_PACK"].strip()
    return enforce_medium_only_routing(settings)


def enforce_medium_only_routing(settings: dict) -> dict:
    """Force medium-only routing, unless SOLVER_HIGH_TIER=1 allows heavy/high tiers."""
    llm = settings.setdefault("llm", {})
    routing = llm.setdefault("routing", {})
    allow_high = os.environ.get("SOLVER_HIGH_TIER") == "1"
    corrected = (
        not allow_high
        and (
            str(routing.get("hard_tier", "light")) != "light"
            or int(routing.get("escalate_rounds", 0) or 0) > 0
            or str(routing.get("stuck_escalate_tier", "light")) != "light"
        )
    )
    if not allow_high:
        routing["hard_tier"] = "light"
        routing["stuck_escalate_tier"] = "light"
        routing["escalate_rounds"] = 0
    routing.setdefault("fast_lane_tier", "light")
    routing.setdefault("deep_lane_default_tier", "light")
    routing.setdefault("summary_tier", "light")
    routing.setdefault("observer_tier", "light")
    llm.setdefault("reasoning_effort", "medium")
    llm.setdefault("reasoning_effort_cap", "medium")
    if corrected:
        settings["_routing_corrected"] = True
    return settings


def _section(settings: dict, name: str) -> dict:
    section = settings.setdefault(name, {})
    if not isinstance(section, dict):
        raise ValueError(f"配置项 {name} 必须是 JSON object")
    return section


def _apply_env(target: dict, env: Mapping[str, str], names: Mapping[str, str]) -> None:
    for env_name, setting_name in names.items():
        if env.get(env_name):
            target[setting_name] = env[env_name]


def _apply_int_env(
    target: dict, env: Mapping[str, str], env_name: str, setting_name: str
) -> None:
    value = env.get(env_name)
    if not value:
        return
    try:
        target[setting_name] = int(value)
    except ValueError as exc:
        raise ValueError(f"环境变量 {env_name} 必须是整数，实际为 {value!r}") from exc
