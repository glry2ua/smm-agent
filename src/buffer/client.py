"""Small async Buffer GraphQL client used after plan validation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx

from buffer.models import (  # noqa: F401 -- re-exported so `from buffer.client import X` keeps working
    BufferAPIError,
    BufferChannel,
    BufferMetric,
    BufferMetricsSummary,
    BufferPost,
    _parse_metrics,
    _parse_post_metadata,
    _post_action_result,
)
from buffer.queries import (
    CREATE_POST_QUERY,
    DELETE_POST_QUERY,
    EDIT_POST_QUERY,
    GET_AGGREGATED_POST_METRICS_QUERY,
    GET_BOARD_QUERY,
    GET_CHANNELS_QUERY,
    GET_POSTS_QUERY,
)
from schemas import SocialPostDraft


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def channel_post_metadata(
    service: str,
    *,
    existing: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return the per-network metadata Buffer requires for a scheduled post.

    Instagram and Facebook both require a non-null ``type`` (post, story, reel)
    via the channel-specific ``metadata`` field — and Buffer re-validates it on
    *every* mutation, including edits, so it must always be sent. The post's
    existing metadata (from the board) takes precedence so a story or reel is
    never silently downgraded to a post. LinkedIn and other networks do not
    require it, so ``None`` is returned and the field is omitted entirely.
    """

    normalized = service.casefold() if service else ""
    existing = existing or {}
    if normalized == "instagram":
        current = existing.get("instagram") or {}
        return {
            "instagram": {
                "type": str(current.get("type") or "post"),
                "shouldShareToFeed": bool(current.get("shouldShareToFeed", True)),
            }
        }
    if normalized == "facebook":
        current = existing.get("facebook") or {}
        return {"facebook": {"type": str(current.get("type") or "post")}}
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
    metadata = channel_post_metadata(service)
    if metadata is not None:
        input_payload["metadata"] = metadata
    return input_payload


def _parse_channels(data: Mapping[str, Any]) -> list[BufferChannel]:
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


def _parse_posts_page(data: Mapping[str, Any]) -> tuple[list[BufferPost], Mapping[str, Any]]:
    connection = data.get("posts")
    if not isinstance(connection, Mapping):
        raise BufferAPIError("Buffer did not return a posts connection")
    edges = connection.get("edges")
    page_info = connection.get("pageInfo")
    if not isinstance(edges, list) or not isinstance(page_info, Mapping):
        raise BufferAPIError("Buffer returned an invalid posts page")
    posts = [
        _parse_post_node(edge["node"])
        for edge in edges
        if isinstance(edge, Mapping)
        and isinstance(edge.get("node"), Mapping)
        and edge["node"].get("id")
    ]
    return posts, page_info


def _next_cursor(page_info: Mapping[str, Any], after: str | None) -> str | None:
    """Return the cursor for the next page, or ``None`` when this is the last."""
    if not page_info.get("hasNextPage"):
        return None
    end_cursor = page_info.get("endCursor")
    if not end_cursor or end_cursor == after:
        raise BufferAPIError("Buffer returned an invalid posts pagination cursor")
    return str(end_cursor)


