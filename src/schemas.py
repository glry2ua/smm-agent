"""Structured social-post output shared by the agent and Buffer client."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from brand.brand_context import ContactInfo


def _normalized_text(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


def _normalized_keywords(values: list[str]) -> list[str]:
    cleaned = [value.strip() for value in values if value.strip()]
    if not 3 <= len(cleaned) <= 8:
        raise ValueError("keywords must contain 3–8 non-empty values")
    if len(cleaned) != len(set(value.casefold() for value in cleaned)):
        raise ValueError("keywords must be unique")
    return cleaned


class ImagePrompt(BaseModel):
    """Structured visual direction produced by Luna for GPT Image 2."""

    model_config = ConfigDict(extra="forbid")

    visual_type: Literal[
        "property-editorial",
        "neighborhood-editorial",
        "typographic-educational",
        "people-editorial",
    ]
    reference_policy: Literal[
        "indoor-flexible", "outdoor-exact", "headshot-exact", "group-exact"
    ] = "indoor-flexible"
    subject: str = Field(min_length=1, max_length=500)
    setting: str = Field(min_length=1, max_length=300)
    composition: str = Field(min_length=1, max_length=500)
    headline: str = Field(min_length=1, max_length=60)
    supporting_text: str | None = Field(default=None, max_length=100)
    must_include: list[str] = Field(default_factory=list, max_length=6)
    avoid: list[str] = Field(default_factory=list, max_length=8)
    business_fields: list[
        Literal["logo", "business_name", "phone", "city", "website"]
    ] = Field(default_factory=list, max_length=5)

    @field_validator(
        "subject", "setting", "composition", "headline", "supporting_text", mode="before"
    )
    @classmethod
    def strip_image_text(cls, value: object) -> object:
        return _normalized_text(value)

    @field_validator("business_fields")
    @classmethod
    def unique_business_fields(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("business_fields must be unique")
        return values

    def render(
        self,
        reference_images: list[object] | None = None,
        contact_info: ContactInfo | None = None,
    ) -> str:
        """Render the validated fields into the prompt sent to GPT Image 2."""

        supporting_text = self.supporting_text or "No supporting text"
        must_include = "; ".join(self.must_include) or "No additional elements"
        avoid = "; ".join(self.avoid) or "No additional exclusions"
        reference_lines: list[str] = []
        reference_roles: list[str] = []
        for index, image in enumerate(reference_images or [], start=1):
            key = str(getattr(image, "key", image))
            role = str(getattr(image, "role", "other"))
            description = str(getattr(image, "description", "")).strip()
            reference_roles.append(role)
            detail = f"; description={description}" if description else ""
            reference_lines.append(f"- Attachment {index}: key={key}; role={role}{detail}")
        references = "\n".join(reference_lines) or "- No reference images supplied"
        people_roles = {"headshot", "headshot-group"}
        people_constraint = (
            "Use the attached person or people as the identity source. Preserve every face and "
            "recognizable detail; do not replace, merge, or add people."
            if people_roles.intersection(reference_roles)
            else "Do not add people."
        )
        contact_values = {
            "business_name": contact_info.business_name if contact_info else None,
            "phone": contact_info.phone if contact_info else None,
            "city": contact_info.city if contact_info else None,
            "website": contact_info.website if contact_info else None,
        }
        requested_business_details = [
            f"- {field}: {contact_values[field]}"
            for field in self.business_fields
            if field != "logo" and contact_values.get(field)
        ]
        if "logo" in self.business_fields:
            requested_business_details.insert(
                0, "- logo: use the supplied role=logo attachment exactly; never redraw it"
            )
        business_details = (
            "\n".join(requested_business_details)
            or "- No business identity or contact details requested"
        )
        return f"""Create one polished vertical social-media image for a San Jose real-estate brand.

ART DIRECTION
- Premium editorial design inspired by an established local luxury-property advisor.
- Warm ivory, charcoal, muted bronze, and restrained navy palette.
- Generous negative space and a precise grid.
- Refined high-contrast serif headline paired with a clean sans-serif.
- Photorealistic architecture or neighborhood imagery with natural California light.
- Sophisticated and approachable, never flashy, generic, or stock-template-like.

