"""Run one configured inference command and persist the final result.json."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from traditional_comm_py.runtime import load_config, resolve_path, write_json


def _normalize_for_main_adapter(request):
    """Keep the legacy model-workspace launcher compatible with main adapters."""

    request = dict(request)
    task_type = request.get("task_type")
    task_config = dict(request.get("task_config") or {})
    model = dict(task_config.get("model") or {})
    path_keys = ("input_path", "reference_path")
    for key in path_keys:
        value = request.get(key)
        if value and not Path(value).is_absolute() and Path(value).parts[:1] in (("data",), ("artifacts",)):
            request[key] = str(Path("imagec_and_MMSA") / value)
    checkpoint = model.get("checkpoint")
    if checkpoint and not Path(checkpoint).is_absolute() and Path(checkpoint).parts[:1] == ("artifacts",):
        model["checkpoint"] = str(Path("imagec_and_MMSA") / checkpoint)
    if task_type == "image_classification":
        model.setdefault("source_root", "imagec_and_MMSA")
    if task_type == "video_sentiment":
        model.setdefault("mmsa_source", "imagec_and_MMSA/MMSA")
    task_config["model"] = model
    request["task_config"] = task_config
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description="JSON stdin/stdout communication wrapper")
    parser.add_argument("--config", default=None)
    parser.add_argument("--result-path", default=None)
    args = parser.parse_args()
    config = load_config(args.config)
    request = _normalize_for_main_adapter(json.load(sys.stdin))
    task_type = request.get("task_type")
    if task_type == "image_classification":
        task_cfg = config["image_classification"]
    elif task_type == "video_sentiment":
        task_cfg = config["video_sentiment"]
    else:
        raise ValueError(f"unsupported task_type: {task_type}")
    command = list(task_cfg["command"])
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=str(resolve_path(".")),
        input=json.dumps(request, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    try:
        result = json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError):
        result = {
            "success": False,
            "prediction": None,
            "metrics": {},
            "model_version": task_cfg["model"]["version"],
            "checkpoint": task_cfg["checkpoint"],
            "error": f"inference command produced invalid JSON: {completed.stdout[-500:]}",
        }
    result["inference_time_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
    result_path = resolve_path(args.result_path or config["runtime"]["communication_result"])
    write_json(result_path, result)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
