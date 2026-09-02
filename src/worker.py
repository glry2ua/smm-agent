"""Cloudflare Python Worker entrypoint."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict
from typing import Any
from urllib.parse import parse_qs, urlparse

from workers import Response, WorkerEntrypoint

from board_actions import (
    delete_posts,
    replace_post_image,
    schedule_posts,
    update_post_text,
)
from brand.brand_context import CONTACT_INFO_KEY, parse_contact_info
from buffer.client import BufferAPIError
from images.image_pipeline import GENERATED_GRAPHICS_PATH_PREFIX, R2ImageAssetStore
from job import run_weekly_job
from settings import Settings
from topics.topics import TopicStore
from web_api import invalidate_board_cache, load_board_cached


def _json_response(
    body: dict[str, object],
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> Response:
    return Response(
        json.dumps(body, default=str),
        status=status,
        headers={"Content-Type": "application/json; charset=utf-8", **(headers or {})},
    )


def _error_response(exc: Exception) -> Response:
    status = 400 if isinstance(exc, ValueError) else 500
    headers: dict[str, str] = {}
    if isinstance(exc, BufferAPIError):
        # Propagate Buffer's status (e.g. 429) instead of masking it as 500,
        # and forward Retry-After so clients can back off.
        if exc.status_code is not None:
            status = exc.status_code
        if exc.retry_after:
            headers["Retry-After"] = str(int(exc.retry_after) + 1)
        if status == 429:
            return _json_response(
                {"error": "Buffer is rate-limiting this API key. Wait a minute and refresh."},
                status=status,
                headers=headers,
            )
    return _json_response(
        {"error": f"{type(exc).__name__}: {exc}"},
        status=status,
        headers=headers,
    )


CONTENT_BOARD_FALLBACK_TITLE = "Content Board"


async def _board_title(env) -> str:
    """Board title from R2 contact.json: "{first_name}'s Agent".

    Falls back to the static title when R2 or the payload is unavailable —
    a broken contact.json should degrade the header, not the board.
    """
    try:
        bucket = getattr(env, "ASSETS", None)
        if bucket is None:
            return CONTENT_BOARD_FALLBACK_TITLE
        asset = await bucket.get(CONTACT_INFO_KEY)
        if asset is None:
            return CONTENT_BOARD_FALLBACK_TITLE
        body = await asset.arrayBuffer()
        info = parse_contact_info(bytes(body))
        return f"{info.first_name}'s Agent"
    except Exception:
        return CONTENT_BOARD_FALLBACK_TITLE


async def _json_body(request) -> dict[str, object]:
    body = await request.json()
    if isinstance(body, Mapping):
        return dict(body)
    try:
        return {str(key): body[key] for key in body}  # type: ignore[attr-defined]
    except Exception as exc:
        raise ValueError("Request body must be a JSON object") from exc


def _post_entries(body: Mapping[str, object]) -> list[dict[str, Any]]:
    """Parse ``posts`` entries (id + service + metadata), falling back to ``ids``."""

    raw = body.get("posts") if body.get("posts") is not None else body.get("ids")
    if not isinstance(raw, list):
        raise ValueError("body.posts must be a list of {id, service?, metadata?} objects")
    entries: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, Mapping):
            metadata = item.get("metadata")
            entry = {
                "id": str(item.get("id") or "").strip(),
                "service": str(item.get("service") or "").strip(),
                "metadata": dict(metadata) if isinstance(metadata, Mapping) else None,
            }
        else:
            entry = {"id": str(item).strip(), "service": "", "metadata": None}
        if entry["id"]:
            entries.append(entry)
    if not entries:
        raise ValueError("body.posts must include at least one post ID")
    return entries


def _optional_due_at(body: Mapping[str, object]) -> str | None:
    value = body.get("due_at")
    if value is None or not str(value).strip():
        return None
    return str(value).strip()


async def _handle_health(env, settings, request, parsed, body):
    return _json_response({"ok": True, "service": "smm-agent"})


async def _handle_board(env, settings, request, parsed, body):
    # `?fresh=1` = explicit user reload: skip the board TTL. Regular page
    # views are served from the client cache or the board TTL.
    fresh = "fresh" in parse_qs(parsed.query)
    board = await load_board_cached(settings, fresh=fresh)
    board["title"] = await _board_title(env)
    return _json_response(board)


async def _handle_topics_list(env, settings, request, parsed, body):
    topics = await TopicStore.from_env(env).list_topics()
    return _json_response(
        {"topics": [asdict(t) for t in topics]}  # type: ignore[misc]
    )


async def _handle_topics_add(env, settings, request, parsed, body):
    topic = body.get("topic")
    if not isinstance(topic, str):
        raise ValueError("body.topic must be a string")
    added = await TopicStore.from_env(env).add_topic(topic)
    return _json_response({"ok": True, "topic": asdict(added)})


async def _handle_topics_reset(env, settings, request, parsed, body):
    store = TopicStore.from_env(env)
    ids = body.get("ids")
    if isinstance(ids, list):
        topic_ids = [int(i) for i in ids if str(i).strip()]
        reset = await store.mark_unused(topic_ids)
    else:
        # No ids given: reset every used topic.
        reset = await store.mark_all_unused()
    return _json_response({"ok": True, "reset": reset})


async def _handle_topics_delete(env, settings, request, parsed, body):
    raw_id = body.get("id")
    try:
        topic_id = int(raw_id)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError("body.id must be a topic ID") from exc
    deleted = await TopicStore.from_env(env).delete_topic(topic_id)
    if not deleted:
        raise ValueError("Topic not found")
    return _json_response({"ok": True, "deleted": True})


async def _handle_posts_patch(env, settings, request, parsed, body):
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("body.text must be a non-empty string")
    result = await update_post_text(settings, _post_entries(body), text)
    return _json_response(result)  # type: ignore[arg-type]


async def _handle_posts_accept(env, settings, request, parsed, body):
    text = body.get("text")
    result = await schedule_posts(
        settings,
        _post_entries(body),
        _optional_due_at(body),
        text if isinstance(text, str) else None,
    )
    return _json_response(result)  # type: ignore[arg-type]


async def _handle_posts_delete(env, settings, request, parsed, body):
    result = await delete_posts(settings, _post_entries(body))
    return _json_response(result)  # type: ignore[arg-type]


async def _handle_posts_image(env, settings, request, parsed, body):
    image = body.get("image")
    if not isinstance(image, Mapping):
        raise ValueError("body.image must include image data")
    store = R2ImageAssetStore.from_env(env)
    result = await replace_post_image(settings, store, _post_entries(body), dict(image))
    return _json_response(result)  # type: ignore[arg-type]


async def _serve_generated_asset(env, path: str) -> Response:
    key = path.removeprefix("/assets/")
    asset = await env.ASSETS.get(key)
    if asset is None:
        return _json_response({"error": "asset not found"}, status=404)
    return Response(
        asset.body,
        headers={
            "Content-Type": "image/png",
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": asset.httpEtag,
        },
    )


Handler = Callable[[Any, Settings, Any, Any, dict[str, object] | None], Awaitable[Response]]

_ROUTES: dict[tuple[str, str], Handler] = {
    ("GET", "/health"): _handle_health,
    ("GET", "/api/board"): _handle_board,
    ("GET", "/api/topics"): _handle_topics_list,
    ("POST", "/api/topics"): _handle_topics_add,
    ("POST", "/api/topics/reset"): _handle_topics_reset,
    ("POST", "/api/topics/delete"): _handle_topics_delete,
    ("PATCH", "/api/posts"): _handle_posts_patch,
    ("POST", "/api/posts/accept"): _handle_posts_accept,
    ("POST", "/api/posts/delete"): _handle_posts_delete,
    ("POST", "/api/posts/image"): _handle_posts_image,
}

_MUTATES_BOARD = {
    ("PATCH", "/api/posts"),
    ("POST", "/api/posts/accept"),
    ("POST", "/api/posts/delete"),
    ("POST", "/api/posts/image"),
}


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        parsed = urlparse(request.url)
        path = parsed.path
        settings = Settings.from_env(self.env)
        route = (request.method, path)

        if request.method == "GET" and path.startswith(GENERATED_GRAPHICS_PATH_PREFIX):
            return await _serve_generated_asset(self.env, path)
        handler = _ROUTES.get(route)
        if handler is None:
            return _json_response({"error": "not found"}, status=404)
        try:
            body = await _json_body(request) if request.method != "GET" else None
            response = await handler(self.env, settings, request, parsed, body)
        except Exception as exc:
            return _error_response(exc)
        if route in _MUTATES_BOARD:
            invalidate_board_cache()
        return response

    async def scheduled(self, controller, env, ctx):
        del controller, ctx
        try:
            result = await run_weekly_job(env, dry_run=False)
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "event": "weekly_run_failed",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
            )
            raise
        else:
            print(json.dumps({"event": "weekly_run_complete", **result}))
