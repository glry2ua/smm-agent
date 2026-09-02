"""Reference-asset catalog and the typed-reference selection policy."""

from __future__ import annotations

import asyncio
import difflib
from dataclasses import dataclass, replace

from brand.brand_context import (
    LOGO_KEY,
    BrandAssetStore,
    ContactInfo,
    ReferenceAsset,
    infer_asset,
)
from images.image_pipeline import ReferenceImage, ReferenceImageStore
from schemas import ImagePrompt, SocialPostDraft

EXACT_OUTDOOR_MARKERS = (
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
EXCLUDES_OUTDOORS = (
    "no outdoor",
    "without outdoor",
    "no exterior",
    "without an exterior",
    "no neighborhood photo",
    "no neighborhood scene",
)
HEADSHOT_MARKERS = ("headshot", "portrait", "person", "people", "advisor")
EXCLUDES_PEOPLE = ("no people", "no person", "without people", "without a person")
GROUP_MARKERS = (
    "group photo",
    "client group",
    "with clients",
    "realtor and clients",
    "advisor and clients",
)


@dataclass(frozen=True, slots=True)
class ReferenceContext:
    """Resolved reference/brand stores plus the typed asset catalog they expose."""

    references: ReferenceImageStore | None
    brands: BrandAssetStore | None
    contact_info: ContactInfo | None
    listed_keys: list[str]
    assets: list[ReferenceAsset]

    @property
    def catalog_keys(self) -> list[str]:
        return [asset.key for asset in self.assets]

    @property
    def asset_catalog(self) -> dict[str, ReferenceAsset]:
        return {asset.key: asset for asset in self.assets}


def _reference_assets(listed_keys: list[str], *, include_logo: bool) -> list[ReferenceAsset]:
    keys = list(dict.fromkeys(listed_keys))
    if include_logo and LOGO_KEY not in keys:
        keys.append(LOGO_KEY)
    assets = [infer_asset(key) for key in keys]
    return [asset for asset in assets if asset.role != "other"]


def _canonical_reference_index(catalog_keys: list[str]) -> dict[str, str | None]:
    """Index catalog keys by a whitespace/case-insensitive form.

    The editor model normalizes whitespace when echoing keys back (e.g. it
    collapses the runs of spaces that several R2 object names contain), so an
    exact-match-only catalog would reject valid selections. Keys that differ
    only in whitespace or case map to the same entry; ambiguous collisions map
    to ``None`` so no wrong image is ever silently chosen.
    """

    index: dict[str, str | None] = {}
    for key in catalog_keys:
        normalized = "".join(key.split()).casefold()
        index[normalized] = None if normalized in index else key
    return index


def _canonical_reference_key(key: str, index: dict[str, str | None]) -> str | None:
    """Return the canonical catalog key the model's echoed key refers to."""

    return index.get("".join(key.split()).casefold())


def _unavailable_keys_error(unavailable: list[str], catalog_keys: list[str]) -> ValueError:
    """Describe unavailable echoed keys, suggesting the closest catalog key."""

    parts: list[str] = []
    for key in unavailable:
        close = difflib.get_close_matches(key, catalog_keys, n=1, cutoff=0.6)
        parts.append(key + (f" (did you mean {close[0]!r}?)" if close else ""))
    return ValueError("reference_image_keys contains unavailable keys: " + ", ".join(parts))


def _required_roles(image_prompt: ImagePrompt, searchable_text: str) -> set[str]:
    """Roles demanded by the prompt's visual type, policy, and markers."""

    required_roles: set[str] = set()
    policy_role = {
        "outdoor-exact": "outdoor",
        "headshot-exact": "headshot",
        "group-exact": "headshot-group",
    }.get(image_prompt.reference_policy)
    if policy_role:
        required_roles.add(policy_role)
    requests_outdoors = not any(phrase in searchable_text for phrase in EXCLUDES_OUTDOORS) and any(
        marker in searchable_text for marker in EXACT_OUTDOOR_MARKERS
    )
    if image_prompt.visual_type == "neighborhood-editorial" or requests_outdoors:
        required_roles.add("outdoor")
    if (
        image_prompt.visual_type == "people-editorial"
        and image_prompt.reference_policy == "indoor-flexible"
        and not any(phrase in searchable_text for phrase in EXCLUDES_PEOPLE)
    ):
        if any(marker in searchable_text for marker in GROUP_MARKERS):
            required_roles.add("headshot-group")
        elif any(marker in searchable_text for marker in HEADSHOT_MARKERS):
            required_roles.add("headshot")
    return required_roles


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
    catalog = asset_catalog or {key: infer_asset(key) for key in reference_keys}
    selected_roles = {catalog[key].role for key in reference_keys if key in catalog}
    required_roles = _required_roles(image_prompt, searchable_text)
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
