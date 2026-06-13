"""Shared JSON configuration helpers for WCRC command-line tools."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json_config(path: str | None) -> tuple[dict[str, Any], Path | None]:
    if not path:
        return {}, None

    config_path = Path(path).expanduser().resolve()
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"cannot read config file {config_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in config file {config_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise SystemExit(f"config file must contain a JSON object: {config_path}")
    return data, config_path


def option_value(args: argparse.Namespace, config: dict[str, Any], name: str, default: Any = None) -> Any:
    value = getattr(args, name, None)
    return value if value is not None else config.get(name, default)


def int_option(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    config: dict[str, Any],
    name: str,
    default: int | None = None,
) -> int | None:
    value = option_value(args, config, name, default)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        parser.error(f"{name} must be an integer")


def bool_option(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    config: dict[str, Any],
    name: str,
    default: bool = False,
) -> bool:
    value = option_value(args, config, name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    parser.error(f"{name} must be true or false")


def resolve_local_path(value: str | None, config_path: Path | None) -> str | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute() and config_path is not None:
        path = config_path.parent / path
    return str(path)
