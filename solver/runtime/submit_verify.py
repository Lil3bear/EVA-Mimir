"""Post-submit platform verification helpers."""

from __future__ import annotations

import re

_DECOY_SCAN_RE = re.compile(
    r"/challenge/flag\d*\.txt|/challenge/flag\b|find\s+/.+flag",
    re.IGNORECASE,
)
_DECOY_PROTOCOL_MARKERS = (
    "responsd ready",
    "setbody",
    "/sys/devices/",
    "hdrtab:",
    "flag=false",
)


def is_decoy_flag_context(raw: str, candidate: str) -> bool:
    """True when *candidate* likely comes from honeypot paths or alien protocols."""
    text = raw or ""
    if not candidate or candidate not in text:
        return False
    if _DECOY_SCAN_RE.search(text):
        return True
    lowered = text.lower()
    if any(marker in lowered for marker in _DECOY_PROTOCOL_MARKERS) and candidate in text:
        return True
    return False


def submission_message_verified(result: str) -> bool:
    """True only when a submit tool result reflects verified platform progress."""
    if not result:
        return False
    if "[✓]" not in result:
        return False
    if any(token in result for token in ("未计分", "题号不匹配", "诱饵")):
        return False
    return True
