"""Draft generation: agent attempts, revision feedback, and deterministic fallback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from brand.brand_context import ContactInfo, ReferenceAsset
from content.social_agent import generate_social_post
from job.references import (
    _canonical_reference_index,
    _canonical_reference_key,
    _unavailable_keys_error,
    validate_reference_policy,
)
from job.validation import validate_draft
from schemas import ImagePrompt, PerformanceAnalysis, SocialPostDraft
from settings import Settings

MAX_DRAFT_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class DraftPreparation:
    draft: SocialPostDraft
    attempts: int
    fallback_used: bool
    validation_errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DraftContext:
    """Everything one draft's generation attempts share."""

    settings: Settings
    topic: str
    due_at: datetime
    reference_keys: list[str]
    performance_analysis: PerformanceAnalysis | None
    contact_info: ContactInfo | None
    assets: list[ReferenceAsset]
    asset_catalog: dict[str, ReferenceAsset]
    now: datetime
    require_headshot_reference: bool


def _canonicalize_selected_keys(
    requested_keys: list[str], catalog_keys: list[str]
) -> tuple[list[str], list[str]]:
    """Map echoed keys back to canonical catalog keys, deduplicate, and cap at 3."""

    reference_index = _canonical_reference_index(catalog_keys)
    selected: list[str] = []
    unavailable: list[str] = []
    for key in requested_keys:
        canonical = _canonical_reference_key(key, reference_index)
        if canonical is None:
            unavailable.append(key)
        elif canonical not in selected:
            selected.append(canonical)
    return selected[:3], unavailable


def _revision_feedback(
    attempt: int, exc: ValueError, draft: SocialPostDraft, assets: list[ReferenceAsset]
) -> str:
    available_roles = sorted({asset.role for asset in assets})
    safe_fallback = (
        "When a missing role is not in Available roles, use "
        "visual_type=typographic-educational, reference_policy=indoor-flexible, no people, "
        "and no outdoor or neighborhood photograph."
    )
    return (
        f"Attempt {attempt} failed: {exc}\n"
        f"Available roles: {', '.join(available_roles) or 'none'}\n"
        f"Required fallback: {safe_fallback}\n"
        f"Rejected draft: {draft.model_dump_json()}"
    )


def _abandon_with_fallback(
    context: DraftContext,
    previous: SocialPostDraft | None,
    attempt: int,
    errors: list[str],
    message: str,
    exc: BaseException,
) -> DraftPreparation:
    """Max attempts reached: raise for headshot tests, else return the fallback draft."""

    if context.require_headshot_reference:
        raise RuntimeError(f"Headshot test draft {message}") from exc
    fallback = _fallback_draft(
        context.topic, context.due_at, previous, context.settings, context.now
    )
    return DraftPreparation(fallback, attempt, True, tuple(errors))


async def _generate_valid_draft(context: DraftContext) -> DraftPreparation:
    revision_feedback: str | None = None
    errors: list[str] = []
    last_draft: SocialPostDraft | None = None
    for attempt in range(1, MAX_DRAFT_ATTEMPTS + 1):
        try:
            draft = await generate_social_post(
                context.settings,
                context.topic,
                context.due_at,
                reference_image_keys=context.reference_keys,
                performance_analysis=context.performance_analysis,
                contact_info=context.contact_info,
                reference_assets=context.assets,
                revision_feedback=revision_feedback,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"[:800]
            errors.append(error)
            if attempt == MAX_DRAFT_ATTEMPTS:
                return _abandon_with_fallback(
                    context,
                    last_draft,
                    attempt,
                    errors,
                    f"generation failed after {attempt} attempts: {error}",
                    exc,
                )
            revision_feedback = (
                f"Attempt {attempt} could not produce valid structured output: {error}\n"
                "Return a complete replacement draft using the available roles."
            )
            continue
        last_draft = draft
        selected_keys, unavailable_keys = _canonicalize_selected_keys(
            list(dict.fromkeys(draft.reference_image_keys)), context.reference_keys
        )
        draft = draft.model_copy(update={"reference_image_keys": selected_keys})
        try:
            if unavailable_keys:
                raise _unavailable_keys_error(unavailable_keys, context.reference_keys)
            validate_draft(draft, context.settings, context.now)
            validate_reference_policy(
                draft, selected_keys, context.asset_catalog, context.contact_info
            )
            if context.require_headshot_reference and (
                draft.image_prompt.reference_policy != "headshot-exact"
                or "headshot" not in {context.asset_catalog[key].role for key in selected_keys}
            ):
                raise ValueError(
                    "Headshot test requires reference_policy=headshot-exact and a role=headshot key"
                )
        except ValueError as exc:
            error = str(exc)[:800]
            errors.append(error)
            if attempt == MAX_DRAFT_ATTEMPTS:
                return _abandon_with_fallback(
                    context,
                    draft,
                    attempt,
                    errors,
                    f"remained invalid after {attempt} attempts: {exc}",
                    exc,
                )
            revision_feedback = _revision_feedback(attempt, exc, draft, context.assets)
            continue
        return DraftPreparation(draft, attempt, False, tuple(errors))
    raise RuntimeError("unreachable")


def _fallback_draft(
    topic: str,
    due_at: datetime,
    previous: SocialPostDraft | None,
    settings: Settings,
    now: datetime,
) -> SocialPostDraft:
    """Build a deterministic, reference-free visual when agent revisions remain invalid."""

    normalized_topic = " ".join(topic.split())[:160] or "Plan your next real-estate move"
    headline = normalized_topic[:60]
    image_prompt = ImagePrompt(
        visual_type="typographic-educational",
        reference_policy="indoor-flexible",
        subject=f"A typography-led educational graphic about: {normalized_topic}",
        setting="Warm ivory studio backdrop with typography only",
        composition=(
            "Large crisp headline, restrained abstract lines, generous negative space, "
            "and no photography or people"
        ),
        headline=headline,
        must_include=[],
        avoid=["people", "property photography", "invented facts", "extra text"],
        business_fields=[],
    )
    if previous is not None:
        candidate = previous.model_copy(
            update={"image_prompt": image_prompt, "reference_image_keys": []}
        )
        try:
            validate_draft(candidate, settings, now)
        except ValueError:
            pass
        else:
            validate_reference_policy(candidate, [], {}, None)
            return candidate
    description = (
        f"{normalized_topic}\n\n"
        "A clear real-estate decision starts with your priorities, timing, and next step. "
        "Define what matters most, then compare each option against the same criteria."
    )
    fallback = SocialPostDraft(
        description=description,
        keywords=["San Jose real estate", "home planning", "buyer guidance"],
        image_prompt=image_prompt,
        reference_image_keys=[],
        due_at=due_at,
    )
    validate_draft(fallback, settings, now)
    validate_reference_policy(fallback, [], {}, None)
    return fallback
