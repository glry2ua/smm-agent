"""Compatibility patches for the OpenAI SDK's Responses API usage models.

The OpenAI ``openai>=2.50`` SDK declares ``cache_write_tokens`` and
``cached_tokens`` as required ``int`` fields on the Responses API usage
breakdown, but the live Responses API only returns ``cached_tokens``. That
mismatch raises a pydantic ``ValidationError`` while parsing the response,
which crashes every agent run and forces the deterministic reference-free
fallback. This module makes the token-detail fields optional with a default
of ``0`` so a missing field no longer fails validation. It is import-time
side-effect only and idempotent.
"""

from __future__ import annotations


def apply_openai_usage_patch() -> None:
    """Make Responses API token-detail fields optional on installed openai SDKs."""

    try:
        from openai.types.responses import response_usage as usage_module
    except Exception:
        return

    for model_name in ("InputTokensDetails", "OutputTokensDetails"):
        model = getattr(usage_module, model_name, None)
        if model is None:
            continue
        for field_name in ("cache_write_tokens", "cached_tokens", "reasoning_tokens"):
            field = model.model_fields.get(field_name)
            if field is None:
                continue
            if field.is_required():
                field.default = 0
                field.default_factory = None  # type: ignore[assignment]
                field.annotation = int | None  # type: ignore[assignment]


apply_openai_usage_patch()