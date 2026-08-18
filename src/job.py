"""Three-post orchestration shared by dry-run, end-to-end, and cron execution."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from brand.brand_context import (
    LOGO_KEY,
    BrandAssetStore,
    ContactInfo,
    ReferenceAsset,
    infer_asset,
)
from buffer.client import BufferAPIError, BufferChannel, BufferClient, build_create_post_input
from buffer.insights import analyze_insights_snapshot, load_buffer_insights, snapshot_post_count
from content.social_agent import generate_social_post, normalize_now
from images.image_pipeline import (
    ImageAssetStore,
    R2ImageAssetStore,
    ReferenceImage,
    ReferenceImageStore,
    generate_and_save_image,
    generate_and_store_image,
)
from schemas import ImagePrompt, PerformanceAnalysis, SocialPostDraft
from settings import Settings
from topics.topics import TopicRepository, TopicStore

PACIFIC = ZoneInfo("America/Los_Angeles")
PUBLISH_TIME = time(hour=8, minute=30)
PUBLISH_DAY_OFFSETS = (0, 2, 4)
CRON_TIME_UTC = time(hour=14)
MAX_POST_COUNT = len(PUBLISH_DAY_OFFSETS)
MAX_DRAFT_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class DraftPreparation:
    draft: SocialPostDraft
    attempts: int
    fallback_used: bool
    validation_errors: tuple[str, ...]


def _monday_anchor(local_now: datetime, *, force_non_monday: bool) -> datetime:
    """Return the Pacific midnight that opens the week this run is anchored to.

    By default the job must run on Monday; when ``force_non_monday`` is set
    (for local testing) the schedule snaps forward to the next Monday so the
    publish times stay inside the future scheduling window.
    """

    if local_now.weekday() == 0:
        return local_now
    if not force_non_monday:
        raise ValueError("The weekly job must run on Monday in the Pacific time zone")
    days_until_monday = (0 - local_now.weekday()) % 7 or 7
    return local_now + timedelta(days=days_until_monday)


def weekly_cron_time(now: datetime | None = None, *, force_non_monday: bool = False) -> datetime:
    """Return this Monday's configured cron instant for local CLI simulation."""

    local_now = normalize_now(now).astimezone(PACIFIC)
    monday = _monday_anchor(local_now, force_non_monday=force_non_monday)
    return datetime.combine(monday.date(), CRON_TIME_UTC, UTC)


def weekly_publish_times(now: datetime, *, force_non_monday: bool = False) -> list[datetime]:
    """Return Monday, Wednesday, and Friday at 08:30 Pacific, expressed in UTC."""

    local_now = normalize_now(now).astimezone(PACIFIC)
    monday = _monday_anchor(local_now, force_non_monday=force_non_monday)
    return [
        datetime.combine(
            monday.date() + timedelta(days=offset), PUBLISH_TIME, PACIFIC
        ).astimezone(UTC)
        for offset in PUBLISH_DAY_OFFSETS
    ]


def validate_draft(post: SocialPostDraft, settings: Settings, now: datetime) -> None:
    """Apply deterministic checks before any external Buffer mutation."""

    earliest = now + timedelta(minutes=settings.min_schedule_lead_minutes)
    latest = now + timedelta(days=settings.schedule_horizon_days)
    if len(post.buffer_text()) > settings.max_post_chars:
        raise ValueError(f"Post exceeds MAX_POST_CHARS ({settings.max_post_chars})")
    due_at = post.due_at.astimezone(UTC)
    if due_at < earliest or due_at > latest:
        raise ValueError("due_at must be inside the configured future scheduling window")


