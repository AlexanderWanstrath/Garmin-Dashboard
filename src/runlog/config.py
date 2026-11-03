"""Load the local config.yaml, which holds personal settings and never enters git."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config.yaml")


class ConfigError(Exception):
    """The config file is missing or malformed."""


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"{path} not found: copy config.example.yaml to {path.name} and fill in your values")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    # Relative paths in the config mean "next to the config file", not "in the working directory".
    data[BASE_KEY] = str(path.resolve().parent)
    return data


BASE_KEY = "_config_dir"


def _resolve(config: dict[str, Any], value: str) -> Path:
    return Path(config.get(BASE_KEY) or ".") / value


def data_dir(config: dict[str, Any]) -> Path:
    return _resolve(config, (config.get("paths") or {}).get("data_dir") or "data")


def plan_path(config: dict[str, Any]) -> Path:
    return _resolve(config, (config.get("paths") or {}).get("plan_file") or "plan.yaml")


def sync_start_date(config: dict[str, Any]) -> date | None:
    value = (config.get("sync") or {}).get("start_date")
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ConfigError(f"sync.start_date must be a date like 2026-09-01, got {value!r}") from exc
