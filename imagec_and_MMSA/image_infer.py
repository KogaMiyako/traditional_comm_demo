"""stdin JSON -> stdout JSON CIFAR-10 inference adapter."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from PIL import Image

from traditional_comm_py.runtime import PROJECT_ROOT, json_error, load_config, resolve_path


def main() -> int:
    request = None
    config = load_config()
    cfg = config["image_classification"]
    model_cfg = cfg["model"]
    checkpoint_display = str(cfg["checkpoint"])
    start = time.perf_counter()
    try:
        request = json.load(sys.stdin)
        task_cfg = request.get("task_config", {}).get("model", {})
        checkpoint_value = task_cfg.get("checkpoint") or cfg["checkpoint"]
        checkpoint = resolve_path(checkpoint_value)
        import torch
        import torchvision.transforms as transforms

        sys.path.insert(0, str(PROJECT_ROOT / "pytorch-cifar"))
        from models.resnet import ResNet18

        state = torch.load(checkpoint, map_location="cpu")
        model = ResNet18()
        model.load_state_dict(state.get("state_dict", state["net"] if "net" in state else state))
        model.eval()
        classes = state.get("classes", ["plane", "car", "bird", "cat", "deer", "dog", "frog", "horse", "ship", "truck"])
        mean = state.get("normalize_mean", cfg["train"]["normalize_mean"])
        std = state.get("normalize_std", cfg["train"]["normalize_std"])
        image_path = resolve_path(request["input_path"])
        with Image.open(image_path) as image:
            image = image.convert("RGB")
            tensor = transforms.Compose([
                transforms.Resize((int(state.get("input_size", 32)), int(state.get("input_size", 32)))),
                transforms.ToTensor(),
                transforms.Normalize(mean, std),
            ])(image).unsqueeze(0)
        with torch.no_grad():
            probabilities = torch.softmax(model(tensor), dim=1)[0]
        values, indices = torch.topk(probabilities, k=min(5, len(classes)))
        top_k = [
            {"label": int(index), "label_name": classes[int(index)], "confidence": float(value)}
            for value, index in zip(values, indices)
        ]
        top1 = top_k[0]
        task_context = request.get("task_context", {})
        ground_truth = task_context.get("ground_truth_label", task_context.get("label"))
        metrics = {"top1": None, "top5": None}
        if ground_truth is not None:
            ground_truth = int(ground_truth)
            metrics = {
                "top1": float(top1["label"] == ground_truth),
                "top5": float(any(item["label"] == ground_truth for item in top_k)),
            }
        result = {
            "success": True,
            "prediction": {
                "label": top1["label"],
                "label_name": top1["label_name"],
                "confidence": top1["confidence"],
                "top_k": top_k,
            },
            "metrics": metrics,
            "model_version": task_cfg.get("version") or state.get("model_version", model_cfg["version"]),
            "checkpoint": checkpoint_value,
            "error": None,
        }
    except Exception as exc:  # protocol errors must still be JSON
        result = json_error(str(exc), model_cfg["version"], checkpoint_display)
    result["inference_time_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
