"""외부 API 재시도: 429/5xx/timeout 3회, 0.5/1.0/2.0s backoff."""

from __future__ import annotations

import time
from typing import Callable

import httpx

BACKOFFS = (0.5, 1.0, 2.0)
RETRY_STATUS = {429, 500, 502, 503, 504}


def request_with_retry(send: Callable[[], httpx.Response], sleep: Callable[[float], None] = time.sleep) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(len(BACKOFFS) + 1):
        try:
            resp = send()
            if resp.status_code not in RETRY_STATUS:
                return resp
            last_exc = None
            last_resp = resp
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            last_resp = None
        if attempt < len(BACKOFFS):
            sleep(BACKOFFS[attempt])
    if last_exc is not None:
        raise last_exc
    return last_resp  # type: ignore[return-value]
