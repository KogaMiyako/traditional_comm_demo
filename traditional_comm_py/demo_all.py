"""Run the complete local traditional-communication demonstration.

The script intentionally keeps all progress messages on stderr and emits one
JSON summary on stdout.  It covers:

* local loopback image reconstruction and CIFAR-10 classification;
* local video reconstruction smoke test;
* local feature-level MOSEI sentiment inference;
* two real localhost TCP endpoints: image tasks on one port and MOSEI
  feature transfer/inference on a different port.

Run it from this directory with the same Python environment used by the
inference adapters, for example ``python demo_all.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from traditional_comm.config import get_task_config, load_config
from traditional_comm.dataset_adapter import materialize_cifar10_sample, select_cifar10_sample
from traditional_comm.samples import generate_samples


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config" / "default.json"
FEATURE_PROTOCOL = "mosei-feature-tcp-v1"
HEADER_LENGTH = struct.Struct("!I")
MAX_HEADER_BYTES = 1024 * 1024
MAX_PAYLOAD_BYTES = 512 * 1024 * 1024
ARTIFACT_RE = re.compile(r"(?:Task|Sender) artifacts saved in (.+)")


def _log(message: str) -> None:
    print(f"[demo] {message}", file=sys.stderr, flush=True)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _resolve_demo_path(value: str | Path, config_path: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def _run_cli(config_path: Path, args: list[str | Path], label: str) -> Path:
    """Run an existing traditional_comm CLI command and return its run dir."""

    values = [str(value) for value in args]
    command = [sys.executable, "-u", "-m", "traditional_comm.cli", values[0], "--config", str(config_path)]
    command.extend(values[1:])
    _log(f"开始 {label}")
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"{label} 失败 (exit={completed.returncode}): {details}")
    matches = ARTIFACT_RE.findall(completed.stdout)
    if not matches:
        raise RuntimeError(f"{label} 未找到运行目录，CLI 输出为: {completed.stdout.strip()}")
    run_dir = Path(matches[-1].strip())
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    run_dir = run_dir.resolve()
    if not run_dir.is_dir():
        raise RuntimeError(f"{label} 的运行目录不存在: {run_dir}")
    _log(f"完成 {label}: {run_dir}")
    return run_dir


def _artifact_summary(run_dir: Path) -> dict[str, Any]:
    result_path = run_dir / "result.json"
    metrics_path = run_dir / "metrics.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
    metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.is_file() else {}
    task_result = result.get("task_result")
    if task_result is None:
        task_result = metrics.get("task", {}).get("task_result")
    return {
        "run_dir": str(run_dir),
        "result_path": str(result_path),
        "metrics_path": str(metrics_path) if metrics_path.is_file() else None,
        "success": bool(task_result.get("success")) if isinstance(task_result, dict) else None,
        "prediction": task_result.get("prediction") if isinstance(task_result, dict) else None,
        "metrics": task_result.get("metrics", {}) if isinstance(task_result, dict) else {},
        "model_version": task_result.get("model_version") if isinstance(task_result, dict) else None,
        "checkpoint": task_result.get("checkpoint") if isinstance(task_result, dict) else None,
        "inference_time_ms": task_result.get("inference_time_ms") if isinstance(task_result, dict) else None,
    }


def _ensure_cifar_sample(config: dict[str, Any]) -> tuple[Path, int, str | None]:
    dataset_config = config["datasets"]["cifar10"]
    sample = select_cifar10_sample(
        dataset_config["root"],
        split="test",
        mode="index",
        index=0,
        samples_per_file=int(dataset_config.get("samples_per_file", 10000)),
    )
    path = materialize_cifar10_sample(sample, config["paths"]["materialized_samples_dir"])
    return path, sample.label, sample.label_name


def _run_loopback(config_path: Path, config: dict[str, Any], output_dir: Path, mosei_path: Path) -> dict[str, Any]:
    samples_dir = Path(config["paths"]["samples_dir"])
    generate_samples(samples_dir)
    runs_dir = output_dir / "loopback"
    results: dict[str, Any] = {}

    image_reconstruction = _run_cli(
        config_path,
        [
            "task-run",
            "--kind",
            "image",
            "--input",
            samples_dir / "sample.ppm",
            "--task-type",
            "image_reconstruction",
            "--task-id",
            "demo-loopback-image-reconstruction",
            "--runs",
            runs_dir / "image_reconstruction",
        ],
        "本地回环-图像重建",
    )
    results["image_reconstruction"] = _artifact_summary(image_reconstruction)

    image_classification = _run_cli(
        config_path,
        [
            "task-run",
            "--kind",
            "image",
            "--dataset",
            "cifar10",
            "--task-type",
            "image_classification",
            "--sample-mode",
            "index",
            "--sample-index",
            "0",
            "--task-id",
            "demo-loopback-image-classification",
            "--runs",
            runs_dir / "image_classification",
        ],
        "本地回环-CIFAR-10 分类",
    )
    results["image_classification"] = _artifact_summary(image_classification)

    video_reconstruction = _run_cli(
        config_path,
        [
            "task-run",
            "--kind",
            "video",
            "--input",
            samples_dir / "sample.tvid",
            "--task-type",
            "video_reconstruction",
            "--task-id",
            "demo-loopback-video-reconstruction",
            "--runs",
            runs_dir / "video_reconstruction",
        ],
        "本地回环-视频重建冒烟测试",
    )
    results["video_reconstruction"] = _artifact_summary(video_reconstruction)

    video_sentiment = _run_cli(
        config_path,
        [
            "task-infer",
            "--kind",
            "video",
            "--input",
            mosei_path,
            "--task-type",
            "video_sentiment",
            "--split",
            "test",
            "--sample-index",
            "0",
            "--task-id",
            "demo-loopback-video-sentiment",
            "--runs",
            runs_dir / "video_sentiment",
        ],
        "本地回环-MOSEI 情感分析",
    )
    results["video_sentiment"] = _artifact_summary(video_sentiment)
    return results


def _wait_for_tcp_receiver(process: subprocess.Popen[str], host: str, port: int, timeout: float = 20.0) -> None:
    from traditional_comm.transport import LanTcpTransport

    deadline = time.monotonic() + timeout
    transport = LanTcpTransport(host, port, connect_timeout_ms=300, receive_timeout_ms=1000)
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(
                f"图像 TCP 接收端提前退出 (exit={process.returncode}): "
                f"{stderr.strip() or stdout.strip()}"
            )
        if transport.health_check().get("online"):
            return
        time.sleep(0.1)
    raise TimeoutError(f"等待 TCP 接收端超时: {host}:{port}")


def _finish_process(process: subprocess.Popen[str], timeout: float = 30.0) -> dict[str, Any]:
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
    return {
        "returncode": process.returncode,
        "stdout_tail": stdout[-2000:],
        "stderr_tail": stderr[-2000:],
    }


def _receiver_record(output_dir: Path, run_dir: Path) -> dict[str, Any]:
    run_id = run_dir.name
    result_path = output_dir / run_id / "receiver_result.json"
    if not result_path.is_file():
        raise FileNotFoundError(f"TCP 接收端未生成结果: {result_path}")
    return json.loads(result_path.read_text(encoding="utf-8"))


def _run_dual_image(
    config_path: Path,
    config: dict[str, Any],
    output_dir: Path,
    host: str,
    port: int,
) -> dict[str, Any]:
    samples_dir = Path(config["paths"]["samples_dir"])
    selected_path, selected_label, selected_label_name = _ensure_cifar_sample(config)
    sender_runs = output_dir / "dual_tcp" / "image_sender"
    receiver_dir = output_dir / "dual_tcp" / "image_receiver"
    receiver_dir.mkdir(parents=True, exist_ok=True)
    receiver_max_connections = max(2, int(config.get("demo", {}).get("receiver_max_connections", 2)))
    receiver_command = [
        sys.executable,
        "-u",
        "-m",
        "traditional_comm.cli",
        "tcp-receive",
        "--config",
        str(config_path),
        "--bind",
        host,
        "--port",
        str(port),
        "--output",
        str(receiver_dir),
        "--max-connections",
        str(receiver_max_connections),
    ]
    _log(f"启动图像双端接收端: {host}:{port}")
    receiver = subprocess.Popen(
        receiver_command,
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    sender_results: dict[str, Any] = {}
    receiver_process: dict[str, Any] = {}
    try:
        _wait_for_tcp_receiver(receiver, host, port)
        reconstruction_run = _run_cli(
            config_path,
            [
                "tcp-send",
                "--host",
                host,
                "--port",
                str(port),
                "--kind",
                "image",
                "--input",
                samples_dir / "sample.ppm",
                "--task-type",
                "image_reconstruction",
                "--output-type",
                "reconstruction",
                "--task-id",
                "demo-dual-image-reconstruction",
                "--runs",
                sender_runs / "image_reconstruction",
            ],
            "双端图像重建发送",
        )
        sender_results["image_reconstruction"] = _artifact_summary(reconstruction_run)

        classification_run = _run_cli(
            config_path,
            [
                "tcp-send",
                "--host",
                host,
                "--port",
                str(port),
                "--kind",
                "image",
                "--input",
                selected_path,
                "--task-type",
                "image_classification",
                "--output-type",
                "structured",
                "--task-id",
                "demo-dual-image-classification",
                "--runs",
                sender_runs / "image_classification",
            ],
            "双端图像分类发送",
        )
        sender_results["image_classification"] = _artifact_summary(classification_run)
        receiver_process = _finish_process(receiver)
    finally:
        if receiver.poll() is None:
            receiver.terminate()
            _finish_process(receiver)

    reconstruction_receiver = _receiver_record(receiver_dir, reconstruction_run)
    classification_receiver = _receiver_record(receiver_dir, classification_run)
    receiver_classification_run = _run_cli(
        config_path,
        [
            "task-infer",
            "--kind",
            "image",
            "--input",
            classification_receiver["decoded_path"],
            "--task-type",
            "image_classification",
            "--ground-truth-label",
            str(selected_label),
            "--task-id",
            "demo-dual-image-classification-receiver",
            "--runs",
            output_dir / "dual_tcp" / "image_receiver_task" / "classification",
        ],
        "双端接收端图像分类推理",
    )
    return {
        "host": host,
        "port": port,
        "sender": sender_results,
        "receiver_process": receiver_process,
        "receiver": {
            "image_reconstruction": reconstruction_receiver,
            "image_classification": classification_receiver,
            "classification_task": _artifact_summary(receiver_classification_run),
        },
        "classification_sample": {
            "path": str(selected_path),
            "label": selected_label,
            "label_name": selected_label_name,
        },
    }


def _send_feature_frame(sock: socket.socket, header: dict[str, Any], payload: bytes = b"") -> int:
    message = dict(header)
    message["payload_size"] = len(payload)
    encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if not encoded or len(encoded) > MAX_HEADER_BYTES:
        raise ValueError("MOSEI feature frame header is empty or too large")
    sock.sendall(HEADER_LENGTH.pack(len(encoded)) + encoded + payload)
    return HEADER_LENGTH.size + len(encoded) + len(payload)


def _receive_exact(sock: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        block = sock.recv(min(1024 * 1024, size - len(data)))
        if not block:
            raise ConnectionError(f"connection closed at {len(data)}/{size} bytes")
        data.extend(block)
    return bytes(data)


def _receive_feature_frame(sock: socket.socket) -> tuple[dict[str, Any], bytes, int]:
    header_size = HEADER_LENGTH.unpack(_receive_exact(sock, HEADER_LENGTH.size))[0]
    if header_size <= 0 or header_size > MAX_HEADER_BYTES:
        raise ValueError(f"invalid feature frame header size: {header_size}")
    encoded = _receive_exact(sock, header_size)
    header = json.loads(encoded.decode("utf-8"))
    if not isinstance(header, dict):
        raise ValueError("feature frame header must be a JSON object")
    payload_size = int(header.get("payload_size", 0))
    if payload_size < 0 or payload_size > MAX_PAYLOAD_BYTES:
        raise ValueError(f"invalid feature payload size: {payload_size}")
    payload = _receive_exact(sock, payload_size) if payload_size else b""
    return header, payload, HEADER_LENGTH.size + header_size + payload_size


def _serve_mosei_feature_once(
    config: dict[str, Any],
    host: str,
    port: int,
    output_dir: Path,
    source_path: Path,
    ready: threading.Event,
    state: dict[str, Any],
) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((host, port))
        server.listen(1)
        server.settimeout(30)
        state["address"] = [host, port]
        ready.set()
        connection, peer = server.accept()
        with connection:
            connection.settimeout(300)
            header, payload, wire_received = _receive_feature_frame(connection)
            run_id = str(header.get("run_id") or f"mosei-received-{uuid.uuid4().hex[:8]}")
            if not re.fullmatch(r"[A-Za-z0-9._-]+", run_id):
                run_id = f"mosei-received-{uuid.uuid4().hex[:8]}"
            if header.get("protocol") != FEATURE_PROTOCOL or header.get("message_type") != "payload":
                raise ValueError("unsupported MOSEI feature protocol or message type")
            if header.get("sha256") != _sha256(payload):
                raise ValueError("MOSEI feature payload checksum mismatch")
            run_dir = output_dir / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            received_path = run_dir / "received_features.pkl"
            received_path.write_bytes(payload)
            task_config = get_task_config(config, "video_sentiment")
            request = {
                "task_type": "video_sentiment",
                "semantic_task": task_config.get("semantic_task", "msa"),
                "dataset": task_config.get("dataset", "mosei"),
                "input_path": str(received_path),
                "reference_path": str(source_path),
                "task_config": task_config,
                "task_context": {
                    "task_id": "demo-dual-video-sentiment-receiver",
                    "task_type": "video_sentiment",
                    "split": "test",
                    "sample_index": int(header.get("sample_index", 0)),
                },
            }
            started = time.perf_counter()
            completed = subprocess.run(
                [sys.executable, "-u", str(ROOT / "video_sentiment_infer.py")],
                cwd=str(ROOT),
                input=json.dumps(request, ensure_ascii=False),
                text=True,
                capture_output=True,
                check=False,
                timeout=300,
            )
            try:
                task_result = json.loads(completed.stdout.strip())
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    "video_sentiment_infer.py returned invalid JSON: "
                    f"{completed.stderr.strip() or completed.stdout.strip()}"
                ) from exc
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr.strip() or "MOSEI inference failed")
            receiver_result = {
                "run_id": run_id,
                "protocol": FEATURE_PROTOCOL,
                "peer": {"host": peer[0], "port": peer[1]},
                "received_path": str(received_path),
                "received_bytes": len(payload),
                "wire_received_bytes": wire_received,
                "sha256": _sha256(payload),
                "task_result": task_result,
                "receiver_inference_time_ms": round((time.perf_counter() - started) * 1000, 3),
                "stderr": completed.stderr.strip() or None,
            }
            result_path = run_dir / "result.json"
            _json_write(run_dir / "receiver_result.json", receiver_result)
            _json_write(result_path, receiver_result)
            ack = {
                "protocol": FEATURE_PROTOCOL,
                "message_type": "ack",
                "run_id": run_id,
                "accepted": bool(task_result.get("success")),
                "received_bytes": len(payload),
                "sha256": receiver_result["sha256"],
                "receiver_result_path": str(result_path),
                "task_result": task_result,
            }
            wire_sent = _send_feature_frame(connection, ack)
            state["result"] = receiver_result
            state["wire_sent_bytes"] = wire_sent
    except Exception as exc:
        state["error"] = str(exc)
        ready.set()
        try:
            if "connection" in locals():
                _send_feature_frame(
                    connection,
                    {
                        "protocol": FEATURE_PROTOCOL,
                        "message_type": "ack",
                        "accepted": False,
                        "error": str(exc),
                    },
                )
        except OSError:
            pass
    finally:
        server.close()


def _run_dual_video(
    config: dict[str, Any],
    output_dir: Path,
    host: str,
    port: int,
    mosei_path: Path,
) -> dict[str, Any]:
    receiver_dir = output_dir / "dual_tcp" / "video_receiver"
    sender_dir = output_dir / "dual_tcp" / "video_sender"
    receiver_dir.mkdir(parents=True, exist_ok=True)
    payload = mosei_path.read_bytes()
    run_id = f"demo-dual-video-sentiment-{uuid.uuid4().hex[:8]}"
    ready = threading.Event()
    state: dict[str, Any] = {}
    receiver_thread = threading.Thread(
        target=_serve_mosei_feature_once,
        args=(config, host, port, receiver_dir, mosei_path, ready, state),
        name="mosei-feature-receiver",
        daemon=True,
    )
    _log(f"启动 MOSEI 特征双端接收端: {host}:{port}")
    receiver_thread.start()
    if not ready.wait(timeout=10):
        raise TimeoutError(f"等待 MOSEI 特征接收端超时: {host}:{port}")
    if state.get("error") and not state.get("address"):
        raise RuntimeError(f"MOSEI 特征接收端启动失败: {state['error']}")
    started = time.perf_counter()
    with socket.create_connection((host, port), timeout=10) as connection:
        connection.settimeout(300)
        wire_sent = _send_feature_frame(
            connection,
            {
                "protocol": FEATURE_PROTOCOL,
                "message_type": "payload",
                "run_id": run_id,
                "sample_id": mosei_path.name,
                "sample_index": 0,
                "payload_size": len(payload),
                "sha256": _sha256(payload),
            },
            payload,
        )
        ack, ack_payload, wire_received = _receive_feature_frame(connection)
    receiver_thread.join(timeout=310)
    if receiver_thread.is_alive():
        raise TimeoutError("MOSEI 特征接收端未在预期时间内结束")
    if state.get("error"):
        raise RuntimeError(f"MOSEI 特征双端任务失败: {state['error']}")
    if ack_payload or ack.get("protocol") != FEATURE_PROTOCOL or not ack.get("accepted"):
        raise RuntimeError(f"MOSEI 特征接收端拒绝任务: {ack}")
    result = state.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("MOSEI 特征接收端没有生成结果")
    sender_result = {
        "run_id": run_id,
        "protocol": FEATURE_PROTOCOL,
        "host": host,
        "port": port,
        "input_path": str(mosei_path),
        "input_bytes": len(payload),
        "wire_sent_bytes": wire_sent,
        "wire_received_bytes": wire_received,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "receiver_result_path": str(receiver_dir / run_id / "receiver_result.json"),
        "task_result": ack.get("task_result"),
    }
    sender_run_dir = sender_dir / run_id
    _json_write(sender_run_dir / "result.json", sender_result)
    _json_write(
        sender_run_dir / "metrics.json",
        {
            "run_id": run_id,
            "transport": FEATURE_PROTOCOL,
            "input_bytes": len(payload),
            "actual_sent_bytes": len(payload),
            "actual_link_total_bytes": wire_sent + wire_received,
            "wire_sent_bytes": wire_sent,
            "wire_received_bytes": wire_received,
            "end_to_end_latency_ms": sender_result["elapsed_ms"],
            "task": {"task_result": ack.get("task_result")},
            "status": "completed",
        },
    )
    return {
        "host": host,
        "port": port,
        "protocol": FEATURE_PROTOCOL,
        "sender": sender_result,
        "receiver": result,
        "sender_result_path": str(sender_run_dir / "result.json"),
        "result_path": str(receiver_dir / run_id / "result.json"),
        "receiver_result_path": str(receiver_dir / run_id / "receiver_result.json"),
    }


def _run_dual(
    config_path: Path,
    config: dict[str, Any],
    output_dir: Path,
    host: str,
    image_port: int,
    video_port: int,
    mosei_path: Path,
) -> dict[str, Any]:
    if image_port == video_port:
        raise ValueError("图像双端和视频双端必须使用两个不同端口")
    image_result = _run_dual_image(config_path, config, output_dir, host, image_port)
    video_result = _run_dual_video(config, output_dir, host, video_port, mosei_path)
    return {"image": image_result, "video_sentiment": video_result}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run all traditional communication demo tasks")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--host", default=None, help="localhost address used by the simulated two-end test")
    parser.add_argument("--image-port", type=int, default=None)
    parser.add_argument("--video-port", type=int, default=None)
    parser.add_argument("--skip-loopback", action="store_true")
    parser.add_argument("--skip-dual", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config_path = args.config.resolve()
    summary: dict[str, Any] = {
        "success": False,
        "config": str(config_path),
        "python": sys.executable,
        "loopback": None,
        "dual_tcp": None,
        "error": None,
    }
    try:
        config = load_config(config_path)
        demo_config = config.get("demo", {})
        output_dir = (args.output_dir or _resolve_demo_path(demo_config.get("output_dir", "../runs/demo_all"), config_path)).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        host = args.host or str(demo_config.get("host", "127.0.0.1"))
        image_port = args.image_port or int(demo_config.get("image_port", 5001))
        video_port = args.video_port or int(demo_config.get("video_feature_port", 5002))
        mosei_path = _resolve_demo_path(
            demo_config.get("mosei_sample", "../../imagec_and_MMSA/data/MOSEI/sample_test.pkl"),
            config_path,
        )
        if not mosei_path.is_file():
            raise FileNotFoundError(f"MOSEI sample does not exist: {mosei_path}")
        summary["output_dir"] = str(output_dir)
        summary["ports"] = {"host": host, "image": image_port, "video_feature": video_port}
        summary["mosei_sample"] = str(mosei_path)

        if not args.skip_loopback:
            summary["loopback"] = _run_loopback(config_path, config, output_dir, mosei_path)
        if not args.skip_dual:
            summary["dual_tcp"] = _run_dual(
                config_path,
                config,
                output_dir,
                host,
                image_port,
                video_port,
                mosei_path,
            )
        summary["success"] = True
        _json_write(output_dir / "demo_summary.json", summary)
    except Exception as exc:
        summary["error"] = str(exc)
        output_value = summary.get("output_dir")
        if output_value:
            _json_write(Path(output_value) / "demo_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
