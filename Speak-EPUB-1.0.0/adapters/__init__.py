"""Adapters package — concrete ScraperPort implementations."""
from .base import guess_adapter
from .novelphoenix import NovelPhoenixAdapter

__all__ = ["guess_adapter", "NovelPhoenixAdapter"]
