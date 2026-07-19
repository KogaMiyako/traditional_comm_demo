from __future__ import annotations

import json
from pathlib import Path

from .runner import create_run_id, run_one


class TraditionalCommunicationController:
    def __init__(self, runs_dir: Path, transport):
        self.runs_dir = Path(runs_dir).resolve()
        self.transport = transport
        self.mode = "traditional"
        self.states: dict[str, dict] = {}

    def health_check(self) -> dict:
        return self.transport.health_check()

    def switch_mode(self, mode: str) -> dict:
        if mode not in {"traditional", "semantic"}:
            raise ValueError(f"unsupported mode: {mode}")
        self.mode = mode
        return {"mode": self.mode}

    def start_run(self, config: dict) -> dict:
        if self.mode != "traditional":
            raise RuntimeError("this controller executes traditional mode only")
        kind = config["kind"]
        input_path = Path(config["input_path"])
        run_id = create_run_id(kind)
        state = {
            "run_id": run_id,
            "mode": self.mode,
            "status": "running",
            "kind": kind,
            "input_path": str(input_path.resolve()),
        }
        self.states[run_id] = state
        try:
            result = run_one(
                kind,
                input_path,
                self.runs_dir,
                self.transport,
                config.get("task", {}),
                run_id=run_id,
            )
            state.update({"status": result["metrics"]["status"], "result": result})
        except Exception as exc:
            state.update({"status": "failed", "error": str(exc)})
            raise
        return {"run_id": run_id, "status": state["status"]}

    def get_status(self, run_id: str) -> dict:
        state = self.states[run_id]
        return {key: state.get(key) for key in ("run_id", "mode", "status", "kind", "input_path", "error")}

    def get_performance(self, run_id: str) -> dict:
        return self.states[run_id]["result"]["metrics"]

    def get_result(self, run_id: str) -> dict:
        result_dir = Path(self.states[run_id]["result"]["run_dir"])
        return json.loads((result_dir / "result.json").read_text(encoding="utf-8"))

    def stop_run(self, run_id: str) -> dict:
        state = self.states[run_id]
        if state["status"] == "running":
            state["status"] = "cancelled"
        return self.get_status(run_id)
