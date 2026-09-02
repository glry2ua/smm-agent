"""Human-readable report rendering for local CLI runs."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from itertools import zip_longest
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


def _channel_label(channel: dict[str, Any]) -> str:
    label = channel["display_name"] or channel["name"] or channel["id"]
    details = " / ".join(value for value in (channel["service"], channel["name"]) if value)
    return label + (f" ({details})" if details else "")


def _metric_lines(metrics: Sequence[dict[str, Any]], indent: str) -> list[str]:
    lines = []
    for metric in metrics:
        suffix = "%" if metric["unit"] == "percentage" else f" {metric['unit']}"
        lines.append(f"{indent}{metric['name']}: {metric['value']:g}{suffix}")
    return lines


def _analysis_section(
    status: str | None,
    analysis: dict[str, Any] | None,
    error: str | None,
    *,
    title: str,
    error_label: str,
    overview_label: str = "Overview: ",
    data_quality: bool = False,
    summary: str | None = None,
    extra_sections: Sequence[tuple[str, str]] = (),
) -> list[str]:
    """Shared performance-analysis block; extra_sections are (header, key) bullet lists."""
    if not status:
        return []
    lines = ["", title, f"Status: {status}"]
    if summary:
        lines.append(summary)
    if analysis:
        lines.append(f"Confidence: {analysis['confidence']}")
        if data_quality:
            lines.append(f"Data quality: {analysis['data_quality']}")
        lines.append(f"{overview_label}{analysis['overview']}")
        for header, key in extra_sections:
            lines.extend([header, *(f"  - {item}" for item in analysis[key])])
    elif error:
        lines.append(f"{error_label}: {error}")
    return lines


def format_buffer_insights_report(result: dict[str, Any]) -> str:
    """Render a compact per-channel Buffer metrics report."""

    window = result["window"]
    lines = [
        "BUFFER INSIGHTS — LAST 30 DAYS",
        "==============================",
        f"Window: {window['start']} to {window['end']}",
        f"Channels: {result['channel_count']}",
    ]
    analysis = result.get("performance_analysis")
    lines.extend(
        _analysis_section(
            result.get("performance_analysis_status"),
            analysis,
            result.get("performance_analysis_error"),
            title="LUNA PERFORMANCE ANALYSIS",
            error_label="Reason",
            data_quality=True,
            extra_sections=(
                ("Cross-channel patterns:", "cross_channel_patterns"),
                ("Next-post actions:", "next_post_actions"),
                ("Experiments:", "experiments"),
                ("Avoid:", "avoid"),
            ),
        )
    )
    if analysis:
        for channel_insight in analysis["channel_insights"]:
            lines.extend(
                [
                    "",
                    f"{channel_insight['channel_service'].upper()} RECOMMENDATIONS",
                    channel_insight["summary"],
                    *(f"  - {item}" for item in channel_insight["recommendations"]),
                ]
            )
    for channel in result["channels"]:
        lines.extend(["", _channel_label(channel)])
        lines.append(f"Metrics updated: {channel['metrics_updated_at'] or 'not yet available'}")
        if not channel["metrics"]:
            lines.append("  No metrics returned.")
            continue
        lines.extend(_metric_lines(channel["metrics"], "  "))
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
                lines.extend(_metric_lines(post["metrics"], "       "))
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


def _post_section(
    index: int,
    total: int,
    topic: dict[str, Any],
    draft: dict[str, Any],
    generation: dict[str, Any] | None,
    generated_image: dict[str, Any] | None,
    post_inputs: list[dict[str, Any]],
    *,
    hyperlinks: bool,
) -> list[str]:
    keywords = ", ".join(draft["keywords"])
    buffer_text = f"{draft['description']}\n\nKeywords: {keywords}"
    lines = [
        "",
        f"POST {index} OF {total} — {_display_schedule(draft['due_at'])}",
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
    if generated_image and generated_image.get("local_path_absolute"):
        lines.append(
            "IMAGE FILE: "
            + _file_link(generated_image["local_path_absolute"], hyperlinks=hyperlinks)
        )
    lines.extend(["", f"CHANNELS ({len(post_inputs)})"])
    for item in post_inputs:
        lines.append(f"  - {_channel_label(item['channel'])}")
    return lines


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
        topic_update_status = (
            "skipped by flag"
            if result.get("topic_update_skipped")
            else "yes"
            if result["used_at_updated"]
            else "no"
        )
        lines.append(
            f"Buffer scheduled drafts created: {result['buffer_posts_created']} | "
            f"D1 topics marked used: {topic_update_status}"
        )
        lines.append("Manual action required in Buffer: review each draft and click Schedule Post.")

    summary = result.get("buffer_insights_summary")
    lines.extend(
        _analysis_section(
            result.get("performance_analysis_status"),
            result.get("performance_analysis"),
            result.get("performance_analysis_error"),
            title="PERFORMANCE FEEDBACK",
            error_label="Fallback reason",
            overview_label="",
            summary=(
                f"Analyzed: {summary['post_count']} posts across "
                f"{summary['channel_count']} channels"
            )
            if summary
            else None,
            extra_sections=(("Next-post actions:", "next_post_actions"),),
        )
    )

    generations = result.get("draft_generation", [])
    generated_images = result.get("generated_images", [])
    for index, (topic, draft, generation, generated_image) in enumerate(
        zip_longest(topics, drafts, generations, generated_images), start=1
    ):
        post_inputs = [item for item in buffer_inputs if item["topic_id"] == topic["id"]]
        lines.extend(
            _post_section(
                index,
                len(drafts),
                topic,
                draft,
                generation,
                generated_image,
                post_inputs,
                hyperlinks=hyperlinks,
            )
        )

    return "\n".join(lines)
