"""Environment-backed configuration with strict validation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """Raised when a configured value would make automation unsafe."""


@dataclass(frozen=True)
class InputSettings:
    min_action_delay_ms: int = 100
    max_action_delay_ms: int = 500
    tap_random_radius_px: int = 12

    @classmethod
    def from_environment(cls) -> InputSettings:
        settings = cls(
            min_action_delay_ms=_read_integer("MIN_ACTION_DELAY_MS", 100),
            max_action_delay_ms=_read_integer("MAX_ACTION_DELAY_MS", 500),
            tap_random_radius_px=_read_integer("TAP_RANDOM_RADIUS_PX", 12),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.min_action_delay_ms < 0:
            raise ConfigurationError("MIN_ACTION_DELAY_MS must be zero or greater")
        if self.max_action_delay_ms < self.min_action_delay_ms:
            raise ConfigurationError(
                "MAX_ACTION_DELAY_MS must be greater than or equal to "
                "MIN_ACTION_DELAY_MS"
            )
        if self.tap_random_radius_px < 0:
            raise ConfigurationError("TAP_RANDOM_RADIUS_PX must be zero or greater")


@dataclass(frozen=True)
class NavigationSettings:
    state_poll_interval_ms: int = 500
    max_state_observations: int = 3
    max_action_retries: int = 2

    @classmethod
    def from_environment(cls) -> NavigationSettings:
        settings = cls(
            state_poll_interval_ms=_read_integer("STATE_POLL_INTERVAL_MS", 500),
            max_state_observations=_read_integer("MAX_STATE_OBSERVATIONS", 3),
            max_action_retries=_read_integer("MAX_ACTION_RETRIES", 2),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.state_poll_interval_ms < 0:
            raise ConfigurationError("STATE_POLL_INTERVAL_MS must be zero or greater")
        if self.max_state_observations < 1:
            raise ConfigurationError("MAX_STATE_OBSERVATIONS must be at least 1")
        if self.max_action_retries < 0:
            raise ConfigurationError("MAX_ACTION_RETRIES must be zero or greater")


def load_env_file(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.is_file():
        return
    for line_number, raw_line in enumerate(
        env_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigurationError(
                f"invalid environment entry at {env_path}:{line_number}"
            )
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ConfigurationError(
                f"empty environment key at {env_path}:{line_number}"
            )
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _read_integer(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
