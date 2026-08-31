"""core/http.py — Core-owned polite HTTP helper (AD-1 firewall).

Mirrors adapters/_http.py politeness values exactly — UA SpeakEPUB/1.0,
timeout 12s, retries 2, jitter 0.2-0.6s, backoff min(20, 2*attempt) — so
behavior is indistinguishable from the adapter-local helper. Exists so
core.config's preview fallback no longer imports an adapter module
(core-no-adapters contract in .importlinter).

Retry policy: on Timeout/ConnectionError and on HTTP 429/5xx always
retry; on other 4xx also retry for robustness. Caller decides final
mapping to [] or AdapterError.
"""
from __future__ import annotations

import random
import time

import requests


UA = "SpeakEPUB/1.0"
_HEADERS = {"User-Agent": UA}


def _get(url: str, timeout: float = 12, retries: int = 2) -> requests.Response:
    """GET with polite UA, retry, jitter and capped backoff.

    Retries `retries` times (total attempts = retries+1). Between attempts
    sleeps `min(20, 2*attempt) + uniform(0.2,0.6)` to respect politeness.
    Retries on network Timeout/ConnectionError and on HTTP 429 / 5xx;
    also retries other 4xx for robustness (final caller maps to []).
    Raises the last exception after exhausting retries.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("invalid url")
    if not isinstance(retries, int) or retries < 0:
        retries = 2
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        timeout = 12
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=timeout)
            # Success
            if resp.status_code < 400:
                return resp
            # Error status -> decide retry
            # Treat 429 and 5xx as retryable
            retryable = resp.status_code == 429 or 500 <= resp.status_code < 600
            # For robustness, also retry other 4xx up to retries
            if not retryable and 400 <= resp.status_code < 500:
                retryable = True
            if retryable and attempt < retries:
                wait = min(20, 2 * (attempt + 1)) + random.uniform(0.2, 0.6)
                time.sleep(wait)
                continue
            # After retries or non-retryable, raise to caller
            # Attach response for caller to inspect status
            http_err = requests.exceptions.HTTPError(
                f"{resp.status_code} for {url}", response=resp
            )
            raise http_err
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            if attempt < retries:
                wait = min(20, 2 * (attempt + 1)) + random.uniform(0.2, 0.6)
                time.sleep(wait)
                continue
            raise
        except requests.exceptions.HTTPError:
            # already handled retry above; re-raise if not retried
            raise
        except Exception as e:
            last_exc = e
            if attempt < retries:
                wait = min(20, 2 * (attempt + 1)) + random.uniform(0.2, 0.6)
                time.sleep(wait)
                continue
            raise
    # Fallback (should not reach)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"request failed after {retries} retries: {url}")
