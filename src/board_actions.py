"""Board mutation endpoints: edit, schedule, delete, image replace, AI rewrite."""

from __future__ import annotations

import asyncio
import base64
import binascii
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from agent_config import load_agent
from buffer.client import BufferAPIError, BufferClient, channel_post_metadata
from images.image_pipeline import ASSET_PATH_PREFIX, ImageAssetStore
from job import PACIFIC, PUBLISH_TIME
from settings import Settings

_PUBLISH_WEEKDAYS = (0, 2, 4)  # Mon, Wed, Fri — mirrors job.PUBLISH_DAY_OFFSETS

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
DATA_URL_PREFIX = re.compile(r"^data:(image/[a-z0-9.+-]+);base64,", re.IGNORECASE)
KEY_EXTENSION = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}

REWRITE_SYSTEM_PROMPT = (
    "You are the social media editor for a boutique real-estate team. Apply the editor's "
    "instruction to the provided post copy and return the revised post text. Keep the voice "
    "helpful and specific, avoid engagement bait and unsupported claims, never invent facts "
    "or contact details, and keep the length close to the original unless asked otherwise. "
    "Return only the final post text with no quotes, preamble, or commentary."
)

REWRITE_MAX_OUTPUT_TOKENS = 1500


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


def _post_ids(post_entries: list[dict[str, Any]]) -> list[str]:
    return [entry["id"] for entry in post_entries]


def _per_post_errors(results: list[BaseException], post_ids: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "id": post_id,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        for post_id, exc in zip(post_ids, results, strict=True)
        if isinstance(exc, BaseException)
    ]


def _next_publish_slot(now: datetime, *, min_lead_minutes: int) -> datetime:
    """Return the next Mon/Wed/Fri 08:30 Pacific slot at least ``min_lead`` away.

    Mirrors the weekly pipeline's schedule (``job.PUBLISH_TIME`` and
    ``job.PUBLISH_DAY_OFFSETS``) so late accepts land on a real publish slot
    instead of a time in the past, which Buffer rejects.
    """

    earliest = now + timedelta(minutes=max(1, min_lead_minutes))
    day = now.astimezone(PACIFIC).date()
    for _ in range(28):
        if day.weekday() in _PUBLISH_WEEKDAYS:
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


