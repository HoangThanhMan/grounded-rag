"""Requests per minute per client, on /api/chat only: every question costs an
LLM call, and a public demo runs on a free-tier quota.

A token bucket in this process. Enough for one replica; with several, each
would count on its own and the limit would multiply - that is when it moves
to Redis.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable

from fastapi import Request

from grounded_rag.api.errors import AppError
from grounded_rag.config import settings

MAX_CLIENTS = 10_000


class TokenBucketLimiter:
    """`rate_per_minute` requests in a burst, refilled at the same rate.
    0 turns it off."""

    def __init__(self, rate_per_minute: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.capacity = float(rate_per_minute)
        self.refill = rate_per_minute / 60.0        # tokens per second
        self.clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}   # key -> (tokens, at)

    def check(self, key: str) -> float | None:
        """None when the request may go ahead, else seconds until it may."""
        if self.capacity <= 0:
            return None
        now = self.clock()
        tokens, at = self._buckets.get(key, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - at) * self.refill)
        if tokens >= 1:
            self._remember(key, (tokens - 1, now))
            return None
        self._remember(key, (tokens, now))
        return (1 - tokens) / self.refill

    def _remember(self, key: str, state: tuple[float, float]) -> None:
        if key not in self._buckets and len(self._buckets) >= MAX_CLIENTS:
            # A client whose bucket has refilled is indistinguishable from a
            # new one, so its entry can go.
            now = self.clock()
            self._buckets = {
                k: (t, a) for k, (t, a) in self._buckets.items()
                if t + (now - a) * self.refill < self.capacity
            }
        self._buckets[key] = state


limiter = TokenBucketLimiter(settings.rate_limit_per_minute)


def client_key(request: Request) -> str:
    """Behind the proxy, the last X-Forwarded-For hop: the address the proxy
    itself saw. Hops before it are whatever the client chose to send."""
    if settings.trust_proxy and (forwarded := request.headers.get("x-forwarded-for")):
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


async def rate_limit(request: Request) -> None:
    wait = limiter.check(client_key(request))
    if wait is not None:
        seconds = max(1, math.ceil(wait))
        raise AppError(
            429,
            "rate_limited",
            f"too many questions, try again in {seconds} s",
            {"Retry-After": str(seconds)},
        )
