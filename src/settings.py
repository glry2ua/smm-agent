"""Environment-backed configuration for the Worker."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


def env_value(env: Any, name: str) -> str:
    """Read a Worker binding or mapping value without assuming one runtime type."""

    if env is None:
        return ""
    try:
        value = env.get(name, "") if isinstance(env, Mapping) else getattr(env, name, "")
    except Exception as exc:
        raise RuntimeError(f"Unable to read configuration variable {name}") from exc
    if value is None:
        return ""
    return str(value)


def _int(value: str, name: str, *, minimum: int = 0) -> int | None:
    if not value.strip():
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise RuntimeError(f"{name} must be an integer") from None
    if parsed < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}")
    return parsed


def _float(value: str, name: str, *, minimum: float = 0.0) -> float | None:
    if not value.strip():
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise RuntimeError(f"{name} must be a number") from None
    if parsed < minimum:
        raise RuntimeError(f"{name} must be at least {minimum:g}")
    return parsed


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    openai_api_key: str
    openai_image_model: str
    openai_image_width: int | None
    openai_image_height: int | None
    openai_image_quality: str
    buffer_api_key: str
    buffer_organization_id: str
    buffer_api_url: str
    asset_public_base_url: str
    min_schedule_lead_minutes: int | None
    schedule_horizon_days: int | None
    max_post_chars: int | None
    retry_max_attempts: int | None
    retry_backoff_seconds: float | None

    @classmethod
    def from_env(cls, env: Any) -> Settings:
        return cls(
            openai_api_key=env_value(env, "OPENAI_API_KEY"),
            openai_image_model=env_value(env, "OPENAI_IMAGE_MODEL"),
            openai_image_width=_int(
                env_value(env, "OPENAI_IMAGE_WIDTH"),
                "OPENAI_IMAGE_WIDTH",
                minimum=1,
            ),
            openai_image_height=_int(
                env_value(env, "OPENAI_IMAGE_HEIGHT"),
                "OPENAI_IMAGE_HEIGHT",
                minimum=1,
            ),
            openai_image_quality=env_value(env, "OPENAI_IMAGE_QUALITY"),
            buffer_api_key=env_value(env, "BUFFER_API_KEY"),
            buffer_organization_id=env_value(env, "BUFFER_ORGANIZATION_ID"),
            buffer_api_url=env_value(env, "BUFFER_API_URL").rstrip("/"),
            asset_public_base_url=env_value(env, "ASSET_PUBLIC_BASE_URL").rstrip("/"),
            min_schedule_lead_minutes=_int(
                env_value(env, "MIN_SCHEDULE_LEAD_MINUTES"),
                "MIN_SCHEDULE_LEAD_MINUTES",
                minimum=1,
            ),
            schedule_horizon_days=_int(
                env_value(env, "SCHEDULE_HORIZON_DAYS"),
                "SCHEDULE_HORIZON_DAYS",
                minimum=1,
            ),
            max_post_chars=_int(
                env_value(env, "MAX_POST_CHARS"),
                "MAX_POST_CHARS",
                minimum=1,
            ),
            retry_max_attempts=_int(
                env_value(env, "RETRY_MAX_ATTEMPTS"),
                "RETRY_MAX_ATTEMPTS",
                minimum=1,
            ),
            retry_backoff_seconds=_float(
                env_value(env, "RETRY_BACKOFF_SECONDS"),
                "RETRY_BACKOFF_SECONDS",
            ),
        )

    @property
    def openai_image_size(self) -> str:
        """Return the Images API's ASCII WIDTHxHEIGHT representation."""

        if self.openai_image_width is None or self.openai_image_height is None:
            raise RuntimeError(
                "Image configuration is missing OPENAI_IMAGE_WIDTH and/or OPENAI_IMAGE_HEIGHT"
            )
        return f"{self.openai_image_width}x{self.openai_image_height}"

    def _validate_image_dimensions(self) -> None:
        if self.openai_image_model != "gpt-image-2":
            return
        if self.openai_image_width is None or self.openai_image_height is None:
            raise RuntimeError(
                "Image configuration is missing OPENAI_IMAGE_WIDTH and/or OPENAI_IMAGE_HEIGHT"
            )
        width = self.openai_image_width
        height = self.openai_image_height
        if width % 16 or height % 16:
            raise RuntimeError(
                "OPENAI_IMAGE_WIDTH and OPENAI_IMAGE_HEIGHT must both be multiples of 16 "
                "for gpt-image-2"
            )
        if max(width, height) > 3840:
            raise RuntimeError("GPT Image 2 dimensions cannot exceed 3840 pixels per edge")
        if max(width, height) / min(width, height) > 3:
            raise RuntimeError("GPT Image 2's long-to-short edge ratio cannot exceed 3:1")
        pixels = width * height
        if not 655_360 <= pixels <= 8_294_400:
            raise RuntimeError(
                "GPT Image 2 output must contain between 655,360 and 8,294,400 pixels"
            )

    def validate_for_run(self, *, require_images: bool = False) -> None:
        required = {
            "OPENAI_API_KEY": self.openai_api_key,
            "OPENAI_IMAGE_MODEL": self.openai_image_model,
            "OPENAI_IMAGE_WIDTH": self.openai_image_width,
            "OPENAI_IMAGE_HEIGHT": self.openai_image_height,
            "OPENAI_IMAGE_QUALITY": self.openai_image_quality,
            "BUFFER_API_KEY": self.buffer_api_key,
            "BUFFER_ORGANIZATION_ID": self.buffer_organization_id,
            "BUFFER_API_URL": self.buffer_api_url,
            "MIN_SCHEDULE_LEAD_MINUTES": self.min_schedule_lead_minutes,
            "SCHEDULE_HORIZON_DAYS": self.schedule_horizon_days,
            "MAX_POST_CHARS": self.max_post_chars,
            "RETRY_MAX_ATTEMPTS": self.retry_max_attempts,
            "RETRY_BACKOFF_SECONDS": self.retry_backoff_seconds,
        }
        if require_images:
            required["ASSET_PUBLIC_BASE_URL"] = self.asset_public_base_url
        missing = [name for name, value in required.items() if _missing(value)]
        if missing:
            raise RuntimeError(
                "Worker configuration is missing required environment variable(s): "
                + ", ".join(missing)
            )
        if self.openai_image_quality not in {"low", "medium", "high", "auto"}:
            raise RuntimeError("OPENAI_IMAGE_QUALITY must be one of: low, medium, high, auto")
        self._validate_image_dimensions()

    def validate_for_images(self) -> None:
        required = {
            "OPENAI_API_KEY": self.openai_api_key,
            "OPENAI_IMAGE_MODEL": self.openai_image_model,
            "OPENAI_IMAGE_WIDTH": self.openai_image_width,
            "OPENAI_IMAGE_HEIGHT": self.openai_image_height,
            "OPENAI_IMAGE_QUALITY": self.openai_image_quality,
            "ASSET_PUBLIC_BASE_URL": self.asset_public_base_url,
        }
        missing = [name for name, value in required.items() if _missing(value)]
        if missing:
            raise RuntimeError(
                "Image publishing configuration is missing required environment variable(s): "
                + ", ".join(missing)
            )
        if self.openai_image_quality not in {"low", "medium", "high", "auto"}:
            raise RuntimeError("OPENAI_IMAGE_QUALITY must be one of: low, medium, high, auto")
        try:
            parsed = urlsplit(self.asset_public_base_url)
        except ValueError:
            raise RuntimeError("ASSET_PUBLIC_BASE_URL must be a valid HTTPS URL") from None
        if parsed.scheme != "https" or not parsed.hostname:
            raise RuntimeError("ASSET_PUBLIC_BASE_URL must be an HTTPS URL with a hostname")
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise RuntimeError(
                "ASSET_PUBLIC_BASE_URL must be the Worker origin without a path, query, or fragment"
            )
        self._validate_image_dimensions()

    def validate_for_buffer(self) -> None:
        required = {
            "BUFFER_API_KEY": self.buffer_api_key,
            "BUFFER_ORGANIZATION_ID": self.buffer_organization_id,
            "BUFFER_API_URL": self.buffer_api_url,
        }
        missing = [name for name, value in required.items() if _missing(value)]
        if missing:
            raise RuntimeError(
                "Buffer configuration is missing required environment variable(s): "
                + ", ".join(missing)
            )

    def validate_for_buffer_analysis(self) -> None:
        """Validate credentials used by the read-only Buffer + Luna analysis path."""

        self.validate_for_buffer()
        required = {
            "OPENAI_API_KEY": self.openai_api_key,
        }
        missing = [name for name, value in required.items() if not value.strip()]
        if missing:
            raise RuntimeError(
                "Buffer analysis is missing required environment variable(s): " + ", ".join(missing)
            )
