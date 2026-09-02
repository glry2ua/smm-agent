"""Publish schedule constants and week-anchoring helpers."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from content.social_agent import normalize_now

PACIFIC = ZoneInfo("America/Los_Angeles")
PUBLISH_TIME = time(hour=8, minute=30)
PUBLISH_DAY_OFFSETS = (0, 2, 4)
CRON_TIME_UTC = time(hour=14)
MAX_POST_COUNT = len(PUBLISH_DAY_OFFSETS)


def _monday_anchor(local_now: datetime, *, force_non_monday: bool) -> datetime:
    """Return the Pacific midnight that opens the week this run is anchored to.

    By default the job must run on Monday; when ``force_non_monday`` is set
    (for local testing) the schedule snaps forward to the next Monday so the
    publish times stay inside the future scheduling window.
    """

    if local_now.weekday() == 0:
        return local_now
    if not force_non_monday:
        raise ValueError("The weekly job must run on Monday in the Pacific time zone")
    days_until_monday = (0 - local_now.weekday()) % 7 or 7
    return local_now + timedelta(days=days_until_monday)


def weekly_cron_time(now: datetime | None = None, *, force_non_monday: bool = False) -> datetime:
    """Return this Monday's configured cron instant for local CLI simulation."""

    local_now = normalize_now(now).astimezone(PACIFIC)
    monday = _monday_anchor(local_now, force_non_monday=force_non_monday)
    return datetime.combine(monday.date(), CRON_TIME_UTC, UTC)


def weekly_publish_times(now: datetime, *, force_non_monday: bool = False) -> list[datetime]:
    """Return Monday, Wednesday, and Friday at 08:30 Pacific, expressed in UTC."""

    local_now = normalize_now(now).astimezone(PACIFIC)
    monday = _monday_anchor(local_now, force_non_monday=force_non_monday)
    return [
        datetime.combine(monday.date() + timedelta(days=offset), PUBLISH_TIME, PACIFIC).astimezone(
            UTC
        )
        for offset in PUBLISH_DAY_OFFSETS
    ]
