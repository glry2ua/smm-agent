"""Board endpoint for the WebUI: current drafts and accepted (scheduled) posts."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from buffer.client import BufferClient
from settings import Settings

LOOKBACK_DAYS = 30
LOOKAHEAD_DAYS = 90

DRAFT_STATUS = "draft"
ACCEPTED_STATUS = "scheduled"


def _card(post: Any, channel_id: str) -> dict[str, Any]:
    assets = [
        {
            "id": str(asset.get("id") or ""),
            "type": str(asset.get("type") or ""),
            "mime_type": str(asset.get("mimeType") or ""),
            "source": str(asset.get("source") or ""),
            "thumbnail": str(asset.get("thumbnail") or ""),
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

    channels = await client.list_available_channels(settings.buffer_organization_id)
    channel_ids = [channel.id for channel in channels]
    if not channel_ids:
        return {
            "fetched_at": reference.isoformat().replace("+00:00", "Z"),
            "channels": [],
            "drafts": [],
            "accepted": [],
        }
    drafts, accepted = await asyncio.gather(
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
        "drafts": [_card(post, post.channel_id) for post in drafts],
        "accepted": [_card(post, post.channel_id) for post in accepted],
    }
