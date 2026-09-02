"""Unified exponential-backoff retry for transient external operations."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from settings import Settings

# Never stall a run waiting out a rate-limit window longer than this.
MAX_RETRY_DELAY_SECONDS = 30.0


def _retry_settings(settings: Settings) -> tuple[int, float]:
    # settings.validate_for_run guarantees both retry knobs are configured.
    assert settings.retry_max_attempts is not None
    assert settings.retry_backoff_seconds is not None
    return settings.retry_max_attempts, settings.retry_backoff_seconds


async def retry[T](
    operation: Callable[[], Awaitable[T]],
    *,
    max_attempts: int,
    backoff_seconds: float,
    retryable: Callable[[BaseException], bool] = lambda exc: True,
    retry_after: Callable[[BaseException], float | None] | None = None,
    on_retry: Callable[[int, float, BaseException], None] | None = None,
) -> T:
    """Run ``operation`` with capped exponential backoff.

    Non-retryable exceptions (per ``retryable``) re-raise immediately.
    ``retry_after`` may override the backoff with a server-provided delay,
    and ``on_retry`` observes each wait before it happens.
    """

    for attempt in range(1, max_attempts + 1):
        try:
            return await operation()
        except Exception as exc:
            if attempt == max_attempts or not retryable(exc):
                raise
            server_delay = retry_after(exc) if retry_after is not None else None
            delay = server_delay if server_delay else backoff_seconds * (2 ** (attempt - 1))
            delay = min(delay, MAX_RETRY_DELAY_SECONDS)
            if on_retry is not None:
                on_retry(attempt, delay, exc)
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable")
