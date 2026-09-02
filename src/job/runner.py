"""Weekly three-post run: topic picking, draft/image generation, Buffer publishing."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from brand.brand_context import LOGO_KEY, BrandAssetStore
from buffer.client import BufferChannel, BufferClient
from buffer.insights import analyze_insights_snapshot, load_buffer_insights
from content.social_agent import normalize_now
from images.image_pipeline import (
    ImageAssetStore,
    R2ImageAssetStore,
    ReferenceImage,
    ReferenceImageStore,
)
from job.channels import _channels_for_run
from job.drafts import DraftContext, DraftPreparation, _generate_valid_draft
from job.imagegen import _generate_images
from job.publishing import _mark_topics_used, _publish_posts
from job.references import ReferenceContext, _load_reference_images, _reference_assets
from job.results import _build_result
from job.retry import _retry_settings
from job.schedule import MAX_POST_COUNT, weekly_publish_times
from schemas import PerformanceAnalysis
from settings import Settings
from topics.topics import Topic, TopicRepository, TopicStore


def _resolve_settings_and_assets(
    env: Any,
    *,
    dry_run: bool,
    asset_store: ImageAssetStore | None,
) -> tuple[Settings, ImageAssetStore | None]:
    settings = Settings.from_env(env)
    settings.validate_for_run(require_images=not dry_run)
    if dry_run:
        return settings, None
    settings.validate_for_images()
    return settings, asset_store or R2ImageAssetStore.from_env(env)


async def _pick_topics(
    store: TopicRepository,
    selected_topic: str | None,
    post_count: int,
    due_times: list[datetime],
) -> list[Topic]:
    """Choose the run's topics, failing fast when too few remain unused."""

    if selected_topic is not None:
        if post_count != 1:
            raise ValueError("selected_topic requires post_count=1")
        topic = await store.pick_available_topic(selected_topic)
        topics = [topic] if topic is not None else []
    else:
        topics = await store.pick_random_available(limit=len(due_times))
    if len(topics) >= len(due_times):
        return topics
    if selected_topic is not None:
        raise RuntimeError(f"Selected topic is unavailable or already used: {selected_topic}")
    raise RuntimeError(
        f"{len(due_times)} unused topics are required, but only {len(topics)} remain"
    )


async def _resolve_reference_context(
    env: Any,
    *,
    dry_run: bool,
    reference_store: ReferenceImageStore | None,
    asset_store: ImageAssetStore | None,
    brand_store: BrandAssetStore | None,
) -> ReferenceContext:
    references = reference_store
    if references is None and asset_store is None and not dry_run:
        references = R2ImageAssetStore.from_env(env)
    if references is None and callable(getattr(asset_store, "get_reference_image", None)):
        # asset_store duck-types as a reference store when it can serve references.
        references = cast("ReferenceImageStore", asset_store)
    brands = brand_store
    if brands is None and isinstance(references, R2ImageAssetStore):
        brands = references
    contact_info = await brands.get_contact_info() if brands is not None else None
    listed_keys = await references.list_reference_keys() if references is not None else []
    assets = _reference_assets(listed_keys, include_logo=brands is not None)
    return ReferenceContext(
        references=references,
        brands=brands,
        contact_info=contact_info,
        listed_keys=listed_keys,
        assets=assets,
    )


def _warn_logo_only_catalog(listed_keys: list[str], asset_count: int) -> None:
    if asset_count > 1:
        return
    # The logo is injected separately; a logo-only catalog means the R2
    # listing returned nothing usable. Show what the bucket actually
    # returned so the cause (empty bucket, unmapped folder, API shape)
    # is visible instead of silently generating without references.
    sample = ", ".join(listed_keys[:10]) or "(listing returned no image keys)"
    print(
        "WARNING: R2 reference catalog is logo-only. "
        f"R2 listing returned {len(listed_keys)} usable key(s): {sample}",
        file=sys.stderr,
        flush=True,
    )


async def _resolve_channels(
    client: BufferClient,
    settings: Settings,
    *,
    dry_run: bool,
    channel_service: str | None,
    channels_cache_path: Path | None,
) -> tuple[list[BufferChannel], str]:
    max_attempts, backoff_seconds = _retry_settings(settings)
    channels, channels_source = await _channels_for_run(
        client,
        settings.buffer_organization_id,
        dry_run=dry_run,
        cache_path=channels_cache_path,
        channel_service=channel_service,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
    )
    if channel_service is not None:
        channels = [
            channel
            for channel in channels
            if channel.service.casefold() == channel_service.casefold()
        ]
    if not channels:
        if channel_service is not None:
            raise RuntimeError(
                f"The Buffer organization has no available {channel_service} channels"
            )
        raise RuntimeError("The Buffer organization has no available channels")
    return channels, channels_source


async def _prepare_performance_analysis(
    client: BufferClient,
    settings: Settings,
    current: datetime,
    channels: list[BufferChannel],
) -> tuple[dict[str, Any] | None, PerformanceAnalysis | None, str, str | None]:
    """Load and analyze recent performance without making publishing depend on analytics."""

    try:
        snapshot = await load_buffer_insights(
            client,
            settings.buffer_organization_id,
            now=current,
            channels=channels,
        )
    except Exception as exc:
        return None, None, "buffer_unavailable", f"{type(exc).__name__}: {exc}"
    analysis, status, error = await analyze_insights_snapshot(settings, snapshot)
    return snapshot, analysis, status, error


