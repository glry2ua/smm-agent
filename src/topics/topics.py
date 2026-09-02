"""D1-backed topic selection for the weekly three-post job."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _safe_get(value: Any, name: str, default: Any = None) -> Any:
    if value is None:
        return default
    try:
        return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name)
    except Exception:
        return default


def _row_changes(result: Any) -> int:
    return int(_safe_get(_safe_get(result, "meta"), "changes", 0) or 0)


def _parse_topic(row: Any) -> Topic:
    return Topic(
        id=int(_safe_get(row, "id")),
        topic=str(_safe_get(row, "topic")),
        used_at=_safe_get(row, "used_at"),
    )


@dataclass(frozen=True, slots=True)
class Topic:
    id: int
    topic: str
    used_at: str | None = None


class TopicRepository(Protocol):
    async def pick_random_available(self, limit: int = 1) -> list[Topic]: ...

    async def pick_available_topic(self, topic: str) -> Topic | None: ...

    async def mark_used(self, topic_id: int, used_at: datetime) -> None: ...


class TopicStore:
    def __init__(self, db: Any) -> None:
        self.db = db

    @classmethod
    def from_env(cls, env: Any) -> TopicStore:
        db = _safe_get(env, "DB")
        if db is None:
            raise RuntimeError("The DB binding is required to select weekly topics")
        return cls(db)

    async def pick_random_available(self, limit: int = 1) -> list[Topic]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        statement = self.db.prepare(
            "SELECT id, topic FROM topics WHERE used_at IS NULL ORDER BY RANDOM() LIMIT ?"
        ).bind(limit)
        result = await _maybe_await(statement.all())
        rows = _safe_get(result, "results", [])
        return [
            Topic(id=int(_safe_get(row, "id")), topic=str(_safe_get(row, "topic"))) for row in rows
        ]

    async def pick_available_topic(self, topic: str) -> Topic | None:
        if not topic.strip():
            raise ValueError("topic must not be empty")
        statement = self.db.prepare(
            "SELECT id, topic FROM topics WHERE used_at IS NULL AND topic = ? LIMIT 1"
        ).bind(topic)
        result = await _maybe_await(statement.all())
        rows = _safe_get(result, "results", [])
        if not rows:
            return None
        row = rows[0]
        return Topic(id=int(_safe_get(row, "id")), topic=str(_safe_get(row, "topic")))

    async def mark_used(self, topic_id: int, used_at: datetime) -> None:
        statement = self.db.prepare(
            "UPDATE topics SET used_at = ? WHERE id = ? AND used_at IS NULL"
        ).bind(used_at.isoformat(), topic_id)
        await _maybe_await(statement.run())

    async def list_topics(self) -> list[Topic]:
        """All topics: unused first (insertion order), most recently used first."""
        statement = self.db.prepare(
            "SELECT id, topic, used_at FROM topics ORDER BY used_at IS NOT NULL, used_at DESC, id"
        )
        result = await _maybe_await(statement.all())
        rows = _safe_get(result, "results", [])
        return [_parse_topic(row) for row in rows]

    async def add_topic(self, topic: str) -> Topic:
        """Insert a new topic, rejecting empty and duplicate topics."""
        cleaned = topic.strip()
        if not cleaned:
            raise ValueError("topic must not be empty")
        if len(cleaned) > 500:
            raise ValueError("topic must be at most 500 characters")

        duplicate = self.db.prepare(
            "SELECT id FROM topics WHERE topic = ? COLLATE NOCASE LIMIT 1"
        ).bind(cleaned)
        result = await _maybe_await(duplicate.all())
        if _safe_get(result, "results", []):
            raise ValueError("That topic already exists")

        insert = self.db.prepare("INSERT INTO topics (topic) VALUES (?)").bind(cleaned)
        await _maybe_await(insert.run())
        row = self.db.prepare(
            "SELECT id, topic, used_at FROM topics WHERE topic = ? ORDER BY id DESC LIMIT 1"
        ).bind(cleaned)
        result = await _maybe_await(row.all())
        inserted = _safe_get(result, "results", [])[0]
        return _parse_topic(inserted)

    async def mark_unused(self, topic_ids: list[int]) -> int:
        """Clear used_at for the given topics; return how many rows changed."""
        changed = 0
        for topic_id in topic_ids:
            statement = self.db.prepare(
                "UPDATE topics SET used_at = NULL WHERE id = ? AND used_at IS NOT NULL"
            ).bind(topic_id)
            result = await _maybe_await(statement.run())
            changed += _row_changes(result)
        return changed

    async def mark_all_unused(self) -> int:
        """Clear used_at for every used topic; return how many rows changed."""
        statement = self.db.prepare("UPDATE topics SET used_at = NULL WHERE used_at IS NOT NULL")
        result = await _maybe_await(statement.run())
        return _row_changes(result)

    async def delete_topic(self, topic_id: int) -> bool:
        """Delete a topic; return True when a row was removed."""
        statement = self.db.prepare("DELETE FROM topics WHERE id = ?").bind(topic_id)
        result = await _maybe_await(statement.run())
        return _row_changes(result) > 0
