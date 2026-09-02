"""Channel resolution for a run: live Buffer listing or dry-run fallbacks."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

from buffer.client import BufferAPIError, BufferChannel, BufferClient
from job.retry import retry


def _load_cached_channels(cache_path: Path) -> list[BufferChannel] | None:
    try:
        payload = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(payload, list):
        return None
    channels = [
        BufferChannel(
            id=str(entry["id"]),
            name=str(entry.get("name") or ""),
            display_name=str(entry.get("display_name") or entry.get("displayName") or ""),
            service=str(entry.get("service") or ""),
        )
        for entry in payload
        if isinstance(entry, dict) and entry.get("id")
    ]
    return channels or None


def _store_cached_channels(cache_path: Path, channels: list[BufferChannel]) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps([asdict(channel) for channel in channels], indent=2))
    except OSError:
        pass  # caching is best-effort; never fail a run over it


def _is_retryable_buffer_error(exc: BaseException) -> bool:
    return isinstance(exc, BufferAPIError) and exc.retryable


def _buffer_retry_after(exc: BaseException) -> float | None:
    return exc.retry_after if isinstance(exc, BufferAPIError) and exc.retryable else None


def _log_channel_retry(attempt: int, max_attempts: int, delay: float, exc: BaseException) -> None:
    status = exc.status_code if isinstance(exc, BufferAPIError) else None
    print(
        f"Buffer unavailable (HTTP {status or 'error'}); "
        f"retry {attempt}/{max_attempts} in {delay:.0f}s...",
        file=sys.stderr,
        flush=True,
    )


async def _list_channels_with_retries(
    client: BufferClient,
    organization_id: str,
    *,
    max_attempts: int,
    backoff_seconds: float,
) -> list[BufferChannel]:
    return await retry(
        lambda: client.list_available_channels(organization_id),
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
        retryable=_is_retryable_buffer_error,
        retry_after=_buffer_retry_after,
        on_retry=lambda attempt, delay, exc: _log_channel_retry(attempt, max_attempts, delay, exc),
    )


async def _channels_for_run(
    client: BufferClient,
    organization_id: str,
    *,
    dry_run: bool,
    cache_path: Path | None,
    channel_service: str | None,
    max_attempts: int,
    backoff_seconds: float,
) -> tuple[list[BufferChannel], str]:
    """Resolve the channel list for this run.

    Live runs always query Buffer (and persist a cache copy for dry-runs).
    Dry-runs never call Buffer: they reuse the cached channel list when one
    exists, otherwise they fall back to a placeholder channel so local runs
    can test topic selection, reference-image pulls, and image generation
    without any Buffer dependency.
    """

    if dry_run:
        if cache_path is not None:
            cached = _load_cached_channels(cache_path)
            if cached is not None:
                return cached, "cache"
        return (
            [
                BufferChannel(
                    id="local-dry-run",
                    name="local-dry-run",
                    display_name="Local Dry Run",
                    service=(channel_service or "linkedin").casefold(),
                )
            ],
            "placeholder",
        )
    channels = await _list_channels_with_retries(
        client,
        organization_id,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
    )
    if cache_path is not None and channels:
        _store_cached_channels(cache_path, channels)
    return channels, "buffer"
