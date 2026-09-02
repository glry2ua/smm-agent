"""Image generation for a run: local dry-run saving or live R2 storage."""

from __future__ import annotations

import asyncio
from pathlib import Path

from brand.brand_context import ContactInfo
from images.image_pipeline import (
    ImageAssetStore,
    ReferenceImage,
    generate_and_save_image,
    generate_and_store_image,
)
from job.retry import _retry_settings, retry
from schemas import SocialPostDraft
from settings import Settings
from topics.topics import Topic


async def _generate_and_save(
    settings: Settings,
    draft: SocialPostDraft,
    topic_id: int,
    output_dir: Path,
    images: list[ReferenceImage],
    contact_info: ContactInfo | None,
):
    max_attempts, backoff_seconds = _retry_settings(settings)
    return await retry(
        lambda: generate_and_save_image(
            settings,
            draft.image_prompt,
            topic_id,
            draft.due_at,
            output_dir,
            Path.cwd(),
            images,
            contact_info=contact_info,
        ),
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
    )


async def _generate_and_store(
    settings: Settings,
    draft: SocialPostDraft,
    topic_id: int,
    store: ImageAssetStore,
    images: list[ReferenceImage],
    contact_info: ContactInfo | None,
):
    max_attempts, backoff_seconds = _retry_settings(settings)
    return await retry(
        lambda: generate_and_store_image(
            settings,
            draft.image_prompt,
            topic_id,
            draft.due_at,
            store,
            images,
            contact_info=contact_info,
        ),
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
    )


async def _generate_images(
    settings: Settings,
    *,
    dry_run: bool,
    topics: list[Topic],
    drafts: list[SocialPostDraft],
    reference_images: list[list[ReferenceImage]],
    store_assets: ImageAssetStore | None,
    local_image_dir: Path | None,
    contact_info: ContactInfo | None,
) -> tuple[list[SocialPostDraft], list]:
    """Return (drafts, generated), with image_url set on drafts for live runs."""

    if dry_run:
        if local_image_dir is None:
            return drafts, []
        generated = await asyncio.gather(
            *(
                _generate_and_save(settings, draft, topic.id, local_image_dir, images, contact_info)
                for topic, draft, images in zip(topics, drafts, reference_images, strict=True)
            )
        )
        return drafts, list(generated)
    # validate_for_run(require_images=True) on live runs guarantees an asset store.
    assert store_assets is not None
    generated = await asyncio.gather(
        *(
            _generate_and_store(settings, draft, topic.id, store_assets, images, contact_info)
            for topic, draft, images in zip(topics, drafts, reference_images, strict=True)
        )
    )

    drafts = [
        draft.model_copy(update={"image_url": image.url})
        for draft, image in zip(drafts, generated, strict=True)
    ]
    return drafts, list(generated)