def _parse_post_node(node: Mapping[str, Any]) -> BufferPost:
    raw_tags = node.get("tags")
    raw_assets = node.get("assets")
    tags = list(raw_tags) if isinstance(raw_tags, list) else []
    assets = list(raw_assets) if isinstance(raw_assets, list) else []
    return BufferPost(
        id=str(node["id"]),
        text=str(node.get("text") or ""),
        channel_id=str(node.get("channelId") or ""),
        status=str(node.get("status") or ""),
        created_at=str(node.get("createdAt") or ""),
        updated_at=str(node.get("updatedAt") or ""),
        due_at=str(node["dueAt"]) if node.get("dueAt") else None,
        sent_at=str(node["sentAt"]) if node.get("sentAt") else None,
        external_link=(str(node["externalLink"]) if node.get("externalLink") else None),
        via=str(node.get("via") or ""),
        tags=tuple(dict(tag) for tag in tags if isinstance(tag, Mapping)),
        assets=tuple(dict(asset) for asset in assets if isinstance(asset, Mapping)),
        metadata=_parse_post_metadata(node.get("metadata")),
        metrics=_parse_metrics(node.get("metrics")),
        metrics_updated_at=(
            str(node["metricsUpdatedAt"]) if node.get("metricsUpdatedAt") else None
        ),
    )


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
            retry_after: float | None = None
            raw_retry_after = response.headers.get("Retry-After")
            if raw_retry_after:
                try:
                    retry_after = float(raw_retry_after)
                except ValueError:
                    retry_after = None
            raise BufferAPIError(
                f"Buffer HTTP error ({response.status_code})",
                retryable=True,
                status_code=response.status_code,
                retry_after=retry_after,
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
        return _parse_channels(data)

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

    async def list_posts(
        self,
        organization_id: str,
        *,
        start: datetime,
        end: datetime,
        channel_ids: list[str],
        statuses: list[str] | None = None,
        page_size: int = 50,
    ) -> list[BufferPost]:
        """Return all posts in a date window, following Buffer cursors.

        ``statuses`` restricts the query to a set of Buffer post statuses such
        as ``sent``, ``scheduled``, or ``draft``. When ``None``, posts of every
        status are returned.
        """
        post_filter: dict[str, Any] = {
            "channelIds": channel_ids,
            "startDate": _utc_iso(start),
            "endDate": _utc_iso(end),
        }
        if statuses is not None:
            post_filter["status"] = statuses

        posts: list[BufferPost] = []
        after: str | None = None
        while True:
            data = await self._graphql(
                GET_POSTS_QUERY,
                {
                    "input": {
                        "organizationId": organization_id,
                        "filter": post_filter,
                        "sort": [
                            {"field": "dueAt", "direction": "desc"},
                            {"field": "createdAt", "direction": "desc"},
                        ],
                    },
                    "first": page_size,
                    "after": after,
                },
            )
            page, page_info = _parse_posts_page(data)
            posts.extend(page)
            after = _next_cursor(page_info, after)
            if after is None:
                return posts

    async def get_board_snapshot(
        self,
        organization_id: str,
        *,
        start: datetime,
        end: datetime,
        statuses: list[str],
        page_size: int = 50,
    ) -> tuple[list[BufferChannel], list[BufferPost]]:
        """Channels plus every post of the given statuses in one HTTP request.

        The whole board is a single GraphQL document: ``channels`` and the
        paginated ``posts`` connection as sibling root fields. The posts
        filter cannot reference the channels result inside the same document,
        so it selects by status and date across the organization — callers
        restrict posts to the returned channels client-side (equivalent to
        the old per-channel filter, which only queried unlocked channels).
        Follow-up pages re-send the same document and only read ``posts``.
        """
        if not organization_id.strip():
            raise BufferAPIError("Buffer configuration is missing BUFFER_ORGANIZATION_ID")
        variables: dict[str, Any] = {
            "organizationId": organization_id,
            "input": {
                "organizationId": organization_id,
                "filter": {
                    "startDate": _utc_iso(start),
                    "endDate": _utc_iso(end),
                    "status": list(statuses),
                },
                "sort": [
                    {"field": "dueAt", "direction": "desc"},
                    {"field": "createdAt", "direction": "desc"},
                ],
            },
            "first": page_size,
        }
        channels: list[BufferChannel] | None = None
        posts: list[BufferPost] = []
        after: str | None = None
        while True:
            data = await self._graphql(GET_BOARD_QUERY, {**variables, "after": after})
            if channels is None:
                channels = _parse_channels(data)
            page, page_info = _parse_posts_page(data)
            posts.extend(page)
            after = _next_cursor(page_info, after)
            if after is None:
                assert channels is not None  # set on the first iteration
                return channels, posts

    async def list_sent_posts(
        self,
        organization_id: str,
        *,
        start: datetime,
        end: datetime,
        channel_ids: list[str],
        page_size: int = 50,
    ) -> list[BufferPost]:
        """Return all sent posts in a date window (see :meth:`list_posts`)."""

        return await self.list_posts(
            organization_id,
            start=start,
            end=end,
            channel_ids=channel_ids,
            statuses=["sent"],
            page_size=page_size,
        )

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
        return _post_action_result("createPost", data)

    async def edit_post(
        self,
        post_id: str,
        *,
        text: str | None = None,
        assets: list[dict[str, Any]] | None = None,
        due_at: str | datetime | None = None,
        mode: str | None = None,
        scheduling_type: str | None = None,
        save_to_draft: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Edit an existing post; omitted fields are preserved by Buffer.

        ``due_at`` accepts a datetime or an ISO-8601 string. ``assets`` replaces
        the ordered asset list (``None`` keeps the current list, ``[]`` clears it).
        ``metadata`` should be provided for Instagram/Facebook posts — Buffer
        re-validates the channel type on every edit.
        """

        input_payload: dict[str, Any] = {"id": post_id}
        if text is not None:
            input_payload["text"] = text
        if assets is not None:
            input_payload["assets"] = assets
        if isinstance(due_at, datetime):
            input_payload["dueAt"] = _utc_iso(due_at)
        elif due_at is not None:
            input_payload["dueAt"] = due_at
        if mode is not None:
            input_payload["mode"] = mode
        if scheduling_type is not None:
            input_payload["schedulingType"] = scheduling_type
        if save_to_draft is not None:
            input_payload["saveToDraft"] = save_to_draft
        if metadata is not None:
            input_payload["metadata"] = metadata
        data = await self._graphql(EDIT_POST_QUERY, {"input": input_payload})
        return _post_action_result("editPost", data)

    async def delete_post(self, post_id: str) -> str:
        """Delete a post and return the deleted post ID."""

        data = await self._graphql(DELETE_POST_QUERY, {"input": {"id": post_id}})
        action = data.get("deletePost")
        if not isinstance(action, Mapping):
            raise BufferAPIError("Buffer response did not include a deletePost result")
        deleted_id = action.get("id")
        if not deleted_id:
            raise BufferAPIError(str(action.get("message", "Buffer did not confirm the delete")))
        return str(deleted_id)