def validate_reference_policy(
    post: SocialPostDraft,
    reference_keys: list[str],
    asset_catalog: dict[str, ReferenceAsset] | None = None,
    contact_info: ContactInfo | None = None,
) -> None:
    """Reject identity/property concepts that lack a matching typed source reference."""

    image_prompt = post.image_prompt
    searchable_text = " ".join(
        (
            image_prompt.subject,
            image_prompt.setting,
            image_prompt.composition,
            *image_prompt.must_include,
        )
    ).casefold()
    exact_outdoor_markers = (
        "outdoor setting",
        "outdoor scene",
        "outdoor photo",
        "outside the",
        "property exterior",
        "home exterior",
        "facade",
        "neighborhood photo",
        "neighborhood scene",
        "street scene",
        "street view",
        "front elevation",
    )
    excludes_outdoors = (
        "no outdoor",
        "without outdoor",
        "no exterior",
        "without an exterior",
        "no neighborhood photo",
        "no neighborhood scene",
    )
    headshot_markers = ("headshot", "portrait", "person", "people", "advisor")
    excludes_people = ("no people", "no person", "without people", "without a person")
    group_markers = (
        "group photo",
        "client group",
        "with clients",
        "realtor and clients",
        "advisor and clients",
    )
    catalog = asset_catalog or {key: infer_asset(key) for key in reference_keys}
    selected_roles = {catalog[key].role for key in reference_keys if key in catalog}
    required_roles: set[str] = set()
    policy_role = {
        "outdoor-exact": "outdoor",
        "headshot-exact": "headshot",
        "group-exact": "headshot-group",
    }.get(image_prompt.reference_policy)
    if policy_role:
        required_roles.add(policy_role)
    requests_outdoors = not any(
        phrase in searchable_text for phrase in excludes_outdoors
    ) and any(marker in searchable_text for marker in exact_outdoor_markers)
    if image_prompt.visual_type == "neighborhood-editorial" or requests_outdoors:
        required_roles.add("outdoor")
    if (
        image_prompt.visual_type == "people-editorial"
        and image_prompt.reference_policy == "indoor-flexible"
        and not any(phrase in searchable_text for phrase in excludes_people)
    ):
        if any(marker in searchable_text for marker in group_markers):
            required_roles.add("headshot-group")
        elif any(marker in searchable_text for marker in headshot_markers):
            required_roles.add("headshot")
    missing_roles = required_roles - selected_roles
    if missing_roles:
        raise ValueError(
            "Outdoor scenes and headshots/groups require matching typed reference images; "
            "missing roles: "
            f"{', '.join(sorted(missing_roles))}; selected roles: "
            f"{', '.join(sorted(selected_roles)) or 'none'}"
        )
    if {"headshot", "headshot-group"}.issubset(selected_roles):
        raise ValueError("Select either a headshot or a headshot-group image, not both")
    if "logo" in image_prompt.business_fields and "logo" not in selected_roles:
        raise ValueError("business_fields includes logo but no role=logo reference was selected")
    contact_fields = set(image_prompt.business_fields) - {"logo"}
    if contact_fields and contact_info is None:
        raise ValueError(
            "business_fields requested contact data but info/contact.json is unavailable"
        )


async def _publish_with_retries(
    client: BufferClient,
    post: SocialPostDraft,
    channel: BufferChannel,
    *,
    max_attempts: int,
    backoff_seconds: float,
) -> dict[str, Any]:
    for attempt in range(1, max_attempts + 1):
        try:
            return await client.create_scheduled_post(post, channel.id, channel.service)
        except BufferAPIError as exc:
            if not exc.retryable or attempt == max_attempts:
                raise
            await asyncio.sleep(backoff_seconds * (2 ** (attempt - 1)))
    raise RuntimeError("unreachable")


async def _with_retries[T](
    operation: Callable[[], Awaitable[T]],
    *,
    max_attempts: int,
    backoff_seconds: float,
) -> T:
    """Retry a transient external operation with the configured exponential backoff."""

    for attempt in range(1, max_attempts + 1):
        try:
            return await operation()
        except Exception:
            if attempt == max_attempts:
                raise
            await asyncio.sleep(backoff_seconds * (2 ** (attempt - 1)))
    raise RuntimeError("unreachable")


async def _list_channels_with_retries(
    client: BufferClient,
    organization_id: str,
    *,
    max_attempts: int,
    backoff_seconds: float,
) -> list[BufferChannel]:
    for attempt in range(1, max_attempts + 1):
        try:
            return await client.list_available_channels(organization_id)
        except BufferAPIError as exc:
            if not exc.retryable or attempt == max_attempts:
                raise
            await asyncio.sleep(backoff_seconds * (2 ** (attempt - 1)))
    raise RuntimeError("unreachable")


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


