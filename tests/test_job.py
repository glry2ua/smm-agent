from datetime import UTC, datetime
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from brand.brand_context import ContactInfo, ReferenceAsset
from buffer.client import BufferAPIError, BufferChannel
from images.image_pipeline import GeneratedImage, ReferenceImage
from job import (
    _generate_and_save,
    _generate_valid_draft,
    _list_channels_with_retries,
    _load_reference_images,
    _prepare_performance_analysis,
    run_weekly_job,
    validate_reference_policy,
    weekly_cron_time,
    weekly_publish_times,
)
from schemas import ImagePrompt, PerformanceAnalysis, SocialPostDraft
from settings import Settings
from topics.topics import Topic


class WeeklyPublishTimesTest(TestCase):
    def test_converts_summer_pacific_time_to_utc(self) -> None:
        times = weekly_publish_times(datetime(2026, 8, 17, 14, tzinfo=UTC))

        self.assertEqual(
            [value.isoformat() for value in times],
            [
                "2026-08-17T15:30:00+00:00",
                "2026-08-19T15:30:00+00:00",
                "2026-08-21T15:30:00+00:00",
            ],
        )

    def test_converts_winter_pacific_time_to_utc(self) -> None:
        times = weekly_publish_times(datetime(2026, 1, 5, 14, tzinfo=UTC))

        self.assertEqual(
            [value.isoformat() for value in times],
            [
                "2026-01-05T16:30:00+00:00",
                "2026-01-07T16:30:00+00:00",
                "2026-01-09T16:30:00+00:00",
            ],
        )


class WeeklyCronTimeTest(TestCase):
    def test_uses_configured_utc_cron_time_in_summer(self) -> None:
        cron_time = weekly_cron_time(datetime(2026, 8, 18, 1, tzinfo=UTC))

        self.assertEqual(cron_time.isoformat(), "2026-08-17T14:00:00+00:00")

    def test_uses_configured_utc_cron_time_in_winter(self) -> None:
        cron_time = weekly_cron_time(datetime(2026, 1, 5, 20, tzinfo=UTC))

        self.assertEqual(cron_time.isoformat(), "2026-01-05T14:00:00+00:00")

    def test_rejects_non_monday_local_runs(self) -> None:
        with self.assertRaisesRegex(ValueError, "must run on Monday"):
            weekly_cron_time(datetime(2026, 8, 18, 14, tzinfo=UTC))


