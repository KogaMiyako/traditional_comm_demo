from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any

from .runner import create_run_id, run_one
from .transport import LanTcpTransport, LoopbackTransport


MEDIA_KINDS = {"text", "image", "video"}
SAMPLE_EXTENSIONS = {
    ".txt": "text",
    ".ppm": "image",
    ".tvid": "video",
    ".jpg": "image",
    ".jpeg": "image",
    ".mp4": "video",
}


class RunCancelled(Exception):
    pass


class WebRunManager:
    """Background run manager used by the local Web dashboard."""

    def __init__(self, samples_dir: Path, runs_dir: Path):
        self.samples_dir = Path(samples_dir).resolve()
        self.runs_dir = Path(runs_dir).resolve()
        self.samples_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._states: dict[str, dict[str, Any]] = {}
        self._cancel_events: dict[str, threading.Event] = {}

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def list_samples(self) -> list[dict]:
        samples = []
        for path in sorted(self.samples_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in SAMPLE_EXTENSIONS:
                continue
            samples.append(
                {
                    "sample_id": path.name,
                    "path": str(path),
                    "media_type": SAMPLE_EXTENSIONS[path.suffix.lower()],
                    "bytes": path.stat().st_size,
                }
            )
        return samples

    def _input_path(self, config: dict) -> Path:
        sample_id = config.get("sample_id")
        if sample_id:
            candidate = (self.samples_dir / str(sample_id)).resolve()
            if self.samples_dir not in candidate.parents:
                raise ValueError("sample_id must refer to a file in the samples directory")
        elif config.get("input_path"):
            candidate = Path(str(config["input_path"])).resolve()
        else:
            raise ValueError("sample_id or input_path is required")
        if not candidate.is_file():
            raise FileNotFoundError(f"input file does not exist: {candidate}")
        return candidate

    @staticmethod
    def _transport(config: dict):
        transport_name = str(config.get("transport", "loopback")).lower()
        if transport_name == "loopback":
            return LoopbackTransport(
                chunk_size=int(config.get("chunk_size", 16 * 1024)),
                delay_ms=float(config.get("delay_ms", 0)),
                loss_rate=float(config.get("loss_rate", 0)),
            )
        if transport_name in {"lan-tcp", "tcp"}:
            return LanTcpTransport(
                remote_host=str(config["host"]),
                remote_port=int(config.get("port", 5000)),
                connect_timeout_ms=int(config.get("connect_timeout_ms", 5000)),
                receive_timeout_ms=int(config.get("receive_timeout_ms", 30000)),
            )
        raise ValueError(f"unsupported Web transport: {transport_name}")

    def _run_dir(self, run_id: str) -> Path:
        state = self._states[run_id]
        return Path(state["run_dir"])

    def _write_event(self, event: dict) -> None:
        run_id = str(event["run_id"])
        with self._lock:
            state = self._states.get(run_id)
            if state is None:
                return
            cancel_event = self._cancel_events.get(run_id)
            if cancel_event and cancel_event.is_set() and event.get("phase") not in {
                "cancel_requested",
                "cancelled",
                "completed",
                "failed",
            }:
                raise RunCancelled(f"run {run_id} was cancelled")
            state.update(
                {
                    "phase": event.get("phase"),
                    "progress": event.get("progress", 0),
                    "message": event.get("message", ""),
                }
            )
            run_dir = Path(state["run_dir"])
            run_dir.mkdir(parents=True, exist_ok=True)
            with (run_dir / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    def start_run(self, config: dict) -> dict:
        config = dict(config)
        kind = str(config.get("kind", ""))
        if kind not in MEDIA_KINDS:
            raise ValueError("kind must be text, image, or video")
        input_path = self._input_path(config)
        run_id = create_run_id(kind)
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "run_id": run_id,
            "mode": "traditional",
            "kind": kind,
            "input_path": str(input_path),
            "run_dir": str(run_dir),
            "transport": str(config.get("transport", "loopback")),
            "status": "preparing",
            "phase": "preparing",
            "progress": 0,
            "message": "run queued",
            "started_at": self._now(),
            "finished_at": None,
            "error": None,
            "metrics": None,
        }
        with self._lock:
            self._states[run_id] = state
            self._cancel_events[run_id] = threading.Event()
        self._write_event(
            {
                "time": self._now(),
                "run_id": run_id,
                "phase": "preparing",
                "progress": 0,
                "message": "run queued",
            }
        )
        thread = threading.Thread(
            target=self._worker,
            args=(run_id, config),
            name=f"traditional-web-{run_id}",
            daemon=True,
        )
        thread.start()
        return self.get_status(run_id)

    def _worker(self, run_id: str, config: dict) -> None:
        state = self._states[run_id]
        try:
            transport = self._transport(config)
            with self._lock:
                state["status"] = "running"
            result = run_one(
                state["kind"],
                Path(state["input_path"]),
                self.runs_dir,
                transport,
                config.get(
                    "task",
                    {
                        "task_id": "web-demo",
                        "task_type": "reconstruction",
                        "output_type": "reconstruction",
                    },
                ),
                run_id=run_id,
                codec_options=config.get("codec_options"),
                event_callback=self._write_event,
            )
            with self._lock:
                state.update(
                    {
                        "status": result["metrics"]["status"],
                        "phase": result["metrics"]["status"],
                        "progress": 100,
                        "message": result["metrics"]["status"],
                        "metrics": result["metrics"],
                        "finished_at": self._now(),
                    }
                )
        except RunCancelled as exc:
            with self._lock:
                state.update(
                    {
                        "status": "cancelled",
                        "phase": "cancelled",
                        "progress": state.get("progress", 0),
                        "message": str(exc),
                        "finished_at": self._now(),
                    }
                )
            self._write_event(
                {
                    "time": self._now(),
                    "run_id": run_id,
                    "phase": "cancelled",
                    "progress": state.get("progress", 0),
                    "message": str(exc),
                }
            )
        except Exception as exc:
            with self._lock:
                state.update(
                    {
                        "status": "failed",
                        "phase": "failed",
                        "progress": 100,
                        "message": str(exc),
                        "error": str(exc),
                        "finished_at": self._now(),
                    }
                )
            self._write_event(
                {
                    "time": self._now(),
                    "run_id": run_id,
                    "phase": "failed",
                    "progress": 100,
                    "message": str(exc),
                }
            )

    def get_status(self, run_id: str) -> dict:
        with self._lock:
            if run_id not in self._states:
                raise KeyError(run_id)
            state = self._states[run_id]
            return {
                key: state.get(key)
                for key in (
                    "run_id",
                    "mode",
                    "kind",
                    "input_path",
                    "run_dir",
                    "transport",
                    "status",
                    "phase",
                    "progress",
                    "message",
                    "started_at",
                    "finished_at",
                    "error",
                )
            }

    def list_runs(self) -> list[dict]:
        with self._lock:
            return [self.get_status(run_id) for run_id in reversed(list(self._states))]

    def get_metrics(self, run_id: str) -> dict | None:
        with self._lock:
            state = self._states.get(run_id)
            if state is None:
                raise KeyError(run_id)
            metrics = state.get("metrics")
            run_dir = Path(state["run_dir"])
        if metrics is not None:
            return metrics
        metrics_path = run_dir / "metrics.json"
        if metrics_path.is_file():
            return json.loads(metrics_path.read_text(encoding="utf-8"))
        return None

    def get_result(self, run_id: str) -> dict | None:
        run_dir = self._run_dir(run_id)
        result_path = run_dir / "result.json"
        if result_path.is_file():
            return json.loads(result_path.read_text(encoding="utf-8"))
        return None

    def get_error(self, run_id: str) -> dict:
        status = self.get_status(run_id)
        return {"run_id": run_id, "has_error": bool(status["error"]), "error": status["error"]}

    def get_events(self, run_id: str) -> list[dict]:
        run_dir = self._run_dir(run_id)
        events_path = run_dir / "events.jsonl"
        if not events_path.is_file():
            return []
        events = []
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events

    def cancel_run(self, run_id: str) -> dict:
        with self._lock:
            if run_id not in self._states:
                raise KeyError(run_id)
            state = self._states[run_id]
            if state["status"] in {"completed", "failed", "cancelled"}:
                return self.get_status(run_id)
            self._cancel_events[run_id].set()
            state.update({"status": "cancel_requested", "message": "cancellation requested"})
        self._write_event(
            {
                "time": self._now(),
                "run_id": run_id,
                "phase": "cancel_requested",
                "progress": state.get("progress", 0),
                "message": "cancellation requested",
            }
        )
        return self.get_status(run_id)

    def get_file(self, run_id: str, name: str) -> Path:
        if not name or Path(name).name != name:
            raise ValueError("file name must not contain a directory")
        run_dir = self._run_dir(run_id).resolve()
        path = (run_dir / name).resolve()
        if run_dir not in path.parents:
            raise ValueError("file is outside the run directory")
        if not path.is_file():
            raise FileNotFoundError(name)
        return path
