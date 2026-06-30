"""Shared async POST-with-retry for the IDP gateway (LLM + embeddings).

Retries rate-limit (429), server (5xx) and transient network errors with exponential backoff +
jitter, honoring a Retry-After header when present. Other 4xx fail fast (a bad request won't fix
itself). One implementation so the LLM and embeddings clients behave identically under load.
"""

from __future__ import annotations

import asyncio
import random
import sys

import httpx


def retry_after_seconds(response: httpx.Response) -> float | None:
    """The Retry-After header in seconds, if present in integer-seconds form."""
    value = response.headers.get("retry-after") or response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None  # HTTP-date form not handled; caller falls back to computed backoff


def _body_snippet(response: httpx.Response, limit: int = 600) -> str:
    """A short, single-line view of the response body for logs (the gateway's error message)."""
    try:
        text = response.text
    except Exception:  # noqa: BLE001 - never let logging crash the call
        return "<unreadable body>"
    text = " ".join(text.split())  # collapse whitespace/newlines onto one line
    return text[:limit] + (" …(truncated)" if len(text) > limit else "") or "<empty body>"


def _backoff(attempt: int, base: float, cap: float) -> float:
    delay = min(base * (2 ** attempt), cap)
    return delay * (0.5 + random.random() / 2)  # jitter in [0.5x, 1x]


async def post_with_retry(
    http: httpx.AsyncClient,
    path: str,
    json: dict,
    *,
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    timeout_retries: int = 2,
) -> httpx.Response:
    """POST json to path. Retries 429/5xx PATIENTLY (``max_retries`` - waiting helps a rate window),
    but a TIMEOUT / transient-network error means the call itself is too slow, so retrying just
    repeats the timeout - cap those at ``timeout_retries`` (fail fast, don't loop). Returns the OK
    response; raises on non-retryable 4xx or after exhausting retries."""
    target = f"{str(http.base_url).rstrip('/')}/{path.lstrip('/')}"
    rate_tries = timeout_tries = 0
    print(f"[http] POST {target}", file=sys.stderr, flush=True)
    while True:
        try:
            response = await http.post(path, json=json)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            # TimeoutException = the call ran but was too slow; other transport errors (ConnectError,
            # NetworkError, ...) = we never reached the host. Different fixes, so name them apart.
            reason = ("timed out (call too slow)" if isinstance(exc, httpx.TimeoutException)
                      else f"cannot reach host (connect/transport error: {type(exc).__name__})")
            timeout_tries += 1
            if timeout_tries > timeout_retries:  # a recurring timeout/connect error won't self-heal
                print(f"[http] GAVE UP on {target}: {reason} after {timeout_tries} attempt(s)",
                      file=sys.stderr, flush=True)
                raise
            d = _backoff(timeout_tries - 1, base_delay, max_delay)
            print(f"[retry] {target}: {reason} -> retry {timeout_tries}/{timeout_retries} "
                  f"in {d:.0f}s", file=sys.stderr, flush=True)
            await asyncio.sleep(d)
            continue
        if response.status_code == 429 or response.status_code >= 500:
            rate_tries += 1
            if rate_tries > max_retries:
                print(f"[http] GAVE UP on {target}: HTTP {response.status_code} after "
                      f"{rate_tries} attempt(s) :: {_body_snippet(response)}", file=sys.stderr, flush=True)
                response.raise_for_status()  # out of retries -> surface the real error
            delay = retry_after_seconds(response) or _backoff(rate_tries - 1, base_delay, max_delay)
            print(f"[retry] {target}: HTTP {response.status_code} (rate/server) -> retry "
                  f"{rate_tries}/{max_retries} in {delay:.0f}s :: {_body_snippet(response)}",
                  file=sys.stderr, flush=True)
            await asyncio.sleep(delay)
            continue
        if response.status_code >= 400:  # other 4xx -> fail fast, but show what the endpoint said
            print(f"[http] {target}: HTTP {response.status_code} :: {_body_snippet(response)}",
                  file=sys.stderr, flush=True)
            response.raise_for_status()
        print(f"[http] {target}: HTTP {response.status_code} OK", file=sys.stderr, flush=True)
        return response
