"""
ScraperPort ABC — Core → Port → Adapter (AD-1).
Frozen DTOs + abstract methods: search / listChapters / fetchChapter / getSelectors.
No adapter imports pipeline/GUI; pipeline never imports concrete adapters.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Selectors:
    start: Optional[str] = None
    end: Optional[str] = None

    def __post_init__(self) -> None:
        # normalize empty string to None so querySelector doesn't throw
        if self.start == "":
            object.__setattr__(self, "start", None)
        if self.end == "":
            object.__setattr__(self, "end", None)


@dataclass(frozen=True)
class SearchResult:
    site: str
    title: str
    url: str
    chapter_count: Optional[int] = None
    author: Optional[str] = None
    cover_url: Optional[str] = None


@dataclass(frozen=True)
class ChapterInfo:
    index: int
    title: str
    url: str


@dataclass(frozen=True)
class ChapterContent:
    url: str
    title: str
    html: str
    text: str


class AdapterError(Exception):
    """Adapter failure with machine-readable code (e.g. LIST_FAILED)."""

    def __init__(self, message: str, code: str = "UNKNOWN") -> None:
        super().__init__(message)
        self.code = code


class ScraperPort(ABC):
    """Contract for site adapters. Discovery surfaces depend only on this ABC."""

    @abstractmethod
    def search(self, title: str) -> List[SearchResult]:
        """Search by title. Mock only in 1.1 — Epic 1.2 implements."""
        raise NotImplementedError

    @abstractmethod
    def listChapters(self, url: str) -> List[ChapterInfo]:
        """List chapters for a novel URL in spine order 1..N."""
        raise NotImplementedError

    @abstractmethod
    def fetchChapter(self, url: str) -> ChapterContent:
        """Fetch single chapter body."""
        raise NotImplementedError

    @abstractmethod
    def getSelectors(self) -> Selectors:
        """Return per-adapter start/end CSS selectors (AD-7)."""
        raise NotImplementedError

    # Alias helpers for camelCase callers (JS/Rust side)
    # Keep snake_case as canonical; wrappers for interop if needed
    def list_chapters(self, url: str) -> List[ChapterInfo]:  # pragma: no cover
        return self.listChapters(url)

    def fetch_chapter(self, url: str) -> ChapterContent:  # pragma: no cover
        return self.fetchChapter(url)

    def get_selectors(self) -> Selectors:  # pragma: no cover
        return self.getSelectors()
