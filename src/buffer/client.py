"""Small async Buffer GraphQL client used after plan validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from schemas import SocialPostDraft

CREATE_POST_QUERY = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess {
      post {
        id
        text
        dueAt
        assets { id mimeType }
      }
    }
    ... on MutationError {
      message
    }
  }
}
"""

GET_CHANNELS_QUERY = """
query GetChannels($organizationId: OrganizationId!) {
  channels(input: {
    organizationId: $organizationId,
    filter: { isLocked: false }
  }) {
    id
    name
    displayName
    service
  }
}
"""

GET_AGGREGATED_POST_METRICS_QUERY = """
query GetAggregatedPostMetrics($input: AggregatedPostMetricsInput!) {
  aggregatedPostMetrics(input: $input) {
    metrics {
      type
      name
      value
      unit
      description
    }
    metricsUpdatedAt
  }
}
"""

GET_SENT_POSTS_QUERY = """
query GetSentPosts($input: PostsInput!, $first: Int!, $after: String) {
  posts(input: $input, first: $first, after: $after) {
    edges {
      node {
        id
        text
        channelId
        status
        createdAt
        updatedAt
        dueAt
        sentAt
        externalLink
        via
        tags { id name color }
        assets { id type mimeType source thumbnail }
        metrics {
          type
          name
          value
          unit
          description
        }
        metricsUpdatedAt
      }
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
"""


