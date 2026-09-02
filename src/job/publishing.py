"""Buffer publishing and topic bookkeeping for live runs."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Any

from buffer.client import BufferChannel, BufferClient
from content.social_agent import normalize_now
from job.channels import _is_retryable_buffer_error
from job.retry import _retry_settings, retry
from schemas import SocialPostDraft
from settings import Settings
from topics.topics import Topic, TopicRepository


async def _publish_posts(
    client: BufferClient,
    settings: Settings,
    topics: list[Topic],
    drafts: list[SocialPostDraft],
    channels: list[BufferChannel],
) -> list[dict[str, Any]]:
    max_attempts, backoff_seconds = _retry_settings(settings)
    publish_jobs = [
        (topic, draft, channel)
        for topic, draft in zip(topics, drafts, strict=True)
        for channel in channels
    ]
    created_posts = await asyncio.gather(
        *(
            retry(
                partial(client.create_scheduled_post, draft, channel.id, channel.service),
                max_attempts=max_attempts,
                backoff_seconds=backoff_seconds,
                retryable=_is_retryable_buffer_error,
            )
            for _, draft, channel in publish_jobs
        )
    )
    return [
        {
            "topic_id": topic.id,
            "channel_id": channel.id,
            "post_id": str(buffer_post["id"]),
        }
        for (topic, _, channel), buffer_post in zip(publish_jobs, created_posts, strict=True)
    ]


async def _mark_topics_used(store: TopicRepository, topics: list[Topic]) -> str:
    used_at = normalize_now()
    await asyncio.gather(*(store.mark_used(topic.id, used_at) for topic in topics))
    return used_at.isoformat()
