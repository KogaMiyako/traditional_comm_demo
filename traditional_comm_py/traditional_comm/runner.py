from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
import tracemalloc
import uuid

from .codecs import codec_info, decode_payload, encode_payload
from .samples import parse_ppm, parse_tvid
from .task_adapter import TaskAdapter, create_task_adapter
from .task_metrics import quality_metrics


def create_run_id(kind: str) -> str:
    return f"traditional-{kind}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validate(kind: str, output: bytes) -> tuple[bool, dict]:
    if kind == "text":
        output.decode("utf-8")
        return True, {"format": "txt", "encoding": "utf-8"}
    if kind == "image":
        info = parse_ppm(output)
        return True, {
            "format": "ppm",
            "width": info["width"],
            "height": info["height"],
        }
    info = parse_tvid(output)
    return True, {
        "format": "tvid-decoded-frames",
        "width": info["width"],
        "height": info["height"],
        "fps": info["fps"],
        "frame_count": info["frame_count"],
    }


def _quality_metrics(kind: str, source: bytes, output: bytes) -> dict:
    return quality_metrics(kind, source, output)


def _codec_config(kind: str, encoded) -> dict:
    config = codec_info(kind)
    config.update(
        {
            "name": encoded.codec,
            "container": encoded.container,
            "encoder": encoded.metadata.get("encoder"),
            "parameters": encoded.metadata.get("parameters", {}),
            "metadata": encoded.metadata,
        }
    )
    return config


def run_one(
    kind: str,
    input_path: Path,
    runs_dir: Path,
    transport,
    task: dict | None = None,
    run_id: str | None = None,
    codec_options: dict | None = None,
    task_adapter: TaskAdapter | None = None,
) -> dict:
    task = task or {}
    task_adapter = task_adapter or create_task_adapter()
    run_id = run_id or create_run_id(kind)
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    input_data = input_path.read_bytes()
    input_hash = sha256(input_data)
    tracemalloc.start()
    process_start = time.process_time()
    started_at = time.time()

    encode_start = time.perf_counter()
    encoded = encode_payload(kind, input_data, codec_options)
    encode_ms = (time.perf_counter() - encode_start) * 1000

    transport_start = time.perf_counter()
    received, transport_stats = transport.send_payload(
        encoded.payload,
        {
            "run_id": run_id,
            "mode": "traditional",
            "sample_id": input_path.name,
            "task_id": task.get("task_id"),
            "media_type": kind,
            "codec": encoded.codec,
            "container": encoded.container,
            "codec_metadata": encoded.metadata,
            "payload_size": len(encoded.payload),
            "expected_total_bytes": len(encoded.payload),
            "sequence_id": 0,
            "channel": task.get("channel", {}),
            "nodes": task.get("nodes", {}),
        },
    )
    transport_ms = (time.perf_counter() - transport_start) * 1000

    received_path = run_dir / f"received_payload.{encoded.container}"
    received_path.write_bytes(received)
    encoded_path = run_dir / f"encoded_payload.{encoded.container}"
    encoded_path.write_bytes(encoded.payload)

    decode_start = time.perf_counter()
    output = decode_payload(kind, received, encoded.metadata)
    decode_ms = (time.perf_counter() - decode_start) * 1000
    valid, validation = _validate(kind, output)
    receiver_decode_valid = transport_stats.get("receiver_decode_valid", True)
    valid = bool(valid and receiver_decode_valid is not False)

    output_extension = {"text": "txt", "image": "jpg", "video": "mp4"}[kind]
    output_path = run_dir / f"output.{output_extension}"
    output_path.write_bytes(received)
    decoded_path = run_dir / {"text": "decoded.txt", "image": "decoded.ppm", "video": "decoded.tvid"}[kind]
    decoded_path.write_bytes(output)

    output_hash = sha256(output)
    content_match = input_hash == output_hash if kind == "text" else None
    input_bytes = len(input_data)
    encoded_bytes = len(encoded.payload)
    reduction = (input_bytes - encoded_bytes) / input_bytes if input_bytes else 0
    total_latency_ms = encode_ms + transport_ms + decode_ms
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    process_cpu_ms = (time.process_time() - process_start) * 1000
    quality = _quality_metrics(kind, input_data, output)
    task_result = task_adapter.run(
        kind=kind,
        source_path=input_path,
        decoded_path=decoded_path,
        source_bytes=input_data,
        decoded_bytes=output,
        task=task,
        quality=quality,
    )
    task_ok = bool(task_result.get("success", False))

    config = {
        "run_id": run_id,
        "mode": "traditional",
        "media_type": kind,
        "input_path": str(input_path.resolve()),
        "input_sha256": input_hash,
        "sample": {
            "sample_id": input_path.name,
            "path": str(input_path.resolve()),
            "media_type": kind,
            "original_format": input_path.suffix.lstrip("."),
            "checksum": input_hash,
        },
        "task": task,
        "codec": _codec_config(kind, encoded),
        "channel": task.get("channel", {}),
        "nodes": task.get("nodes", {}),
        "system": task.get("system", {}),
        "transport": transport_stats.get("transport", type(transport).__name__),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_at)),
    }
    metrics = {
        "run_id": run_id,
        "mode": "traditional",
        "media_type": kind,
        "codec": encoded.codec,
        "container": encoded.container,
        "input_bytes": input_bytes,
        "encoded_payload_bytes": encoded_bytes,
        "actual_sent_bytes": transport_stats["sent_bytes"],
        "actual_received_bytes": transport_stats["received_bytes"],
        "actual_link_total_bytes": transport_stats.get(
            "actual_link_total_bytes",
            transport_stats["sent_bytes"],
        ),
        "data_reduction_ratio": round(reduction, 6),
        "encode_time_ms": round(encode_ms, 3),
        "transport_time_ms": round(transport_ms, 3),
        "decode_time_ms": round(decode_ms, 3),
        "end_to_end_latency_ms": round(total_latency_ms, 3),
        "average_throughput_mbps": transport_stats["average_throughput_mbps"],
        "peak_throughput_mbps": transport_stats["peak_throughput_mbps"],
        "receiver_decode_time_ms": transport_stats.get("receiver_decode_time_ms"),
        "receiver_decode_valid": receiver_decode_valid,
        "receiver_result_path": transport_stats.get("receiver_result_path"),
        "quality": quality,
        "task": {
            "content_match": content_match,
            "output_valid": int(valid),
            "task_result": task_result,
        },
        "resource": {
            "python_process_cpu_ms": round(process_cpu_ms, 3),
            "tracemalloc_current_bytes": current,
            "tracemalloc_peak_bytes": peak,
            "gpu_usage": None,
        },
        "status": "completed" if valid and task_ok else "failed",
    }
    _write_json(run_dir / "config.json", config)
    _write_json(run_dir / "metrics.json", metrics)
    _write_json(run_dir / "transport.json", transport_stats)
    _write_json(
        run_dir / "result.json",
        {
            "run_id": run_id,
            "encoded_path": str(encoded_path),
            "received_path": str(received_path),
            "output_path": str(output_path),
            "decoded_path": str(decoded_path),
            "output_sha256": output_hash,
            "content_match": content_match,
            "validation": validation,
            "receiver_decode_valid": receiver_decode_valid,
            "receiver_result_path": transport_stats.get("receiver_result_path"),
            "task_result": task_result,
        },
    )
    return {
        "run_id": run_id,
        "run_dir": run_dir,
        "kind": kind,
        "metrics": metrics,
        "output_path": output_path,
    }


