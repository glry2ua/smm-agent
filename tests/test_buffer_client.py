from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

from buffer.client import BufferAPIError, BufferClient, build_create_post_input
from schemas import ImagePrompt, SocialPostDraft


def image_prompt() -> ImagePrompt:
    return ImagePrompt(
        visual_type="property-editorial",
        subject="A bright San Jose living room",
        setting="An elegant residential interior",
        composition="Full-bleed photo with a quiet ivory text panel",
        headline="MOVE WITH CLARITY",
    )


class BuildCreatePostInputTest(TestCase):
    def test_saves_a_prescheduled_draft_that_cannot_auto_publish(self) -> None:
        draft = SocialPostDraft(
            description="Post copy",
            keywords=["one", "two", "three"],
            image_prompt=image_prompt(),
            due_at=datetime(2026, 8, 19, 15, 30, tzinfo=UTC),
        )

        post_input = build_create_post_input(draft, "channel-1")

        self.assertFalse(post_input["needsApproval"])
        self.assertTrue(post_input["saveToDraft"])
        self.assertEqual(post_input["mode"], "customScheduled")
        self.assertEqual(post_input["dueAt"], "2026-08-19T15:30:00.000Z")
        self.assertEqual(post_input["assets"], [])

    def test_attaches_generated_image_as_current_buffer_asset_input(self) -> None:
        draft = SocialPostDraft(
            description="Post copy",
            keywords=["one", "two", "three"],
            image_prompt=image_prompt(),
            image_url="https://social.example/assets/generated_graphics/post.png",
            due_at=datetime(2026, 8, 19, 15, 30, tzinfo=UTC),
        )

        post_input = build_create_post_input(draft, "channel-1")

        self.assertEqual(
            post_input["assets"],
            [{"image": {"url": "https://social.example/assets/generated_graphics/post.png"}}],
        )

    def test_omits_metadata_for_linkedin_channels(self) -> None:
        draft = SocialPostDraft(
            description="Post copy",
            keywords=["one", "two", "three"],
            image_prompt=image_prompt(),
            due_at=datetime(2026, 8, 19, 15, 30, tzinfo=UTC),
        )

        post_input = build_create_post_input(draft, "channel-1", "linkedin")

        self.assertNotIn("metadata", post_input)

    def test_attaches_instagram_post_type_metadata(self) -> None:
        draft = SocialPostDraft(
            description="Post copy",
            keywords=["one", "two", "three"],
            image_prompt=image_prompt(),
            due_at=datetime(2026, 8, 19, 15, 30, tzinfo=UTC),
        )

        post_input = build_create_post_input(draft, "channel-1", "instagram")

        self.assertEqual(
            post_input["metadata"],
            {"instagram": {"type": "post", "shouldShareToFeed": True}},
        )

    def test_attaches_facebook_post_type_metadata(self) -> None:
        draft = SocialPostDraft(
            description="Post copy",
            keywords=["one", "two", "three"],
            image_prompt=image_prompt(),
            due_at=datetime(2026, 8, 19, 15, 30, tzinfo=UTC),
        )

        post_input = build_create_post_input(draft, "channel-1", "facebook")

        self.assertEqual(post_input["metadata"], {"facebook": {"type": "post"}})


class AggregatedPostMetricsTest(IsolatedAsyncioTestCase):
    async def test_queries_a_bounded_channel_window_and_parses_metrics(self) -> None:
        client = BufferClient("buffer-key")
        client._graphql = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "aggregatedPostMetrics": {
                    "metrics": [
                        {
                            "type": "postCount",
                            "name": "Posts",
                            "value": 12,
                            "unit": "count",
                            "description": "Number of sent posts",
                        },
                        {
                            "type": "engagementRate",
                            "name": "Engagement rate",
                            "value": 4.25,
                            "unit": "percentage",
                            "description": "Engagements divided by impressions",
                        },
                    ],
                    "metricsUpdatedAt": "2026-08-17T08:00:00Z",
                }
            }
        )

        summary = await client.get_aggregated_post_metrics(
            "organization-1",
            start=datetime(2026, 7, 18, 14, tzinfo=UTC),
            end=datetime(2026, 8, 17, 14, tzinfo=UTC),
            channel_ids=["channel-1"],
        )

        variables = client._graphql.await_args.args[1]  # type: ignore[attr-defined]
        self.assertEqual(
            variables,
            {
                "input": {
                    "organizationId": "organization-1",
                    "startDateTime": "2026-07-18T14:00:00.000Z",
                    "endDateTime": "2026-08-17T14:00:00.000Z",
                    "channelIds": ["channel-1"],
                }
            },
        )
        self.assertEqual(summary.metrics_updated_at, "2026-08-17T08:00:00Z")
        self.assertEqual(summary.metrics[0].type, "postCount")
        self.assertEqual(summary.metrics[1].value, 4.25)


