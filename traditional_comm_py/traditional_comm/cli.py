from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runner import run_all, run_one
from .samples import generate_samples
from .transport import LanTcpReceiver, LanTcpTransport, LoopbackTransport


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLES = ROOT / "samples"
DEFAULT_RUNS = ROOT / "runs"
DEFAULT_RECEIVER_RUNS = ROOT / "runs_receiver"


def _add_loopback_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    command.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    command.add_argument("--chunk-size", type=int, default=16 * 1024)
    command.add_argument("--delay-ms", type=float, default=0)
    command.add_argument("--loss-rate", type=float, default=0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Python traditional communication baseline")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("demo", "generate-samples", "run"):
        command = sub.add_parser(name)
        _add_loopback_arguments(command)

    receiver = sub.add_parser("tcp-receive", help="start a LAN TCP receiver")
    receiver.add_argument("--bind", default="0.0.0.0", help="local bind address")
    receiver.add_argument("--port", type=int, default=5000)
    receiver.add_argument("--output", type=Path, default=DEFAULT_RECEIVER_RUNS)
    receiver.add_argument(
        "--max-connections",
        type=int,
        default=1,
        help="number of payload connections; use 0 to keep serving",
    )

    sender = sub.add_parser("tcp-send", help="send one sample to a LAN TCP receiver")
    sender.add_argument("--host", required=True, help="receiver IP or hostname")
    sender.add_argument("--port", type=int, default=5000)
    sender.add_argument("--kind", choices=("text", "image", "video"), required=True)
    sender.add_argument("--input", type=Path, required=True)
    sender.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    sender.add_argument("--task-id", default="lan-tcp-demo")
    sender.add_argument("--task-type", default="reconstruction")
    sender.add_argument("--output-type", default="reconstruction")
    sender.add_argument("--connect-timeout-ms", type=int, default=5000)
    sender.add_argument("--receive-timeout-ms", type=int, default=30000)
    sender.add_argument("--jpeg-quality", type=int, default=3)
    sender.add_argument("--h264-crf", type=int, default=23)
    sender.add_argument("--h264-preset", default="ultrafast")

    return parser


def _write_summary(runs_dir: Path, transport_name: str, results: list[dict]) -> None:
    runs_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "mode": "traditional",
        "transport": transport_name,
        "results": [result["metrics"] for result in results],
    }
    (runs_dir / "latest_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _print_results(results: list[dict]) -> None:
    for result in results:
        metrics = result["metrics"]
        print(
            f"{result['kind']}: status={metrics['status']} "
            f"input={metrics['input_bytes']}B payload={metrics['encoded_payload_bytes']}B "
            f"latency={metrics['end_to_end_latency_ms']}ms "
            f"content_match={metrics['task']['content_match']}"
        )


def _run_loopback(args: argparse.Namespace) -> None:
    samples_dir = args.samples.resolve()
    runs_dir = args.runs.resolve()
    if args.command in {"demo", "generate-samples"}:
        print(f"Generated samples in {samples_dir}")
        print(generate_samples(samples_dir))
    if args.command == "generate-samples":
        return
    transport = LoopbackTransport(args.chunk_size, args.delay_ms, args.loss_rate)
    results = run_all(
        samples_dir,
        runs_dir,
        transport,
        {"task_id": "smoke-test", "task_type": "reconstruction", "output_type": "reconstruction"},
    )
    _write_summary(runs_dir, "loopback", results)
    _print_results(results)
    print(f"Run artifacts saved in {runs_dir}")


def _run_receiver(args: argparse.Namespace) -> None:
    receiver = LanTcpReceiver(args.bind, args.port, args.output)
    info = receiver.start()
    max_connections = None if args.max_connections == 0 else args.max_connections
    print(
        f"TCP receiver listening on {info['address'][0]}:{info['address'][1]} "
        f"output={receiver.output_dir}"
    )
    try:
        results = receiver.serve_forever(max_connections=max_connections)
        print(json.dumps(results, ensure_ascii=False, indent=2))
    except KeyboardInterrupt:
        print("TCP receiver stopped")
    finally:
        receiver.close()


def _run_sender(args: argparse.Namespace) -> None:
    input_path = args.input.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input file does not exist: {input_path}")
    transport = LanTcpTransport(
        args.host,
        args.port,
        connect_timeout_ms=args.connect_timeout_ms,
        receive_timeout_ms=args.receive_timeout_ms,
    )
    print(json.dumps(transport.health_check(), ensure_ascii=False, indent=2))
    result = run_one(
        args.kind,
        input_path,
        args.runs.resolve(),
        transport,
        {
            "task_id": args.task_id,
            "task_type": args.task_type,
            "output_type": args.output_type,
        },
        codec_options={
            "jpeg_quality": args.jpeg_quality,
            "h264_crf": args.h264_crf,
            "h264_preset": args.h264_preset,
        },
    )
    _write_summary(args.runs.resolve(), "lan-tcp", [result])
    _print_results([result])
    print(f"Sender artifacts saved in {result['run_dir']}")
    if result["metrics"].get("receiver_result_path"):
        print(f"Receiver result: {result['metrics']['receiver_result_path']}")


def main() -> None:
    args = build_parser().parse_args()
    if args.command in {"demo", "generate-samples", "run"}:
        _run_loopback(args)
    elif args.command == "tcp-receive":
        _run_receiver(args)
    elif args.command == "tcp-send":
        _run_sender(args)


if __name__ == "__main__":
    main()
