from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config" / "default.json"


def _resolve_path(
    value: str | Path | None,
    base: Path,
    preserve_final_symlink: bool = False,
) -> str | None:
    if value is None:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    # Keep the configured project-level ``dataset`` link visible for callers
    # and tests, while concrete dataset paths below still resolve normally.
    return str(path.absolute() if preserve_final_symlink else path.resolve())


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load the JSON configuration and resolve all project-relative paths."""
    config_path = Path(path or DEFAULT_CONFIG_PATH).resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"configuration file does not exist: {config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config = copy.deepcopy(config)
    config["_config_path"] = str(config_path)
    config_base = config_path.parent

    paths = config.setdefault("paths", {})
    for key in (
        "dataset_root",
        "samples_dir",
        "materialized_samples_dir",
        "runs_dir",
        "receiver_runs_dir",
        "model_dir",
    ):
        if key in paths:
            paths[key] = _resolve_path(
                paths[key],
                config_base,
                preserve_final_symlink=key == "dataset_root",
            )

    dataset_root = Path(paths["dataset_root"])
    for dataset_config in config.setdefault("datasets", {}).values():
        if "root" in dataset_config:
            dataset_config["root"] = _resolve_path(dataset_config["root"], dataset_root)

    return config


def get_task_config(config: dict[str, Any], task_type: str) -> dict[str, Any]:
    tasks = config.get("tasks", {})
    if task_type not in tasks:
        raise KeyError(f"task is not configured: {task_type}")
    return copy.deepcopy(tasks[task_type])


def get_dataset_config(config: dict[str, Any], dataset_name: str) -> dict[str, Any]:
    datasets = config.get("datasets", {})
    if dataset_name not in datasets:
        raise KeyError(f"dataset is not configured: {dataset_name}")
    return copy.deepcopy(datasets[dataset_name])
