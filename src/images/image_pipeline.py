"""Generate a social visual with GPT Image 2 and persist it for Buffer."""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from brand.brand_context import (
    CONTACT_INFO_KEY,
    LOGO_KEY,
    AssetRole,
    ContactInfo,
    infer_asset,
    parse_contact_info,
)
from schemas import ImagePrompt
from settings import Settings

ASSET_PATH_PREFIX = "/assets/"
GENERATED_GRAPHICS_PATH_PREFIX = f"{ASSET_PATH_PREFIX}generated_graphics/"


class ImageAssetStore(Protocol):
    async def put(self, key: str, body: bytes, content_type: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ReferenceImage:
    key: str
    body: bytes
    content_type: str
    role: AssetRole = "other"
    description: str = ""


class ReferenceImageStore(Protocol):
    async def list_reference_keys(self) -> list[str]: ...

    async def get_reference_image(self, key: str) -> ReferenceImage: ...


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    key: str
    url: str | None
    model: str
    size: str
    quality: str
    local_path_absolute: str | None = None
    local_path_relative: str | None = None


class R2ImageAssetStore:
    def __init__(self, bucket: object) -> None:
        self.bucket = bucket

    @classmethod
    def from_env(cls, env: object) -> R2ImageAssetStore:
        bucket = getattr(env, "ASSETS", None)
        if bucket is None:
            raise RuntimeError("The ASSETS R2 binding is required for generated images")
        return cls(bucket)

    async def put(self, key: str, body: bytes, content_type: str) -> None:
        await self.bucket.put(
            key,
            body,
            httpMetadata={
                "contentType": content_type,
                "cacheControl": "public, max-age=31536000, immutable",
            },
        )

    async def list_reference_keys(self) -> list[str]:
        """List source photos in any R2 folder, excluding generated output."""

        keys: list[str] = []
        cursor: str | None = None
        while len(keys) < 500:
            limit = min(1000, 500 - len(keys))
            page = (
                await self.bucket.list(limit=limit, cursor=cursor)
                if cursor
                else await self.bucket.list(limit=limit)
            )
            for item in getattr(page, "objects", []):
                key = str(getattr(item, "key", ""))
                if _is_reference_image_key(key):
                    keys.append(key)
            if not getattr(page, "truncated", False):
                break
            cursor = str(getattr(page, "cursor", "")) or None
            if cursor is None:
                break
        return keys

    async def get_reference_image(self, key: str) -> ReferenceImage:
        if not _is_reference_image_key(key):
            raise ValueError(f"Invalid R2 reference image key: {key}")
        asset = await self.bucket.get(key)
        if asset is None:
            raise RuntimeError(f"R2 reference image not found: {key}")
        body = await _r2_body(asset)
        metadata = getattr(asset, "httpMetadata", None)
        content_type = getattr(metadata, "contentType", None) or _content_type_for_key(key)
        return ReferenceImage(
            key=key,
            body=body,
            content_type=str(content_type),
            role=infer_asset(key).role,
        )

    async def get_contact_info(self) -> ContactInfo:
        asset = await self.bucket.get(CONTACT_INFO_KEY)
        if asset is None:
            raise RuntimeError(f"Required R2 object not found: {CONTACT_INFO_KEY}")
        return parse_contact_info(await _r2_body(asset))

    async def get_logo_image(self) -> ReferenceImage:
        asset = await self.bucket.get(LOGO_KEY)
        if asset is None:
            raise RuntimeError(f"Required R2 object not found: {LOGO_KEY}")
        return ReferenceImage(
            key=LOGO_KEY,
            body=await _r2_body(asset),
            content_type="image/png",
            role="logo",
        )


async def _r2_body(asset: object) -> bytes:
    array_buffer = await asset.arrayBuffer()
    try:
        from js import Uint8Array
    except ImportError:
        return bytes(array_buffer)
    return Uint8Array.new(array_buffer).to_py().tobytes()


def _is_reference_image_key(key: str) -> bool:
    normalized = key.casefold()
    return (
        bool(key)
        and not normalized.startswith("generated_graphics/")
        and not normalized.startswith("info/")
        and normalized.endswith((".png", ".jpg", ".jpeg", ".webp"))
    )


def _content_type_for_key(key: str) -> str:
    suffix = key.rsplit(".", 1)[-1].casefold()
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
    }.get(suffix, "image/png")


def image_key(topic_id: int, due_at: datetime, prompt: str) -> str:
    digest = hashlib.sha256(prompt.encode()).hexdigest()[:12]
    return f"generated_graphics/{due_at:%Y/%m/%d}/topic-{topic_id}-{digest}.png"


async def generate_image_bytes(
    settings: Settings,
    image_prompt: ImagePrompt,
    reference_images: list[ReferenceImage] | None = None,
    contact_info: ContactInfo | None = None,
) -> bytes:
    """Generate one PNG and return its decoded bytes."""

    from openai import AsyncOpenAI

    if not settings.openai_image_model:
        raise RuntimeError("Image generation requires a non-empty OPENAI_IMAGE_MODEL")
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    common = {
        "model": settings.openai_image_model,
        "prompt": image_prompt.render(reference_images, contact_info),
        "size": settings.openai_image_size,
        "quality": settings.openai_image_quality,
        "output_format": "png",
        "background": "opaque",
    }
    if reference_images:
        files = [
            (
                f"{index:02d}-{image.role}-{Path(image.key).name}",
                image.body,
                image.content_type,
            )
            for index, image in enumerate(reference_images, start=1)
        ]
        response = await client.images.edit(image=files, **common)
    else:
        response = await client.images.generate(**common)
    if not response.data or not response.data[0].b64_json:
        raise RuntimeError("GPT Image 2 did not return image data")
    return base64.b64decode(response.data[0].b64_json, validate=True)


async def generate_and_store_image(
    settings: Settings,
    image_prompt: ImagePrompt,
    topic_id: int,
    due_at: datetime,
    store: ImageAssetStore,
    reference_images: list[ReferenceImage] | None = None,
    contact_info: ContactInfo | None = None,
) -> GeneratedImage:
    settings.validate_for_images()
    prompt = image_prompt.render(reference_images, contact_info)
    body = await generate_image_bytes(
        settings, image_prompt, reference_images, contact_info=contact_info
    )
    key = image_key(topic_id, due_at, prompt)
    await store.put(key, body, "image/png")
    return GeneratedImage(
        key=key,
        url=f"{settings.asset_public_base_url}{ASSET_PATH_PREFIX}{key}",
        model=settings.openai_image_model,
        size=settings.openai_image_size,
        quality=settings.openai_image_quality,
    )


async def generate_and_save_image(
    settings: Settings,
    image_prompt: ImagePrompt,
    topic_id: int,
    due_at: datetime,
    output_root: Path,
    relative_to: Path,
    reference_images: list[ReferenceImage] | None = None,
    contact_info: ContactInfo | None = None,
) -> GeneratedImage:
    """Generate one PNG and save it to a local dry-run output directory."""

    prompt = image_prompt.render(reference_images, contact_info)
    key = image_key(topic_id, due_at, prompt)
    relative_key = key.removeprefix("generated_graphics/")
    destination = (output_root / relative_key).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(
        await generate_image_bytes(
            settings, image_prompt, reference_images, contact_info=contact_info
        )
    )
    return GeneratedImage(
        key=key,
        url=None,
        model=settings.openai_image_model,
        size=settings.openai_image_size,
        quality=settings.openai_image_quality,
        local_path_absolute=str(destination),
        local_path_relative=os.path.relpath(destination, start=relative_to.resolve()),
    )
