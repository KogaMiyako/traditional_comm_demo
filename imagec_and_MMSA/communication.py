"""Run one configured inference command and persist the final result.json."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

from traditional_comm_py.runtime import load_config, resolve_path, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="JSON stdin/stdout communication wrapper")
    parser.add_argument("--config", default=None)
    parser.add_argument("--result-path", default=None)
    args = parser.parse_args()
    config = load_config(args.config)
    request = json.load(sys.stdin)
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
