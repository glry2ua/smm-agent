"""Strict R2 brand data and folder-based reference-image roles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from image_pipeline import ReferenceImage

CONTACT_INFO_KEY = "info/contact.json"
LOGO_KEY = "info/logo.png"

AssetRole = Literal["logo", "indoor", "outdoor", "headshot", "headshot-group", "other"]


@dataclass(frozen=True, slots=True)
class ContactInfo:
    business_name: str
    phone: str
    city: str
    website: str

    def prompt_facts(self) -> str:
        return "\n".join(
            (
                f"- business_name: {self.business_name}",
                f"- phone: {self.phone}",
                f"- city: {self.city}",
                f"- website: {self.website}",
            )
        )


@dataclass(frozen=True, slots=True)
class ReferenceAsset:
    key: str
    role: AssetRole

    def prompt_line(self) -> str:
        return f"- key={self.key} | role={self.role}"


class BrandAssetStore(Protocol):
    async def get_contact_info(self) -> ContactInfo: ...

    async def get_logo_image(self) -> ReferenceImage: ...


def parse_contact_info(body: bytes) -> ContactInfo:
    """Parse contact.json, rejecting missing, extra, or non-string fields."""

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"R2 {CONTACT_INFO_KEY} is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"R2 {CONTACT_INFO_KEY} must contain one JSON object")
    expected = {"business_name", "phone", "city", "website"}
    if set(payload) != expected:
        missing = sorted(expected - set(payload))
        extra = sorted(set(payload) - expected)
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if extra:
            details.append("unexpected: " + ", ".join(extra))
        raise RuntimeError(f"R2 {CONTACT_INFO_KEY} has invalid fields ({'; '.join(details)})")
    invalid = [
        key
        for key in sorted(expected)
        if not isinstance(payload[key], str) or not payload[key].strip()
    ]
    if invalid:
        raise RuntimeError(
            f"R2 {CONTACT_INFO_KEY} requires non-empty string values for: {', '.join(invalid)}"
        )
    return ContactInfo(**{key: payload[key].strip() for key in expected})


def infer_asset(key: str) -> ReferenceAsset:
    """Map the existing R2 folder layout to an explicit image-generation role."""

    path_parts = PurePosixPath(key).parts
    normalized_parts = [
        part.casefold().replace("_", "-").replace(" ", "-").rstrip("s")
        for part in path_parts[:-1]
    ]
    folder = normalized_parts[0] if normalized_parts else ""
    nested_group = folder in {"headshot", "portrait"} and any(
        part in {"group", "client", "client-group"} for part in normalized_parts[1:]
    )
    role: AssetRole = (
        "logo"
        if key.casefold() == LOGO_KEY
        else "headshot-group"
        if nested_group
        or folder in {"headshot-group", "group-headshot", "group", "client-group"}
        else "headshot"
        if folder in {"headshot", "portrait"}
        else "indoor"
        if folder in {"indoor", "interior"}
        else "outdoor"
        if folder in {"outdoor", "exterior"}
        else "other"
    )
    return ReferenceAsset(key=key, role=role)
