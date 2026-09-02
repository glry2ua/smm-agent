"""Buffer API response models and their defensive parsers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


class BufferAPIError(RuntimeError):
    """An actionable Buffer API or GraphQL error."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class BufferChannel:
    id: str
    name: str
    display_name: str
    service: str


@dataclass(frozen=True, slots=True)
class BufferMetric:
    type: str
    name: str
    value: float
    unit: str
    description: str


@dataclass(frozen=True, slots=True)
class BufferMetricsSummary:
    metrics: tuple[BufferMetric, ...]
    metrics_updated_at: str | None


@dataclass(frozen=True, slots=True)
class BufferPost:
    id: str
    text: str
    channel_id: str
    status: str
    created_at: str
    updated_at: str
    due_at: str | None
    sent_at: str | None
    external_link: str | None
    via: str
    tags: tuple[dict[str, Any], ...]
    assets: tuple[dict[str, Any], ...]
    metadata: dict[str, Any] | None
    metrics: tuple[BufferMetric, ...]
    metrics_updated_at: str | None


def _parse_metrics(raw_metrics: Any) -> tuple[BufferMetric, ...]:
    if raw_metrics is None:
        return ()
    if not isinstance(raw_metrics, list):
        raise BufferAPIError("Buffer did not return a post metrics list")
    parsed_metrics = []
    for metric in raw_metrics:
        if not isinstance(metric, Mapping) or not metric.get("type"):
            continue
        try:
            value = float(metric.get("value", 0))
        except (TypeError, ValueError) as exc:
            raise BufferAPIError("Buffer returned a non-numeric metric value") from exc
        parsed_metrics.append(
            BufferMetric(
                type=str(metric["type"]),
                name=str(metric.get("name") or metric["type"]),
                value=value,
                unit=str(metric.get("unit") or "count"),
                description=str(metric.get("description") or ""),
            )
        )
    return tuple(parsed_metrics)


def _parse_post_metadata(raw_metadata: Any) -> dict[str, Any] | None:
    """Keep only the service keys the board needs to rebuild edit input."""

    if not isinstance(raw_metadata, Mapping):
        return None
    key = {
        "InstagramPostMetadata": "instagram",
        "FacebookPostMetadata": "facebook",
    }.get(str(raw_metadata.get("__typename") or ""))
    if key is None:
        return None
    payload: dict[str, Any] = {"type": str(raw_metadata.get("type") or "")}
    if key == "instagram":
        payload["shouldShareToFeed"] = bool(raw_metadata.get("shouldShareToFeed", True))
    return {key: payload}


def _post_action_result(field: str, data: Mapping[str, Any]) -> dict[str, Any]:
    """Unwrap a PostActionPayload union or raise with the MutationError message."""

    action = data.get(field)
    if not isinstance(action, Mapping):
        raise BufferAPIError(f"Buffer response did not include a {field} result")
    post_data = action.get("post")
    if not isinstance(post_data, Mapping) or not post_data.get("id"):
        raise BufferAPIError(str(action.get("message", "Buffer did not return a post")))
    return dict(post_data)
