"""stdin JSON -> stdout JSON MMSA MOSEI sentiment adapter."""

from __future__ import annotations

import json
import pickle
import sys
import time
from pathlib import Path
from typing import Any, Dict

import numpy as np

from traditional_comm_py.runtime import PROJECT_ROOT, json_error, load_config, resolve_path


def _mmsa_imports():
    sys.path.insert(0, str(PROJECT_ROOT / "MMSA" / "src"))
    from easydict import EasyDict as edict
    from MMSA.models import AMIO

    return edict, AMIO


def _sample_from_file(path: Path, request: Dict[str, Any]) -> Dict[str, Any]:
    if path.suffix.lower() == ".npz":
        archive = np.load(path, allow_pickle=True)
        return {key: archive[key] for key in archive.files}
    with path.open("rb") as handle:
        data = pickle.load(handle)
    if all(split in data for split in ("train", "valid", "test")):
        split = request.get("task_context", {}).get("split", "test")
        index = int(request.get("task_context", {}).get("sample_index", 0))
        section = data[split]
        sample = {
            "text": np.asarray(section["text"][index]),
            "audio": np.asarray(section["audio"][index]),
            "vision": np.asarray(section["vision"][index]),
        }
        if "regression_labels" in section:
            sample["label"] = float(np.asarray(section["regression_labels"])[index])
        if "id" in section:
            sample["id"] = str(section["id"][index])
        return sample
    return data


def _metric_value(metrics: Dict[str, Any], *names):
    for name in names:
        if name in metrics:
            value = metrics[name]
            try:
                value = float(value)
                return value if np.isfinite(value) else None
            except (TypeError, ValueError):
                return value
    return None


def main() -> int:
    config = load_config()
    cfg = config["video_sentiment"]
    model_cfg = cfg["model"]
    checkpoint_display = str(cfg["checkpoint"])
    start = time.perf_counter()
    try:
        request = json.load(sys.stdin)
        task_model = request.get("task_config", {}).get("model", {})
        checkpoint_value = task_model.get("checkpoint") or cfg["checkpoint"]
        checkpoint = resolve_path(checkpoint_value)
        import torch

        state = torch.load(checkpoint, map_location="cpu")
        model_args = dict(state.get("model_args", {}))
        edict, AMIO = _mmsa_imports()
        sample = _sample_from_file(resolve_path(request["input_path"]), request)
        text = np.asarray(sample["text"], dtype=np.float32)
        audio = np.asarray(sample["audio"], dtype=np.float32)
        vision = np.asarray(sample["vision"], dtype=np.float32)
        if text.ndim != 2 or audio.ndim != 2 or vision.ndim != 2:
            raise ValueError(f"sample text/audio/vision must be 2D, got {text.shape}, {audio.shape}, {vision.shape}")
        if model_args.get("need_normalized", False):
            audio = audio.mean(axis=0, keepdims=True)
            vision = vision.mean(axis=0, keepdims=True)
        model_args["feature_dims"] = [int(text.shape[1]), int(audio.shape[1]), int(vision.shape[1])]
        model_args["seq_lens"] = [int(text.shape[0]), int(audio.shape[0]), int(vision.shape[0])]
        model_args["device"] = torch.device("cpu")
        model_args["model_save_path"] = checkpoint
        model_args = edict(model_args)
        model = AMIO(model_args)
        model.load_state_dict(state["state_dict"], strict=True)
        model.eval()
        with torch.no_grad():
            output = model(
                torch.from_numpy(text).unsqueeze(0),
                torch.from_numpy(audio).unsqueeze(0),
                torch.from_numpy(vision).unsqueeze(0),
            )
        score = float(output["M"].reshape(-1)[0])
        label = "positive" if score >= float(cfg["positive_threshold"]) else "negative"
        test_metrics = state.get("metrics", {})
        metrics = {
            "mae": _metric_value(test_metrics, "mae", "MAE"),
            "correlation": _metric_value(test_metrics, "correlation", "Corr"),
            "accuracy": _metric_value(test_metrics, "accuracy", "Has0_acc_2"),
            "f1": _metric_value(test_metrics, "f1", "Has0_F1_score"),
        }
        ground_truth = sample.get("label", request.get("task_context", {}).get("ground_truth_score"))
        if ground_truth is not None:
            truth = float(ground_truth)
            metrics["mae"] = abs(score - truth)
            metrics["accuracy"] = float((score >= 0.0) == (truth >= 0.0))
            metrics["f1"] = metrics["accuracy"]
            metrics["correlation"] = None
        result = {
            "success": True,
            "prediction": {"sentiment_score": score, "label": label},
            "metrics": metrics,
            "model_version": task_model.get("version") or state.get("model_version", model_cfg["version"]),
            "checkpoint": checkpoint_value,
            "error": None,
        }
    except Exception as exc:
        result = json_error(str(exc), model_cfg["version"], checkpoint_display)
    result["inference_time_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
