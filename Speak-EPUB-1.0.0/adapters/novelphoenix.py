"""
adapters/novelphoenix.py — skeleton ScraperPort impl proving port direction (AD-1).
Network logic is mock only — Epic 1.2 implements real search/listChapters/fetchChapter.
"""
from __future__ import annotations

from typing import List

from core.ports import ChapterContent, ChapterInfo, ScraperPort, SearchResult, Selectors


class NovelPhoenixAdapter(ScraperPort):
    """NovelPhoenix adapter — selectors + heuristic fallback owned by adapter (AD-5/AD-7)."""

    def search(self, title: str) -> List[SearchResult]:
        raise NotImplementedError("mock only — Epic 1.2 implements")

    def listChapters(self, url: str) -> List[ChapterInfo]:
        raise NotImplementedError("mock only — Epic 1.2 implements")

    def fetchChapter(self, url: str) -> ChapterContent:
        raise NotImplementedError("mock only — Epic 1.2 implements")

    def getSelectors(self) -> Selectors:
        # Skeleton — per-site start/end selectors (AD-7). None means heuristic fallback.
        return Selectors(start=None, end=None)
