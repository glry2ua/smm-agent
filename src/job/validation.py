"""Deterministic pre-publish draft validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from schemas import SocialPostDraft
from settings import Settings


def validate_draft(post: SocialPostDraft, settings: Settings, now: datetime) -> None:
    """Apply deterministic checks before any external Buffer mutation."""

    # settings.validate_for_run guarantees these knobs are configured.
    assert settings.min_schedule_lead_minutes is not None
    assert settings.schedule_horizon_days is not None
    assert settings.max_post_chars is not None
    earliest = now + timedelta(minutes=settings.min_schedule_lead_minutes)
    latest = now + timedelta(days=settings.schedule_horizon_days)
    if len(post.buffer_text()) > settings.max_post_chars:
        raise ValueError(f"Post exceeds MAX_POST_CHARS ({settings.max_post_chars})")
    due_at = post.due_at.astimezone(UTC)
    if due_at < earliest or due_at > latest:
        raise ValueError("due_at must be inside the configured future scheduling window")
