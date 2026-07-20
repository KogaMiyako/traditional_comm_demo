"""Train the stable ResNet18 CIFAR-10 model from pytorch-cifar."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Tuple

import numpy as np

from traditional_comm_py.runtime import (
    PROJECT_ROOT,
    environment_info,
    ensure_parent,
    load_config,
    resolve_path,
    set_seed,
    setup_logging,
    write_json,
)


CLASSES = ["plane", "car", "bird", "cat", "deer", "dog", "frog", "horse", "ship", "truck"]


def build_model():
    sys.path.insert(0, str(PROJECT_ROOT / "pytorch-cifar"))
    from models.resnet import ResNet18

    return ResNet18()


def make_loaders(cfg):
    import torch
    import torchvision
    import torchvision.transforms as transforms
    from PIL import Image
    from torch.utils.data import DataLoader, Dataset, Subset

    class DirectCIFAR10(Dataset):
        def __init__(self, data_root, train, transform):
            import pickle

            self.transform = transform
            names = [f"data_batch_{i}" for i in range(1, 6)] if train else ["test_batch"]
            images, labels = [], []
            for name in names:
                with (data_root / name).open("rb") as handle:
                    batch = pickle.load(handle, encoding="latin1")
                images.append(np.asarray(batch["data"], dtype=np.uint8))
                labels.extend(batch["labels"])
            self.data = np.concatenate(images, axis=0).reshape(-1, 3, 32, 32).transpose(0, 2, 3, 1)
            self.targets = list(labels)

        def __len__(self):
            return len(self.targets)

        def __getitem__(self, index):
            image = Image.fromarray(self.data[index])
            if self.transform:
                image = self.transform(image)
            return image, int(self.targets[index])

    train_cfg = cfg["train"]
    root = resolve_path(cfg["data_root"])
    mean, std = train_cfg["normalize_mean"], train_cfg["normalize_std"]
    train_transform = transforms.Compose([
        transforms.RandomCrop(train_cfg.get("input_size", 32), padding=4),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize(mean, std),
    ])
    test_transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize(mean, std),
    ])
    direct_layout = (root / "data_batch_1").is_file() and (root / "test_batch").is_file()
    if direct_layout:
        train_set = DirectCIFAR10(root, train=True, transform=train_transform)
        test_set = DirectCIFAR10(root, train=False, transform=test_transform)
    else:
        train_set = torchvision.datasets.CIFAR10(
            root=str(root), train=True, download=bool(train_cfg["download_if_missing"]), transform=train_transform
        )
        test_set = torchvision.datasets.CIFAR10(
            root=str(root), train=False, download=bool(train_cfg["download_if_missing"]), transform=test_transform
        )
    if train_cfg.get("max_train_samples"):
        train_set = Subset(train_set, range(min(int(train_cfg["max_train_samples"]), len(train_set))))
    if train_cfg.get("max_test_samples"):
        test_set = Subset(test_set, range(min(int(train_cfg["max_test_samples"]), len(test_set))))
    loader_args = {
        "batch_size": int(train_cfg["batch_size"]),
        "num_workers": int(train_cfg["num_workers"]),
        "pin_memory": bool(torch.cuda.is_available()),
    }
    return (
        DataLoader(train_set, shuffle=True, **loader_args),
        DataLoader(test_set, shuffle=False, **loader_args),
    )


def evaluate(model, loader, device) -> Tuple[Dict[str, float], np.ndarray, np.ndarray]:
    import torch

    model.eval()
    total, correct, top5_correct = 0, 0, 0
    predictions, targets = [], []
    loss_total = 0.0
    criterion = torch.nn.CrossEntropyLoss()
    with torch.no_grad():
        for inputs, labels in loader:
            inputs, labels = inputs.to(device), labels.to(device)
            logits = model(inputs)
            loss_total += float(criterion(logits, labels).item()) * labels.size(0)
            topk = logits.topk(5, dim=1).indices
            correct += int((topk[:, 0] == labels).sum())
            top5_correct += int((topk == labels.view(-1, 1)).any(dim=1).sum())
            total += labels.size(0)
            predictions.append(logits.cpu().numpy())
            targets.append(labels.cpu().numpy())
    logits_np = np.concatenate(predictions, axis=0)
    target_np = np.concatenate(targets, axis=0)
    pred_np = logits_np.argmax(axis=1)
    try:
        from sklearn.metrics import f1_score

        f1 = float(f1_score(target_np, pred_np, average="weighted", zero_division=0))
    except ImportError:
        f1 = float("nan")
    metrics = {
        "loss": loss_total / max(total, 1),
        "accuracy": correct / max(total, 1),
        "f1": f1,
        "top1": correct / max(total, 1),
        "top5": top5_correct / max(total, 1),
        "samples": total,
    }
    return metrics, logits_np, target_np


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    config = load_config(args.config)
    cfg = config["image_classification"]
    log_path = resolve_path(cfg["log_path"])
    logger = setup_logging(log_path, "train_image")
    set_seed(int(cfg["train"]["seed"]))

    import torch

    requested_device = cfg["train"].get("device", "cuda" if torch.cuda.is_available() else "cpu")
    device = torch.device(requested_device)
    if device.type == "cuda" and not torch.cuda.is_available():
        logger.warning("requested CUDA is unavailable; falling back to CPU")
        device = torch.device("cpu")
    logger.info("device=%s", device)
    train_loader, test_loader = make_loaders(cfg)
    model = build_model().to(device)
    optimizer = torch.optim.SGD(
        model.parameters(),
        lr=float(cfg["train"]["learning_rate"]),
        momentum=float(cfg["train"]["momentum"]),
        weight_decay=float(cfg["train"]["weight_decay"]),
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, int(cfg["train"]["epochs"])))
    criterion = torch.nn.CrossEntropyLoss()
    best_top1 = -1.0
    checkpoint_path = resolve_path(cfg["checkpoint"])
    for epoch in range(1, int(cfg["train"]["epochs"]) + 1):
        model.train()
        running_loss, seen, correct = 0.0, 0, 0
        for inputs, labels in train_loader:
            inputs, labels = inputs.to(device), labels.to(device)
            optimizer.zero_grad()
            logits = model(inputs)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()
            running_loss += float(loss.item()) * labels.size(0)
            seen += labels.size(0)
            correct += int((logits.argmax(dim=1) == labels).sum())
        scheduler.step()
        metrics, _, _ = evaluate(model, test_loader, device)
        logger.info(
            "epoch=%d train_loss=%.5f train_accuracy=%.5f test_top1=%.5f test_top5=%.5f",
            epoch, running_loss / max(seen, 1), correct / max(seen, 1), metrics["top1"], metrics["top5"]
        )
        if metrics["top1"] >= best_top1:
            best_top1 = metrics["top1"]
            state = {
                "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
                "model_name": cfg["model"]["name"],
                "model_version": cfg["model"]["version"],
                "classes": CLASSES,
                "normalize_mean": cfg["train"]["normalize_mean"],
                "normalize_std": cfg["train"]["normalize_std"],
                "input_size": int(cfg["model"]["input_size"]),
                "epoch": epoch,
                "metrics": metrics,
                "config_path": config["_config_path"],
                "environment": environment_info(),
            }
            ensure_parent(checkpoint_path)
            torch.save(state, checkpoint_path)
    final_metrics, _, _ = evaluate(model, test_loader, device)
    write_json(resolve_path(cfg["metrics_path"]), final_metrics)
    write_json(resolve_path(cfg["classes_path"]), {"dataset": "cifar10", "classes": CLASSES})
    write_json(resolve_path(cfg["environment_path"]), environment_info())
    logger.info("checkpoint=%s", checkpoint_path)
    logger.info("metrics=%s", json.dumps(final_metrics, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