class CreateScheduledPostTest(IsolatedAsyncioTestCase):
    async def test_sends_image_asset_and_returns_buffer_asset_response(self) -> None:
        client = BufferClient("buffer-key")
        client._graphql = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "createPost": {
                    "post": {
                        "id": "post-1",
                        "text": "Post copy",
                        "dueAt": "2026-08-19T15:30:00.000Z",
                        "assets": [{"id": "asset-1", "mimeType": "image/png"}],
                    }
                }
            }
        )
        draft = SocialPostDraft(
            description="Post copy",
            keywords=["one", "two", "three"],
            image_prompt=image_prompt(),
            image_url="https://social.example/assets/generated_graphics/post.png",
            due_at=datetime(2026, 8, 19, 15, 30, tzinfo=UTC),
        )

        result = await client.create_scheduled_post(draft, "channel-1", "instagram")

        variables = client._graphql.await_args.args[1]  # type: ignore[attr-defined]
        self.assertEqual(
            variables["input"]["assets"],
            [{"image": {"url": draft.image_url}}],
        )
        self.assertEqual(
            variables["input"]["metadata"],
            {"instagram": {"type": "post", "shouldShareToFeed": True}},
        )
        self.assertIn("assets", client._graphql.await_args.args[0])  # type: ignore[attr-defined]
        self.assertEqual(result["id"], "post-1")
        self.assertEqual(result["assets"][0]["id"], "asset-1")

    async def test_reports_union_mutation_error_without_fabricating_a_post(self) -> None:
        client = BufferClient("buffer-key")
        client._graphql = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "createPost": {
                    "message": "Buffer could not fetch the public image URL",
                }
            }
        )
        draft = SocialPostDraft(
            description="Post copy",
            keywords=["one", "two", "three"],
            image_prompt=image_prompt(),
            image_url="https://social.example/assets/generated_graphics/post.png",
            due_at=datetime(2026, 8, 19, 15, 30, tzinfo=UTC),
        )

        with self.assertRaisesRegex(BufferAPIError, "could not fetch"):
            await client.create_scheduled_post(draft, "channel-1")

    async def test_paginates_sent_posts_with_full_analyst_context(self) -> None:
        client = BufferClient("buffer-key")
        first_post = {
            "id": "post-1",
            "text": "A useful opening hook.\n\nA detailed post body.",
            "channelId": "channel-1",
            "status": "sent",
            "createdAt": "2026-08-10T12:00:00Z",
            "updatedAt": "2026-08-10T14:00:00Z",
            "dueAt": "2026-08-10T13:00:00Z",
            "sentAt": "2026-08-10T13:01:00Z",
            "externalLink": "https://social.example/post-1",
            "via": "api",
            "tags": [{"id": "tag-1", "name": "buyers", "color": "blue"}],
            "assets": [
                {
                    "id": "asset-1",
                    "type": "image",
                    "mimeType": "image/png",
                    "source": "https://social.example/image.png",
                    "thumbnail": "https://social.example/thumb.png",
                }
            ],
            "metrics": [
                {
                    "type": "reactions",
                    "name": "Reactions",
                    "value": 8,
                    "unit": "count",
                    "description": "Reactions received",
                }
            ],
            "metricsUpdatedAt": "2026-08-17T08:00:00Z",
        }
        client._graphql = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                {
                    "posts": {
                        "edges": [{"node": first_post}],
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                    }
                },
                {
                    "posts": {
                        "edges": [],
                        "pageInfo": {"hasNextPage": False, "endCursor": "cursor-1"},
                    }
                },
            ]
        )

        posts = await client.list_sent_posts(
            "organization-1",
            start=datetime(2026, 7, 18, 14, tzinfo=UTC),
            end=datetime(2026, 8, 17, 14, tzinfo=UTC),
            channel_ids=["channel-1"],
        )

        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].text, first_post["text"])
        self.assertEqual(posts[0].external_link, "https://social.example/post-1")
        self.assertEqual(posts[0].tags[0]["name"], "buyers")
        self.assertEqual(posts[0].assets[0]["mimeType"], "image/png")
        self.assertEqual(posts[0].metrics[0].value, 8)
        first_variables = client._graphql.await_args_list[0].args[1]  # type: ignore[attr-defined]
        second_variables = client._graphql.await_args_list[1].args[1]  # type: ignore[attr-defined]
        self.assertEqual(first_variables["after"], None)
        self.assertEqual(second_variables["after"], "cursor-1")
        self.assertEqual(first_variables["input"]["filter"]["status"], ["sent"])
        self.assertEqual(
            first_variables["input"]["filter"]["startDate"],
            "2026-07-18T14:00:00.000Z",
        )
