"""
adapters/base.py — helper: fallback guessing.
Used when title search fails or unknown-domain URL is pasted (CAP-1 fallback).
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse


# Registry of known domains → adapter name (AD-1: Core never imports concrete adapters directly,
# but this helper lives in adapters layer and is called by Core aggregator via import).
KNOWN_ADAPTERS: dict[str, str] = {
    "novelphoenix.com": "novelphoenix",
    "www.novelphoenix.com": "novelphoenix",
}


def guess_adapter(url: str) -> Optional[str]:  # type: ignore[override]
    """
    Heuristic: return adapter name for URL, or None if unknown.
    Future: plug more adapters without touching Core.
    """
    if not isinstance(url, str):
        return None
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return None
    if host in KNOWN_ADAPTERS:
        return KNOWN_ADAPTERS[host]
    # host-suffix check avoids false positives from query params (e.g. evil.com?x=novelphoenix.com)
    for domain, name in KNOWN_ADAPTERS.items():
        if host == domain or host.endswith("." + domain):
            return name
    # fallback substring only on host, not full url, to avoid query param spoof
    return None
