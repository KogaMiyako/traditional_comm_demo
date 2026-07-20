"""Small runtime helpers for the downstream inference command adapters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path(__file__).resolve().parent / "config" / "default.json"


def load_config(config_path: Optional[str | Path] = None) -> dict[str, Any]:
    path = Path(config_path) if config_path else DEFAULT_CONFIG
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    config["_config_path"] = str(path)
    return config


def resolve_path(value: str | Path, base: Path = PROJECT_ROOT) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path)


def json_error(message: str, model_version: str = "unknown", checkpoint: str = "") -> dict[str, Any]:
    return {
        "success": False,
        "prediction": None,
        "metrics": {},
        "model_version": model_version,
        "checkpoint": checkpoint,
        "error": message,
    }
