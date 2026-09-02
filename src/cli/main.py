"""CLI entry point: argument dispatch into Buffer and generation run modes."""

from __future__ import annotations

import asyncio
import json
import os
import sys

from buffer.client import BufferClient
from buffer.insights import analyze_insights_snapshot, load_buffer_insights
from cli.args import BUFFER_MODES, DRY_RUN_MODES, HEADSHOT_TEST_TOPIC, parse_args
from cli.display import display_generated_images
from cli.env import load_env_file
from cli.reports import format_buffer_insights_report, format_run_report
from cli.stores import (
    LocalReferenceImageStore,
    WranglerImageAssetStore,
    WranglerReferenceImageStore,
    WranglerTopicStore,
)
from images.image_pipeline import ReferenceImageStore
from job import run_weekly_job, weekly_cron_time
from settings import Settings


async def _run_buffer_mode(args) -> None:
    settings = Settings.from_env(os.environ)
    if args.mode == "buffer_insights":
        settings.validate_for_buffer_analysis()
    else:
        settings.validate_for_buffer()
    client = BufferClient(settings.buffer_api_key, api_url=settings.buffer_api_url)
    if args.mode == "buffer_insights":
        result = await load_buffer_insights(client, settings.buffer_organization_id)
        analysis, status, error = await analyze_insights_snapshot(settings, result)
        result["performance_analysis_status"] = status
        result["performance_analysis_error"] = error
        result["performance_analysis"] = (
            analysis.model_dump(mode="json") if analysis is not None else None
        )
        print(json.dumps(result, indent=2) if args.json else format_buffer_insights_report(result))
        return
    channels = await client.list_available_channels(settings.buffer_organization_id)
    print(
        json.dumps(
            {
                "organization_id": settings.buffer_organization_id,
                "channel_count": len(channels),
                "channels": [
                    {
                        "id": channel.id,
                        "name": channel.name,
                        "display_name": channel.display_name,
                        "service": channel.service,
                    }
                    for channel in channels
                ],
            },
            indent=2,
        )
    )


async def _run_generation_mode(args) -> None:
    dry_run = args.mode in DRY_RUN_MODES
    selected_service = next(
        (
            name
            for name, enabled in (
                ("linkedin", args.linkedin),
                ("instagram", args.instagram),
                ("facebook", args.facebook),
            )
            if enabled
        ),
        None,
    )
    remote_assets = WranglerImageAssetStore()
    reference_store: ReferenceImageStore | None = None
    if args.reference_images:
        reference_store = LocalReferenceImageStore(args.reference_images)
    elif args.reference_keys:
        reference_store = WranglerReferenceImageStore(args.reference_keys)
    result = await run_weekly_job(
        os.environ,
        dry_run=dry_run,
        selected_topic=(HEADSHOT_TEST_TOPIC if args.mode == "headshot-test" else args.topic),
        require_headshot_reference=args.mode == "headshot-test",
        skip_topic_update=args.skip_topic_update,
        post_count=args.n,
        channel_service=selected_service,
        topic_store=WranglerTopicStore(),
        asset_store=remote_assets,
        reference_store=reference_store,
        brand_store=remote_assets,
        local_image_dir=(args.output_dir.resolve() if dry_run else None),
        channels_cache_path=(
            args.output_dir.resolve() / "buffer_channels.json" if dry_run else None
        ),
        now=weekly_cron_time(force_non_monday=args.force),
        force_non_monday=args.force,
        skip_performance_analysis=args.skip_perf,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_run_report(result, hyperlinks=sys.stdout.isatty()))
        if dry_run:
            displayed = await display_generated_images(result)
            if not displayed and sys.stdout.isatty():
                print("Inline preview unavailable; open the image links above.")


async def main() -> None:
    args = parse_args()
    load_env_file()
    if args.mode in BUFFER_MODES:
        await _run_buffer_mode(args)
    else:
        await _run_generation_mode(args)


if __name__ == "__main__":
    asyncio.run(main())
