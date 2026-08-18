"""Load agent definitions from Markdown files with YAML-like frontmatter."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

AGENTS_DIRECTORY = Path(__file__).resolve().parent.parent / "agents"
_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
_THINKING_LEVELS = {"none", "minimal", "low", "medium", "high", "xhigh"}


class AgentConfigError(ValueError):
    """Raised when an agent Markdown file is missing or malformed."""


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """The metadata and instruction template for one runtime agent."""

    name: str
    description: str
    model: str
    thinking: str | None
    verbosity: str | None
    instructions: str

    def model_settings(self) -> Any:
        """Build SDK model settings from the Markdown metadata."""

        if self.thinking is None and self.verbosity is None:
            return None

        from openai.types.shared import Reasoning

        from agents import ModelSettings

        values: dict[str, Any] = {}
        if self.thinking is not None and self.thinking != "none":
            values["reasoning"] = Reasoning(effort=self.thinking)
        if self.verbosity is not None:
            values["verbosity"] = self.verbosity
        return ModelSettings(**values)


def _metadata_and_body(text: str, path: Path) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        raise AgentConfigError(f"{path} must start with frontmatter delimiter ---")

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise AgentConfigError(f"{path} must start with frontmatter delimiter ---")
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        raise AgentConfigError(f"{path} has unterminated frontmatter") from None

    metadata: dict[str, str] = {}
    for line_number, line in enumerate(lines[1:end], start=2):
        if not line.strip():
            continue
        if ":" not in line:
            raise AgentConfigError(f"{path}:{line_number} must contain a metadata key and value")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise AgentConfigError(f"{path}:{line_number} has an empty metadata key or value")
        if key in metadata:
            raise AgentConfigError(f"{path}:{line_number} duplicates metadata key {key!r}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        metadata[key] = value

    body = "\n".join(lines[end + 1 :]).strip()
    if not body:
        raise AgentConfigError(f"{path} has no instruction body")
    return metadata, body


def _parse_model(raw_model: str, path: Path) -> tuple[str, str | None]:
    model, separator, thinking = raw_model.partition("#")
    if not model.strip():
        raise AgentConfigError(f"{path} has an empty model")
    if separator and thinking not in _THINKING_LEVELS:
        allowed = ", ".join(sorted(_THINKING_LEVELS))
        raise AgentConfigError(
            f"{path} has unsupported thinking level {thinking!r}; expected one of: {allowed}"
        )
    return model.strip(), thinking.strip() if separator else None


def load_agent(name: str, *, directory: Path = AGENTS_DIRECTORY) -> AgentConfig:
    """Load ``<directory>/<name>.md`` and validate its frontmatter."""

    path = directory / f"{name}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise AgentConfigError(f"Agent definition not found: {path}") from None
    except OSError as exc:
        raise AgentConfigError(f"Unable to read agent definition {path}: {exc}") from exc

    metadata, instructions = _metadata_and_body(text, path)
    unknown = set(metadata) - {"description", "model", "verbosity"}
    if unknown:
        raise AgentConfigError(
            f"{path} has unsupported metadata key(s): {', '.join(sorted(unknown))}"
        )
    for key in ("description", "model"):
        if key not in metadata:
            raise AgentConfigError(f"{path} is missing required metadata key {key!r}")

    model, thinking = _parse_model(metadata["model"], path)
    verbosity = metadata.get("verbosity")
    if verbosity is not None and verbosity not in {"low", "medium", "high"}:
        raise AgentConfigError(f"{path} has unsupported verbosity {verbosity!r}")
    return AgentConfig(
        name=name,
        description=metadata["description"],
        model=model,
        thinking=thinking,
        verbosity=verbosity,
        instructions=instructions,
    )


def render_agent(
    name: str,
    values: dict[str, object],
    *,
    directory: Path = AGENTS_DIRECTORY,
) -> str:
    """Render an agent's ``{{placeholder}}`` values into its instructions."""

    config = load_agent(name, directory=directory)

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise AgentConfigError(f"Agent {name!r} requires missing template value {key!r}")
        return str(values[key])

    rendered = _PLACEHOLDER.sub(replace, config.instructions)
    return rendered