CONTENT
- Visual type: {self.visual_type}
- Reference policy: {self.reference_policy}
- Subject: {self.subject}
- Setting: {self.setting}
- Composition: {self.composition}
- Render this exact headline once: {self.headline}
- Render this exact supporting text at most once: {supporting_text}
- Must include: {must_include}

VERIFIED BUSINESS DETAILS TO RENDER
{business_details}
- Render only the fields listed above, verbatim. Do not normalize, shorten, or invent values.

REFERENCE MATERIAL
- Supplied images, in exact attachment order:
{references}
- Treat each reference only according to its role. A headshot controls the Realtor's identity; a
  headshot-group controls the identities and relationship of the Realtor and clients; an indoor or
  outdoor reference controls the setting and architecture; the logo controls only the brand mark.
- When identity and setting references are both supplied, place the referenced person or group
  naturally into the referenced setting without changing their identity or the setting's
  recognizable details.
- Use only the references that support the requested subject. Preserve recognizable property,
  neighborhood, and identity details instead of replacing them with generic approximations.
- Integrate the source photography into one cohesive editorial design; do not make a contact sheet,
  before-and-after layout, or arbitrary collage.

CONSTRAINTS
- Portrait 2:3 composition with safe margins for cross-channel cropping.
- Do not add any text beyond the headline, supporting text, and verified business details above.
- Do not invent prices, statistics, awards, testimonials, contact details, names, or logos.
- If the reference policy is outdoor-exact, headshot-exact, or group-exact, use each matching
  role-labeled supplied reference as the exact source for its assigned role. Do not substitute a
  generic scene, person, camera angle, or architectural arrangement.
- {people_constraint}
- Keep all text crisp, correctly spelled, and comfortably legible on a phone.
- Avoid: {avoid}
"""


class SocialPostDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=4500)
    keywords: list[str] = Field(min_length=3, max_length=8)
    image_prompt: ImagePrompt
    reference_image_keys: list[str] = Field(default_factory=list, max_length=3)
    image_url: str | None = None
    due_at: datetime

    @field_validator("description", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return _normalized_text(value)

    @field_validator("keywords")
    @classmethod
    def clean_keywords(cls, values: list[str]) -> list[str]:
        return _normalized_keywords(values)

    @field_validator("due_at")
    @classmethod
    def require_aware_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("due_at must include a UTC offset")
        return value

    def buffer_text(self) -> str:
        return f"{self.description}\n\nKeywords: {', '.join(self.keywords)}"


class SocialPostContent(BaseModel):
    """Model-generated fields; scheduling is owned by the worker."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=4500)
    keywords: list[str] = Field(min_length=3, max_length=8)
    image_prompt: ImagePrompt
    reference_image_keys: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("description", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return _normalized_text(value)

    @field_validator("keywords")
    @classmethod
    def clean_keywords(cls, values: list[str]) -> list[str]:
        return _normalized_keywords(values)


class ChannelPerformanceInsight(BaseModel):
    """Evidence-based messaging guidance for one social network."""

    model_config = ConfigDict(extra="forbid")

    channel_service: str = Field(min_length=1, max_length=50)
    summary: str = Field(min_length=1, max_length=800)
    winning_patterns: list[str] = Field(default_factory=list, max_length=6)
    underperforming_patterns: list[str] = Field(default_factory=list, max_length=6)
    recommendations: list[str] = Field(default_factory=list, max_length=8)
    post_ids_considered: list[str] = Field(default_factory=list, max_length=30)


class PerformanceAnalysis(BaseModel):
    """Structured recommendations derived from recent Buffer post performance."""

    model_config = ConfigDict(extra="forbid")

    overview: str = Field(min_length=1, max_length=1200)
    data_quality: str = Field(min_length=1, max_length=800)
    confidence: Literal["low", "medium", "high"]
    cross_channel_patterns: list[str] = Field(default_factory=list, max_length=8)
    channel_insights: list[ChannelPerformanceInsight] = Field(default_factory=list, max_length=12)
    next_post_actions: list[str] = Field(default_factory=list, max_length=10)
    experiments: list[str] = Field(default_factory=list, max_length=6)
    avoid: list[str] = Field(default_factory=list, max_length=8)
