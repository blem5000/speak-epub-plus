"""Tests for core/http.py — Core-owned polite HTTP helper (B1 remediation).

Mirrors the test approach used for adapters/_http.py in test_novelphoenix.py:
patch core.http.requests.get + core.http.time.sleep and assert the real
_get body — UA header, timeout, retry counts, and raised HTTPError shape.
"""
from unittest.mock import Mock, patch

import pytest
import requests

from core.http import UA, _get


# ------------------------------------------------------------------ helpers
def _resp(status_code: int, url: str = "https://www.novelphoenix.com/novel/1/chapter/2"):
    m = Mock()
    m.status_code = status_code
    m.text = "<html><body>ok</body></html>"
    m.url = url
    m.headers = {}
    return m


def _timeout():
    return requests.exceptions.Timeout("timed out")


# ------------------------------------------------------------------ success
@patch("core.http.requests.get")
def test_get_success_sends_polite_ua_and_timeout(mock_get):
    mock_get.return_value = _resp(200)
    resp = _get("https://www.novelphoenix.com/novel/1/chapter/2")
    assert resp.status_code == 200
    mock_get.assert_called_once()
    args, kwargs = mock_get.call_args
    assert args[0] == "https://www.novelphoenix.com/novel/1/chapter/2"
    assert kwargs["headers"] == {"User-Agent": UA}
    assert kwargs["headers"]["User-Agent"] == "SpeakEPUB/1.0"
    assert kwargs["timeout"] == 12


# ------------------------------------------------------------------ validation
@patch("core.http.requests.get")
def test_get_invalid_url_raises_without_network(mock_get):
    with pytest.raises(ValueError):
        _get("")
    with pytest.raises(ValueError):
        _get("   ")
    with pytest.raises(ValueError):
        _get(None)  # type: ignore[arg-type]
    mock_get.assert_not_called()


# ------------------------------------------------------------------ retry: 429
@patch("core.http.time.sleep", return_value=None)
@patch("core.http.requests.get")
def test_get_retries_429_then_succeeds(mock_get, mock_sleep):
    mock_get.side_effect = [_resp(429), _resp(200)]
    resp = _get("https://www.novelphoenix.com/novel/1/chapter/2")
    assert resp.status_code == 200
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once()


@patch("core.http.time.sleep", return_value=None)
@patch("core.http.requests.get")
def test_get_exhausted_429_raises_http_error_with_response(mock_get, mock_sleep):
    mock_get.side_effect = [_resp(429), _resp(429), _resp(429)]
    with pytest.raises(requests.exceptions.HTTPError) as ei:
        _get("https://www.novelphoenix.com/novel/1/chapter/2", retries=2)
    assert ei.value.response is not None
    assert ei.value.response.status_code == 429
    assert mock_get.call_count == 3  # retries=2 -> 3 total attempts
    assert mock_sleep.call_count == 2


# ------------------------------------------------------------------ retry: 5xx
@patch("core.http.time.sleep", return_value=None)
@patch("core.http.requests.get")
def test_get_retries_5xx_then_raises_http_error(mock_get, mock_sleep):
    mock_get.side_effect = [_resp(500), _resp(503)]
    with pytest.raises(requests.exceptions.HTTPError) as ei:
        _get("https://www.novelphoenix.com/novel/1/chapter/2", retries=1)
    assert ei.value.response is not None
    assert ei.value.response.status_code == 503
    assert mock_get.call_count == 2


# ------------------------------------------------------------------ retry: other 4xx (documented robustness policy)
@patch("core.http.time.sleep", return_value=None)
@patch("core.http.requests.get")
def test_get_retries_other_4xx_per_documented_policy(mock_get, mock_sleep):
    mock_get.side_effect = [_resp(403), _resp(200)]
    resp = _get("https://www.novelphoenix.com/novel/1/chapter/2")
    assert resp.status_code == 200
    assert mock_get.call_count == 2


# ------------------------------------------------------------------ retry: timeout
@patch("core.http.time.sleep", return_value=None)
@patch("core.http.requests.get")
def test_get_retries_timeout_then_raises(mock_get, mock_sleep):
    mock_get.side_effect = [_timeout(), _timeout()]
    with pytest.raises(requests.exceptions.Timeout):
        _get("https://www.novelphoenix.com/novel/1/chapter/2", retries=1)
    assert mock_get.call_count == 2
    assert mock_sleep.call_count == 1


# ------------------------------------------------------------------ coercion
@patch("core.http.time.sleep", return_value=None)
@patch("core.http.requests.get")
def test_get_coerces_bad_retries_to_default(mock_get, mock_sleep):
    # retries=None is invalid -> coerced to default 2 -> 3 attempts
    mock_get.side_effect = [_resp(429), _resp(429), _resp(200)]
    resp = _get("https://www.novelphoenix.com/novel/1/chapter/2", retries=None)  # type: ignore[arg-type]
    assert resp.status_code == 200
    assert mock_get.call_count == 3


@patch("core.http.requests.get")
def test_get_coerces_bad_timeout_to_default(mock_get):
    mock_get.return_value = _resp(200)
    _get("https://www.novelphoenix.com/novel/1/chapter/2", timeout="bogus")  # type: ignore[arg-type]
    _, kwargs = mock_get.call_args
    assert kwargs["timeout"] == 12
