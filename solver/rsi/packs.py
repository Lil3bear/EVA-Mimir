"""Regression pack resolution for local RSI runs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping, Sequence

_DEFAULT_PACKS_FILE = "config/regression_codes.json"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _packs_file_path(settings: dict) -> Path:
    rsi = settings.get("rsi") or {}
    rel = str(rsi.get("packs_file") or _DEFAULT_PACKS_FILE).strip()
    candidate = Path(rel)
    if candidate.is_file():
        return candidate
    rooted = _project_root() / rel
    if rooted.is_file():
        return rooted
    return candidate


def load_packs(settings: dict | None = None) -> dict[str, dict]:
    """Load named regression packs from config file + inline settings overrides."""
    settings = settings or {}
    packs: dict[str, dict] = {}

    path = _packs_file_path(settings)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            file_packs = raw.get("packs") if isinstance(raw, dict) else {}
            if isinstance(file_packs, dict):
                for name, spec in file_packs.items():
                    if isinstance(spec, dict):
                        packs[str(name)] = dict(spec)
        except (OSError, json.JSONDecodeError):
            pass

    inline = (settings.get("rsi") or {}).get("packs")
    if isinstance(inline, dict):
        for name, spec in inline.items():
            if isinstance(spec, list):
                packs[str(name)] = {"codes": [str(c) for c in spec]}
            elif isinstance(spec, dict):
                merged = dict(packs.get(str(name), {}))
                merged.update(spec)
                packs[str(name)] = merged

    return packs


def pack_codes(pack_name: str, settings: dict | None = None) -> list[str]:
    """Return explicit code list for a pack (prefix-only packs return empty list)."""
    packs = load_packs(settings)
    spec = packs.get(pack_name)
    if not isinstance(spec, dict):
        return []
    codes = spec.get("codes")
    if isinstance(codes, list):
        return [str(c).strip() for c in codes if str(c).strip()]
    return []


def pack_prefix_filter(pack_name: str, settings: dict | None = None) -> str | None:
    """Return SOLVER_PREFIX_FILTER value when pack is prefix-based."""
    packs = load_packs(settings)
    spec = packs.get(pack_name)
    if not isinstance(spec, dict):
        return None
    prefix = spec.get("prefix")
    if isinstance(prefix, str) and prefix.strip():
        return prefix.strip()
    prefixes = spec.get("prefixes")
    if isinstance(prefixes, list) and prefixes:
        # Multi-prefix packs use first prefix as filter hint; caller may combine with only_codes.
        first = str(prefixes[0]).strip()
        return first or None
    return None


def _parse_env_codes(raw: str) -> set[str]:
    return {code.strip() for code in raw.split(",") if code.strip()}


def resolve_only_codes(
    settings: dict,
    environ: Mapping[str, str] | None = None,
    *,
    pack_name: str = "",
) -> set[str] | None:
    """Resolve SOLVER_ONLY_CODES: env > settings.rsi.only_codes > pack > None (run all)."""
    env = os.environ if environ is None else environ

    env_raw = env.get("SOLVER_ONLY_CODES", "").strip()
    if env_raw:
        return _parse_env_codes(env_raw)

    rsi = settings.get("rsi") or {}
    configured = rsi.get("only_codes")
    if isinstance(configured, list):
        codes = {str(c).strip() for c in configured if str(c).strip()}
        return codes or None

    pack = (pack_name or env.get("SOLVER_RSI_PACK", "")).strip()
    if pack:
        codes = pack_codes(pack, settings)
        if codes:
            return set(codes)

    return None


def resolve_prefix_filter(
    settings: dict,
    environ: Mapping[str, str] | None = None,
    *,
    pack_name: str = "",
) -> str | None:
    """Env SOLVER_PREFIX_FILTER wins; else derive from RSI pack if prefix-based."""
    env = os.environ if environ is None else environ
    env_prefix = env.get("SOLVER_PREFIX_FILTER", "").strip()
    if env_prefix:
        return env_prefix

    pack = (pack_name or env.get("SOLVER_RSI_PACK", "")).strip()
    if not pack:
        return None
    return pack_prefix_filter(pack, settings)


def list_packs_summary(settings: dict | None = None) -> list[dict]:
    """Human-readable pack catalog for CLI."""
    rows: list[dict] = []
    for name, spec in sorted(load_packs(settings).items()):
        if not isinstance(spec, dict):
            continue
        codes = pack_codes(name, settings)
        prefix = pack_prefix_filter(name, settings)
        rows.append(
            {
                "name": name,
                "description": str(spec.get("description", "")),
                "codes": codes,
                "prefix_filter": prefix,
                "count": len(codes) if codes else ("prefix:" + prefix if prefix else 0),
            }
        )
    return rows


def codes_for_cli(pack_name: str, settings: dict | None = None) -> str:
    """Comma-separated codes for shell export."""
    return ",".join(pack_codes(pack_name, settings or {}))
