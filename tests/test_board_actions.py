import base64
from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from board_actions import (
    ai_edit_post_image,
    decode_image_upload,
    delete_posts,
    replace_post_image,
    rewrite_post_text,
    schedule_posts,
    update_post_text,
)
from buffer.client import BufferAPIError, BufferClient
from settings import Settings


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


def edited(post_id: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": post_id,
        "text": "Revised copy",
        "status": "draft",
    }
    payload.update(overrides)
    return payload


def post_entry(post_id: str, **overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {"id": post_id, "service": "", "metadata": None}
    entry.update(overrides)
    return entry


class UpdatePostTextTest(IsolatedAsyncioTestCase):
    async def test_edits_every_post_in_the_group(self) -> None:
        client = AsyncMock()
        client.edit_post.side_effect = lambda post_id, **_: edited(post_id)

        with patch("board_actions.BufferClient", return_value=client):
            result = await update_post_text(
                settings(), [post_entry("a"), post_entry("b")], "Revised copy"
            )

        self.assertTrue(result["ok"])
        self.assertEqual([item["id"] for item in result["results"]], ["a", "b"])
        calls = client.edit_post.await_args_list
        self.assertEqual([call.args[0] for call in calls], ["a", "b"])
        self.assertEqual(calls[0].kwargs["text"], "Revised copy")

    async def test_sends_channel_metadata_for_instagram_posts(self) -> None:
        client = AsyncMock()
        client.edit_post.side_effect = lambda post_id, **_: edited(post_id)

        with patch("board_actions.BufferClient", return_value=client):
            await update_post_text(
                settings(),
                [
                    post_entry(
                        "a",
                        service="instagram",
                        metadata={"instagram": {"type": "story", "shouldShareToFeed": False}},
                    ),
                    post_entry("b", service="linkedin"),
                ],
                "Revised copy",
            )

        calls = client.edit_post.await_args_list
        self.assertEqual(
            calls[0].kwargs["metadata"],
            {"instagram": {"type": "story", "shouldShareToFeed": False}},
        )
        self.assertNotIn("metadata", calls[1].kwargs)

    async def test_raises_when_every_edit_fails(self) -> None:
        client = AsyncMock()
        client.edit_post.side_effect = BufferAPIError("Buffer HTTP error (401)")

        with patch("board_actions.BufferClient", return_value=client):
            with self.assertRaises(RuntimeError):
                await update_post_text(settings(), [post_entry("a")], "New text")


class SchedulePostsTest(IsolatedAsyncioTestCase):
    NOW = datetime(2026, 8, 31, 7, 0, tzinfo=UTC)  # Monday, before the 08:30 PT slot

    async def _schedule(
        self,
        *,
        due_at: str | None = None,
        text: str | None = None,
        now: datetime | None = None,
    ) -> tuple[AsyncMock, dict]:
        client = AsyncMock()
        client.edit_post.side_effect = lambda post_id, **_: edited(post_id, status="scheduled")
        with patch("board_actions.BufferClient", return_value=client):
            result = await schedule_posts(
                settings(), [post_entry("a")], due_at=due_at, text=text, now=now or self.NOW
            )
        return client, result

    async def test_schedules_by_turning_off_save_to_draft(self) -> None:
        client, result = await self._schedule(due_at="2026-09-04T15:30:00.000Z")

        self.assertTrue(result["ok"])
        self.assertFalse(result["rescheduled"])
        call = client.edit_post.await_args
        self.assertEqual(call.args[0], "a")
        self.assertEqual(call.kwargs["due_at"], datetime(2026, 9, 4, 15, 30, tzinfo=UTC))
        self.assertEqual(call.kwargs["mode"], "customScheduled")
        self.assertEqual(call.kwargs["scheduling_type"], "automatic")
        self.assertIs(call.kwargs["save_to_draft"], False)
        self.assertIsNone(call.kwargs["text"])

    async def test_past_due_at_reschedules_to_next_publish_slot(self) -> None:
        client, result = await self._schedule(due_at="2026-08-01T15:30:00.000Z")

        self.assertTrue(result["rescheduled"])
        self.assertEqual(result["scheduled_at"], "2026-08-31T15:30:00.000Z")
        call = client.edit_post.await_args
        self.assertEqual(call.kwargs["due_at"], datetime(2026, 8, 31, 15, 30, tzinfo=UTC))

    async def test_missing_due_at_uses_next_publish_slot(self) -> None:
        client, result = await self._schedule(due_at=None)

        self.assertTrue(result["rescheduled"])
        self.assertEqual(
            client.edit_post.await_args.kwargs["due_at"],
            datetime(2026, 8, 31, 15, 30, tzinfo=UTC),
        )

    async def test_too_close_to_slot_reschedules_forward(self) -> None:
        # Requested time is only 10 minutes out (lead requirement: 30 minutes).
        client, result = await self._schedule(
            due_at="2026-08-31T07:10:00+00:00",
            now=datetime(2026, 8, 31, 7, 0, tzinfo=UTC),
        )

        self.assertTrue(result["rescheduled"])
        self.assertEqual(
            client.edit_post.await_args.kwargs["due_at"],
            datetime(2026, 8, 31, 15, 30, tzinfo=UTC),
        )

    async def test_edited_text_rides_along_with_the_schedule_edit(self) -> None:
        client, _ = await self._schedule(due_at="2026-09-04T15:30:00.000Z", text="  Edited copy  ")

        call = client.edit_post.await_args
        self.assertEqual(call.kwargs["text"], "Edited copy")


class DeletePostsTest(IsolatedAsyncioTestCase):
    async def test_reports_each_deleted_id(self) -> None:
        client = AsyncMock()
        client.delete_post.side_effect = ["p1", "p2"]

        with patch("board_actions.BufferClient", return_value=client):
            result = await delete_posts(settings(), [post_entry("p1"), post_entry("p2")])

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["results"],
            [{"id": "p1", "ok": True}, {"id": "p2", "ok": True}],
        )


