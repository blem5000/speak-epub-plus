"""
core/aggregator.py — title search fan-out (Epic 1.2).

Parallel per-site search with 5s timeout, dedupe (site,url), fault-isolate
per adapter on ValueError/AdapterError → [] . Does not import adapters
concrete (AD-1: core → adapters forbidden via importlinter); depends only on
core.ports ScraperPort.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import List

from .ports import AdapterError, SearchResult, ScraperPort


def _safe_search(adapter: ScraperPort, title: str) -> List[SearchResult]:
    try:
        return adapter.search(title)
    except BaseException:
        return []


def search_all(title: str, adapters: List[ScraperPort]) -> List[SearchResult]:
    """Search all adapters in parallel, 5s per adapter, dedupe, fault-isolate.

    Args:
        title: novel title (validation is per-adapter; empty leads to [] via faults)
        adapters: list of ScraperPort instances

    Returns:
        merged deduped list of SearchResult
    """
    if not adapters:
        return []
    if not isinstance(title, str) or not title.strip():
        return []
    # deduplicate by (site, url)
    seen: set[tuple[str, str]] = set()
    merged: List[SearchResult] = []

    # Use ThreadPoolExecutor with max_workers = min(len(adapters),10)
    # Use manual shutdown(wait=False) so a slow adapter timing out after 5s
    # does not block overall return; spec requires <5s per site parallel.
    pool = ThreadPoolExecutor(max_workers=min(len(adapters), 10) or 1)
    try:
        future_map = {pool.submit(_safe_search, adapter, title): adapter for adapter in adapters}
        for fut, adapter in future_map.items():
            try:
                results = fut.result(timeout=5)
            except FutureTimeout:
                # per-adapter timeout → contribute []
                continue
            except Exception:
                continue
            if not results:
                continue
            for r in results:
                if not r or not getattr(r, "url", None) or not getattr(r, "site", None):
                    continue
                key = (r.site, r.url)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(r)
    finally:
        # Do not wait for slow futures; they will be abandoned.
        # cancel_futures=True for pending, running will be left.
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            # Python <3.9 no cancel_futures
            pool.shutdown(wait=False)
    return merged
