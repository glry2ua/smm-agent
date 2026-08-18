"""Local CLI for dry-run and end-to-end execution against remote D1."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from brand.brand_context import CONTACT_INFO_KEY, LOGO_KEY, ContactInfo, parse_contact_info
from buffer.client import BufferClient
from buffer.insights import analyze_insights_snapshot, load_buffer_insights
from images.image_pipeline import ReferenceImage, ReferenceImageStore
from job import run_weekly_job, weekly_cron_time
from settings import Settings
from topics.topics import Topic

PACIFIC = ZoneInfo("America/Los_Angeles")
HEADSHOT_TEST_TOPIC = "Who is a San Jose Realtor experienced with move-up buyers?"


def _reference_content_type(key: str) -> str:
    suffix = Path(key).suffix.casefold()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".png": "image/png",
    }.get(suffix, "application/octet-stream")


def _validate_reference_key(key: str) -> None:
    normalized = key.casefold()
    if (
        not key
        or normalized.startswith("generated_graphics/")
        or Path(key).suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp"}
    ):
        raise ValueError(f"Invalid reference image key: {key}")


class WranglerTopicStore:
    """Use the authenticated Wrangler CLI to access the production D1 database."""

    database = "smm-agent-db"

    async def _execute(self, sql: str) -> list[dict[str, Any]]:
        process = await asyncio.create_subprocess_exec(
            "npx",
            "--yes",
            "wrangler@latest",
            "d1",
            "execute",
            self.database,
            "--remote",
            "--json",
            "--command",
            sql,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            message = stderr.decode().strip() or stdout.decode().strip()
            raise RuntimeError(f"Wrangler D1 command failed: {message}")
        payload = json.loads(stdout.decode())
        blocks = payload if isinstance(payload, list) else [payload]
        if not blocks:
            return []
        results = blocks[0].get("results", [])
        return results if isinstance(results, list) else []

    async def pick_random_available(self, limit: int = 1) -> list[Topic]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        rows = await self._execute(
            "SELECT id, topic FROM keywords "
            f"WHERE used_at IS NULL ORDER BY RANDOM() LIMIT {int(limit)}"
        )
        return [Topic(id=int(row["id"]), topic=str(row["topic"])) for row in rows]

    async def pick_available_topic(self, topic: str) -> Topic | None:
        if not topic.strip():
            raise ValueError("topic must not be empty")
        escaped_topic = topic.replace("'", "''")
        rows = await self._execute(
            "SELECT id, topic FROM keywords "
            f"WHERE used_at IS NULL AND topic = '{escaped_topic}' LIMIT 1"
        )
        if not rows:
            return None
        row = rows[0]
        return Topic(id=int(row["id"]), topic=str(row["topic"]))

    async def mark_used(self, topic_id: int, used_at: datetime) -> None:
        timestamp = used_at.isoformat().replace("'", "''")
        await self._execute(
            "UPDATE keywords SET used_at = "
            f"'{timestamp}' WHERE id = {int(topic_id)} AND used_at IS NULL"
        )


class WranglerImageAssetStore:
    """Upload generated image bytes to the production R2 bucket during local live runs."""

    bucket = "smm-agent-assets"

    async def put(self, key: str, body: bytes, content_type: str) -> None:
        with tempfile.NamedTemporaryFile(suffix=".png") as image_file:
            image_file.write(body)
            image_file.flush()
            process = await asyncio.create_subprocess_exec(
                "npx",
                "--yes",
                "wrangler@latest",
                "r2",
                "object",
                "put",
                f"{self.bucket}/{key}",
                "--file",
                image_file.name,
                "--content-type",
                content_type,
                "--cache-control",
                "public, max-age=31536000, immutable",
                "--remote",
                "--force",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
        if process.returncode != 0:
            message = stderr.decode().strip() or stdout.decode().strip()
            raise RuntimeError(f"Wrangler R2 upload failed: {message}")

    async def list_reference_keys(self) -> list[str]:
        # Wrangler has no object-list command; use --reference-key for local live runs.
        return []

    async def get_reference_image(self, key: str) -> ReferenceImage:
        _validate_reference_key(key)
        return await _download_r2_reference(self.bucket, key)

    async def get_contact_info(self) -> ContactInfo:
        return parse_contact_info(await _download_r2_bytes(self.bucket, CONTACT_INFO_KEY))

    async def get_logo_image(self) -> ReferenceImage:
        return ReferenceImage(
            key=LOGO_KEY,
            body=await _download_r2_bytes(self.bucket, LOGO_KEY),
            content_type="image/png",
            role="logo",
        )


async def _download_r2_reference(bucket: str, key: str) -> ReferenceImage:
    return ReferenceImage(
        key=key,
        body=await _download_r2_bytes(bucket, key),
        content_type=_reference_content_type(key),
    )


async def _download_r2_bytes(bucket: str, key: str) -> bytes:
    with tempfile.TemporaryDirectory() as temporary_directory:
        destination = Path(temporary_directory) / Path(key).name
        process = await asyncio.create_subprocess_exec(
            "npx",
            "--yes",
            "wrangler@latest",
            "r2",
            "object",
            "get",
            f"{bucket}/{key}",
            "--file",
            str(destination),
            "--remote",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            message = stderr.decode().strip() or stdout.decode().strip()
            raise RuntimeError(f"Wrangler R2 download failed: {message}")
        return destination.read_bytes()


class WranglerReferenceImageStore:
    """Read explicitly selected source images from the production R2 bucket."""

    bucket = WranglerImageAssetStore.bucket

    def __init__(self, keys: list[str]) -> None:
        self.keys = list(dict.fromkeys(keys))
        for key in self.keys:
            _validate_reference_key(key)

    async def list_reference_keys(self) -> list[str]:
        return self.keys.copy()

    async def get_reference_image(self, key: str) -> ReferenceImage:
        if key not in self.keys:
            raise ValueError(f"Reference image was not selected for this run: {key}")
        return await _download_r2_reference(self.bucket, key)


class LocalReferenceImageStore:
    """Expose local source images as a small reference catalog for a dry-run."""

    def __init__(self, paths: list[Path]) -> None:
        self.images: dict[str, Path] = {}
        for path in paths:
            resolved = path.expanduser().resolve()
            if not resolved.is_file():
                raise ValueError(f"Reference image does not exist: {path}")
            key = f"headshots/{resolved.name}"
            if key in self.images:
                raise ValueError(f"Duplicate reference image filename: {resolved.name}")
            _validate_reference_key(key)
            self.images[key] = resolved

    async def list_reference_keys(self) -> list[str]:
        return list(self.images)

    async def get_reference_image(self, key: str) -> ReferenceImage:
        path = self.images.get(key)
        if path is None:
            raise ValueError(f"Reference image was not selected for this run: {key}")
        return ReferenceImage(
            key=key,
            body=path.read_bytes(),
            content_type=_reference_content_type(key),
        )


def load_env_file(path: Path = Path(".env")) -> None:
    """Load a minimal KEY=value file without overriding exported variables."""

    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


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
        "--skip-keyword-update",
        action="store_true",
        help="submit posts without marking the selected D1 keywords as used (end-to-end only)",
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
    args = parser.parse_args(argv)
    if args.skip_keyword_update and args.mode != "end-to-end":
        parser.error("--skip-keyword-update can only be used with end-to-end")
    platform_selected = args.linkedin or args.instagram or args.facebook
    if platform_selected and args.mode in {"buffer_state", "buffer_insights"}:
        parser.error("platform filters can only be used with dry-run or end-to-end")
    if args.n is not None and args.mode in {"buffer_state", "buffer_insights"}:
        parser.error("--n can only be used with dry-run or end-to-end")
    if args.force and args.mode in {"buffer_state", "buffer_insights"}:
        parser.error("--force can only be used with dry-run or end-to-end")
    if args.topic and args.mode not in {"dry-run"}:
        parser.error("--topic can only be used with dry-run")
    if args.topic and args.n not in {None, 1}:
        parser.error("--topic requires a single post; use --n=1")
    if args.reference_images and args.reference_keys:
        parser.error("use either --reference-image or --reference-key, not both")
    if args.reference_images and args.mode not in {"dry-run", "headshot-test"}:
        parser.error("local reference images can only be used with a dry-run")
    if args.reference_keys and args.mode not in {"dry-run", "headshot-test", "end-to-end"}:
        parser.error("R2 reference keys can only be used with a generation run")
    if args.mode == "headshot-test":
        if args.topic:
            parser.error("headshot-test uses its built-in headshot topic")
        if args.n not in {None, 1}:
            parser.error("headshot-test always generates one post")
        if not args.reference_images and not args.reference_keys:
            parser.error("headshot-test requires --reference-image or --reference-key")
        args.n = 1
    elif args.n is None:
        args.n = 1 if args.topic else 3
    return args


def format_buffer_insights_report(result: dict[str, Any]) -> str:
    """Render a compact per-channel Buffer metrics report."""

    window = result["window"]
    lines = [
        "BUFFER INSIGHTS — LAST 30 DAYS",
        "==============================",
        f"Window: {window['start']} to {window['end']}",
        f"Channels: {result['channel_count']}",
    ]
    analysis_status = result.get("performance_analysis_status")
    analysis = result.get("performance_analysis")
    if analysis_status:
        lines.extend(["", "LUNA PERFORMANCE ANALYSIS", f"Status: {analysis_status}"])
        if analysis:
            lines.extend(
                [
                    f"Confidence: {analysis['confidence']}",
                    f"Data quality: {analysis['data_quality']}",
                    f"Overview: {analysis['overview']}",
                    "Cross-channel patterns:",
                    *(f"  - {item}" for item in analysis["cross_channel_patterns"]),
                    "Next-post actions:",
                    *(f"  - {item}" for item in analysis["next_post_actions"]),
                    "Experiments:",
                    *(f"  - {item}" for item in analysis["experiments"]),
                    "Avoid:",
                    *(f"  - {item}" for item in analysis["avoid"]),
                ]
            )
            for channel_insight in analysis["channel_insights"]:
                lines.extend(
                    [
                        "",
                        f"{channel_insight['channel_service'].upper()} RECOMMENDATIONS",
                        channel_insight["summary"],
                        *(f"  - {item}" for item in channel_insight["recommendations"]),
                    ]
                )
        elif result.get("performance_analysis_error"):
            lines.append(f"Reason: {result['performance_analysis_error']}")
    for channel in result["channels"]:
        label = channel["display_name"] or channel["name"] or channel["id"]
        details = " / ".join(value for value in (channel["service"], channel["name"]) if value)
        lines.extend(["", label + (f" ({details})" if details else "")])
        lines.append(f"Metrics updated: {channel['metrics_updated_at'] or 'not yet available'}")
        if not channel["metrics"]:
            lines.append("  No metrics returned.")
            continue
        for metric in channel["metrics"]:
            suffix = "%" if metric["unit"] == "percentage" else f" {metric['unit']}"
            lines.append(f"  {metric['name']}: {metric['value']:g}{suffix}")
        lines.extend(["", f"  POSTS ({channel['post_count']})"])
        for index, post in enumerate(channel["posts"], start=1):
            published_at = post["sent_at"] or post["due_at"] or post["created_at"]
            lines.extend(
                [
                    "",
                    f"  {index}. {published_at}",
                    f"     ID: {post['id']}",
                    f"     Link: {post['external_link'] or 'not available'}",
                    f"     Metrics updated: {post['metrics_updated_at'] or 'not yet available'}",
                    "     Copy:",
                    *(f"       {line}" if line else "" for line in post["text"].splitlines()),
                    "     Metrics:",
                ]
            )
            if post["metrics"]:
                for metric in post["metrics"]:
                    suffix = "%" if metric["unit"] == "percentage" else f" {metric['unit']}"
                    lines.append(f"       {metric['name']}: {metric['value']:g}{suffix}")
            else:
                lines.append("       No metrics returned.")
    return "\n".join(lines)


def _display_schedule(value: str) -> str:
    due_at = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(PACIFIC)
    hour = due_at.strftime("%I").lstrip("0")
    return due_at.strftime(f"%A, %b %d at {hour}:%M %p %Z")


def _file_link(path: str, *, hyperlinks: bool) -> str:
    if not hyperlinks:
        return path
    absolute = Path(path).resolve()
    return f"\033]8;;{absolute.as_uri()}\033\\{path}\033]8;;\033\\"


def _kitty_icat_command() -> list[str] | None:
    """Return Kitty's image-display command when running inside Kitty."""

    is_kitty = bool(os.environ.get("KITTY_WINDOW_ID")) or os.environ.get("TERM") == "xterm-kitty"
    if not is_kitty or not sys.stdout.isatty():
        return None
    kitten = shutil.which("kitten")
    if kitten:
        return [kitten, "icat"]
    kitty = shutil.which("kitty")
    if kitty:
        return [kitty, "+kitten", "icat"]
    candidates = (
        Path("/Applications/kitty.app/Contents/MacOS/kitten"),
        Path.home() / "Applications/kitty.app/Contents/MacOS/kitten",
        Path.home() / ".local/kitty.app/bin/kitten",
    )
    for candidate in candidates:
        if candidate.is_file():
            return [str(candidate), "icat"]
    return None


