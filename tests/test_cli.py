from contextlib import redirect_stderr
from datetime import UTC, datetime
from io import StringIO
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from buffer.client import BufferChannel, BufferMetric, BufferMetricsSummary, BufferPost
from buffer.insights import analyze_insights_snapshot, load_buffer_insights
from cli import (
    HEADSHOT_TEST_TOPIC,
    WranglerTopicStore,
    _kitty_icat_command,
    format_buffer_insights_report,
    format_run_report,
    parse_args,
)
from settings import Settings


class FormatRunReportTest(TestCase):
    def test_groups_deliveries_by_post_for_human_review(self) -> None:
        result = {
            "mode": "dry-run",
            "topics": [{"id": 7, "topic": "Useful topic"}],
            "drafts": [
                {
                    "description": "Concise post copy.",
                    "keywords": ["one", "two", "three"],
                    "image_prompt": {
                        "headline": "MOVE WITH CLARITY",
                        "subject": "A refined San Jose home interior",
                    },
                    "image_url": None,
                    "due_at": "2026-08-17T15:30:00Z",
                }
            ],
            "generated_images": [
                {
                    "local_path_absolute": "/tmp/dry-run/topic-7.png",
                    "local_path_relative": "dry_run_outputs/topic-7.png",
                }
            ],
            "images_generated": 1,
            "buffer_inputs": [
                {
                    "topic_id": 7,
                    "channel": {
                        "id": "channel-1",
                        "name": "@example",
                        "display_name": "Example Account",
                        "service": "instagram",
                    },
                    "input": {},
                }
            ],
            "channel_count": 1,
            "buffer_posts_created": 0,
            "used_at_updated": False,
        }

        report = format_run_report(result)

        self.assertIn("DRY RUN — NOTHING WAS PUBLISHED", report)
        self.assertIn("1 posts | 1 channels | 1 scheduled deliveries", report)
        self.assertIn("POST 1 OF 1 — Monday, Aug 17 at 8:30 AM PDT", report)
        self.assertIn("Topic [7]: Useful topic", report)
        self.assertIn("COPY\nConcise post copy.", report)
        self.assertIn("KEYWORDS: one, two, three", report)
        self.assertIn("IMAGE PROMPT\nMOVE WITH CLARITY", report)
        self.assertIn("R2 REFERENCES: none selected", report)
        self.assertIn("GPT Image 2 files saved locally: 1", report)
        self.assertIn("IMAGE: generated locally for review", report)
        self.assertIn("IMAGE FILE: /tmp/dry-run/topic-7.png", report)
        self.assertIn("Example Account (instagram / @example)", report)

    def test_reports_skipped_keyword_update_for_live_run(self) -> None:
        result = {
            "mode": "live",
            "topics": [],
            "drafts": [],
            "buffer_inputs": [],
            "channel_count": 0,
            "buffer_posts_created": 0,
            "used_at_updated": False,
            "keyword_update_skipped": True,
        }

        report = format_run_report(result)

        self.assertIn("D1 keywords marked used: skipped by flag", report)
        self.assertIn("Buffer scheduled drafts created: 0", report)
        self.assertIn("click Schedule Post", report)


