from __future__ import annotations

import json
import shlex
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from .config import get_task_config, load_config


class TaskAdapter(Protocol):
    def run(
        self,
        kind: str,
        source_path: Path,
        decoded_path: Path,
        source_bytes: bytes,
        decoded_bytes: bytes,
        task: Mapping[str, Any] | None,
        quality: Mapping[str, Any],
    ) -> dict[str, Any]: ...


def _legacy_task_type(kind: str, task_type: str) -> str:
    aliases = {
        "imgc": "image_classification",
        "imgr": "image_reconstruction",
        "msa": "video_sentiment",
    }
    if task_type in aliases:
        return aliases[task_type]
    if task_type == "reconstruction":
        return {
            "image": "image_reconstruction",
            "video": "video_reconstruction",
        }.get(kind, "text_reconstruction")
    return task_type


def _result_template(
    task_type: str,
    task_config: Mapping[str, Any],
    task: Mapping[str, Any],
) -> dict[str, Any]:
    model = task_config.get("model", {})
    return {
        "task_id": task.get("task_id") or task_config.get("task_id") or task_type,
        "task_type": task_type,
        "semantic_task": task_config.get("semantic_task"),
        "dataset": task_config.get("dataset"),
        "ground_truth": task.get("label") if "label" in task else None,
        "input_type": task_config.get("input_type"),
        "output_type": task.get("output_type") or task_config.get("output_type"),
        "success": False,
        "status": "failed",
        "prediction": None,
        "metrics": {},
        "inference_time_ms": 0.0,
        "model_version": task.get("model_version") or model.get("version", ""),
        "checkpoint": task.get("checkpoint") or model.get("checkpoint"),
        "error": None,
    }


class ConfiguredTaskAdapter:
    """Run post-decode tasks using the UDeepSC-compatible task contract.

    The built-in reconstruction path is dependency-free. Classification and
    sentiment tasks use a configured command so the reference UDeepSC code can
    remain optional and outside the traditional communication package.
    """

    def __init__(self, config: dict[str, Any] | str | Path | None = None):
        self.config = load_config(config) if not isinstance(config, dict) else config

    def run(
        self,
        kind: str,
        source_path: Path,
        decoded_path: Path,
        source_bytes: bytes,
        decoded_bytes: bytes,
        task: Mapping[str, Any] | None,
        quality: Mapping[str, Any],
    ) -> dict[str, Any]:
        task = dict(task or {})
        requested_type = str(task.get("task_type") or "reconstruction")
        task_type = _legacy_task_type(kind, requested_type)
        task_config = get_task_config(self.config, task_type)
        inline_config = task.get("task_config", {})
        if isinstance(inline_config, Mapping):
            task_config.update(inline_config)

        result = _result_template(task_type, task_config, task)
        started = time.perf_counter()
        if task_type in {"image_reconstruction", "video_reconstruction", "text_reconstruction"}:
            result.update(
                {
                    "success": decoded_path.is_file(),
                    "status": "completed" if decoded_path.is_file() else "failed",
                    "prediction": {"output_path": str(decoded_path)},
                    "metrics": dict(quality),
                    "error": None if decoded_path.is_file() else "decoded output does not exist",
                }
            )
        elif task_type in {"image_classification", "video_sentiment"}:
            result = self._run_external(
                result,
                task_config,
                source_path,
                decoded_path,
                task,
            )
        else:
            result.update(
                {
                    "status": "unsupported",
                    "error": f"unsupported task type: {task_type}",
                }
            )
        result["inference_time_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return result

    def _run_external(
        self,
        result: dict[str, Any],
        task_config: Mapping[str, Any],
        source_path: Path,
        decoded_path: Path,
        task: Mapping[str, Any],
    ) -> dict[str, Any]:
        backend = str(task_config.get("backend", "command"))
        command = task.get("command") or task_config.get("command")
        if backend != "command" or not command:
            result.update(
                {
                    "status": "not_configured",
                    "error": "task backend command/checkpoint is not configured",
                }
            )
            return result

        command_args = shlex.split(command, posix=False) if isinstance(command, str) else list(command)
        command_cwd = task_config.get("command_cwd")
        if command_cwd:
            command_cwd_path = Path(str(command_cwd))
            if not command_cwd_path.is_absolute():
                config_path = Path(str(self.config.get("_config_path", Path.cwd())))
                command_cwd_path = config_path.parent / command_cwd_path
            command_cwd_path = command_cwd_path.resolve()
        else:
            command_cwd_path = None
        request = {
            "task_type": result["task_type"],
            "semantic_task": result["semantic_task"],
            "dataset": result["dataset"],
            "input_path": str(decoded_path.resolve()),
            "reference_path": str(source_path.resolve()),
            "task_config": dict(task_config),
            "task_context": dict(task),
        }
        try:
            completed = subprocess.run(
                command_args,
                input=json.dumps(request, ensure_ascii=False),
                text=True,
                capture_output=True,
                check=False,
                timeout=int(task_config.get("timeout_seconds", 300)),
                cwd=str(command_cwd_path) if command_cwd_path else None,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            result.update({"status": "failed", "error": str(exc)})
            return result
        if completed.returncode != 0:
            result.update(
                {
                    "status": "failed",
                    "error": completed.stderr.strip() or f"task command exited with {completed.returncode}",
                }
            )
            return result
        try:
            external_result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            result.update({"status": "failed", "error": f"task command returned invalid JSON: {exc}"})
            return result
        if not isinstance(external_result, Mapping):
            result.update({"status": "failed", "error": "task command result must be a JSON object"})
            return result
        for key in ("prediction", "metrics", "model_version", "checkpoint", "error"):
            if key in external_result:
                result[key] = external_result[key]
        result["success"] = bool(external_result.get("success", True)) and not result.get("error")
        result["status"] = "completed" if result["success"] else "failed"
        return result


def create_task_adapter(config: dict[str, Any] | str | Path | None = None) -> ConfiguredTaskAdapter:
    return ConfiguredTaskAdapter(config)