class ReplacePostImageTest(IsolatedAsyncioTestCase):
    async def test_stores_upload_and_sets_the_asset(self) -> None:
        client = AsyncMock()
        client.edit_post.side_effect = lambda post_id, **_: edited(post_id)
        store = AsyncMock()
        payload = {"data": "data:image/png;base64,aGVsbG8="}

        with patch("board_actions.BufferClient", return_value=client):
            result = await replace_post_image(settings(), store, [post_entry("a")], payload)

        self.assertTrue(result["ok"])
        key = store.put.await_args.args[0]
        self.assertTrue(key.startswith("generated_graphics/uploads/"))
        self.assertTrue(key.endswith(".png"))
        url = result["image_url"]
        self.assertEqual(url, f"https://smm-agent.example.com/assets/{key}")
        self.assertEqual(store.put.await_args.args[1], b"hello")
        client.edit_post.assert_awaited_once_with("a", assets=[{"image": {"url": url}}])

    async def test_rejects_unsupported_type_and_bad_base64(self) -> None:
        with self.assertRaises(ValueError):
            decode_image_upload({"data": "data:image/gif;base64,aGVsbG8="})
        with self.assertRaises(ValueError):
            decode_image_upload({"data": "not-base64!!"})


class AiEditPostImageTest(IsolatedAsyncioTestCase):
    async def test_edits_current_image_and_sets_the_result(self) -> None:
        client = AsyncMock()
        client.edit_post.side_effect = lambda post_id, **_: edited(post_id)
        store = AsyncMock()

        encoded = base64.b64encode(b"edited-image").decode()
        stub = AsyncMock()
        stub.images.edit.return_value = type(
            "ImagesResponse", (), {"data": [type("Data", (), {"b64_json": encoded})()]}
        )()

        with (
            patch("board_actions.BufferClient", return_value=client),
            patch("board_actions._fetch_image_bytes", return_value=(b"current", "image/png")),
            patch("openai.AsyncOpenAI", return_value=stub),
        ):
            result = await ai_edit_post_image(
                settings(),
                store,
                [post_entry("a", service="instagram", metadata={"instagram": {"type": "post"}})],
                {"url": "https://assets.example/current.png", "instruction": "make it sunset"},
            )

        self.assertTrue(result["ok"])
        key = store.put.await_args.args[0]
        self.assertTrue(key.startswith("generated_graphics/uploads/"))
        self.assertTrue(key.endswith(".png"))
        self.assertEqual(store.put.await_args.args[1], b"edited-image")
        url = result["image_url"]
        self.assertEqual(url, f"https://smm-agent.example.com/assets/{key}")
        call = client.edit_post.await_args
        self.assertEqual(call.args[0], "a")
        self.assertEqual(call.kwargs["assets"], [{"image": {"url": url}}])
        self.assertEqual(
            call.kwargs["metadata"],
            {"instagram": {"type": "post", "shouldShareToFeed": True}},
        )
        edit_kwargs = stub.images.edit.await_args.kwargs
        self.assertEqual(edit_kwargs["prompt"], "make it sunset")
        self.assertEqual(edit_kwargs["image"], [("current.png", b"current", "image/png")])

    async def test_requires_instruction_and_valid_url(self) -> None:
        with self.assertRaises(ValueError):
            await ai_edit_post_image(
                settings(), AsyncMock(), [post_entry("a")], {"url": "https://x/y.png"}
            )
        with self.assertRaises(ValueError):
            await ai_edit_post_image(
                settings(),
                AsyncMock(),
                [post_entry("a")],
                {"instruction": "sunset", "url": "file:///etc/passwd"},
            )


