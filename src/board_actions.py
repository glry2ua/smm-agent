"""Board mutation endpoints: edit, schedule, delete, image replace."""

from __future__ import annotations

import asyncio
import base64
import binascii
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from buffer.client import BufferClient, channel_post_metadata
from images.image_pipeline import ASSET_PATH_PREFIX, ImageAssetStore
from job import PACIFIC, PUBLISH_DAY_OFFSETS, PUBLISH_TIME
from settings import Settings

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
DATA_URL_PREFIX = re.compile(r"^data:(image/[a-z0-9.+-]+);base64,", re.IGNORECASE)
KEY_EXTENSION = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


def _client(settings: Settings) -> BufferClient:
    settings.validate_for_buffer()
    return BufferClient(settings.buffer_api_key, api_url=settings.buffer_api_url)


def _clean_posts(post_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe post entries by ID, keeping each entry's service + metadata."""

    ordered: dict[str, dict[str, Any]] = {}
    for entry in post_entries:
        post_id = str(entry.get("id") or "").strip()
        if not post_id:
            continue
        ordered.setdefault(post_id, {"id": post_id, "service": "", "metadata": None})
        service = str(entry.get("service") or "").strip()
        if service:
            ordered[post_id]["service"] = service
        metadata = entry.get("metadata")
        if isinstance(metadata, Mapping) and metadata:
            ordered[post_id]["metadata"] = dict(metadata)
    if not ordered:
        raise ValueError("At least one post ID is required")
    return list(ordered.values())


def _post_edit_kwargs(entry: dict[str, Any]) -> dict[str, Any]:
    """The per-post Buffer edit kwargs needed to satisfy channel validation."""

    metadata = channel_post_metadata(
        entry.get("service") or "",
        existing=entry.get("metadata"),
    )
    if metadata is not None:
        return {"metadata": metadata}
    return {}


def _next_publish_slot(now: datetime, *, min_lead_minutes: int) -> datetime:
    """Return the next Mon/Wed/Fri 08:30 Pacific slot at least ``min_lead`` away.

    Uses the weekly pipeline's schedule (``job.PUBLISH_TIME`` and
    ``job.PUBLISH_DAY_OFFSETS``) so late accepts land on a real publish slot
    instead of a time in the past, which Buffer rejects.
    """

    earliest = now + timedelta(minutes=max(1, min_lead_minutes))
    day = now.astimezone(PACIFIC).date()
    for _ in range(28):
        if day.weekday() in PUBLISH_DAY_OFFSETS:
            slot = datetime.combine(day, PUBLISH_TIME, PACIFIC).astimezone(UTC)
            if slot >= earliest:
                return slot
        day += timedelta(days=1)
    raise RuntimeError("No upcoming publish slot found within 28 days")


def _parse_due_at(value: str | None) -> datetime | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("due_at must be an ISO-8601 datetime") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def _apply_to_posts(
    posts: list[dict[str, Any]],
    edit: Callable[[dict[str, Any]], Awaitable[Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run one Buffer edit per post, preserving input order.

    Returns the shared response prefix (``ok``) plus one result per post:
    successes carry the response dict under ``post``, failures ``error``.
    Raises RuntimeError with the first error only when every post failed.
    """

    outcomes = await asyncio.gather(
        *(edit(entry) for entry in posts),
        return_exceptions=True,
    )
    results = [
        {"id": entry["id"], "ok": True, "post": dict(outcome)}
        if not isinstance(outcome, BaseException)
        else {
            "id": entry["id"],
            "ok": False,
            "error": f"{type(outcome).__name__}: {outcome}",
        }
        for entry, outcome in zip(posts, outcomes, strict=True)
    ]
    errors = [result for result in results if not result["ok"]]
    if len(errors) == len(posts):
        raise RuntimeError(errors[0]["error"])
    return {"ok": not errors}, results


async def update_post_text(
    settings: Settings,
    post_entries: list[dict[str, Any]],
    text: str,
) -> dict[str, Any]:
    """Set the text on every listed post via Buffer editPost."""

    client = _client(settings)
    posts = _clean_posts(post_entries)

    async def edit(entry: dict[str, Any]) -> Any:
        return await client.edit_post(entry["id"], text=text.strip(), **_post_edit_kwargs(entry))

    info, results = await _apply_to_posts(posts, edit)
    return {**info, "results": results}


async def schedule_posts(
    settings: Settings,
    post_entries: list[dict[str, Any]],
    due_at: str | None = None,
    text: str | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Convert drafts to scheduled posts (and optionally set text in the same edit).

    A due time in the past is replaced with the next weekly publish slot, since
    Buffer refuses to schedule into the past and would otherwise leave the
    draft stuck. A valid future due time is kept untouched.
    """

    client = _client(settings)
    posts = _clean_posts(post_entries)
    current = now or datetime.now(UTC)
    requested = _parse_due_at(due_at)
    min_lead_minutes = (
        settings.min_schedule_lead_minutes if settings.min_schedule_lead_minutes is not None else 30
    )
    earliest = current + timedelta(minutes=min_lead_minutes)
    if requested is not None and requested >= earliest:
        effective_due_at: datetime = requested
    else:
        effective_due_at = _next_publish_slot(current, min_lead_minutes=min_lead_minutes)

    async def edit(entry: dict[str, Any]) -> Any:
        return await client.edit_post(
            entry["id"],
            due_at=effective_due_at,
            mode="customScheduled",
            scheduling_type="automatic",
            save_to_draft=False,
            text=text.strip() if text is not None and text.strip() else None,
            **_post_edit_kwargs(entry),
        )

    info, results = await _apply_to_posts(posts, edit)
    return {
        **info,
        "scheduled_at": effective_due_at.astimezone(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "rescheduled": requested is None or requested < earliest,
        "results": results,
    }


async def delete_posts(settings: Settings, post_entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Delete every listed post from Buffer."""

    client = _client(settings)
    posts = _clean_posts(post_entries)

    async def edit(entry: dict[str, Any]) -> Any:
        return await client.delete_post(entry["id"])

    info, results = await _apply_to_posts(posts, edit)
    for result in results:
        result.pop("post", None)
    return {**info, "results": results}


def decode_image_upload(payload: Mapping[str, Any]) -> tuple[bytes, str]:
    """Return (bytes, mime type) for a base64 or data-URL image upload."""

    data = str(payload.get("data") or "")
    mime = str(payload.get("mime") or "")
    match = DATA_URL_PREFIX.match(data)
    if match:
        mime = mime or match.group(1)
        data = data[match.end() :]
    encoded = data.strip()
    if not encoded:
        raise ValueError("Image upload did not include any image data")
    if not mime or mime not in ALLOWED_IMAGE_MIME_TYPES:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_MIME_TYPES))
        raise ValueError(f"Unsupported image type; expected one of: {allowed}")
    try:
        body = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Image upload is not valid base64 data") from exc
    if not body:
        raise ValueError("Image upload decoded to an empty file")
    if len(body) > MAX_UPLOAD_BYTES:
        raise ValueError("Image uploads are limited to 10 MB")
    return body, mime


async def _set_post_image(
    settings: Settings,
    store: ImageAssetStore,
    post_entries: list[dict[str, Any]],
    body: bytes,
    mime: str,
) -> dict[str, Any]:
    """Store image bytes in R2 and set them as the only asset on every post."""

    base_url = settings.asset_public_base_url.rstrip("/")
    if not base_url:
        raise RuntimeError("ASSET_PUBLIC_BASE_URL must be configured to replace post images")
    key = f"generated_graphics/uploads/{uuid.uuid4().hex}.{KEY_EXTENSION[mime]}"
    await store.put(key, body, mime)
    image_url = f"{base_url}{ASSET_PATH_PREFIX}{key}"
    client = _client(settings)
    posts = _clean_posts(post_entries)
    assets = [{"image": {"url": image_url}}]

    async def edit(entry: dict[str, Any]) -> Any:
        return await client.edit_post(entry["id"], assets=assets, **_post_edit_kwargs(entry))

    info, results = await _apply_to_posts(posts, edit)
    return {**info, "image_url": image_url, "results": results}


async def replace_post_image(
    settings: Settings,
    store: ImageAssetStore,
    post_entries: list[dict[str, Any]],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Store a custom image in R2 and set it as the only asset on every post."""

    body, mime = decode_image_upload(payload)
    return await _set_post_image(settings, store, post_entries, body, mime)