async def update_post_text(
    settings: Settings,
    post_entries: list[dict[str, Any]],
    text: str,
) -> dict[str, Any]:
    """Set the text on every listed post via Buffer editPost."""

    client = _client(settings)
    posts = _clean_posts(post_entries)
    ids = _post_ids(posts)
    outcomes = await asyncio.gather(
        *(
            client.edit_post(entry["id"], text=text.strip(), **_post_edit_kwargs(entry))
            for entry in posts
        ),
        return_exceptions=True,
    )
    errors = _per_post_errors(outcomes, ids)
    if len(errors) == len(ids):
        raise RuntimeError(errors[0]["error"])
    return {"ok": not errors, "results": _ok_results(outcomes, ids) + errors}


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
    ids = _post_ids(posts)
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
    outcomes = await asyncio.gather(
        *(
            client.edit_post(
                entry["id"],
                due_at=effective_due_at,
                mode="customScheduled",
                scheduling_type="automatic",
                save_to_draft=False,
                text=text.strip() if text is not None and text.strip() else None,
                **_post_edit_kwargs(entry),
            )
            for entry in posts
        ),
        return_exceptions=True,
    )
    errors = _per_post_errors(outcomes, ids)
    if len(errors) == len(ids):
        raise RuntimeError(errors[0]["error"])
    return {
        "ok": not errors,
        "scheduled_at": effective_due_at.astimezone(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "rescheduled": requested is None or requested < earliest,
        "results": _ok_results(outcomes, ids) + errors,
    }


async def delete_posts(settings: Settings, post_entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Delete every listed post from Buffer."""

    client = _client(settings)
    posts = _clean_posts(post_entries)
    ids = _post_ids(posts)
    outcomes = await asyncio.gather(
        *(client.delete_post(post_id) for post_id in ids),
        return_exceptions=True,
    )
    errors = _per_post_errors(outcomes, ids)
    if len(errors) == len(ids):
        raise RuntimeError(errors[0]["error"])
    return {
        "ok": not errors,
        "results": [
            {"id": post_id, "ok": not isinstance(result, BaseException)}
            for post_id, result in zip(ids, outcomes, strict=True)
        ]
        + errors,
    }


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
    ids = _post_ids(posts)
    assets = [{"image": {"url": image_url}}]
    outcomes = await asyncio.gather(
        *(
            client.edit_post(entry["id"], assets=assets, **_post_edit_kwargs(entry))
            for entry in posts
        ),
        return_exceptions=True,
    )
    errors = _per_post_errors(outcomes, ids)
    if len(errors) == len(ids):
        raise RuntimeError(errors[0]["error"])
    return {
        "ok": not errors,
        "image_url": image_url,
        "results": _ok_results(outcomes, ids) + errors,
    }


async def replace_post_image(
    settings: Settings,
    store: ImageAssetStore,
    post_entries: list[dict[str, Any]],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Store a custom image in R2 and set it as the only asset on every post."""

    body, mime = decode_image_upload(payload)
    return await _set_post_image(settings, store, post_entries, body, mime)


async def _fetch_image_bytes(url: str) -> tuple[bytes, str]:
    """Download the current post image; returns (bytes, mime type)."""

    import httpx

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http:
        response = await http.get(url)
        response.raise_for_status()
    body = response.content
    if not body:
        raise ValueError("The current image could not be downloaded")
    if len(body) > MAX_UPLOAD_BYTES:
        raise ValueError("The current image is too large to edit (limit is 10 MB)")
    mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if mime not in ALLOWED_IMAGE_MIME_TYPES:
        mime = "image/png"
    return body, mime


async def ai_edit_post_image(
    settings: Settings,
    store: ImageAssetStore,
    post_entries: list[dict[str, Any]],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Edit the post's current image with GPT Image and set the result as the asset."""

    if not settings.openai_api_key.strip():
        raise RuntimeError("OPENAI_API_KEY is required for AI image edits")
    instruction = str(payload.get("instruction") or "").strip()
    if not instruction:
        raise ValueError("An edit instruction is required")
    url = str(payload.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("The post's current image URL is missing or invalid")

    from openai import AsyncOpenAI

    body, mime = await _fetch_image_bytes(url)
    image_client = AsyncOpenAI(api_key=settings.openai_api_key)
    edited = await image_client.images.edit(
        model=settings.openai_image_model,
        image=[(f"current.{KEY_EXTENSION[mime]}", body, mime)],
        prompt=instruction,
        size=settings.openai_image_size,
        quality=settings.openai_image_quality,
        output_format="png",
        background="opaque",
    )
    if not edited.data or not edited.data[0].b64_json:
        raise RuntimeError("GPT Image did not return edited image data")
    new_body = base64.b64decode(edited.data[0].b64_json, validate=True)
    return await _set_post_image(settings, store, post_entries, new_body, "image/png")


async def rewrite_post_text(
    settings: Settings,
    current_text: str,
    instruction: str,
    *,
    openai_client: Any = None,
) -> str:
    """Return an LLM-revised post text; a single fast model call, no agent loop."""

    if not settings.openai_api_key.strip():
        raise RuntimeError("OPENAI_API_KEY is required for AI text edits")
    if not instruction.strip():
        raise ValueError("An edit instruction is required")
    if not current_text.strip():
        raise ValueError("The post being edited has no text to revise")

    client = openai_client
    if client is None:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
    model = load_agent("social-post-editor").model

    response = await asyncio.wait_for(
        client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"<INSTRUCTION>\n{instruction.strip()}\n</INSTRUCTION>\n\n"
                        f"<POST_TEXT>\n{current_text.strip()}\n</POST_TEXT>"
                    ),
                },
            ],
            max_output_tokens=REWRITE_MAX_OUTPUT_TOKENS,
            reasoning={"effort": "low"},
        ),
        timeout=60.0,
    )
    text = getattr(response, "output_text", None)
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("The model returned an empty edit")
    return text.strip()


def _ok_results(outcomes: list[Any], post_ids: list[str]) -> list[dict[str, Any]]:
    return [
        {"id": post_id, "ok": True, "post": dict(result)}
        for post_id, result in zip(post_ids, outcomes, strict=True)
        if not isinstance(result, BaseException)
    ]


def describe_error(exc: BaseException) -> str:
    if isinstance(exc, BufferAPIError):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"
