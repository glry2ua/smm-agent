"""Inline Kitty image previews for local dry-run outputs."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path
from typing import Any


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