async def run_weekly_job(
    env: Any,
    *,
    dry_run: bool,
    post_count: int = MAX_POST_COUNT,
    selected_topic: str | None = None,
    require_headshot_reference: bool = False,
    skip_keyword_update: bool = False,
    channel_service: str | None = None,
    topic_store: TopicRepository | None = None,
    asset_store: ImageAssetStore | None = None,
    reference_store: ReferenceImageStore | None = None,
    brand_store: BrandAssetStore | None = None,
    local_image_dir: Path | None = None,
    now: datetime | None = None,
    force_non_monday: bool = False,
) -> dict[str, Any]:
    if post_count not in range(1, MAX_POST_COUNT + 1):
        raise ValueError(f"post_count must be between 1 and {MAX_POST_COUNT}")
    settings = Settings.from_env(env)
    settings.validate_for_run(require_images=not dry_run)
    store_assets = None
    if not dry_run:
        settings.validate_for_images()
        store_assets = asset_store or R2ImageAssetStore.from_env(env)
    current = normalize_now(now)
    due_times = weekly_publish_times(current, force_non_monday=force_non_monday)[:post_count]
    store = topic_store or TopicStore.from_env(env)
    if selected_topic is not None:
        if post_count != 1:
            raise ValueError("selected_topic requires post_count=1")
        topic = await store.pick_available_topic(selected_topic)
        topics = [topic] if topic is not None else []
    else:
        topics = await store.pick_random_available(limit=len(due_times))
    if len(topics) < len(due_times):
        if selected_topic is not None:
            raise RuntimeError(f"Selected topic is unavailable or already used: {selected_topic}")
        raise RuntimeError(
            f"{len(due_times)} unused topics are required, but only {len(topics)} remain"
        )
    references = reference_store
    if references is None:
        if dry_run:
            references = None
        elif asset_store is None:
            references = R2ImageAssetStore.from_env(env)
        elif callable(getattr(asset_store, "get_reference_image", None)):
            references = asset_store  # type: ignore[assignment]
    brands = brand_store
    if brands is None and isinstance(references, R2ImageAssetStore):
        brands = references
    contact_info = await brands.get_contact_info() if brands is not None else None
    listed_reference_keys = (
        await references.list_reference_keys() if references is not None else []
    )
    reference_assets = _reference_assets(listed_reference_keys, include_logo=brands is not None)
    reference_catalog = [asset.key for asset in reference_assets]
    asset_catalog = {asset.key: asset for asset in reference_assets}

    client = BufferClient(settings.buffer_api_key, api_url=settings.buffer_api_url)
    channels = await _list_channels_with_retries(
        client,
        settings.buffer_organization_id,
        max_attempts=settings.retry_max_attempts,
        backoff_seconds=settings.retry_backoff_seconds,
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

    (
        insights_snapshot,
        performance_analysis,
        performance_analysis_status,
        performance_analysis_error,
    ) = await _prepare_performance_analysis(client, settings, current, channels)
    draft_preparations = await asyncio.gather(
        *(
            _generate_valid_draft(
                settings,
                topic.topic,
                due_at,
                reference_catalog,
                performance_analysis,
                contact_info,
                reference_assets,
                asset_catalog,
                current,
                require_headshot_reference=require_headshot_reference,
            )
            for topic, due_at in zip(topics, due_times, strict=True)
        )
    )
    drafts = [preparation.draft for preparation in draft_preparations]
    selected_keys = [draft.reference_image_keys for draft in drafts]
    non_logo_selected = any(key != LOGO_KEY for keys in selected_keys for key in keys)
    if references is None and non_logo_selected:
        raise RuntimeError(
            "Reference images were selected but no reference image store is available"
        )
    reference_images: list[list[ReferenceImage]] = (
        await asyncio.gather(
            *(
                _load_reference_images(references, brands, keys, asset_catalog)
                for keys in selected_keys
            )
        )
        if references is not None or brands is not None
        else [[] for _ in drafts]
    )
    generated_images = []
    if dry_run and local_image_dir is not None:
        generated_images = await asyncio.gather(
            *(
                _generate_and_save(settings, draft, topic.id, local_image_dir, images, contact_info)
                for topic, draft, images in zip(topics, drafts, reference_images, strict=True)
            )
        )
    elif not dry_run:
        generated_images = await asyncio.gather(
            *(
                _generate_and_store(settings, draft, topic.id, store_assets, images, contact_info)
                for topic, draft, images in zip(topics, drafts, reference_images, strict=True)
            )
        )
        drafts = [
            draft.model_copy(update={"image_url": generated.url})
            for draft, generated in zip(drafts, generated_images, strict=True)
        ]
    buffer_inputs = [
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

    result: dict[str, Any] = {
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
        "buffer_inputs": buffer_inputs,
        "channel_count": len(channels),
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
        "keyword_update_skipped": not dry_run and skip_keyword_update,
    }
    if dry_run:
        return result

    publish_jobs = [
        (topic, draft, channel)
        for topic, draft in zip(topics, drafts, strict=True)
        for channel in channels
    ]
    created_posts = await asyncio.gather(
        *(
            _publish_with_retries(
                client,
                draft,
                channel,
                max_attempts=settings.retry_max_attempts,
                backoff_seconds=settings.retry_backoff_seconds,
            )
            for _, draft, channel in publish_jobs
        )
    )
    buffer_posts = [
        {
            "topic_id": topic.id,
            "channel_id": channel.id,
            "post_id": str(buffer_post["id"]),
        }
        for (topic, _, channel), buffer_post in zip(publish_jobs, created_posts, strict=True)
    ]
    result["buffer_posts"] = buffer_posts
    result["buffer_posts_created"] = len(buffer_posts)
    if skip_keyword_update:
        return result
    used_at = normalize_now()
    await asyncio.gather(*(store.mark_used(topic.id, used_at) for topic in topics))
    result["used_at_updated"] = True
    result["used_at"] = used_at.isoformat()
    return result


async def _load_reference_images(
    store: ReferenceImageStore | None,
    brand_store: BrandAssetStore | None,
    keys: list[str],
    asset_catalog: dict[str, ReferenceAsset] | None = None,
) -> list[ReferenceImage]:
    async def load(key: str) -> ReferenceImage:
        if key == LOGO_KEY:
            if brand_store is None:
                raise RuntimeError(f"{LOGO_KEY} was selected but no R2 brand store is available")
            return await brand_store.get_logo_image()
        if store is None:
            raise RuntimeError(f"{key} was selected but no reference image store is available")
        return await store.get_reference_image(key)

    images = list(await asyncio.gather(*(load(key) for key in keys)))
    catalog = asset_catalog or {}
    return [
        replace(
            image,
            role=catalog[image.key].role,
        )
        if image.key in catalog
        else image
        for image in images
    ]


def _reference_assets(listed_keys: list[str], *, include_logo: bool) -> list[ReferenceAsset]:
    keys = list(dict.fromkeys(listed_keys))
    if include_logo and LOGO_KEY not in keys:
        keys.append(LOGO_KEY)
    assets = [infer_asset(key) for key in keys]
    return [asset for asset in assets if asset.role != "other"]


async def _generate_draft(
    settings: Settings,
    topic: str,
    due_at: datetime,
    reference_keys: list[str],
    performance_analysis: PerformanceAnalysis | None,
    contact_info: ContactInfo | None,
    assets: list[ReferenceAsset],
    revision_feedback: str | None = None,
) -> SocialPostDraft:
    if contact_info is None and not assets and revision_feedback is None:
        return await generate_social_post(
            settings, topic, due_at, reference_keys, performance_analysis
        )
    args = (
        settings,
        topic,
        due_at,
        reference_keys,
        performance_analysis,
        contact_info,
        assets,
    )
    if revision_feedback is None:
        return await generate_social_post(*args)
    return await generate_social_post(*args, revision_feedback)


async def _generate_valid_draft(
    settings: Settings,
    topic: str,
    due_at: datetime,
    reference_keys: list[str],
    performance_analysis: PerformanceAnalysis | None,
    contact_info: ContactInfo | None,
    assets: list[ReferenceAsset],
    asset_catalog: dict[str, ReferenceAsset],
    now: datetime,
    *,
    require_headshot_reference: bool,
) -> DraftPreparation:
    revision_feedback: str | None = None
    catalog_set = set(reference_keys)
    errors: list[str] = []
    last_draft: SocialPostDraft | None = None
    for attempt in range(1, MAX_DRAFT_ATTEMPTS + 1):
        try:
            draft = await _generate_draft(
                settings,
                topic,
                due_at,
                reference_keys,
                performance_analysis,
                contact_info,
                assets,
                revision_feedback,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:800]
            errors.append(error)
            if attempt == MAX_DRAFT_ATTEMPTS:
                if require_headshot_reference:
                    raise RuntimeError(
                        f"Headshot test draft generation failed after {attempt} attempts: {error}"
                    ) from exc
                fallback = _fallback_draft(topic, due_at, last_draft, settings, now)
                return DraftPreparation(fallback, attempt, True, tuple(errors))
            revision_feedback = (
                f"Attempt {attempt} could not produce valid structured output: {error}\n"
                "Return a complete replacement draft using the available roles."
            )
            continue
        last_draft = draft
        requested_keys = list(dict.fromkeys(draft.reference_image_keys))
        unavailable_keys = [key for key in requested_keys if key not in catalog_set]
        selected_keys = list(
            key for key in requested_keys if key in catalog_set
        )[:3]
        draft = draft.model_copy(update={"reference_image_keys": selected_keys})
        try:
            if unavailable_keys:
                raise ValueError(
                    "reference_image_keys contains unavailable keys: "
                    + ", ".join(unavailable_keys)
                )
            validate_draft(draft, settings, now)
            validate_reference_policy(draft, selected_keys, asset_catalog, contact_info)
            if require_headshot_reference and (
                draft.image_prompt.reference_policy != "headshot-exact"
                or "headshot" not in {asset_catalog[key].role for key in selected_keys}
            ):
                raise ValueError(
                    "Headshot test requires reference_policy=headshot-exact and a role=headshot key"
                )
        except ValueError as exc:
            error = str(exc)[:800]
            errors.append(error)
            if attempt == MAX_DRAFT_ATTEMPTS:
                if require_headshot_reference:
                    raise RuntimeError(
                        f"Headshot test draft remained invalid after {attempt} attempts: {exc}"
                    ) from exc
                fallback = _fallback_draft(topic, due_at, draft, settings, now)
                return DraftPreparation(fallback, attempt, True, tuple(errors))
            available_roles = sorted({asset.role for asset in assets})
            safe_fallback = (
                "When a missing role is not in Available roles, use "
                "visual_type=typographic-educational, reference_policy=indoor-flexible, no people, "
                "and no outdoor or neighborhood photograph."
            )
            revision_feedback = (
                f"Attempt {attempt} failed: {exc}\n"
                f"Available roles: {', '.join(available_roles) or 'none'}\n"
                f"Required fallback: {safe_fallback}\n"
                f"Rejected draft: {draft.model_dump_json()}"
            )
            continue
        return DraftPreparation(draft, attempt, False, tuple(errors))
    raise RuntimeError("unreachable")


def _fallback_draft(
    topic: str,
    due_at: datetime,
    previous: SocialPostDraft | None,
    settings: Settings,
    now: datetime,
) -> SocialPostDraft:
    """Build a deterministic, reference-free visual when agent revisions remain invalid."""

    normalized_topic = " ".join(topic.split())[:160] or "Plan your next real-estate move"
    headline = normalized_topic[:60]
    image_prompt = ImagePrompt(
        visual_type="typographic-educational",
        reference_policy="indoor-flexible",
        subject=f"A typography-led educational graphic about: {normalized_topic}",
        setting="Warm ivory studio backdrop with typography only",
        composition=(
            "Large crisp headline, restrained abstract lines, generous negative space, "
            "and no photography or people"
        ),
        headline=headline,
        must_include=[],
        avoid=["people", "property photography", "invented facts", "extra text"],
        business_fields=[],
    )
    if previous is not None:
        candidate = previous.model_copy(
            update={"image_prompt": image_prompt, "reference_image_keys": []}
        )
        try:
            validate_draft(candidate, settings, now)
        except ValueError:
            pass
        else:
            validate_reference_policy(candidate, [], {}, None)
            return candidate
    description = (
        f"{normalized_topic}\n\n"
        "A clear real-estate decision starts with your priorities, timing, and next step. "
        "Define what matters most, then compare each option against the same criteria."
    )
    fallback = SocialPostDraft(
        description=description,
        keywords=["San Jose real estate", "home planning", "buyer guidance"],
        image_prompt=image_prompt,
        reference_image_keys=[],
        due_at=due_at,
    )
    validate_draft(fallback, settings, now)
    validate_reference_policy(fallback, [], {}, None)
    return fallback


async def _generate_and_save(
    settings: Settings,
    draft: SocialPostDraft,
    topic_id: int,
    output_dir: Path,
    images: list[ReferenceImage],
    contact_info: ContactInfo | None,
):
    args = (
        settings,
        draft.image_prompt,
        topic_id,
        draft.due_at,
        output_dir,
        Path.cwd(),
        images,
    )
    async def operation():
        if contact_info is None:
            return await generate_and_save_image(*args)
        return await generate_and_save_image(*args, contact_info)

    return await _with_retries(
        operation,
        max_attempts=settings.retry_max_attempts,
        backoff_seconds=settings.retry_backoff_seconds,
    )


async def _generate_and_store(
    settings: Settings,
    draft: SocialPostDraft,
    topic_id: int,
    store: ImageAssetStore,
    images: list[ReferenceImage],
    contact_info: ContactInfo | None,
):
    args = (settings, draft.image_prompt, topic_id, draft.due_at, store, images)
    async def operation():
        if contact_info is None:
            return await generate_and_store_image(*args)
        return await generate_and_store_image(*args, contact_info)

    return await _with_retries(
        operation,
        max_attempts=settings.retry_max_attempts,
        backoff_seconds=settings.retry_backoff_seconds,
    )