class BufferAPIError(RuntimeError):
    """An actionable Buffer API or GraphQL error."""

    def __init__(self, message: str, *, retryable: bool = False, status_code: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


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
    metrics: tuple[BufferMetric, ...]
    metrics_updated_at: str | None


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


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


def _channel_post_metadata(service: str) -> dict[str, Any] | None:
    """Return the per-network metadata Buffer requires for a scheduled post.

    Instagram and Facebook both require a non-null ``type`` (post, story, reel)
    via the channel-specific ``metadata`` field. LinkedIn and other networks do
    not require it, so ``None`` is returned and the field is omitted entirely.
    """

    normalized = service.casefold()
    if normalized == "instagram":
        return {"instagram": {"type": "post", "shouldShareToFeed": True}}
    if normalized == "facebook":
        return {"facebook": {"type": "post"}}
    return None


def build_create_post_input(
    post: SocialPostDraft,
    channel_id: str,
    service: str = "",
) -> dict[str, Any]:
    """Build the exact mutation input used by both dry-run and live execution."""

    input_payload: dict[str, Any] = {
        "text": post.buffer_text(),
        "channelId": channel_id,
        "schedulingType": "automatic",
        "mode": "customScheduled",
        "dueAt": _utc_iso(post.due_at),
        "assets": [{"image": {"url": post.image_url}}] if post.image_url else [],
        "needsApproval": False,
        "saveToDraft": True,
        "aiAssisted": True,
    }
    metadata = _channel_post_metadata(service)
    if metadata is not None:
        input_payload["metadata"] = metadata
    return input_payload


class BufferClient:
    def __init__(self, api_key: str, *, api_url: str = "https://api.buffer.com") -> None:
        if not api_key.strip():
            raise BufferAPIError("Buffer configuration is missing BUFFER_API_KEY")
        if not api_url.strip():
            raise BufferAPIError("Buffer configuration requires a non-empty BUFFER_API_URL")
        self.api_key = api_key
        self.api_url = api_url.rstrip("/")

    async def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    self.api_url,
                    headers=headers,
                    json={"query": query, "variables": variables},
                )
            except httpx.TimeoutException as exc:
                raise BufferAPIError("Buffer request timed out", retryable=True) from exc
            except httpx.TransportError as exc:
                raise BufferAPIError("Buffer transport error", retryable=True) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise BufferAPIError(
                "Buffer returned a non-JSON response",
                retryable=response.status_code >= 500,
                status_code=response.status_code,
            ) from exc
        if not isinstance(payload, Mapping):
            raise BufferAPIError("Buffer returned an invalid GraphQL response")

        if response.status_code == 429 or response.status_code >= 500:
            raise BufferAPIError(
                f"Buffer HTTP error ({response.status_code})",
                retryable=True,
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise BufferAPIError(
                f"Buffer HTTP error ({response.status_code})",
                status_code=response.status_code,
            )

        if payload.get("errors"):
            messages = "; ".join(
                str(error.get("message", "GraphQL error"))
                for error in payload["errors"]
                if isinstance(error, Mapping)
            )
            raise BufferAPIError(messages or "Buffer GraphQL error")

        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise BufferAPIError("Buffer response did not include GraphQL data")
        return dict(data)

    async def list_available_channels(self, organization_id: str) -> list[BufferChannel]:
        if not organization_id.strip():
            raise BufferAPIError("Buffer configuration is missing BUFFER_ORGANIZATION_ID")
        data = await self._graphql(
            GET_CHANNELS_QUERY,
            {"organizationId": organization_id},
        )
        channels = data.get("channels")
        if not isinstance(channels, list):
            raise BufferAPIError("Buffer did not return a channel list")
        return [
            BufferChannel(
                id=str(channel["id"]),
                name=str(channel.get("name") or ""),
                display_name=str(channel.get("displayName") or ""),
                service=str(channel.get("service") or ""),
            )
            for channel in channels
            if isinstance(channel, Mapping) and channel.get("id")
        ]

    async def get_aggregated_post_metrics(
        self,
        organization_id: str,
        *,
        start: datetime,
        end: datetime,
        channel_ids: list[str],
    ) -> BufferMetricsSummary:
        """Return aggregate post metrics for a bounded set of channels and dates."""

        if not organization_id.strip():
            raise BufferAPIError("Buffer configuration is missing BUFFER_ORGANIZATION_ID")
        data = await self._graphql(
            GET_AGGREGATED_POST_METRICS_QUERY,
            {
                "input": {
                    "organizationId": organization_id,
                    "startDateTime": _utc_iso(start),
                    "endDateTime": _utc_iso(end),
                    "channelIds": channel_ids,
                }
            },
        )
        aggregate = data.get("aggregatedPostMetrics")
        if not isinstance(aggregate, Mapping):
            raise BufferAPIError("Buffer did not return aggregated post metrics")
        updated_at = aggregate.get("metricsUpdatedAt")
        return BufferMetricsSummary(
            metrics=_parse_metrics(aggregate.get("metrics")),
            metrics_updated_at=str(updated_at) if updated_at else None,
        )

    async def list_sent_posts(
        self,
        organization_id: str,
        *,
        start: datetime,
        end: datetime,
        channel_ids: list[str],
        page_size: int = 50,
    ) -> list[BufferPost]:
        """Return all sent posts in a date window, following Buffer cursors."""

        posts: list[BufferPost] = []
        after: str | None = None
        while True:
            data = await self._graphql(
                GET_SENT_POSTS_QUERY,
                {
                    "input": {
                        "organizationId": organization_id,
                        "filter": {
                            "status": ["sent"],
                            "channelIds": channel_ids,
                            "startDate": _utc_iso(start),
                            "endDate": _utc_iso(end),
                        },
                        "sort": [
                            {"field": "dueAt", "direction": "desc"},
                            {"field": "createdAt", "direction": "desc"},
                        ],
                    },
                    "first": page_size,
                    "after": after,
                },
            )
            connection = data.get("posts")
            if not isinstance(connection, Mapping):
                raise BufferAPIError("Buffer did not return a posts connection")
            edges = connection.get("edges")
            page_info = connection.get("pageInfo")
            if not isinstance(edges, list) or not isinstance(page_info, Mapping):
                raise BufferAPIError("Buffer returned an invalid posts page")
            for edge in edges:
                node = edge.get("node") if isinstance(edge, Mapping) else None
                if not isinstance(node, Mapping) or not node.get("id"):
                    continue
                tags = node.get("tags") if isinstance(node.get("tags"), list) else []
                assets = node.get("assets") if isinstance(node.get("assets"), list) else []
                posts.append(
                    BufferPost(
                        id=str(node["id"]),
                        text=str(node.get("text") or ""),
                        channel_id=str(node.get("channelId") or ""),
                        status=str(node.get("status") or ""),
                        created_at=str(node.get("createdAt") or ""),
                        updated_at=str(node.get("updatedAt") or ""),
                        due_at=str(node["dueAt"]) if node.get("dueAt") else None,
                        sent_at=str(node["sentAt"]) if node.get("sentAt") else None,
                        external_link=(
                            str(node["externalLink"]) if node.get("externalLink") else None
                        ),
                        via=str(node.get("via") or ""),
                        tags=tuple(dict(tag) for tag in tags if isinstance(tag, Mapping)),
                        assets=tuple(dict(asset) for asset in assets if isinstance(asset, Mapping)),
                        metrics=_parse_metrics(node.get("metrics")),
                        metrics_updated_at=(
                            str(node["metricsUpdatedAt"]) if node.get("metricsUpdatedAt") else None
                        ),
                    )
                )
            if not page_info.get("hasNextPage"):
                break
            end_cursor = page_info.get("endCursor")
            if not end_cursor or end_cursor == after:
                raise BufferAPIError("Buffer returned an invalid posts pagination cursor")
            after = str(end_cursor)
        return posts

    async def create_scheduled_post(
        self,
        post: SocialPostDraft,
        channel_id: str,
        service: str = "",
    ) -> dict[str, Any]:
        data = await self._graphql(
            CREATE_POST_QUERY,
            {"input": build_create_post_input(post, channel_id, service)},
        )

        action = data.get("createPost")
        if not isinstance(action, Mapping):
            raise BufferAPIError("Buffer response did not include a createPost result")
        post_data = action.get("post")
        if not isinstance(post_data, Mapping) or not post_data.get("id"):
            raise BufferAPIError(str(action.get("message", "Buffer did not return a post ID")))
        return dict(post_data)
