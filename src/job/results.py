"""Assembly of the run's result dict (key order mirrors the original contract)."""

from __future__ import annotations

from typing import Any

from buffer.client import BufferChannel, build_create_post_input
from buffer.insights import snapshot_post_count
from job.drafts import DraftPreparation
from job.references import ReferenceContext
from schemas import PerformanceAnalysis, SocialPostDraft
from topics.topics import Topic


def _buffer_inputs(
    topics: list[Topic],
    drafts: list[SocialPostDraft],
    channels: list[BufferChannel],
) -> list[dict[str, Any]]:
    return [
        {
            "topic_id": topic.id,
            "channel": {
                "id": channel.id,
                "name": channel.name,
                "display_name": channel.display_name,
                "service": channel.service,
            },
            "input": build_create_post_input(draft, channel.id, channel.service),
        }
        for topic, draft in zip(topics, drafts, strict=True)
        for channel in channels
    ]


def _build_result(
    *,
    dry_run: bool,
    post_count: int,
    topics: list[Topic],
    drafts: list[SocialPostDraft],
    generated_images: list,
    selected_keys: list[list[str]],
    channels: list[BufferChannel],
    channels_source: str,
    ref_ctx: ReferenceContext,
    channel_service: str | None,
    insights_snapshot: dict[str, Any] | None,
    performance_analysis: PerformanceAnalysis | None,
    performance_analysis_status: str,
    performance_analysis_error: str | None,
    draft_preparations: list[DraftPreparation],
    skip_topic_update: bool,
) -> dict[str, Any]:
    return {
        "mode": "dry-run" if dry_run else "live",
        "post_count": post_count,
        "topics": [{"id": topic.id, "topic": topic.topic} for topic in topics],
        "drafts": [draft.model_dump(mode="json") for draft in drafts],
        "generated_images": [
            {
                "key": image.key,
                "url": image.url,
                "model": image.model,
                "size": image.size,
                "quality": image.quality,
                "local_path_absolute": image.local_path_absolute,
                "local_path_relative": image.local_path_relative,
                "reference_image_keys": selected_keys[index],
            }
            for index, image in enumerate(generated_images)
        ],
        "images_generated": len(generated_images),
        "buffer_inputs": _buffer_inputs(topics, drafts, channels),
        "channel_count": len(channels),
        "channels_source": channels_source,
        "reference_catalog": ref_ctx.catalog_keys,
        "listed_reference_key_count": len(ref_ctx.listed_keys),
        "channel_service_filter": channel_service,
        "buffer_insights_summary": (
            {
                "window": insights_snapshot["window"],
                "channel_count": insights_snapshot["channel_count"],
                "post_count": snapshot_post_count(insights_snapshot),
            }
            if insights_snapshot is not None
            else None
        ),
        "performance_analysis_status": performance_analysis_status,
        "performance_analysis_error": performance_analysis_error,
        "performance_analysis": (
            performance_analysis.model_dump(mode="json")
            if performance_analysis is not None
            else None
        ),
        "draft_count": len(drafts),
        "draft_generation": [
            {
                "attempts": preparation.attempts,
                "fallback_used": preparation.fallback_used,
                "validation_errors": list(preparation.validation_errors),
            }
            for preparation in draft_preparations
        ],
        "buffer_channel_query_completed": True,
        "buffer_posts_created": 0,
        "buffer_submission_type": "scheduled-draft",
        "used_at_updated": False,
        "topic_update_skipped": not dry_run and skip_topic_update,
    }