async def display_generated_images(result: dict[str, Any]) -> int:
    """Render local dry-run images inline through Kitty when supported."""

    command = _kitty_icat_command()
    paths = [
        image["local_path_absolute"]
        for image in result.get("generated_images", [])
        if image.get("local_path_absolute")
    ]
    if command is None or not paths:
        return 0
    print("\nKITTY IMAGE PREVIEWS")
    process = await asyncio.create_subprocess_exec(
        *command,
        "--stdin=no",
        "--align=left",
        *paths,
    )
    return len(paths) if await process.wait() == 0 else 0


def format_run_report(result: dict[str, Any], *, hyperlinks: bool = False) -> str:
    """Render a compact, post-first report for a human validating a local run."""

    topics = result["topics"]
    drafts = result["drafts"]
    buffer_inputs = result["buffer_inputs"]
    deliveries = len(buffer_inputs)
    dry_run = result["mode"] == "dry-run"
    title = "DRY RUN — NOTHING WAS PUBLISHED" if dry_run else "END-TO-END RUN COMPLETE"
    lines = [
        title,
        "=" * len(title),
        (
            f"{len(drafts)} posts | {result['channel_count']} channels | "
            f"{deliveries} scheduled deliveries"
        ),
        "Validation: PASSED",
    ]
    if dry_run:
        lines.append("D1 topics remain unused; no Buffer drafts or R2 objects were created.")
        lines.append(f"GPT Image 2 files saved locally: {result['images_generated']}")
    else:
        keyword_status = (
            "skipped by flag"
            if result.get("keyword_update_skipped")
            else "yes"
            if result["used_at_updated"]
            else "no"
        )
        lines.append(
            f"Buffer scheduled drafts created: {result['buffer_posts_created']} | "
            f"D1 keywords marked used: {keyword_status}"
        )
        lines.append("Manual action required in Buffer: review each draft and click Schedule Post.")

    analysis_status = result.get("performance_analysis_status")
    analysis = result.get("performance_analysis")
    if analysis_status:
        lines.extend(["", "PERFORMANCE FEEDBACK", f"Status: {analysis_status}"])
        summary = result.get("buffer_insights_summary")
        if summary:
            lines.append(
                f"Analyzed: {summary['post_count']} posts across "
                f"{summary['channel_count']} channels"
            )
        if analysis:
            lines.extend(
                [
                    f"Confidence: {analysis['confidence']}",
                    analysis["overview"],
                    "Next-post actions:",
                    *(f"  - {action}" for action in analysis["next_post_actions"]),
                ]
            )
        elif result.get("performance_analysis_error"):
            lines.append(f"Fallback reason: {result['performance_analysis_error']}")

    for index, (topic, draft) in enumerate(zip(topics, drafts, strict=True), start=1):
        generation = (
            result.get("draft_generation", [])[index - 1]
            if index <= len(result.get("draft_generation", []))
            else None
        )
        generated_image = (
            result.get("generated_images", [])[index - 1]
            if index <= len(result.get("generated_images", []))
            else None
        )
        post_inputs = [item for item in buffer_inputs if item["topic_id"] == topic["id"]]
        keywords = ", ".join(draft["keywords"])
        buffer_text = f"{draft['description']}\n\nKeywords: {keywords}"
        lines.extend(
            [
                "",
                f"POST {index} OF {len(drafts)} — {_display_schedule(draft['due_at'])}",
                "-" * 72,
                f"Topic [{topic['id']}]: {topic['topic']}",
                f"Length: {len(buffer_text)} characters",
                *(
                    [
                        "Draft recovery: deterministic visual fallback used after "
                        f"{generation['attempts']} attempts"
                    ]
                    if generation and generation["fallback_used"]
                    else [f"Draft recovery: passed on attempt {generation['attempts']}"]
                    if generation and generation["attempts"] > 1
                    else []
                ),
                "",
                "COPY",
                draft["description"],
                "",
                f"KEYWORDS: {keywords}",
                "",
                "IMAGE PROMPT",
                draft["image_prompt"]["headline"],
                draft["image_prompt"]["subject"],
                (
                    "R2 REFERENCES: " + ", ".join(draft.get("reference_image_keys", []))
                    if draft.get("reference_image_keys")
                    else "R2 REFERENCES: none selected"
                ),
                (
                    f"IMAGE: {draft['image_url']}"
                    if draft.get("image_url")
                    else "IMAGE: generated locally for review"
                    if generated_image
                    else "IMAGE: not generated"
                ),
            ]
        )
        if generated_image and generated_image.get("local_path_absolute"):
            lines.append(
                "IMAGE FILE: "
                + _file_link(
                    generated_image["local_path_absolute"],
                    hyperlinks=hyperlinks,
                )
            )
        lines.extend(["", f"CHANNELS ({len(post_inputs)})"])
        for item in post_inputs:
            channel = item["channel"]
            label = channel["display_name"] or channel["name"] or channel["id"]
            details = " / ".join(value for value in (channel["service"], channel["name"]) if value)
            lines.append(f"  - {label}" + (f" ({details})" if details else ""))

    return "\n".join(lines)


async def main() -> None:
    args = parse_args()
    load_env_file()
    if args.mode in {"buffer_state", "buffer_insights"}:
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
            print(
                json.dumps(result, indent=2) if args.json else format_buffer_insights_report(result)
            )
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
        return
    dry_run = args.mode in {"dry-run", "headshot-test"}
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
        skip_keyword_update=args.skip_keyword_update,
        post_count=args.n,
        channel_service=selected_service,
        topic_store=WranglerTopicStore(),
        asset_store=remote_assets if not dry_run else None,
        reference_store=reference_store,
        brand_store=remote_assets,
        local_image_dir=(args.output_dir.resolve() if dry_run else None),
        now=weekly_cron_time(force_non_monday=args.force),
        force_non_monday=args.force,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_run_report(result, hyperlinks=sys.stdout.isatty()))
        if dry_run:
            displayed = await display_generated_images(result)
            if not displayed and sys.stdout.isatty():
                print("Inline preview unavailable; open the image links above.")


if __name__ == "__main__":
    asyncio.run(main())
