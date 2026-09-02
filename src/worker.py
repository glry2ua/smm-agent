"""Cloudflare Python Worker entrypoint."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from board_actions import (
    ai_edit_post_image,
    delete_posts,
    replace_post_image,
    rewrite_post_text,
    schedule_posts,
    update_post_text,
)
from images.image_pipeline import GENERATED_GRAPHICS_PATH_PREFIX, R2ImageAssetStore
from job import run_weekly_job
from settings import Settings
from web_api import load_board


def _json_response(body: dict[str, object], *, status: int = 200) -> Response:
    return Response(
        json.dumps(body, default=str),
        status=status,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )


def _error_response(exc: Exception) -> Response:
    status = 400 if isinstance(exc, ValueError) else 500
    return _json_response(
        {"error": f"{type(exc).__name__}: {exc}"},
        status=status,
    )


async def _json_body(request) -> dict[str, object]:
    body = await request.json()
    if isinstance(body, Mapping):
        return dict(body)
    try:
        return {str(key): body[key] for key in body.keys()}  # type: ignore[attr-defined]
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


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        parsed = urlparse(request.url)
        path = parsed.path
        settings = Settings.from_env(self.env)

        if request.method == "GET" and path == "/health":
            return _json_response({"ok": True, "service": "smm-agent"})
        if request.method == "GET" and path == "/api/board":
            try:
                board = await load_board(settings)
            except Exception as exc:
                return _error_response(exc)
            return _json_response(board)
        if path == "/api/posts" and request.method == "PATCH":
            try:
                body = await _json_body(request)
                text = body.get("text")
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("body.text must be a non-empty string")
                result = await update_post_text(settings, _post_entries(body), text)
            except Exception as exc:
                return _error_response(exc)
            return _json_response(result)  # type: ignore[arg-type]
        if path == "/api/posts/accept" and request.method == "POST":
            try:
                body = await _json_body(request)
                text = body.get("text")
                result = await schedule_posts(
                    settings,
                    _post_entries(body),
                    _optional_due_at(body),
                    text if isinstance(text, str) else None,
                )
            except Exception as exc:
                return _error_response(exc)
            return _json_response(result)  # type: ignore[arg-type]
        if path == "/api/posts/delete" and request.method == "POST":
            try:
                body = await _json_body(request)
                result = await delete_posts(settings, _post_entries(body))
            except Exception as exc:
                return _error_response(exc)
            return _json_response(result)  # type: ignore[arg-type]
        if path == "/api/posts/image" and request.method == "POST":
            try:
                body = await _json_body(request)
                image = body.get("image")
                if not isinstance(image, Mapping):
                    raise ValueError("body.image must include image data")
                store = R2ImageAssetStore.from_env(self.env)
                result = await replace_post_image(settings, store, _post_entries(body), dict(image))
            except Exception as exc:
                return _error_response(exc)
            return _json_response(result)  # type: ignore[arg-type]
        if path == "/api/posts/image/ai" and request.method == "POST":
            try:
                body = await _json_body(request)
                store = R2ImageAssetStore.from_env(self.env)
                result = await ai_edit_post_image(settings, store, _post_entries(body), body)
            except Exception as exc:
                return _error_response(exc)
            return _json_response(result)  # type: ignore[arg-type]
        if path == "/api/posts/rewrite" and request.method == "POST":
            try:
                body = await _json_body(request)
                text = body.get("text")
                instruction = body.get("instruction")
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("body.text must be the current post text")
                if not isinstance(instruction, str) or not instruction.strip():
                    raise ValueError("body.instruction must describe the requested edit")
                new_text = await rewrite_post_text(settings, text, instruction)
            except Exception as exc:
                return _error_response(exc)
            return _json_response({"ok": True, "text": new_text})
        if request.method == "GET" and path.startswith(GENERATED_GRAPHICS_PATH_PREFIX):
            key = path.removeprefix("/assets/")
            asset = await self.env.ASSETS.get(key)
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
        return _json_response({"error": "not found"}, status=404)

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
