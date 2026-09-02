"""Reusable Buffer performance snapshot loading for CLI and weekly generation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from buffer.client import BufferChannel, BufferClient, BufferMetric
from content.social_agent import analyze_buffer_performance
from schemas import PerformanceAnalysis
from settings import Settings


def _metric_dict(metric: BufferMetric) -> dict[str, Any]:
    return {
        "type": metric.type,
        "name": metric.name,
        "value": metric.value,
        "unit": metric.unit,
        "description": metric.description,
    }


def _channel_snapshot(
    channel: BufferChannel,
    summary: Any,
    posts: list[Any],
) -> dict[str, Any]:
    return {
        "id": channel.id,
        "name": channel.name,
        "display_name": channel.display_name,
        "service": channel.service,
        "metrics_updated_at": summary.metrics_updated_at,
        "metrics": [_metric_dict(metric) for metric in summary.metrics],
        "post_count": len(posts),
        "posts": [
            {
                "id": post.id,
                "text": post.text,
                "channel_id": post.channel_id,
                "status": post.status,
                "created_at": post.created_at,
                "updated_at": post.updated_at,
                "due_at": post.due_at,
                "sent_at": post.sent_at,
                "external_link": post.external_link,
                "via": post.via,
                "tags": list(post.tags),
                "assets": list(post.assets),
                "metrics_updated_at": post.metrics_updated_at,
                "metrics": [_metric_dict(metric) for metric in post.metrics],
            }
            for post in posts
        ],
    }


async def load_buffer_insights(
    client: BufferClient,
    organization_id: str,
    *,
    now: datetime | None = None,
    channels: list[BufferChannel] | None = None,
) -> dict[str, Any]:
    """Load a rolling 30-day aggregate and per-post snapshot for selected channels."""

    end = now or datetime.now(UTC)
    if end.tzinfo is None or end.utcoffset() is None:
        end = end.replace(tzinfo=UTC)
    end = end.astimezone(UTC)
    start = end - timedelta(days=30)
    selected_channels = (
        channels if channels is not None else await client.list_available_channels(organization_id)
    )

    # Index-aligned with selected_channels: gather 1 is the aggregate summary for
    # channel i, gather 2 is that channel's sent posts. Nested so both groups
    # fetch concurrently.
    async def _fetch_summaries() -> list[Any]:
        return await asyncio.gather(
            *(
                client.get_aggregated_post_metrics(
                    organization_id, start=start, end=end, channel_ids=[channel.id]
                )
                for channel in selected_channels
            )
        )

    async def _fetch_post_lists() -> list[list[Any]]:
        return await asyncio.gather(
            *(
                client.list_sent_posts(
                    organization_id, start=start, end=end, channel_ids=[channel.id]
                )
                for channel in selected_channels
            )
        )

    summaries, post_lists = await asyncio.gather(_fetch_summaries(), _fetch_post_lists())
    return {
        "organization_id": organization_id,
        "window": {
            "days": 30,
            "start": start.isoformat().replace("+00:00", "Z"),
            "end": end.isoformat().replace("+00:00", "Z"),
        },
        "channel_count": len(selected_channels),
        "channels": [
            _channel_snapshot(channel, summary, posts)
            for channel, summary, posts in zip(
                selected_channels, summaries, post_lists, strict=True
            )
        ],
    }


def snapshot_post_count(snapshot: dict[str, Any]) -> int:
    """Count posts in a validated internal snapshot shape."""

    return sum(int(channel.get("post_count", 0)) for channel in snapshot.get("channels", []))


async def analyze_insights_snapshot(
    settings: Settings,
    snapshot: dict[str, Any],
) -> tuple[PerformanceAnalysis | None, str, str | None]:
    """Analyze a snapshot with consistent non-fatal status handling."""

    if snapshot_post_count(snapshot) == 0:
        return None, "no_posts", None
    try:
        analysis = await analyze_buffer_performance(settings, snapshot)
    except Exception as exc:
        return None, "analysis_unavailable", f"{type(exc).__name__}: {exc}"
    return analysis, "complete", None
