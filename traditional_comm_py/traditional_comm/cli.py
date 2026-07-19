from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runner import run_all
from .samples import generate_samples
from .transport import LoopbackTransport


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLES = ROOT / "samples"
DEFAULT_RUNS = ROOT / "runs"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Python traditional communication local baseline")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("demo", "generate-samples", "run"):
        command = sub.add_parser(name)
        command.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
        command.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
        command.add_argument("--chunk-size", type=int, default=16 * 1024)
        command.add_argument("--delay-ms", type=float, default=0)
        command.add_argument("--loss-rate", type=float, default=0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
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
    summary = {
        "mode": "traditional",
        "transport": "loopback",
        "results": [result["metrics"] for result in results],
    }
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / "latest_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for result in results:
        metrics = result["metrics"]
        print(
            f"{result['kind']}: status={metrics['status']} "
            f"input={metrics['input_bytes']}B payload={metrics['encoded_payload_bytes']}B "
            f"latency={metrics['end_to_end_latency_ms']}ms "
            f"content_match={metrics['task']['content_match']}"
        )
    print(f"Run artifacts saved in {runs_dir}")


if __name__ == "__main__":
    main()
