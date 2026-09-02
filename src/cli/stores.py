"""Wrangler-backed topic, asset, and reference-image stores for local runs."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from brand.brand_context import CONTACT_INFO_KEY, LOGO_KEY, ContactInfo, parse_contact_info
from images.image_pipeline import ReferenceImage, is_reference_image_key
from topics.topics import Topic


def _reference_content_type(key: str) -> str:
    suffix = Path(key).suffix.casefold()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".png": "image/png",
    }.get(suffix, "application/octet-stream")


def _validate_reference_key(key: str) -> None:
    normalized = key.casefold()
    if (
        not key
        or normalized.startswith("generated_graphics/")
        or Path(key).suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp"}
    ):
        raise ValueError(f"Invalid reference image key: {key}")


class WranglerTopicStore:
    """Use the authenticated Wrangler CLI to access the production D1 database."""

    database = "smm-agent-db"

    async def _execute(self, sql: str) -> list[dict[str, Any]]:
        process = await asyncio.create_subprocess_exec(
            "npx",
            "--yes",
            "wrangler@latest",
            "d1",
            "execute",
            self.database,
            "--remote",
            "--json",
            "--command",
            sql,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            message = stderr.decode().strip() or stdout.decode().strip()
            raise RuntimeError(f"Wrangler D1 command failed: {message}")
        payload = json.loads(stdout.decode())
        blocks = payload if isinstance(payload, list) else [payload]
        if not blocks:
            return []
        results = blocks[0].get("results", [])
        return results if isinstance(results, list) else []

    async def pick_random_available(self, limit: int = 1) -> list[Topic]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        rows = await self._execute(
            "SELECT id, topic FROM topics "
            f"WHERE used_at IS NULL ORDER BY RANDOM() LIMIT {int(limit)}"
        )
        return [Topic(id=int(row["id"]), topic=str(row["topic"])) for row in rows]

    async def pick_available_topic(self, topic: str) -> Topic | None:
        if not topic.strip():
            raise ValueError("topic must not be empty")
        escaped_topic = topic.replace("'", "''")
        rows = await self._execute(
            "SELECT id, topic FROM topics "
            f"WHERE used_at IS NULL AND topic = '{escaped_topic}' LIMIT 1"
        )
        if not rows:
            return None
        row = rows[0]
        return Topic(id=int(row["id"]), topic=str(row["topic"]))

    async def mark_used(self, topic_id: int, used_at: datetime) -> None:
        timestamp = used_at.isoformat().replace("'", "''")
        await self._execute(
            "UPDATE topics SET used_at = "
            f"'{timestamp}' WHERE id = {int(topic_id)} AND used_at IS NULL"
        )


def _cloudflare_token() -> str | None:
    """Return an API token from the environment or the active wrangler login."""

    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if token:
        return token
    candidates: list[Path] = []
    xdg_config = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg_config:
        candidates.append(Path(xdg_config) / "wrangler" / "config" / "default.toml")
    candidates.extend(
        Path.home() / relative
        for relative in (
            Path("Library/Preferences/.wrangler/config/default.toml"),
            Path(".wrangler/config/default.toml"),
        )
    )
    for path in candidates:
        try:
            text = path.read_text()
        except OSError:
            continue
        match = re.search(r'^oauth_token\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if match:
            return match.group(1)
    return None


def _object_keys_from_page(payload: dict[str, Any]) -> tuple[list[str], str | None]:
    """Extract usable reference keys and the next cursor from an R2 list page."""

    result = payload.get("result")
    # The untyped R2 list endpoint returns a bare array under "result"; entries
    # may be plain key strings or {"key": ...} objects depending on API version.
    # The typed listing nests the page under "keys" or "objects".
    if isinstance(result, list):
        raw: list[Any] = []
        for entry in result:
            if isinstance(entry, str):
                raw.append(entry)
            elif isinstance(entry, dict) and isinstance(entry.get("key"), str):
                raw.append(entry["key"])
    else:
        result = result or {}
        raw = result.get("keys")
        if raw is None:
            raw = [
                item.get("key") for item in result.get("objects") or [] if isinstance(item, dict)
            ]
    keys = [str(key) for key in raw if isinstance(key, str) and is_reference_image_key(str(key))]
    cursors = payload.get("result_info") or {}
    if not cursors and not isinstance(result, list):
        cursors = result.get("cursors") or {}
    next_cursor = cursors.get("cursor") or cursors.get("next")
    return keys, str(next_cursor) if next_cursor else None


def _account_id_from_whoami(text: str) -> str:
    start = text.find("{")
    if start < 0:
        raise RuntimeError("Wrangler whoami returned no JSON account information")
    payload = json.loads(text[start:])
    # Older wrangler emits {"accounts": [...]}; newer versions nest under {"whoami": {...}}.
    accounts = payload.get("accounts")
    if accounts is None:
        accounts = (payload.get("whoami") or {}).get("accounts")
    for entry in accounts or []:
        account_id = (entry.get("account") or {}).get("id") or entry.get("id")
        if account_id:
            return str(account_id)
    raise RuntimeError(
        "No Cloudflare account found in wrangler whoami output: " + json.dumps(payload)[:400]
    )


async def _cloudflare_account_id() -> str:
    env_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if env_id:
        return env_id
    process = await asyncio.create_subprocess_exec(
        "npx",
        "--yes",
        "wrangler@latest",
        "whoami",
        "--json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        message = stderr.decode().strip() or stdout.decode().strip()
        raise RuntimeError(f"Wrangler whoami failed: {message}")
    return _account_id_from_whoami(stdout.decode())


class WranglerImageAssetStore:
    """Upload generated image bytes to the production R2 bucket during local live runs."""

    bucket = "smm-agent-assets"

    async def put(self, key: str, body: bytes, content_type: str) -> None:
        with tempfile.NamedTemporaryFile(suffix=".png") as image_file:
            image_file.write(body)
            image_file.flush()
            process = await asyncio.create_subprocess_exec(
                "npx",
                "--yes",
                "wrangler@latest",
                "r2",
                "object",
                "put",
                f"{self.bucket}/{key}",
                "--file",
                image_file.name,
                "--content-type",
                content_type,
                "--cache-control",
                "public, max-age=31536000, immutable",
                "--remote",
                "--force",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
        if process.returncode != 0:
            message = stderr.decode().strip() or stdout.decode().strip()
            raise RuntimeError(f"Wrangler R2 upload failed: {message}")

    async def list_reference_keys(self) -> list[str]:
        """List source photos through the Cloudflare API, mirroring the Worker's
        R2 bucket listing so local runs exercise the same automatic retrieval
        catalog as the real deployment."""

        token = _cloudflare_token()
        if token is None:
            raise RuntimeError(
                "Listing R2 reference images requires CLOUDFLARE_API_TOKEN or an active "
                "`wrangler login` session"
            )
        account = await _cloudflare_account_id()
        base = (
            "https://api.cloudflare.com/client/v4/accounts/"
            f"{quote(account, safe='')}/r2/buckets/{quote(self.bucket, safe='')}/objects"
        )
        keys: list[str] = []
        cursor: str | None = None
        while len(keys) < 500:
            url = f"{base}?per_page=1000" + (f"&cursor={quote(cursor, safe='')}" if cursor else "")
            payload = await asyncio.to_thread(self._fetch_json, url, token)
            if not payload.get("success", True):
                errors = payload.get("errors") or []
                raise RuntimeError(f"Cloudflare R2 object listing failed: {errors}")
            page_keys, cursor = _object_keys_from_page(payload)
            keys.extend(page_keys[: 500 - len(keys)])
            if cursor is None:
                break
        return keys

    @staticmethod
    def _fetch_json(url: str, token: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode())

    async def get_reference_image(self, key: str) -> ReferenceImage:
        _validate_reference_key(key)
        return await _download_r2_reference(self.bucket, key)

    async def get_contact_info(self) -> ContactInfo:
        return parse_contact_info(await _download_r2_bytes(self.bucket, CONTACT_INFO_KEY))

    async def get_logo_image(self) -> ReferenceImage:
        return ReferenceImage(
            key=LOGO_KEY,
            body=await _download_r2_bytes(self.bucket, LOGO_KEY),
            content_type="image/png",
            role="logo",
        )


async def _download_r2_reference(bucket: str, key: str) -> ReferenceImage:
    return ReferenceImage(
        key=key,
        body=await _download_r2_bytes(bucket, key),
        content_type=_reference_content_type(key),
    )


async def _download_r2_bytes(bucket: str, key: str) -> bytes:
    with tempfile.TemporaryDirectory() as temporary_directory:
        destination = Path(temporary_directory) / Path(key).name
        process = await asyncio.create_subprocess_exec(
            "npx",
            "--yes",
            "wrangler@latest",
            "r2",
            "object",
            "get",
            f"{bucket}/{key}",
            "--file",
            str(destination),
            "--remote",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            message = stderr.decode().strip() or stdout.decode().strip()
            raise RuntimeError(f"Wrangler R2 download failed: {message}")
        return destination.read_bytes()


class WranglerReferenceImageStore:
    """Read explicitly selected source images from the production R2 bucket."""

    bucket = WranglerImageAssetStore.bucket

    def __init__(self, keys: list[str]) -> None:
        self.keys = list(dict.fromkeys(keys))
        for key in self.keys:
            _validate_reference_key(key)

    async def list_reference_keys(self) -> list[str]:
        return self.keys.copy()

    async def get_reference_image(self, key: str) -> ReferenceImage:
        if key not in self.keys:
            raise ValueError(f"Reference image was not selected for this run: {key}")
        return await _download_r2_reference(self.bucket, key)


class LocalReferenceImageStore:
    """Expose local source images as a small reference catalog for a dry-run."""

    def __init__(self, paths: list[Path]) -> None:
        self.images: dict[str, Path] = {}
        for path in paths:
            resolved = path.expanduser().resolve()
            if not resolved.is_file():
                raise ValueError(f"Reference image does not exist: {path}")
            key = f"headshots/{resolved.name}"
            if key in self.images:
                raise ValueError(f"Duplicate reference image filename: {resolved.name}")
            _validate_reference_key(key)
            self.images[key] = resolved

    async def list_reference_keys(self) -> list[str]:
        return list(self.images)

    async def get_reference_image(self, key: str) -> ReferenceImage:
        path = self.images.get(key)
        if path is None:
            raise ValueError(f"Reference image was not selected for this run: {key}")
        return ReferenceImage(
            key=key,
            body=path.read_bytes(),
            content_type=_reference_content_type(key),
        )
