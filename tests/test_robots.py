"""Tests for the robots.txt handling and the per-host politeness (fetch.py).

The rules: a path the site disallows for our user agent is not fetched, the
site's Crawl-delay is respected, and a missing/locked robots.txt never
blocks the app (fail-open).
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import fetch as fetch_mod  # noqa: E402

URL = "https://www.novelphoenix.com/novel/123/chapter/1"


class _FakeRobotParser:
    """A stand-in for urllib.robotparser.RobotFileParser."""

    def __init__(self, allowed: bool = True, delay: float | None = None, disallow_all: bool = False):
        self._allowed = allowed
        self._delay = delay
        self.disallow_all = disallow_all
        self.allow_all = False

    def can_fetch(self, useragent, url):  # noqa: ARG002
        return self._allowed

    def crawl_delay(self, useragent):  # noqa: ARG002
        return self._delay


@pytest.fixture(autouse=True)
def _clear_robots_cache():
    fetch_mod._ROBOTS_CACHE.clear()
    fetch_mod._HOST_NEXT_OK.clear()
    yield
    fetch_mod._ROBOTS_CACHE.clear()
    fetch_mod._HOST_NEXT_OK.clear()


class TestRobotsRules:
    def test_allowed_path(self):
        with patch.object(fetch_mod, "_robots_parser", return_value=_FakeRobotParser(allowed=True)):
            assert fetch_mod.robots_allows(URL) == (True, "")

    def test_disallowed_path_is_reported(self):
        with patch.object(fetch_mod, "_robots_parser", return_value=_FakeRobotParser(allowed=False)):
            allowed, blocked = fetch_mod.robots_allows(URL)
        assert allowed is False
        assert blocked == URL

    def test_missing_robots_allows_everything(self):
        with patch.object(fetch_mod, "_robots_parser", return_value=None):
            assert fetch_mod.robots_allows(URL) == (True, "")

    def test_locked_robots_is_treated_as_unknown(self):
        # a robots.txt served with 401/403 would make the stdlib parser
        # disallow everything — that must not break the app
        with patch.object(fetch_mod, "_robots_parser", return_value=None):
            assert fetch_mod.robots_allows(URL) == (True, "")

    def test_crawl_delay_is_honoured(self):
        with patch.object(fetch_mod, "_robots_parser", return_value=_FakeRobotParser(delay=12.0)):
            assert fetch_mod.robots_crawl_delay(URL) == 12.0
            assert fetch_mod.host_delay_floor(URL) == 12.0

    def test_our_own_floor_applies(self):
        with patch.object(fetch_mod, "_robots_parser", return_value=_FakeRobotParser(delay=None)):
            assert fetch_mod.host_delay_floor(URL) == fetch_mod.HOST_MIN_DELAY_SEC


class TestPerHostDelay:
    def test_second_request_waits_for_the_host(self):
        with patch.object(fetch_mod, "_robots_parser", return_value=None):
            with patch("core.fetch.time.sleep") as sleep:
                fetch_mod.respect_host_delay(URL)
                fetch_mod.respect_host_delay(URL)
        # the first call may not sleep (nothing pending), the second must
        assert sleep.called

    def test_wait_is_bounded(self):
        with patch.object(fetch_mod, "_robots_parser", return_value=None):
            with patch("core.fetch.time.sleep") as sleep:
                fetch_mod._HOST_NEXT_OK["www.novelphoenix.com"] = 1e12
                fetch_mod.respect_host_delay(URL)
        assert sleep.called
        assert sleep.call_args[0][0] <= 60.0

    def test_the_delay_is_a_max_not_a_sum(self):
        # our own 3 s floor + the caller's 5 s must not add up to 8 s
        import time as _time

        with patch.object(fetch_mod, "_robots_parser", return_value=None):
            with patch("core.fetch.time.sleep"):
                before = _time.time()
                fetch_mod.respect_host_delay(URL, extra=5.0)
                earliest = fetch_mod._HOST_NEXT_OK["www.novelphoenix.com"]
        assert 0 < (earliest - before) <= 5.5, earliest - before


class TestRealSiteRules:
    """The rules of the site the app actually scrapes (checked live once)."""

    def test_novelphoenix_allows_our_paths(self):
        allowed, blocked = fetch_mod.robots_allows(URL)
        assert allowed is True, blocked