class ParseArgsTest(TestCase):
    def test_allows_skipping_keyword_update_for_end_to_end(self) -> None:
        args = parse_args(["end-to-end", "--skip-keyword-update"])

        self.assertTrue(args.skip_keyword_update)

    def test_rejects_skipping_keyword_update_for_dry_run(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parse_args(["dry-run", "--skip-keyword-update"])

    def test_allows_linkedin_filter_for_end_to_end(self) -> None:
        args = parse_args(["end-to-end", "--linkedin"])

        self.assertTrue(args.linkedin)

    def test_allows_instagram_filter_for_end_to_end(self) -> None:
        args = parse_args(["end-to-end", "--instagram"])

        self.assertTrue(args.instagram)

    def test_allows_facebook_filter_for_end_to_end(self) -> None:
        args = parse_args(["end-to-end", "--facebook"])

        self.assertTrue(args.facebook)

    def test_rejects_multiple_platform_filters(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parse_args(["end-to-end", "--linkedin", "--instagram"])

    def test_allows_explicit_r2_references_for_end_to_end(self) -> None:
        args = parse_args(
            [
                "end-to-end",
                "--reference-key",
                "headshots/realtor.png",
                "--reference-key",
                "outdoors/home.jpg",
            ]
        )

        self.assertEqual(
            args.reference_keys,
            ["headshots/realtor.png", "outdoors/home.jpg"],
        )

    def test_accepts_a_bounded_post_count_for_generation_runs(self) -> None:
        args = parse_args(["dry-run", "--n=1"])

        self.assertEqual(args.n, 1)

    def test_headshot_test_is_one_post_and_accepts_a_local_reference(self) -> None:
        args = parse_args(["headshot-test", "--reference-image", "/tmp/headshot.png"])

        self.assertEqual(args.n, 1)
        self.assertEqual([str(path) for path in args.reference_images], ["/tmp/headshot.png"])
        self.assertEqual(
            HEADSHOT_TEST_TOPIC,
            "Who is a San Jose Realtor experienced with move-up buyers?",
        )

    def test_headshot_test_requires_a_reference_source(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parse_args(["headshot-test"])

    def test_rejects_post_count_outside_one_to_three(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parse_args(["dry-run", "--n=4"])

    def test_rejects_post_count_for_buffer_state(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parse_args(["buffer_state", "--n=1"])

    def test_rejects_linkedin_filter_for_buffer_state(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parse_args(["buffer_state", "--linkedin"])

    def test_rejects_instagram_filter_for_buffer_state(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parse_args(["buffer_state", "--instagram"])

    def test_rejects_facebook_filter_for_buffer_state(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parse_args(["buffer_state", "--facebook"])

    def test_accepts_buffer_insights_mode(self) -> None:
        args = parse_args(["buffer_insights", "--json"])

        self.assertEqual(args.mode, "buffer_insights")
        self.assertTrue(args.json)

    def test_rejects_linkedin_filter_for_buffer_insights(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parse_args(["buffer_insights", "--linkedin"])

    def test_rejects_instagram_filter_for_buffer_insights(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parse_args(["buffer_insights", "--instagram"])

    def test_rejects_facebook_filter_for_buffer_insights(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parse_args(["buffer_insights", "--facebook"])


class WranglerTopicStoreTest(IsolatedAsyncioTestCase):
    async def test_selects_an_exact_unused_topic(self) -> None:
        store = WranglerTopicStore()
        store._execute = AsyncMock(return_value=[{"id": 76, "topic": HEADSHOT_TEST_TOPIC}])

        topic = await store.pick_available_topic(HEADSHOT_TEST_TOPIC)

        self.assertEqual(topic.id, 76)
        self.assertEqual(topic.topic, HEADSHOT_TEST_TOPIC)
        store._execute.assert_awaited_once()
        self.assertIn("used_at IS NULL", store._execute.await_args.args[0])


class BufferInsightsTest(IsolatedAsyncioTestCase):
    async def test_runs_luna_analysis_for_a_snapshot_with_posts(self) -> None:
        snapshot = {"channels": [{"post_count": 1}]}
        expected = AsyncMock()
        with patch(
            "buffer.insights.analyze_buffer_performance",
            new=AsyncMock(return_value=expected),
        ) as analyze:
            result, status, error = await analyze_insights_snapshot(Settings.from_env({}), snapshot)

        self.assertIs(result, expected)
        self.assertEqual(status, "complete")
        self.assertIsNone(error)
        analyze.assert_awaited_once_with(Settings.from_env({}), snapshot)

    async def test_skips_luna_when_the_snapshot_has_no_posts(self) -> None:
        with patch("buffer.insights.analyze_buffer_performance", new=AsyncMock()) as analyze:
            result, status, error = await analyze_insights_snapshot(
                Settings.from_env({}), {"channels": [{"post_count": 0}]}
            )

        self.assertIsNone(result)
        self.assertEqual(status, "no_posts")
        self.assertIsNone(error)
        analyze.assert_not_awaited()

    async def test_queries_each_channel_for_the_same_30_day_window(self) -> None:
        client = AsyncMock()
        client.list_available_channels.return_value = [
            BufferChannel("linkedin-1", "@agent", "Agent", "linkedin"),
            BufferChannel("instagram-1", "agent", "Agent IG", "instagram"),
        ]
        client.get_aggregated_post_metrics.side_effect = [
            BufferMetricsSummary(
                metrics=(BufferMetric("postCount", "Posts", 10, "count", ""),),
                metrics_updated_at="2026-08-17T08:00:00Z",
            ),
            BufferMetricsSummary(
                metrics=(BufferMetric("reactions", "Reactions", 24, "count", ""),),
                metrics_updated_at="2026-08-17T08:00:00Z",
            ),
        ]
        client.list_sent_posts.side_effect = [
            [
                BufferPost(
                    id="post-1",
                    text="Full post copy",
                    channel_id="linkedin-1",
                    status="sent",
                    created_at="2026-08-10T12:00:00Z",
                    updated_at="2026-08-10T13:00:00Z",
                    due_at="2026-08-10T12:30:00Z",
                    sent_at="2026-08-10T12:31:00Z",
                    external_link="https://social.example/post-1",
                    via="api",
                    tags=(),
                    assets=(),
                    metrics=(BufferMetric("reactions", "Reactions", 8, "count", ""),),
                    metrics_updated_at="2026-08-17T08:00:00Z",
                )
            ],
            [],
        ]

        result = await load_buffer_insights(
            client,
            "organization-1",
            now=datetime(2026, 8, 17, 14, tzinfo=UTC),
        )

        self.assertEqual(result["window"]["start"], "2026-07-18T14:00:00Z")
        self.assertEqual(result["window"]["end"], "2026-08-17T14:00:00Z")
        self.assertEqual(result["channel_count"], 2)
        self.assertEqual(result["channels"][0]["post_count"], 1)
        self.assertEqual(result["channels"][0]["posts"][0]["text"], "Full post copy")
        calls = client.get_aggregated_post_metrics.await_args_list
        self.assertEqual(calls[0].kwargs["channel_ids"], ["linkedin-1"])
        self.assertEqual(calls[1].kwargs["channel_ids"], ["instagram-1"])
        self.assertEqual(calls[0].kwargs["start"], calls[1].kwargs["start"])
        post_calls = client.list_sent_posts.await_args_list
        self.assertEqual(post_calls[0].kwargs["channel_ids"], ["linkedin-1"])
        self.assertEqual(post_calls[1].kwargs["channel_ids"], ["instagram-1"])

    def test_formats_a_compact_human_report(self) -> None:
        report = format_buffer_insights_report(
            {
                "window": {
                    "start": "2026-07-18T14:00:00Z",
                    "end": "2026-08-17T14:00:00Z",
                },
                "channel_count": 1,
                "performance_analysis_status": "complete",
                "performance_analysis_error": None,
                "performance_analysis": {
                    "overview": "Concrete buyer guidance is the strongest direction.",
                    "data_quality": "Small but usable sample.",
                    "confidence": "medium",
                    "cross_channel_patterns": ["Specific hooks outperform generic greetings."],
                    "channel_insights": [
                        {
                            "channel_service": "linkedin",
                            "summary": "Educational copy has the clearest signal.",
                            "winning_patterns": [],
                            "underperforming_patterns": [],
                            "recommendations": ["Open with a concrete buyer decision."],
                            "post_ids_considered": ["post-1"],
                        }
                    ],
                    "next_post_actions": ["Use a practical checklist."],
                    "experiments": ["Test a question-led opening."],
                    "avoid": ["Generic platform-test copy."],
                },
                "channels": [
                    {
                        "id": "linkedin-1",
                        "name": "@agent",
                        "display_name": "Agent",
                        "service": "linkedin",
                        "metrics_updated_at": "2026-08-17T08:00:00Z",
                        "metrics": [
                            {"name": "Posts", "value": 10.0, "unit": "count"},
                            {
                                "name": "Engagement rate",
                                "value": 4.25,
                                "unit": "percentage",
                            },
                        ],
                        "post_count": 1,
                        "posts": [
                            {
                                "id": "post-1",
                                "text": "A strong opening hook.\n\nUseful supporting detail.",
                                "created_at": "2026-08-10T12:00:00Z",
                                "due_at": "2026-08-10T12:30:00Z",
                                "sent_at": "2026-08-10T12:31:00Z",
                                "external_link": "https://social.example/post-1",
                                "metrics_updated_at": "2026-08-17T08:00:00Z",
                                "metrics": [{"name": "Reactions", "value": 8.0, "unit": "count"}],
                            }
                        ],
                    }
                ],
            }
        )

        self.assertIn("BUFFER INSIGHTS — LAST 30 DAYS", report)
        self.assertIn("LUNA PERFORMANCE ANALYSIS", report)
        self.assertIn("Concrete buyer guidance is the strongest direction.", report)
        self.assertIn("LINKEDIN RECOMMENDATIONS", report)
        self.assertIn("Open with a concrete buyer decision.", report)
        self.assertIn("Agent (linkedin / @agent)", report)
        self.assertIn("Posts: 10 count", report)
        self.assertIn("Engagement rate: 4.25%", report)
        self.assertIn("POSTS (1)", report)
        self.assertIn("A strong opening hook.", report)
        self.assertIn("Reactions: 8 count", report)


class KittyPreviewTest(TestCase):
    def test_uses_kitten_icat_inside_kitty(self) -> None:
        with (
            patch.dict("cli.os.environ", {"KITTY_WINDOW_ID": "1"}, clear=True),
            patch("cli.sys.stdout.isatty", return_value=True),
            patch(
                "cli.shutil.which",
                side_effect=lambda name: "/usr/bin/kitten" if name == "kitten" else None,
            ),
        ):
            command = _kitty_icat_command()

        self.assertEqual(command, ["/usr/bin/kitten", "icat"])

    def test_skips_inline_preview_outside_kitty(self) -> None:
        with (
            patch.dict("cli.os.environ", {"TERM": "xterm-256color"}, clear=True),
            patch("cli.sys.stdout.isatty", return_value=True),
        ):
            command = _kitty_icat_command()

        self.assertIsNone(command)
