"""D1-backed topic selection for the weekly three-post job."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _field(value: Any, name: str, default: Any = None) -> Any:
    if value is None:
        return default
    try:
        return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name)
    except Exception:
        return default


def _binding(env: Any, name: str) -> Any:
    return _field(env, name)


@dataclass(frozen=True, slots=True)
class Topic:
    id: int
    topic: str


class TopicRepository(Protocol):
    async def pick_random_available(self, limit: int = 1) -> list[Topic]: ...

    async def pick_available_topic(self, topic: str) -> Topic | None: ...

    async def mark_used(self, topic_id: int, used_at: datetime) -> None: ...


class TopicStore:
    def __init__(self, db: Any) -> None:
        self.db = db

    @classmethod
    def from_env(cls, env: Any) -> TopicStore:
        db = _binding(env, "DB")
        if db is None:
            raise RuntimeError("The DB binding is required to select weekly topics")
        return cls(db)

    async def pick_random_available(self, limit: int = 1) -> list[Topic]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        statement = self.db.prepare(
            "SELECT id, topic FROM keywords WHERE used_at IS NULL ORDER BY RANDOM() LIMIT ?"
        ).bind(limit)
        result = await _await(statement.all())
        rows = _field(result, "results", [])
        return [Topic(id=int(_field(row, "id")), topic=str(_field(row, "topic"))) for row in rows]

    async def pick_available_topic(self, topic: str) -> Topic | None:
        if not topic.strip():
            raise ValueError("topic must not be empty")
        statement = self.db.prepare(
            "SELECT id, topic FROM keywords WHERE used_at IS NULL AND topic = ? LIMIT 1"
        ).bind(topic)
        result = await _await(statement.all())
        rows = _field(result, "results", [])
        if not rows:
            return None
        row = rows[0]
        return Topic(id=int(_field(row, "id")), topic=str(_field(row, "topic")))

    async def mark_used(self, topic_id: int, used_at: datetime) -> None:
        statement = self.db.prepare(
            "UPDATE keywords SET used_at = ? WHERE id = ? AND used_at IS NULL"
        ).bind(used_at.isoformat(), topic_id)
        await _await(statement.run())
