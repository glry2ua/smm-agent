"""CLI argument parsing with a declarative cross-flag validation table."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

DRY_RUN_MODES = {"dry-run", "headshot-test"}
BUFFER_MODES = {"buffer_state", "buffer_insights"}
GENERATION_MODES = DRY_RUN_MODES | {"end-to-end"}

HEADSHOT_TEST_TOPIC = "Who is a San Jose Realtor experienced with move-up buyers?"

# Each rule fires at most once; predicates return True when the flag combination is invalid.
VALIDATION_RULES: list[tuple[Callable[[argparse.Namespace], bool], str]] = [
    (
        lambda args: args.skip_topic_update and args.mode != "end-to-end",
        "--skip-topic-update can only be used with end-to-end",
    ),
    (
        lambda args: (
            args.mode in BUFFER_MODES and (args.linkedin or args.instagram or args.facebook)
        ),
        "platform filters can only be used with dry-run or end-to-end",
    ),
    (
        lambda args: args.n is not None and args.mode in BUFFER_MODES,
        "--n can only be used with dry-run or end-to-end",
    ),
    (
        lambda args: args.force and args.mode in BUFFER_MODES,
        "--force can only be used with dry-run or end-to-end",
    ),
    (
        lambda args: args.topic and args.mode != "dry-run",
        "--topic can only be used with dry-run",
    ),
    (
        lambda args: args.skip_perf and args.mode not in DRY_RUN_MODES,
        "--skip-perf can only be used with dry-run or headshot-test",
    ),
    (
        lambda args: args.topic and args.n not in {None, 1},
        "--topic requires a single post; use --n=1",
    ),
    (
        lambda args: args.reference_images and args.reference_keys,
        "use either --reference-image or --reference-key, not both",
    ),
    (
        lambda args: args.reference_images and args.mode not in DRY_RUN_MODES,
        "local reference images can only be used with a dry-run",
    ),
    (
        lambda args: args.reference_keys and args.mode not in GENERATION_MODES,
        "R2 reference keys can only be used with a generation run",
    ),
    (
        lambda args: args.mode == "headshot-test" and args.n not in {None, 1},
        "headshot-test always generates one post",
    ),
    (
        lambda args: (
            args.mode == "headshot-test" and not args.reference_images and not args.reference_keys
        ),
        "headshot-test requires --reference-image or --reference-key",
    ),
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the weekly social-post workflow locally")
    parser.add_argument(
        "mode",
        choices=("dry-run", "headshot-test", "end-to-end", "buffer_state", "buffer_insights"),
        help=(
            "dry-run skips Buffer createPost and D1 used_at; "
            "headshot-test runs one deterministic dry-run post with a headshot reference; "
            "end-to-end performs production mutations; "
            "buffer_state lists the configured Buffer organization and channels; "
            "buffer_insights reports per-channel metrics for the last 30 days"
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the complete machine-readable result instead of the validation report",
    )
    parser.add_argument(
        "--skip-topic-update",
        action="store_true",
        help="submit posts without marking the selected D1 topics as used (end-to-end only)",
    )
    platform_group = parser.add_mutually_exclusive_group()
    platform_group.add_argument(
        "--linkedin",
        action="store_true",
        help="build and submit posts only for available LinkedIn channels",
    )
    platform_group.add_argument(
        "--instagram",
        action="store_true",
        help="build and submit posts only for available Instagram channels",
    )
    platform_group.add_argument(
        "--facebook",
        action="store_true",
        help="build and submit posts only for available Facebook channels",
    )
    parser.add_argument(
        "--n",
        type=int,
        choices=(1, 2, 3),
        default=None,
        metavar="N",
        help="generate and schedule N posts for this run (1–3; default: 3)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="run on a non-Monday for local testing (anchors the schedule to next Monday)",
    )
    parser.add_argument(
        "--topic",
        help="select one exact unused D1 topic (dry-run only; implies --n=1)",
    )
    parser.add_argument(
        "--reference-image",
        dest="reference_images",
        action="append",
        type=Path,
        metavar="PATH",
        help="include a local source image in the dry-run reference catalog (repeatable)",
    )
    parser.add_argument(
        "--reference-key",
        dest="reference_keys",
        action="append",
        metavar="R2_KEY",
        help="include an exact remote R2 source-image key in the generation catalog (repeatable)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dry_run_outputs"),
        help="directory for GPT Image 2 outputs generated by dry-run",
    )
    parser.add_argument(
        "--skip-perf",
        action="store_true",
        help="skip the Buffer performance analysis queries (dry-run only)",
    )
    args = parser.parse_args(argv)
    for invalid, message in VALIDATION_RULES:
        if invalid(args):
            parser.error(message)
    if args.mode == "headshot-test":
        args.n = 1
    elif args.n is None:
        args.n = 1 if args.topic else 3
    return args
