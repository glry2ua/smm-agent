"""Cloudflare Python Worker entrypoint."""

from __future__ import annotations

import json
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from images.image_pipeline import GENERATED_GRAPHICS_PATH_PREFIX
from job import run_weekly_job


def _json_response(body: dict[str, object], *, status: int = 200) -> Response:
    return Response(
        json.dumps(body),
        status=status,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        parsed = urlparse(request.url)
        if request.method == "GET" and parsed.path == "/health":
            return _json_response({"ok": True, "service": "smm-agent"})
        if request.method == "GET" and parsed.path.startswith(GENERATED_GRAPHICS_PATH_PREFIX):
            key = parsed.path.removeprefix("/assets/")
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