def run_task_only(
    kind: str,
    input_path: Path,
    runs_dir: Path,
    task: dict | None = None,
    run_id: str | None = None,
    task_adapter: TaskAdapter | None = None,
) -> dict:
    """Run a downstream task directly on a task-compatible input file.

    This is used for feature-level datasets such as MOSEI.  A MOSEI ``.pkl``
    feature sample is not an encoded video container, so it must not be sent
    through the H.264/MP4 transport path.  The result still uses the same
    run directory and task-result schema as a normal communication run.
    """

    task = task or {}
    task_adapter = task_adapter or create_task_adapter()
    run_id = run_id or create_run_id(f"task-{kind}")
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    input_path = input_path.resolve()
    input_data = input_path.read_bytes()
    task_result = task_adapter.run(
        kind=kind,
        source_path=input_path,
        decoded_path=input_path,
        source_bytes=input_data,
        decoded_bytes=input_data,
        task=task,
        quality={},
    )
    status = "completed" if task_result.get("success") else "failed"
    config = {
        "run_id": run_id,
        "mode": "traditional",
        "execution": "task-only",
        "media_type": kind,
        "input_path": str(input_path),
        "task": task,
        "transport": None,
        "note": "No media codec or transport was run; input is already task-compatible.",
    }
    metrics = {
        "run_id": run_id,
        "mode": "traditional",
        "execution": "task-only",
        "media_type": kind,
        "input_bytes": len(input_data),
        "encoded_payload_bytes": None,
        "actual_sent_bytes": None,
        "actual_received_bytes": None,
        "end_to_end_latency_ms": task_result.get("inference_time_ms"),
        "task": {"task_result": task_result},
        "status": status,
    }
    _write_json(run_dir / "config.json", config)
    _write_json(run_dir / "metrics.json", metrics)
    _write_json(run_dir / "result.json", {"run_id": run_id, "input_path": str(input_path), "task_result": task_result})
    return {"run_id": run_id, "run_dir": run_dir, "kind": kind, "metrics": metrics, "output_path": input_path}


def run_all(
    samples_dir: Path,
    runs_dir: Path,
    transport,
    task: dict | None = None,
    codec_options: dict | None = None,
    task_adapter: TaskAdapter | None = None,
) -> list[dict]:
    runs_dir.mkdir(parents=True, exist_ok=True)
    inputs = {
        "text": samples_dir / "sample.txt",
        "image": samples_dir / "sample.ppm",
        "video": samples_dir / "sample.tvid",
    }
    missing = [str(path) for path in inputs.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing samples: " + ", ".join(missing))
    return [
        run_one(
            kind,
            path,
            runs_dir,
            transport,
            task,
            codec_options=codec_options,
            task_adapter=task_adapter,
        )
        for kind, path in inputs.items()
    ]