class RewritePostTextTest(IsolatedAsyncioTestCase):
    async def test_returns_the_model_text(self) -> None:
        stub = AsyncMock()
        stub.responses.create.return_value = type(
            "Response", (), {"output_text": "  Revised copy  "}
        )()

        result = await rewrite_post_text(
            settings(), "Old copy", "Make it tighter", openai_client=stub
        )

        self.assertEqual(result, "Revised copy")
        kwargs = stub.responses.create.await_args.kwargs
        self.assertEqual(kwargs["reasoning"], {"effort": "low"})
        self.assertEqual(kwargs["input"][0]["role"], "system")
        self.assertIn("<INSTRUCTION>", kwargs["input"][1]["content"])
        self.assertIn("<POST_TEXT>", kwargs["input"][1]["content"])

    async def test_requires_an_instruction(self) -> None:
        with self.assertRaises(ValueError):
            await rewrite_post_text(settings(), "Old copy", "   ")


class ClientMutationParsingTest(IsolatedAsyncioTestCase):
    async def test_edit_post_returns_updated_post(self) -> None:
        client = BufferClient("key")
        client._graphql = AsyncMock(  # type: ignore[method-assign]
            return_value={"editPost": {"post": {"id": "p1", "text": "New"}}}
        )

        post = await client.edit_post("p1", text="New", save_to_draft=False)

        self.assertEqual(post["id"], "p1")
        variables = client._graphql.await_args.args[1]
        self.assertEqual(
            variables["input"],
            {"id": "p1", "text": "New", "saveToDraft": False},
        )

    async def test_edit_post_surfaces_mutation_errors(self) -> None:
        client = BufferClient("key")
        client._graphql = AsyncMock(  # type: ignore[method-assign]
            return_value={"editPost": {"message": "Post not found"}}
        )

        with self.assertRaises(BufferAPIError):
            await client.edit_post("p1", text="New")

    async def test_delete_post_returns_deleted_id(self) -> None:
        client = BufferClient("key")
        client._graphql = AsyncMock(  # type: ignore[method-assign]
            return_value={"deletePost": {"id": "p1"}}
        )

        self.assertEqual(await client.delete_post("p1"), "p1")
