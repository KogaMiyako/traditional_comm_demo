from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any

from .runner import create_run_id, run_one
from .transport import LanTcpReceiver, LanTcpTransport, LoopbackTransport


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


class WebReceiverManager:
    """Own the TCP receiver lifecycle for the receiver-side Web page."""

    def __init__(self, runs_dir: Path):
        self.runs_dir = Path(runs_dir).resolve()
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._receiver: LanTcpReceiver | None = None
        self._stop_event: threading.Event | None = None
        self._thread: threading.Thread | None = None
        self._state: dict[str, Any] = {
            "online": False,
            "status": "stopped",
            "bind_host": "0.0.0.0",
            "port": None,
            "address": None,
            "output_dir": str(self.runs_dir),
            "started_at": None,
            "stopped_at": None,
            "last_connection_at": None,
            "last_error": None,
            "received_count": 0,
            "health_check_count": 0,
            "last_result": None,
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _status_locked(self) -> dict[str, Any]:
        status = dict(self._state)
        if status.get("address") is not None:
            status["address"] = list(status["address"])
        status["thread_alive"] = bool(self._thread and self._thread.is_alive())
        return status

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_locked()

    def start(self, bind_host: str = "0.0.0.0", port: int = 5000) -> dict[str, Any]:
        with self._lock:
            if self._receiver is not None and self._state["online"]:
                return self._status_locked()

            receiver = LanTcpReceiver(bind_host, int(port), self.runs_dir)
            info = receiver.start()
            stop_event = threading.Event()
            self._receiver = receiver
            self._stop_event = stop_event
            self._state.update(
                {
                    "online": True,
                    "status": "listening",
                    "bind_host": str(bind_host),
                    "port": info["address"][1],
                    "address": info["address"],
                    "output_dir": str(self.runs_dir),
                    "started_at": self._now(),
                    "stopped_at": None,
                    "last_connection_at": None,
                    "last_error": None,
                    "received_count": 0,
                    "health_check_count": 0,
                    "last_result": None,
                }
            )
            thread = threading.Thread(
                target=self._serve_loop,
                args=(receiver, stop_event),
                name="traditional-web-receiver",
                daemon=True,
            )
            self._thread = thread
            thread.start()
            return self._status_locked()

    def _load_result(self, run_id: str | None) -> dict[str, Any] | None:
        if not run_id:
            return None
        result_path = self.runs_dir / str(run_id) / "receiver_result.json"
        if not result_path.is_file():
            return None
        try:
            return json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _serve_loop(self, receiver: LanTcpReceiver, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                connection_stats = receiver.serve_once()
            except OSError as exc:
                if stop_event.is_set():
                    break
                with self._lock:
                    self._state["last_error"] = str(exc)
                    self._state["status"] = "failed"
                break
            except Exception as exc:
                with self._lock:
                    self._state["last_error"] = str(exc)
                    self._state["status"] = "failed"
                break

            with self._lock:
                self._state["last_connection_at"] = self._now()
                if connection_stats.get("message_type") == "health_check":
                    self._state["health_check_count"] += 1
                    continue
                self._state["received_count"] += 1
                run_id = connection_stats.get("run_id")
                result = self._load_result(run_id)
                self._state["last_result"] = result or {
                    "run_id": run_id,
                    "received_bytes": connection_stats.get("received_bytes", 0),
                    "receiver_decode_valid": connection_stats.get("receiver_decode_valid"),
                    "receiver_error": connection_stats.get("error"),
                }

        with self._lock:
            if self._receiver is receiver:
                self._state["online"] = False
                if self._state.get("status") != "failed":
                    self._state["status"] = "stopped"
                self._state["stopped_at"] = self._now()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            receiver = self._receiver
            stop_event = self._stop_event
            thread = self._thread
            if receiver is None:
                return self._status_locked()
            if stop_event is not None:
                stop_event.set()
            receiver.close()

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        with self._lock:
            self._receiver = None
            self._stop_event = None
            self._thread = None
            self._state["online"] = False
            if self._state.get("status") != "failed":
                self._state["status"] = "stopped"
            self._state["stopped_at"] = self._now()
            return self._status_locked()

    def list_results(self, limit: int = 50) -> list[dict[str, Any]]:
        candidates = []
        for result_path in self.runs_dir.glob("*/receiver_result.json"):
            try:
                candidates.append((result_path.stat().st_mtime, result_path))
            except OSError:
                continue
        results = []
        for _, result_path in sorted(candidates, reverse=True)[: max(1, int(limit))]:
            try:
                results.append(json.loads(result_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return results

    def get_result(self, run_id: str) -> dict[str, Any] | None:
        return self._load_result(run_id)

    def get_file(self, run_id: str, name: str) -> Path:
        if not name or Path(name).name != name:
            raise ValueError("file name must not contain a directory")
        run_dir = (self.runs_dir / str(run_id)).resolve()
        if self.runs_dir not in run_dir.parents:
            raise ValueError("run_id is outside the receiver directory")
        path = (run_dir / name).resolve()
        if run_dir not in path.parents:
            raise ValueError("file is outside the receiver run directory")
        if not path.is_file():
            raise FileNotFoundError(name)
        return path