async def _load_insights(
    client: BufferClient,
    settings: Settings,
    current: datetime,
    channels: list[BufferChannel],
    *,
    skip: bool,
) -> tuple[dict[str, Any] | None, PerformanceAnalysis | None, str, str | None]:
    if skip:
        return None, None, "skipped", None
    return await _prepare_performance_analysis(client, settings, current, channels)


async def _prepare_drafts(
    settings: Settings,
    topics: list[Topic],
    due_times: list[datetime],
    current: datetime,
    *,
    ref_ctx: ReferenceContext,
    performance_analysis: PerformanceAnalysis | None,
    require_headshot_reference: bool,
) -> list[DraftPreparation]:
    contexts = [
        DraftContext(
            settings=settings,
            topic=topic.topic,
            due_at=due_at,
            reference_keys=ref_ctx.catalog_keys,
            performance_analysis=performance_analysis,
            contact_info=ref_ctx.contact_info,
            assets=ref_ctx.assets,
            asset_catalog=ref_ctx.asset_catalog,
            now=current,
            require_headshot_reference=require_headshot_reference,
        )
        for topic, due_at in zip(topics, due_times, strict=True)
    ]
    return list(await asyncio.gather(*(_generate_valid_draft(context) for context in contexts)))


async def _resolve_reference_images(
    ref_ctx: ReferenceContext,
    selected_keys: list[list[str]],
) -> list[list[ReferenceImage]]:
    non_logo_selected = any(key != LOGO_KEY for keys in selected_keys for key in keys)
    if ref_ctx.references is None and non_logo_selected:
        raise RuntimeError(
            "Reference images were selected but no reference image store is available"
        )
    if ref_ctx.references is None and ref_ctx.brands is None:
        return [[] for _ in selected_keys]
    return list(
        await asyncio.gather(
            *(
                _load_reference_images(
                    ref_ctx.references, ref_ctx.brands, keys, ref_ctx.asset_catalog
                )
                for keys in selected_keys
            )
        )
    )


async def run_weekly_job(
    env: Any,
    *,
    dry_run: bool,
    post_count: int = MAX_POST_COUNT,
    selected_topic: str | None = None,
    require_headshot_reference: bool = False,
    skip_topic_update: bool = False,
    channel_service: str | None = None,
    topic_store: TopicRepository | None = None,
    asset_store: ImageAssetStore | None = None,
    reference_store: ReferenceImageStore | None = None,
    brand_store: BrandAssetStore | None = None,
    local_image_dir: Path | None = None,
    now: datetime | None = None,
    force_non_monday: bool = False,
    skip_performance_analysis: bool = False,
    channels_cache_path: Path | None = None,
) -> dict[str, Any]:
    if post_count not in range(1, MAX_POST_COUNT + 1):
        raise ValueError(f"post_count must be between 1 and {MAX_POST_COUNT}")
    settings, store_assets = _resolve_settings_and_assets(
        env, dry_run=dry_run, asset_store=asset_store
    )
    current = normalize_now(now)
    due_times = weekly_publish_times(current, force_non_monday=force_non_monday)[:post_count]
    store = topic_store or TopicStore.from_env(env)
    topics = await _pick_topics(store, selected_topic, post_count, due_times)

    ref_ctx = await _resolve_reference_context(
        env,
        dry_run=dry_run,
        reference_store=reference_store,
        asset_store=asset_store,
        brand_store=brand_store,
    )
    _warn_logo_only_catalog(ref_ctx.listed_keys, len(ref_ctx.catalog_keys))

    client = BufferClient(settings.buffer_api_key, api_url=settings.buffer_api_url)
    channels, channels_source = await _resolve_channels(
        client,
        settings,
        dry_run=dry_run,
        channel_service=channel_service,
        channels_cache_path=channels_cache_path,
    )
    (
        insights_snapshot,
        performance_analysis,
        performance_analysis_status,
        performance_analysis_error,
    ) = await _load_insights(client, settings, current, channels, skip=skip_performance_analysis)
    draft_preparations = await _prepare_drafts(
        settings,
        topics,
        due_times,
        current,
        ref_ctx=ref_ctx,
        performance_analysis=performance_analysis,
        require_headshot_reference=require_headshot_reference,
    )
    drafts = [preparation.draft for preparation in draft_preparations]
    selected_keys = [draft.reference_image_keys for draft in drafts]
    reference_images = await _resolve_reference_images(ref_ctx, selected_keys)
    drafts, generated_images = await _generate_images(
        settings,
        dry_run=dry_run,
        topics=topics,
        drafts=drafts,
        reference_images=reference_images,
        store_assets=store_assets,
        local_image_dir=local_image_dir,
        contact_info=ref_ctx.contact_info,
    )

    result = _build_result(
        dry_run=dry_run,
        post_count=post_count,
        topics=topics,
        drafts=drafts,
        generated_images=generated_images,
        selected_keys=selected_keys,
        channels=channels,
        channels_source=channels_source,
        ref_ctx=ref_ctx,
        channel_service=channel_service,
        insights_snapshot=insights_snapshot,
        performance_analysis=performance_analysis,
        performance_analysis_status=performance_analysis_status,
        performance_analysis_error=performance_analysis_error,
        draft_preparations=draft_preparations,
        skip_topic_update=skip_topic_update,
    )
    if dry_run:
        return result

    buffer_posts = await _publish_posts(client, settings, topics, drafts, channels)
    result["buffer_posts"] = buffer_posts
    result["buffer_posts_created"] = len(buffer_posts)
    if skip_topic_update:
        return result
    result["used_at"] = await _mark_topics_used(store, topics)
    result["used_at_updated"] = True
    return result
