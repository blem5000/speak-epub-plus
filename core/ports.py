"""
ScraperPort ABC — Core → Port → Adapter (AD-1).
Frozen DTOs + abstract methods: search / listChapters / fetchChapter / getSelectors.
No adapter imports pipeline/GUI; pipeline never imports concrete adapters.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List, Optional


@dataclass(frozen=True)
class Selectors:
    start: Optional[str] = None
    end: Optional[str] = None

    def __post_init__(self) -> None:
        # normalize empty/whitespace strings to None so querySelector doesn't
        # throw on a blank selector
        for field in ("start", "end"):
            value = getattr(self, field)
            if isinstance(value, str) and not value.strip():
                object.__setattr__(self, field, None)


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
    url: str
    # the title is optional: the layers fall back to the URL or "Chapter N"
    title: str = ""


@dataclass(frozen=True)
class ChapterContent:
    url: str
    title: str
    html: str
    text: str
    cover_url: Optional[str] = None


class AdapterError(Exception):
    """Adapter failure with machine-readable code (e.g. LIST_FAILED).

    `details` carries structured data (the list of missing chapter URLs, the
    offending range, ...) so callers do not have to parse the message.
    """

    def __init__(self, message: str, code: str = "UNKNOWN", details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details if details is not None else {}


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
