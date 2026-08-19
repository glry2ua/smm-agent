from dataclasses import replace
from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from buffer.client import BufferChannel, BufferPost
from settings import Settings
from webui_api import load_board


def settings() -> Settings:
    return Settings(
        openai_api_key="openai-key",
        openai_image_model="gpt-image-2",
        openai_image_width=1088,
        openai_image_height=1360,
        openai_image_quality="medium",
        buffer_api_key="buffer-key",
        buffer_organization_id="organization-1",
        buffer_api_url="https://api.buffer.com",
        asset_public_base_url="https://smm-agent.example.com",
        min_schedule_lead_minutes=30,
        schedule_horizon_days=8,
        max_post_chars=5000,
        retry_max_attempts=3,
        retry_backoff_seconds=1.0,
    )


def buffer_post(
    *,
    post_id: str,
    status: str,
    due_at: str,
    channel_id: str = "channel-1",
) -> BufferPost:
    return BufferPost(
        id=post_id,
        text="A useful post body.",
        channel_id=channel_id,
        status=status,
        created_at="2026-08-17T12:00:00Z",
        updated_at="2026-08-17T13:00:00Z",
        due_at=due_at,
        sent_at=None,
        external_link=None,
        via="api",
        tags=(),
        assets=(
            {
                "id": f"asset-{post_id}",
                "type": "image",
                "mimeType": "image/png",
                "source": f"https://social.example/{post_id}.png",
                "thumbnail": f"https://social.example/{post_id}-thumb.png",
            },
        ),
        metrics=(),
        metrics_updated_at=None,
    )


def mock_client(
    *,
    channels: list[BufferChannel],
    posts: list[list[BufferPost]],
) -> AsyncMock:
    client = AsyncMock()
    client.list_available_channels.return_value = channels
    client.list_posts.side_effect = posts
    return client


class LoadBoardTest(IsolatedAsyncioTestCase):
    async def test_builds_drafts_and_accepted_from_buffer(self) -> None:
        channels = [
            BufferChannel("channel-1", "agent", "Agent", "linkedin"),
            BufferChannel("channel-2", "agentig", "Agent IG", "instagram"),
        ]
        client = mock_client(
            channels=channels,
            posts=[
                [
                    buffer_post(
                        post_id="draft-1",
                        status="draft",
                        due_at="2026-08-25T15:00:00Z",
                        channel_id="channel-1",
                    ),
                    buffer_post(
                        post_id="draft-2",
                        status="draft",
                        due_at="2026-08-27T15:00:00Z",
                        channel_id="channel-2",
                    ),
                ],
                [
                    buffer_post(
                        post_id="scheduled-1",
                        status="scheduled",
                        due_at="2026-08-24T15:00:00Z",
                    )
                ],
            ],
        )
        with patch("webui_api.BufferClient", return_value=client):
            board = await load_board(
                settings(),
                now=datetime(2026, 8, 18, 12, tzinfo=UTC),
            )

        self.assertEqual(board["fetched_at"], "2026-08-18T12:00:00Z")
        self.assertEqual(
            [channel["id"] for channel in board["channels"]],
            ["channel-1", "channel-2"],
        )
        self.assertEqual([post["id"] for post in board["drafts"]], ["draft-1", "draft-2"])
        self.assertEqual([post["id"] for post in board["accepted"]], ["scheduled-1"])

        first = client.list_posts.await_args_list[0]
        self.assertEqual(first.kwargs["statuses"], ["draft"])
        self.assertEqual(
            first.kwargs["channel_ids"],
            ["channel-1", "channel-2"],
        )
        self.assertEqual(
            first.kwargs["start"],
            datetime(2026, 7, 19, 12, tzinfo=UTC),
        )
        self.assertEqual(
            first.kwargs["end"],
            datetime(2026, 11, 16, 12, tzinfo=UTC),
        )
        second = client.list_posts.await_args_list[1]
        self.assertEqual(second.kwargs["statuses"], ["scheduled"])

        draft = board["drafts"][0]
        self.assertEqual(draft["text"], "A useful post body.")
        self.assertEqual(draft["channel_id"], "channel-1")
        self.assertEqual(draft["due_at"], "2026-08-25T15:00:00Z")
        self.assertEqual(
            draft["assets"][0]["thumbnail"],
            "https://social.example/draft-1-thumb.png",
        )

    async def test_returns_empty_board_when_no_channels(self) -> None:
        client = mock_client(channels=[], posts=[])
        with patch("webui_api.BufferClient", return_value=client):
            board = await load_board(
                settings(),
                now=datetime(2026, 8, 18, 12, tzinfo=UTC),
            )

        self.assertEqual(board["channels"], [])
        self.assertEqual(board["drafts"], [])
        self.assertEqual(board["accepted"], [])
        client.list_posts.assert_not_awaited()

    async def test_board_window_covers_recent_and_upcoming_posts(self) -> None:
        client = mock_client(
            channels=[BufferChannel("c1", "a", "A", "x")],
            posts=[[], []],
        )
        with patch("webui_api.BufferClient", return_value=client):
            await load_board(settings(), now=datetime(2026, 8, 18, 12, tzinfo=UTC))

        calls = client.list_posts.await_args_list
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertEqual(call.kwargs["start"], datetime(2026, 7, 19, 12, tzinfo=UTC))
            self.assertEqual(call.kwargs["end"], datetime(2026, 11, 16, 12, tzinfo=UTC))


class LoadBoardConfigTest(IsolatedAsyncioTestCase):
    async def test_requires_buffer_configuration(self) -> None:
        incomplete = replace(settings(), buffer_api_key="", buffer_organization_id="")
        with self.assertRaisesRegex(RuntimeError, "BUFFER_API_KEY"):
            await load_board(incomplete)

    async def test_normalizes_naive_now_to_utc(self) -> None:
        client = mock_client(
            channels=[BufferChannel("c1", "a", "A", "x")],
            posts=[[], []],
        )
        with patch("webui_api.BufferClient", return_value=client):
            await load_board(settings(), now=datetime(2026, 8, 18, 12))

        call = client.list_posts.await_args_list[0]
        self.assertEqual(call.kwargs["start"], datetime(2026, 7, 19, 12, tzinfo=UTC))
        self.assertEqual(call.kwargs["end"], datetime(2026, 11, 16, 12, tzinfo=UTC))
