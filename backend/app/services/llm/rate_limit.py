"""Monotonic, reservation-based rate limiting for LLM requests."""

from __future__ import annotations

import time
from typing import Callable


class TokenBucket:
    """A token bucket whose negative balance reserves future capacity.

    Callers serialize ``reserve``. A reservation immediately debits the bucket,
    so concurrent waiters receive distinct release times instead of waking as a
    burst. Monotonic time keeps wall-clock adjustments from changing quotas.
    """

    def __init__(
        self,
        capacity: float,
        refill_per_sec: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.capacity = max(0.0, float(capacity))
        self.refill_per_sec = max(0.0, float(refill_per_sec))
        self.tokens = self.capacity
        self._clock = clock
        self.last = clock()

    def acquire(self, cost: float) -> float:
        """Reserve ``cost`` tokens and return the delay before they are usable."""
        now = self._clock()
        elapsed = max(0.0, now - self.last)
        self.tokens = min(
            self.capacity,
            self.tokens + elapsed * self.refill_per_sec,
        )
        self.last = now
        requested = max(0.0, float(cost))
        self.tokens -= requested
        if self.tokens >= 0 or self.refill_per_sec <= 0:
            return 0.0
        return -self.tokens / self.refill_per_sec


# Kept as a compatibility alias for code/tests that imported the private name.
_TokenBucket = TokenBucket
