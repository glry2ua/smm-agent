"""Board endpoint for the web UI: drafts, scheduled, and sent (posted) posts."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from buffer.client import BufferAPIError, BufferClient
from settings import Settings

LOOKBACK_DAYS = 30
LOOKAHEAD_DAYS = 90

DRAFT_STATUS = "draft"
ACCEPTED_STATUS = "scheduled"
SENT_STATUS = "sent"

# Buffer's quotas are brutal (250 calls/24h shared across key + integrations)
# and each raw board load costs 4 calls. Cache per-isolate: channels barely
# ever change; posts are cached briefly and invalidated by mutations. When
# Buffer rate-limits us, serve the stale board instead of an error.
CHANNELS_TTL_SECONDS = 600
BOARD_TTL_SECONDS = 60
_CACHE: dict[str, tuple[float, Any]] = {}


def invalidate_board_cache() -> None:
    """Drop cached board data after a successful mutation."""
    for key in list(_CACHE):
        if key.startswith("board:"):
            del _CACHE[key]


async def load_board_cached(
    settings: Settings,
    *,
    now: datetime | None = None,
    fresh: bool = False,
) -> dict[str, Any]:
    """``load_board`` behind the TTL cache, falling back to stale data on 429.

    ``fresh`` skips the board TTL for explicit user reloads; the channels
    cache and the stale-on-429 fallback still apply.
    """
    key = f"board:{settings.buffer_organization_id}"
    now_mono = time.monotonic()
    hit = _CACHE.get(key)
    if not fresh and hit is not None and now_mono - hit[0] < BOARD_TTL_SECONDS:
        return hit[1]

    try:
        board = await load_board(settings, now=now)
    except BufferAPIError as exc:
        if exc.status_code == 429 and hit is not None:
            # Rate-limited: stale data beats no data. Keep the original
            # fetched_at so the UI shows how old it is.
            return hit[1]
        raise
    _CACHE[key] = (now_mono, board)
    return board


def _origin_relative(url: str, base_url: str) -> str:
    """Rewrite asset-origin URLs to origin-relative paths.

    Asset URLs stored on Buffer point at the deployed Worker origin. Served
    as absolute URLs, browsers fetch images cross-origin, which Cloudflare
    Access blocks when the page is served from a different origin (local dev).
    Relative paths resolve against whichever origin serves the page: the
    Worker itself in production, the local worker via the Vite proxy in dev.
    """
    if base_url and url.startswith(f"{base_url}/"):
        return url[len(base_url):]
    return url


def _card(post: Any, channel_id: str, asset_base_url: str) -> dict[str, Any]:
    assets = [
        {
            "id": str(asset.get("id") or ""),
            "type": str(asset.get("type") or ""),
            "mime_type": str(asset.get("mimeType") or ""),
            "source": _origin_relative(str(asset.get("source") or ""), asset_base_url),
            "thumbnail": _origin_relative(
                str(asset.get("thumbnail") or ""), asset_base_url
            ),
        }
        for asset in post.assets
    ]
    return {
        "id": post.id,
        "text": post.text,
        "channel_id": channel_id,
        "status": post.status,
        "created_at": post.created_at,
        "due_at": post.due_at,
        "sent_at": post.sent_at,
        "assets": assets,
        "metadata": post.metadata,
    }


async def load_board(settings: Settings, *, now: datetime | None = None) -> dict[str, Any]:
    """Load the kanban board: channels plus draft and scheduled posts."""

    settings.validate_for_buffer()
    client = BufferClient(
        settings.buffer_api_key,
        api_url=settings.buffer_api_url,
    )
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None or reference.utcoffset() is None:
        reference = reference.replace(tzinfo=UTC)
    start = reference.astimezone(UTC) - timedelta(days=LOOKBACK_DAYS)
    end = reference.astimezone(UTC) + timedelta(days=LOOKAHEAD_DAYS)

    channels_key = f"channels:{settings.buffer_organization_id}"
    now_mono = time.monotonic()
    hit = _CACHE.get(channels_key)
    if hit is not None and now_mono - hit[0] < CHANNELS_TTL_SECONDS:
        channels = hit[1]
    else:
        channels = await client.list_available_channels(
            settings.buffer_organization_id
        )
        _CACHE[channels_key] = (now_mono, channels)
    channel_ids = [channel.id for channel in channels]
    if not channel_ids:
        return {
            "fetched_at": reference.isoformat().replace("+00:00", "Z"),
            "channels": [],
            "drafts": [],
            "accepted": [],
            "posted": [],
        }
    drafts, accepted, sent = await asyncio.gather(
        client.list_posts(
            settings.buffer_organization_id,
            start=start,
            end=end,
            channel_ids=channel_ids,
            statuses=[DRAFT_STATUS],
        ),
        client.list_posts(
            settings.buffer_organization_id,
            start=start,
            end=end,
            channel_ids=channel_ids,
            statuses=[ACCEPTED_STATUS],
        ),
        client.list_posts(
            settings.buffer_organization_id,
            start=start,
            end=end,
            channel_ids=channel_ids,
            statuses=[SENT_STATUS],
        ),
    )
    return {
        "fetched_at": reference.isoformat().replace("+00:00", "Z"),
        "channels": [
            {
                "id": channel.id,
                "name": channel.name,
                "display_name": channel.display_name,
                "service": channel.service,
            }
            for channel in channels
        ],
        "drafts": [
            _card(post, post.channel_id, settings.asset_public_base_url)
            for post in drafts
        ],
        "accepted": [
            _card(post, post.channel_id, settings.asset_public_base_url)
            for post in accepted
        ],
        "posted": [
            _card(post, post.channel_id, settings.asset_public_base_url)
            for post in sent
        ],
    }