class PostCountValidationTest(IsolatedAsyncioTestCase):
    async def test_rejects_post_count_outside_one_to_three(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 1 and 3"):
            await run_weekly_job({}, dry_run=True, post_count=4)


class PostCountRunTest(IsolatedAsyncioTestCase):
    async def test_generates_only_the_requested_number_of_posts(self) -> None:
        class FakeTopicStore:
            def __init__(self) -> None:
                self.limits: list[int] = []

            async def pick_random_available(self, limit: int = 1) -> list[Topic]:
                self.limits.append(limit)
                return [Topic(id=1, topic="One focused topic")]

            async def mark_used(self, topic_id: int, used_at: datetime) -> None:
                del topic_id, used_at

        async def generate_draft(
            settings: Settings,
            topic: str,
            due_at: datetime,
            reference_image_keys: list[str],
            analysis: PerformanceAnalysis | None,
        ) -> SocialPostDraft:
            del settings, topic, reference_image_keys, analysis
            return SocialPostDraft(
                description="One post",
                keywords=["one", "two", "three"],
                image_prompt=image_prompt(),
                due_at=due_at,
            )

        env = {
            "OPENAI_API_KEY": "openai-key",
            "OPENAI_IMAGE_MODEL": "gpt-image-2",
            "OPENAI_IMAGE_WIDTH": "1088",
            "OPENAI_IMAGE_HEIGHT": "1360",
            "OPENAI_IMAGE_QUALITY": "medium",
            "BUFFER_API_KEY": "buffer-key",
            "BUFFER_ORGANIZATION_ID": "organization-id",
            "BUFFER_API_URL": "https://api.buffer.com",
            "MIN_SCHEDULE_LEAD_MINUTES": "30",
            "SCHEDULE_HORIZON_DAYS": "8",
            "MAX_POST_CHARS": "5000",
            "RETRY_MAX_ATTEMPTS": "3",
            "RETRY_BACKOFF_SECONDS": "1",
        }
        channel = BufferChannel(
            id="channel-1",
            name="channel",
            display_name="Channel",
            service="linkedin",
        )
        store = FakeTopicStore()

        with (
            patch("job.generate_social_post", new=AsyncMock(side_effect=generate_draft)) as draft,
            patch(
                "job._prepare_performance_analysis",
                new=AsyncMock(return_value=(None, None, "not_run", None)),
            ),
            patch(
                "job.generate_and_save_image",
                new=AsyncMock(
                    return_value=GeneratedImage(
                        key="generated_graphics/topic-1.png",
                        url=None,
                        model="gpt-image-2",
                        size="1024x1536",
                        quality="medium",
                        local_path_absolute="/tmp/topic-1.png",
                        local_path_relative="topic-1.png",
                    )
                ),
            ),
            patch("job.BufferClient") as client_class,
        ):
            client = client_class.return_value
            client.list_available_channels = AsyncMock(return_value=[channel])

            result = await run_weekly_job(
                env,
                dry_run=True,
                post_count=1,
                topic_store=store,
                local_image_dir=Path("/tmp"),
                now=datetime(2026, 8, 17, 14, tzinfo=UTC),
            )

        self.assertEqual(store.limits, [1])
        self.assertEqual(draft.await_count, 1)
        self.assertEqual(result["post_count"], 1)
        self.assertEqual(result["draft_count"], 1)
        self.assertEqual(result["images_generated"], 1)
        self.assertEqual(len(result["buffer_inputs"]), 1)

    async def test_uses_a_preselected_unused_topic_for_a_single_post(self) -> None:
        selected = "Who is a San Jose Realtor experienced with move-up buyers?"

        class FakeTopicStore:
            async def pick_random_available(self, limit: int = 1) -> list[Topic]:
                raise AssertionError(f"random selection should not run: {limit}")

            async def pick_available_topic(self, topic: str) -> Topic | None:
                return Topic(id=76, topic=topic) if topic == selected else None

            async def mark_used(self, topic_id: int, used_at: datetime) -> None:
                del topic_id, used_at

        async def generate_draft(
            settings: Settings,
            topic: str,
            due_at: datetime,
            reference_image_keys: list[str],
            analysis: PerformanceAnalysis | None,
        ) -> SocialPostDraft:
            del settings, reference_image_keys, analysis
            return SocialPostDraft(
                description=f"Post about {topic}",
                keywords=["one", "two", "three"],
                image_prompt=image_prompt(),
                due_at=due_at,
            )

        env = {
            "OPENAI_API_KEY": "openai-key",
            "OPENAI_IMAGE_MODEL": "gpt-image-2",
            "OPENAI_IMAGE_WIDTH": "1088",
            "OPENAI_IMAGE_HEIGHT": "1360",
            "OPENAI_IMAGE_QUALITY": "medium",
            "BUFFER_API_KEY": "buffer-key",
            "BUFFER_ORGANIZATION_ID": "organization-id",
            "BUFFER_API_URL": "https://api.buffer.com",
            "MIN_SCHEDULE_LEAD_MINUTES": "30",
            "SCHEDULE_HORIZON_DAYS": "8",
            "MAX_POST_CHARS": "5000",
            "RETRY_MAX_ATTEMPTS": "3",
            "RETRY_BACKOFF_SECONDS": "1",
        }
        channel = BufferChannel("channel-1", "channel", "Channel", "linkedin")

        with (
            patch("job.generate_social_post", new=AsyncMock(side_effect=generate_draft)),
            patch(
                "job._prepare_performance_analysis",
                new=AsyncMock(return_value=(None, None, "not_run", None)),
            ),
            patch("job.BufferClient") as client_class,
        ):
            client_class.return_value.list_available_channels = AsyncMock(return_value=[channel])
            result = await run_weekly_job(
                env,
                dry_run=True,
                post_count=1,
                selected_topic=selected,
                topic_store=FakeTopicStore(),
                now=datetime(2026, 8, 17, 14, tzinfo=UTC),
            )

        self.assertEqual(result["topics"], [{"id": 76, "topic": selected}])
        self.assertEqual(result["draft_count"], 1)


class SettingsTest(TestCase):
    def test_builds_image_size_from_separate_dimensions(self) -> None:
        settings = Settings.from_env(
            {
                "OPENAI_IMAGE_WIDTH": "1088",
                "OPENAI_IMAGE_HEIGHT": "1360",
            }
        )

        self.assertEqual(settings.openai_image_width, 1088)
        self.assertEqual(settings.openai_image_height, 1360)
        self.assertEqual(settings.openai_image_size, "1088x1360")

    def test_rejects_gpt_image_2_edges_that_are_not_multiples_of_16(self) -> None:
        settings = Settings.from_env(
            {
                "OPENAI_API_KEY": "openai-key",
                "OPENAI_IMAGE_MODEL": "gpt-image-2",
                "OPENAI_IMAGE_WIDTH": "1080",
                "OPENAI_IMAGE_HEIGHT": "1350",
                "OPENAI_IMAGE_QUALITY": "medium",
                "BUFFER_API_KEY": "buffer-key",
                "BUFFER_ORGANIZATION_ID": "org-id",
                "BUFFER_API_URL": "https://api.buffer.com",
                "MIN_SCHEDULE_LEAD_MINUTES": "30",
                "SCHEDULE_HORIZON_DAYS": "8",
                "MAX_POST_CHARS": "5000",
                "RETRY_MAX_ATTEMPTS": "3",
                "RETRY_BACKOFF_SECONDS": "1",
            }
        )

        with self.assertRaisesRegex(RuntimeError, "multiples of 16"):
            settings.validate_for_run()

    def test_reports_all_missing_required_environment_variables(self) -> None:
        settings = Settings.from_env({})

        with self.assertRaisesRegex(
            RuntimeError,
            "OPENAI_API_KEY.*OPENAI_IMAGE_MODEL.*OPENAI_IMAGE_WIDTH.*"
            "BUFFER_API_KEY.*BUFFER_ORGANIZATION_ID.*BUFFER_API_URL",
        ):
            settings.validate_for_run()

    def test_buffer_validation_does_not_require_openai_configuration(self) -> None:
        settings = Settings.from_env(
            {
                "BUFFER_API_KEY": "buffer-key",
                "BUFFER_ORGANIZATION_ID": "org-id",
                "BUFFER_API_URL": "https://api.buffer.com",
                "OPENAI_IMAGE_MODEL": "gpt-image-2",
            }
        )

        settings.validate_for_buffer()

    def test_buffer_analysis_requires_luna_configuration(self) -> None:
        settings = Settings.from_env(
            {
                "BUFFER_API_KEY": "buffer-key",
                "BUFFER_ORGANIZATION_ID": "org-id",
                "BUFFER_API_URL": "https://api.buffer.com",
            }
        )

        with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
            settings.validate_for_buffer_analysis()

        configured = Settings.from_env(
            {
                "BUFFER_API_KEY": "buffer-key",
                "BUFFER_ORGANIZATION_ID": "org-id",
                "BUFFER_API_URL": "https://api.buffer.com",
                "OPENAI_API_KEY": "openai-key",
            }
        )
        configured.validate_for_buffer_analysis()

    def test_rejects_invalid_numeric_configuration_instead_of_using_a_fallback(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "RETRY_MAX_ATTEMPTS must be an integer"):
            Settings.from_env({"RETRY_MAX_ATTEMPTS": "not-a-number"})

    def test_rejects_an_asset_url_that_would_not_match_the_worker_route(self) -> None:
        settings = Settings.from_env(
            {
                "OPENAI_API_KEY": "openai-key",
                "OPENAI_IMAGE_MODEL": "gpt-image-2",
                "OPENAI_IMAGE_WIDTH": "1088",
                "OPENAI_IMAGE_HEIGHT": "1360",
                "OPENAI_IMAGE_QUALITY": "medium",
                "ASSET_PUBLIC_BASE_URL": "https://social.example/assets",
            }
        )

        with self.assertRaisesRegex(RuntimeError, "without a path"):
            settings.validate_for_images()

    def test_missing_configuration_errors_do_not_include_secret_values(self) -> None:
        secret = "do-not-print-this-openai-key"
        settings = Settings.from_env({"OPENAI_API_KEY": secret})

        with self.assertRaises(RuntimeError) as context:
            settings.validate_for_run()

        self.assertNotIn(secret, str(context.exception))


def image_prompt(reference_policy: str = "indoor-flexible") -> ImagePrompt:
    return ImagePrompt(
        visual_type="property-editorial",
        reference_policy=reference_policy,
        subject="A calm San Jose living room",
        setting="An elegant residential interior",
        composition="Full-bleed interior image above a restrained editorial text panel",
        headline="CHOOSE THE RIGHT FIT",
    )


class ReferencePolicyTest(TestCase):
    def test_outdoor_exact_policy_requires_a_selected_reference(self) -> None:
        post = SocialPostDraft(
            description="Post copy",
            keywords=["one", "two", "three"],
            image_prompt=image_prompt("outdoor-exact"),
            due_at=datetime(2026, 8, 19, 15, 30, tzinfo=UTC),
        )

        with self.assertRaisesRegex(ValueError, "Outdoor scenes and headshots"):
            validate_reference_policy(post, [])

        validate_reference_policy(post, ["outdoors/front.jpg"])

    def test_outdoor_language_cannot_be_labeled_indoor_flexible(self) -> None:
        post = SocialPostDraft(
            description="Post copy",
            keywords=["one", "two", "three"],
            image_prompt=ImagePrompt(
                visual_type="neighborhood-editorial",
                subject="A recognizable property exterior",
                setting="A neighborhood street view",
                composition="Exact facade perspective",
                headline="SEE THE DIFFERENCE",
            ),
            due_at=datetime(2026, 8, 19, 15, 30, tzinfo=UTC),
        )

        with self.assertRaisesRegex(ValueError, "Outdoor scenes and headshots"):
            validate_reference_policy(post, [])

    def test_indoor_flexible_policy_can_run_without_a_reference(self) -> None:
        post = SocialPostDraft(
            description="Post copy",
            keywords=["one", "two", "three"],
            image_prompt=image_prompt(),
            due_at=datetime(2026, 8, 19, 15, 30, tzinfo=UTC),
        )

        validate_reference_policy(post, [])

    def test_typographic_neighborhood_copy_does_not_imply_an_outdoor_photo(self) -> None:
        post = SocialPostDraft(
            description="Post copy",
            keywords=["one", "two", "three"],
            image_prompt=ImagePrompt(
                visual_type="typographic-educational",
                reference_policy="indoor-flexible",
                subject="A typographic guide to comparing San Jose neighborhoods",
                setting="Warm ivory studio backdrop with no outdoor photograph and no people",
                composition="Editorial type and abstract map lines",
                headline="COMPARE THE WHOLE MOVE",
            ),
            due_at=datetime(2026, 8, 19, 15, 30, tzinfo=UTC),
        )

        validate_reference_policy(post, [])

    def test_group_policy_requires_group_asset_not_a_headshot(self) -> None:
        post = SocialPostDraft(
            description="Post copy",
            keywords=["one", "two", "three"],
            image_prompt=ImagePrompt(
                visual_type="people-editorial",
                reference_policy="group-exact",
                subject="Advisor with a client group",
                setting="Community gathering",
                composition="Use the supplied group photograph",
                headline="RELATIONSHIPS FIRST",
            ),
            due_at=datetime(2026, 8, 19, 15, 30, tzinfo=UTC),
        )
        catalog = {
            "people/advisor.jpg": ReferenceAsset(
                "people/advisor.jpg", "headshot"
            ),
            "people/group.jpg": ReferenceAsset(
                "people/group.jpg", "headshot-group"
            ),
        }

        with self.assertRaisesRegex(ValueError, "headshot-group"):
            validate_reference_policy(post, ["people/advisor.jpg"], catalog)

        validate_reference_policy(post, ["people/group.jpg"], catalog)

    def test_logo_field_requires_the_actual_logo_asset(self) -> None:
        post = SocialPostDraft(
            description="Post copy",
            keywords=["one", "two", "three"],
            image_prompt=image_prompt().model_copy(update={"business_fields": ["logo"]}),
            due_at=datetime(2026, 8, 19, 15, 30, tzinfo=UTC),
        )

        with self.assertRaisesRegex(ValueError, "role=logo"):
            validate_reference_policy(post, ["headshots/advisor.jpg"])

        validate_reference_policy(post, ["info/logo.png"])

    def test_headshot_in_an_outdoor_setting_requires_both_references(self) -> None:
        post = SocialPostDraft(
            description="Post copy",
            keywords=["one", "two", "three"],
            image_prompt=ImagePrompt(
                visual_type="people-editorial",
                reference_policy="headshot-exact",
                subject="The Realtor helping local homeowners",
                setting="Outside the supplied San Jose home",
                composition="Place the headshot identity naturally in the outdoor setting",
                headline="LOCAL GUIDANCE",
            ),
            due_at=datetime(2026, 8, 19, 15, 30, tzinfo=UTC),
        )
        catalog = {
            "headshots/realtor.png": ReferenceAsset("headshots/realtor.png", "headshot"),
            "outdoors/home.jpg": ReferenceAsset("outdoors/home.jpg", "outdoor"),
        }

        with self.assertRaisesRegex(ValueError, "missing roles: outdoor"):
            validate_reference_policy(post, ["headshots/realtor.png"], catalog)

        validate_reference_policy(
            post,
            ["headshots/realtor.png", "outdoors/home.jpg"],
            catalog,
        )


class ReferenceLoadingTest(IsolatedAsyncioTestCase):
    async def test_preserves_selected_order_and_routes_logo_to_fixed_brand_object(self) -> None:
        reference_store = AsyncMock()
        reference_store.get_reference_image.side_effect = [
            ReferenceImage("headshots/realtor.png", b"person", "image/png"),
            ReferenceImage("outdoors/home.jpg", b"setting", "image/jpeg"),
        ]
        brand_store = AsyncMock()
        brand_store.get_logo_image.return_value = ReferenceImage(
            "info/logo.png", b"logo", "image/png", role="logo"
        )
        catalog = {
            "headshots/realtor.png": ReferenceAsset("headshots/realtor.png", "headshot"),
            "outdoors/home.jpg": ReferenceAsset("outdoors/home.jpg", "outdoor"),
            "info/logo.png": ReferenceAsset("info/logo.png", "logo"),
        }

        images = await _load_reference_images(
            reference_store,
            brand_store,
            ["headshots/realtor.png", "outdoors/home.jpg", "info/logo.png"],
            catalog,
        )

        self.assertEqual(
            [(image.key, image.role) for image in images],
            [
                ("headshots/realtor.png", "headshot"),
                ("outdoors/home.jpg", "outdoor"),
                ("info/logo.png", "logo"),
            ],
        )
        self.assertEqual(reference_store.get_reference_image.await_count, 2)
        brand_store.get_logo_image.assert_awaited_once()


class AgentRevisionTest(IsolatedAsyncioTestCase):
    async def test_retries_with_validation_feedback_when_references_are_unavailable(self) -> None:
        class FakeTopicStore:
            async def pick_random_available(self, limit: int = 1) -> list[Topic]:
                return [Topic(id=1, topic="Local guidance")]

            async def mark_used(self, topic_id: int, used_at: datetime) -> None:
                del topic_id, used_at

        due_at = datetime(2026, 8, 17, 15, 30, tzinfo=UTC)
        rejected = SocialPostDraft(
            description="Unsupported concept",
            keywords=["one", "two", "three"],
            image_prompt=ImagePrompt(
                visual_type="people-editorial",
                reference_policy="headshot-exact",
                subject="The Realtor outside a local home",
                setting="Outside the supplied home",
                composition="Place the Realtor in the outdoor setting",
                headline="LOCAL GUIDANCE",
            ),
            reference_image_keys=["headshots/missing.png", "outdoors/missing.jpg"],
            due_at=due_at,
        )
        corrected = SocialPostDraft(
            description="Supported concept",
            keywords=["one", "two", "three"],
            image_prompt=ImagePrompt(
                visual_type="typographic-educational",
                reference_policy="indoor-flexible",
                subject="A concise home-planning guide with no people",
                setting="Warm ivory studio backdrop",
                composition="No people; clean editorial typography",
                headline="PLAN THE WHOLE MOVE",
            ),
            reference_image_keys=[],
            due_at=due_at,
        )
        env = {
            "OPENAI_API_KEY": "openai-key",
            "OPENAI_IMAGE_MODEL": "gpt-image-2",
            "OPENAI_IMAGE_WIDTH": "1088",
            "OPENAI_IMAGE_HEIGHT": "1360",
            "OPENAI_IMAGE_QUALITY": "medium",
            "BUFFER_API_KEY": "buffer-key",
            "BUFFER_ORGANIZATION_ID": "organization-id",
            "BUFFER_API_URL": "https://api.buffer.com",
            "MIN_SCHEDULE_LEAD_MINUTES": "30",
            "SCHEDULE_HORIZON_DAYS": "8",
            "MAX_POST_CHARS": "5000",
            "RETRY_MAX_ATTEMPTS": "3",
            "RETRY_BACKOFF_SECONDS": "1",
        }
        contact = ContactInfo(
            business_name="Test Business",
            phone="(555) 555-5555",
            city="San Jose, CA",
            website="https://test-business.example/",
        )
        brand_store = AsyncMock()
        brand_store.get_contact_info.return_value = contact
        channel = BufferChannel("channel-1", "channel", "Channel", "linkedin")

        with (
            patch(
                "job.generate_social_post",
                new=AsyncMock(side_effect=[rejected, corrected]),
            ) as generate,
            patch(
                "job._prepare_performance_analysis",
                new=AsyncMock(return_value=(None, None, "not_run", None)),
            ),
            patch("job.BufferClient") as client_class,
        ):
            client_class.return_value.list_available_channels = AsyncMock(return_value=[channel])
            result = await run_weekly_job(
                env,
                dry_run=True,
                post_count=1,
                topic_store=FakeTopicStore(),
                brand_store=brand_store,
                now=datetime(2026, 8, 17, 14, tzinfo=UTC),
            )

        self.assertEqual(generate.await_count, 2)
        feedback = generate.await_args_list[1].args[-1]
        self.assertIn("unavailable keys", feedback)
        self.assertIn("Available roles: logo", feedback)
        self.assertIn("Rejected draft", feedback)
        self.assertEqual(result["drafts"][0]["description"], "Supported concept")
        self.assertEqual(result["drafts"][0]["reference_image_keys"], [])

    async def test_uses_deterministic_visual_fallback_after_three_invalid_drafts(self) -> None:
        settings = Settings.from_env(
            {
                "OPENAI_API_KEY": "openai-key",
                "OPENAI_IMAGE_MODEL": "gpt-image-2",
                "OPENAI_IMAGE_WIDTH": "1088",
                "OPENAI_IMAGE_HEIGHT": "1360",
                "OPENAI_IMAGE_QUALITY": "medium",
                "BUFFER_API_KEY": "buffer-key",
                "BUFFER_ORGANIZATION_ID": "organization-id",
                "BUFFER_API_URL": "https://api.buffer.com",
                "MIN_SCHEDULE_LEAD_MINUTES": "30",
                "SCHEDULE_HORIZON_DAYS": "8",
                "MAX_POST_CHARS": "5000",
                "RETRY_MAX_ATTEMPTS": "3",
                "RETRY_BACKOFF_SECONDS": "0",
            }
        )
        due_at = datetime(2026, 8, 17, 15, 30, tzinfo=UTC)
        rejected = SocialPostDraft(
            description="Useful copy that should be preserved.",
            keywords=["one", "two", "three"],
            image_prompt=ImagePrompt(
                visual_type="neighborhood-editorial",
                reference_policy="outdoor-exact",
                subject="A neighborhood scene",
                setting="Outdoor setting",
                composition="Full-bleed photograph",
                headline="COMPARE YOUR OPTIONS",
            ),
            reference_image_keys=["info/logo.png"],
            due_at=due_at,
        )
        contact = ContactInfo(
            business_name="Test Business",
            phone="(555) 555-5555",
            city="San Jose, CA",
            website="https://test-business.example/",
        )
        logo = ReferenceAsset("info/logo.png", "logo")

        with patch(
            "job.generate_social_post",
            new=AsyncMock(return_value=rejected),
        ) as generate:
            preparation = await _generate_valid_draft(
                settings,
                "Willow Glen vs Almaden Valley",
                due_at,
                [logo.key],
                None,
                contact,
                [logo],
                {logo.key: logo},
                datetime(2026, 8, 17, 14, tzinfo=UTC),
                require_headshot_reference=False,
            )

        self.assertEqual(generate.await_count, 3)
        self.assertTrue(preparation.fallback_used)
        self.assertEqual(preparation.attempts, 3)
        self.assertEqual(len(preparation.validation_errors), 3)
        self.assertEqual(preparation.draft.description, rejected.description)
        self.assertEqual(
            preparation.draft.image_prompt.visual_type,
            "typographic-educational",
        )
        self.assertEqual(preparation.draft.reference_image_keys, [])


def performance_analysis() -> PerformanceAnalysis:
    return PerformanceAnalysis(
        overview="Specific educational posts are the strongest direction.",
        data_quality="Small but usable sample.",
        confidence="medium",
        cross_channel_patterns=["Specific openings outperform generic tests."],
        channel_insights=[],
        next_post_actions=["Open with a concrete buyer question."],
        experiments=["Test a short checklist."],
        avoid=["Generic platform-test copy."],
    )


class SkipKeywordUpdateTest(IsolatedAsyncioTestCase):
    async def test_live_run_can_leave_selected_keywords_unused(self) -> None:
        class FakeTopicStore:
            def __init__(self) -> None:
                self.marked: list[int] = []

            async def pick_random_available(self, limit: int = 1) -> list[Topic]:
                return [Topic(id=index, topic=f"Topic {index}") for index in range(1, limit + 1)]

            async def mark_used(self, topic_id: int, used_at: datetime) -> None:
                del used_at
                self.marked.append(topic_id)

        async def generate_draft(
            settings: Settings,
            topic: str,
            due_at: datetime,
            reference_image_keys: list[str],
            analysis: PerformanceAnalysis | None,
        ) -> SocialPostDraft:
            del settings, topic, reference_image_keys
            self.assertEqual(analysis, performance_analysis())
            return SocialPostDraft(
                description="Post copy",
                keywords=["one", "two", "three"],
                image_prompt=image_prompt(),
                due_at=due_at,
            )

        store = FakeTopicStore()
        env = {
            "OPENAI_API_KEY": "openai-key",
            "OPENAI_IMAGE_MODEL": "gpt-image-2",
            "OPENAI_IMAGE_WIDTH": "1088",
            "OPENAI_IMAGE_HEIGHT": "1360",
            "OPENAI_IMAGE_QUALITY": "medium",
            "BUFFER_API_KEY": "buffer-key",
            "BUFFER_ORGANIZATION_ID": "organization-id",
            "BUFFER_API_URL": "https://api.buffer.com",
            "MIN_SCHEDULE_LEAD_MINUTES": "30",
            "SCHEDULE_HORIZON_DAYS": "8",
            "MAX_POST_CHARS": "5000",
            "RETRY_MAX_ATTEMPTS": "3",
            "RETRY_BACKOFF_SECONDS": "1",
            "ASSET_PUBLIC_BASE_URL": "https://social.example",
        }
        channel = BufferChannel(
            id="channel-1",
            name="channel",
            display_name="Channel",
            service="linkedin",
        )
        instagram_channel = BufferChannel(
            id="channel-2",
            name="instagram-channel",
            display_name="Instagram Channel",
            service="instagram",
        )

        with (
            patch("job.generate_social_post", new=AsyncMock(side_effect=generate_draft)),
            patch(
                "job.load_buffer_insights",
                new=AsyncMock(
                    return_value={
                        "organization_id": "organization-id",
                        "window": {"days": 30, "start": "start", "end": "end"},
                        "channel_count": 1,
                        "channels": [{"post_count": 2}],
                    }
                ),
            ) as load_insights,
            patch(
                "job.analyze_insights_snapshot",
                new=AsyncMock(return_value=(performance_analysis(), "complete", None)),
            ) as analyze_performance,
            patch(
                "job.generate_and_store_image",
                new=AsyncMock(
                    side_effect=lambda settings, prompt, topic_id, due_at, store, references: (
                        GeneratedImage(
                            key=f"generated_graphics/topic-{topic_id}.png",
                            url=(
                                f"https://social.example/assets/generated_graphics/topic-{topic_id}.png"
                            ),
                            model="gpt-image-2",
                            size="1024x1536",
                            quality="high",
                        )
                    )
                ),
            ),
            patch("job.BufferClient") as client_class,
        ):
            client = client_class.return_value
            client.list_available_channels = AsyncMock(return_value=[channel, instagram_channel])
            client.create_scheduled_post = AsyncMock(
                side_effect=[{"id": "post-1"}, {"id": "post-2"}, {"id": "post-3"}]
            )

            result = await run_weekly_job(
                env,
                dry_run=False,
                skip_keyword_update=True,
                channel_service="linkedin",
                topic_store=store,
                asset_store=AsyncMock(),
                now=datetime(2026, 8, 17, 14, tzinfo=UTC),
            )

        self.assertEqual(store.marked, [])
        self.assertFalse(result["used_at_updated"])
        self.assertTrue(result["keyword_update_skipped"])
        self.assertEqual(result["buffer_posts_created"], 3)
        self.assertEqual(result["channel_count"], 1)
        self.assertEqual(result["channel_service_filter"], "linkedin")
        self.assertEqual(result["performance_analysis_status"], "complete")
        self.assertEqual(result["buffer_insights_summary"]["post_count"], 2)
        self.assertEqual(
            result["performance_analysis"]["next_post_actions"],
            ["Open with a concrete buyer question."],
        )
        self.assertEqual(load_insights.await_args.kwargs["channels"], [channel])
        analyze_performance.assert_awaited_once()
        self.assertTrue(
            all(
                call.args[1] == "channel-1" for call in client.create_scheduled_post.await_args_list
            )
        )
        self.assertEqual(result["images_generated"], 3)
        self.assertTrue(
            all(call.args[0].image_url for call in client.create_scheduled_post.await_args_list)
        )


class PerformanceFallbackTest(IsolatedAsyncioTestCase):
    async def test_buffer_metrics_failure_returns_a_nonfatal_fallback(self) -> None:
        configured = Settings.from_env(
            {
                "BUFFER_ORGANIZATION_ID": "organization-id",
            }
        )
        channel = BufferChannel("channel-1", "channel", "Channel", "linkedin")

        with patch(
            "job.load_buffer_insights",
            new=AsyncMock(side_effect=BufferAPIError("metrics unavailable")),
        ):
            snapshot, analysis_result, status, error = await _prepare_performance_analysis(
                AsyncMock(),
                configured,
                datetime(2026, 8, 17, 14, tzinfo=UTC),
                [channel],
            )

        self.assertIsNone(snapshot)
        self.assertIsNone(analysis_result)
        self.assertEqual(status, "buffer_unavailable")
        self.assertEqual(error, "BufferAPIError: metrics unavailable")


class ExternalRetryTest(IsolatedAsyncioTestCase):
    async def test_retries_transient_buffer_channel_discovery(self) -> None:
        channel = BufferChannel("channel-1", "channel", "Channel", "linkedin")
        client = AsyncMock()
        client.list_available_channels.side_effect = [
            BufferAPIError("temporary", retryable=True),
            [channel],
        ]

        channels = await _list_channels_with_retries(
            client,
            "organization-id",
            max_attempts=3,
            backoff_seconds=0,
        )

        self.assertEqual(channels, [channel])
        self.assertEqual(client.list_available_channels.await_count, 2)

    async def test_retries_image_generation_before_failing_the_job(self) -> None:
        settings = Settings.from_env(
            {
                "RETRY_MAX_ATTEMPTS": "3",
                "RETRY_BACKOFF_SECONDS": "0",
            }
        )
        draft = SocialPostDraft(
            description="Post copy",
            keywords=["one", "two", "three"],
            image_prompt=image_prompt(),
            due_at=datetime(2026, 8, 19, 15, 30, tzinfo=UTC),
        )
        expected = GeneratedImage(
            key="generated_graphics/topic-1.png",
            url=None,
            model="gpt-image-2",
            size="1088x1360",
            quality="medium",
        )

        with patch(
            "job.generate_and_save_image",
            new=AsyncMock(side_effect=[RuntimeError("temporary"), expected]),
        ) as generate:
            result = await _generate_and_save(
                settings,
                draft,
                1,
                Path("/tmp"),
                [],
                None,
            )

        self.assertEqual(result, expected)
        self.assertEqual(generate.await_count, 2)
