"""Shared runtime helpers.

The command line programs deliberately keep stdout machine-readable.  Human
diagnostics belong on stderr or in the configured log files.
"""

from __future__ import annotations

import importlib.metadata
import json
import logging
import os
import platform
import random
import sys
import math
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "traditional_comm_py" / "config" / "default.json"


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    path = Path(config_path) if config_path else DEFAULT_CONFIG
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    config["_config_path"] = str(path.resolve())
    return config


def resolve_path(value: str | Path, base: Path = PROJECT_ROOT) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Any) -> None:
    ensure_parent(path)
    payload = _json_safe(payload)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (int, str, bool)) or value is None:
        return value
    if isinstance(value, np.integer):
        return int(value)
    return str(value)


def setup_logging(log_path: Path, name: str) -> logging.Logger:
    ensure_parent(log_path)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    except ImportError:
        pass


def environment_info(extra_packages: Iterable[str] = ()) -> Dict[str, Any]:
    package_names = ["numpy", "Pillow", "scikit-learn", "torch", "torchvision", "MMSA"]
    package_names.extend(extra_packages)
    packages: Dict[str, str] = {}
    for name in package_names:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not-installed"
    try:
        import torch

        torch_info = {
            "version": torch.__version__,
            "cuda_available": bool(torch.cuda.is_available()),
            "cuda_version": torch.version.cuda,
        }
    except ImportError:
        torch_info = {"version": None, "cuda_available": False, "cuda_version": None}
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "working_directory": os.getcwd(),
        "packages": packages,
        "torch": torch_info,
    }


def json_error(message: str, model_version: str = "unknown", checkpoint: str = "") -> Dict[str, Any]:
    return {
        "success": False,
        "prediction": None,
        "metrics": {},
        "model_version": model_version,
        "checkpoint": checkpoint,
        "error": message,
    }
