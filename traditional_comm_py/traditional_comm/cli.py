from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import DEFAULT_CONFIG_PATH, load_config
from .dataset_adapter import materialize_cifar10_sample, select_cifar10_sample
from .runner import run_all, run_one, run_task_only
from .samples import generate_samples
from .task_adapter import create_task_adapter
from .transport import LanTcpReceiver, LanTcpTransport, LoopbackTransport


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLES = ROOT / "samples"
DEFAULT_RUNS = ROOT / "runs"
DEFAULT_RECEIVER_RUNS = ROOT / "runs_receiver"


def _add_loopback_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    command.add_argument("--samples", type=Path, default=None)
    command.add_argument("--runs", type=Path, default=None)
    command.add_argument("--chunk-size", type=int, default=None)
    command.add_argument("--delay-ms", type=float, default=None)
    command.add_argument("--loss-rate", type=float, default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Python traditional communication baseline")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("demo", "generate-samples", "run"):
        command = sub.add_parser(name)
        _add_loopback_arguments(command)

    receiver = sub.add_parser("tcp-receive", help="start a LAN TCP receiver")
    receiver.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    receiver.add_argument("--bind", default=None, help="local bind address")
    receiver.add_argument("--port", type=int, default=None)
    receiver.add_argument("--output", type=Path, default=None)
    receiver.add_argument(
        "--max-connections",
        type=int,
        default=None,
        help="number of payload connections; use 0 to keep serving",
    )

    sender = sub.add_parser("tcp-send", help="send one sample to a LAN TCP receiver")
    sender.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    sender.add_argument("--host", required=True, help="receiver IP or hostname")
    sender.add_argument("--port", type=int, default=None)
    sender.add_argument("--kind", choices=("text", "image", "video"), required=True)
    sender.add_argument("--input", type=Path, required=True)
    sender.add_argument("--runs", type=Path, default=None)
    sender.add_argument("--task-id", default="lan-tcp-demo")
    sender.add_argument("--task-type", default="reconstruction")
    sender.add_argument("--output-type", default="reconstruction")
    sender.add_argument("--connect-timeout-ms", type=int, default=None)
    sender.add_argument("--receive-timeout-ms", type=int, default=None)
    sender.add_argument("--jpeg-quality", type=int, default=None)
    sender.add_argument("--h264-crf", type=int, default=None)
    sender.add_argument("--h264-preset", default=None)

    task_run = sub.add_parser("task-run", help="run one local traditional communication task")
    task_run.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    task_run.add_argument("--kind", choices=("text", "image", "video"), required=True)
    task_run.add_argument("--input", type=Path, default=None)
    task_run.add_argument("--dataset", choices=("cifar10",), default=None)
    task_run.add_argument("--split", choices=("train", "test"), default=None)
    task_run.add_argument("--sample-mode", choices=("random", "first", "index"), default=None)
    task_run.add_argument("--sample-index", type=int, default=None)
    task_run.add_argument("--seed", type=int, default=None)
    task_run.add_argument("--runs", type=Path, default=None)
    task_run.add_argument("--task-id", default="local-task")
    task_run.add_argument("--task-type", default=None)
    task_run.add_argument("--chunk-size", type=int, default=None)
    task_run.add_argument("--delay-ms", type=float, default=None)
    task_run.add_argument("--loss-rate", type=float, default=None)
    task_run.add_argument("--jpeg-quality", type=int, default=None)
    task_run.add_argument("--h264-crf", type=int, default=None)
    task_run.add_argument("--h264-preset", default=None)

    task_infer = sub.add_parser(
        "task-infer",
        help="run a downstream task directly on an image or feature-level MOSEI sample",
    )
    task_infer.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    task_infer.add_argument("--kind", choices=("image", "video"), required=True)
    task_infer.add_argument("--input", type=Path, required=True)
    task_infer.add_argument("--task-type", choices=("image_classification", "video_sentiment"), required=True)
    task_infer.add_argument("--split", choices=("train", "dev", "test"), default=None)
    task_infer.add_argument("--sample-index", type=int, default=None)
    task_infer.add_argument("--ground-truth-label", type=int, default=None)
    task_infer.add_argument("--ground-truth-score", type=float, default=None)
    task_infer.add_argument("--runs", type=Path, default=None)
    task_infer.add_argument("--task-id", default="task-infer")

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
    app_config = load_config(args.config)
    configured_paths = app_config["paths"]
    samples_dir = Path(args.samples or configured_paths["samples_dir"]).resolve()
    runs_dir = Path(args.runs or configured_paths["runs_dir"]).resolve()
    loopback_config = app_config.get("transport", {}).get("loopback", {})
    chunk_size = args.chunk_size if args.chunk_size is not None else int(loopback_config.get("chunk_size", 16 * 1024))
    delay_ms = args.delay_ms if args.delay_ms is not None else float(loopback_config.get("delay_ms", 0))
    loss_rate = args.loss_rate if args.loss_rate is not None else float(loopback_config.get("loss_rate", 0))
    if args.command in {"demo", "generate-samples"}:
        print(f"Generated samples in {samples_dir}")
        print(generate_samples(samples_dir))
    if args.command == "generate-samples":
        return
    transport = LoopbackTransport(chunk_size, delay_ms, loss_rate)
    task_adapter = create_task_adapter(app_config)
    codec_config = app_config.get("codec", {})
    codec_options = {
        "jpeg_quality": codec_config.get("image", {}).get("jpeg_quality", 3),
        "h264_crf": codec_config.get("video", {}).get("h264_crf", 23),
        "h264_preset": codec_config.get("video", {}).get("h264_preset", "ultrafast"),
    }
    results = run_all(
        samples_dir,
        runs_dir,
        transport,
        {"task_id": "smoke-test", "task_type": "reconstruction", "output_type": "reconstruction"},
        codec_options=codec_options,
        task_adapter=task_adapter,
    )
    _write_summary(runs_dir, "loopback", results)
    _print_results(results)
    print(f"Run artifacts saved in {runs_dir}")


def _run_receiver(args: argparse.Namespace) -> None:
    app_config = load_config(args.config)
    lan_config = app_config.get("transport", {}).get("lan_tcp", {})
    bind = args.bind or lan_config.get("bind", "0.0.0.0")
    port = args.port or int(lan_config.get("port", 5000))
    output_dir = Path(args.output or app_config["paths"]["receiver_runs_dir"]).resolve()
    receiver = LanTcpReceiver(bind, port, output_dir)
    info = receiver.start()
    max_connections_value = args.max_connections
    if max_connections_value is None:
        max_connections_value = int(lan_config.get("max_connections", 1))
    max_connections = None if max_connections_value == 0 else max_connections_value
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
    app_config = load_config(args.config)
    input_path = args.input.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input file does not exist: {input_path}")
    lan_config = app_config.get("transport", {}).get("lan_tcp", {})
    port = args.port or int(lan_config.get("port", 5000))
    transport = LanTcpTransport(
        args.host,
        port,
        connect_timeout_ms=args.connect_timeout_ms or int(lan_config.get("connect_timeout_ms", 5000)),
        receive_timeout_ms=args.receive_timeout_ms or int(lan_config.get("receive_timeout_ms", 30000)),
    )
    codec_config = app_config.get("codec", {})
    image_codec = codec_config.get("image", {})
    video_codec = codec_config.get("video", {})
    codec_options = {
        "jpeg_quality": args.jpeg_quality if args.jpeg_quality is not None else image_codec.get("jpeg_quality", 3),
        "h264_crf": args.h264_crf if args.h264_crf is not None else video_codec.get("h264_crf", 23),
        "h264_preset": args.h264_preset or video_codec.get("h264_preset", "ultrafast"),
    }
    task_adapter = create_task_adapter(app_config)
    runs_dir = Path(args.runs or app_config["paths"]["runs_dir"]).resolve()
    print(json.dumps(transport.health_check(), ensure_ascii=False, indent=2))
    result = run_one(
        args.kind,
        input_path,
        runs_dir,
        transport,
        {
            "task_id": args.task_id,
            "task_type": args.task_type,
            "output_type": args.output_type,
        },
        codec_options=codec_options,
        task_adapter=task_adapter,
    )
    _write_summary(runs_dir, "lan-tcp", [result])
    _print_results([result])
    print(f"Sender artifacts saved in {result['run_dir']}")
    if result["metrics"].get("receiver_result_path"):
        print(f"Receiver result: {result['metrics']['receiver_result_path']}")


def _run_task(args: argparse.Namespace) -> None:
    app_config = load_config(args.config)
    task_type = args.task_type or {
        "text": "text_reconstruction",
        "image": "image_reconstruction",
        "video": "video_reconstruction",
    }[args.kind]
    task_context = {"task_id": args.task_id, "task_type": task_type}
    if args.dataset:
        if args.kind != "image" or args.dataset != "cifar10":
            raise ValueError("the current dataset adapter supports CIFAR-10 image tasks only")
        selection = app_config.get("sample_selection", {})
        dataset_config = app_config["datasets"]["cifar10"]
        split = args.split or selection.get("split", "test")
        mode = args.sample_mode or selection.get("mode", "random")
        seed = args.seed if args.seed is not None else selection.get("seed", 100)
        sample_index = args.sample_index if args.sample_index is not None else selection.get("index")
        sample = select_cifar10_sample(
            dataset_config["root"],
            split=split,
            mode=mode,
            seed=seed,
            index=sample_index,
            samples_per_file=int(dataset_config.get("samples_per_file", 10000)),
        )
        input_path = materialize_cifar10_sample(
            sample,
            app_config["paths"]["materialized_samples_dir"],
        )
        task_context.update(
            {
                "dataset": "cifar10",
                "dataset_split": sample.split,
                "dataset_index": sample.index,
                "label": sample.label,
                "label_name": sample.label_name,
                "sample_selection": {"mode": mode, "seed": seed},
            }
        )
    elif args.input:
        input_path = args.input.resolve()
    else:
        raise ValueError("one of --input or --dataset is required")
    if not input_path.is_file():
        raise FileNotFoundError(f"input file does not exist: {input_path}")
    loopback_config = app_config.get("transport", {}).get("loopback", {})
    transport = LoopbackTransport(
        args.chunk_size if args.chunk_size is not None else int(loopback_config.get("chunk_size", 16 * 1024)),
        args.delay_ms if args.delay_ms is not None else float(loopback_config.get("delay_ms", 0)),
        args.loss_rate if args.loss_rate is not None else float(loopback_config.get("loss_rate", 0)),
    )
    codec_config = app_config.get("codec", {})
    codec_options = {
        "jpeg_quality": args.jpeg_quality if args.jpeg_quality is not None else codec_config.get("image", {}).get("jpeg_quality", 3),
        "h264_crf": args.h264_crf if args.h264_crf is not None else codec_config.get("video", {}).get("h264_crf", 23),
        "h264_preset": args.h264_preset or codec_config.get("video", {}).get("h264_preset", "ultrafast"),
    }
    runs_dir = Path(args.runs or app_config["paths"]["runs_dir"]).resolve()
    result = run_one(
        args.kind,
        input_path,
        runs_dir,
        transport,
        task_context,
        codec_options=codec_options,
        task_adapter=create_task_adapter(app_config),
    )
    _write_summary(runs_dir, "loopback", [result])
    _print_results([result])
    print(f"Task artifacts saved in {result['run_dir']}")


def _run_task_infer(args: argparse.Namespace) -> None:
    app_config = load_config(args.config)
    input_path = args.input.resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input file does not exist: {input_path}")
    task_context = {
        "task_id": args.task_id,
        "task_type": args.task_type,
    }
    if args.split:
        task_context["split"] = args.split
    if args.sample_index is not None:
        task_context["sample_index"] = args.sample_index
    if args.ground_truth_label is not None:
        task_context["ground_truth_label"] = args.ground_truth_label
    if args.ground_truth_score is not None:
        task_context["ground_truth_score"] = args.ground_truth_score
    runs_dir = Path(args.runs or app_config["paths"]["runs_dir"]).resolve()
    result = run_task_only(
        args.kind,
        input_path,
        runs_dir,
        task_context,
        task_adapter=create_task_adapter(app_config),
    )
    print(json.dumps(result["metrics"]["task"]["task_result"], ensure_ascii=False, indent=2))
    print(f"Task artifacts saved in {result['run_dir']}")


def main() -> None:
    args = build_parser().parse_args()
    if args.command in {"demo", "generate-samples", "run"}:
        _run_loopback(args)
    elif args.command == "tcp-receive":
        _run_receiver(args)
    elif args.command == "tcp-send":
        _run_sender(args)
    elif args.command == "task-run":
        _run_task(args)
    elif args.command == "task-infer":
        _run_task_infer(args)


if __name__ == "__main__":
    main()
