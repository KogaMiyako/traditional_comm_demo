"""Train MMSA's stable LF-DNN regression model on MOSEI features."""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path
from typing import Any, Dict

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
from traditional_comm_py.mosei_adapter import ensure_mmsa_feature_file


def _mmsa_imports():
    sys.path.insert(0, str(PROJECT_ROOT / "MMSA" / "src"))
    from easydict import EasyDict as edict
    from MMSA.data_loader import MMDataLoader
    from MMSA.models import AMIO
    from MMSA.trains import ATIO

    return edict, MMDataLoader, AMIO, ATIO


def _load_feature_metadata(feature_path: Path) -> Dict[str, Any]:
    with feature_path.open("rb") as handle:
        data = pickle.load(handle)
    if not all(split in data for split in ("train", "valid", "test")):
        raise ValueError("MOSEI feature file must contain train, valid, and test splits")
    train = data["train"]
    text = np.asarray(train["text"])
    audio = np.asarray(train["audio"])
    vision = np.asarray(train["vision"])
    if text.ndim != 3 or audio.ndim != 3 or vision.ndim != 3:
        raise ValueError(f"expected 3D text/audio/vision arrays, got {text.shape}, {audio.shape}, {vision.shape}")
    return {
        "feature_dims": [int(text.shape[2]), int(audio.shape[2]), int(vision.shape[2])],
        "seq_lens": [int(text.shape[1]), int(audio.shape[1]), int(vision.shape[1])],
        "sample_count": {key: len(data[key]["regression_labels"]) for key in ("train", "valid", "test")},
    }


def _build_args(cfg, feature_path: Path, checkpoint_path: Path, feature_dims, seq_lens):
    edict, _, _, _ = _mmsa_imports()
    train_cfg = cfg["train"]
    args = edict({
        "model_name": cfg["model"]["name"],
        "dataset_name": "mosei",
        "featurePath": str(feature_path),
        "custom_feature": None,
        "feature_T": None,
        "feature_A": None,
        "feature_V": None,
        "train_mode": "regression",
        "need_data_aligned": bool(train_cfg["need_data_aligned"]),
        "need_model_aligned": bool(train_cfg["need_model_aligned"]),
        "need_normalized": bool(train_cfg["need_normalized"]),
        "use_bert": bool(train_cfg["use_bert"]),
        "feature_dims": list(feature_dims),
        "seq_lens": list(seq_lens),
        "num_classes": 3,
        "KeyEval": "Loss",
        "language": "en",
        "missing_rate": [0.2, 0.2, 0.2],
        "missing_seed": [1111, 1111, 1111],
        "hidden_dims": list(train_cfg["hidden_dims"]),
        "text_out": int(train_cfg["text_out"]),
        "post_fusion_dim": int(train_cfg["post_fusion_dim"]),
        "dropouts": list(train_cfg["dropouts"]),
        "batch_size": int(train_cfg["batch_size"]),
        "learning_rate": float(train_cfg["learning_rate"]),
        "weight_decay": float(train_cfg["weight_decay"]),
        "early_stop": int(train_cfg["early_stop"]),
        "update_epochs": 1,
        "model_save_path": checkpoint_path,
        "device": train_cfg.get("device", "cpu"),
        "cur_seed": int(train_cfg["seed"]),
    })
    return args


def _limit_loader(loader, max_samples):
    if not max_samples:
        return loader
    from torch.utils.data import DataLoader, Subset

    dataset = loader.dataset
    count = min(int(max_samples), len(dataset))
    return DataLoader(
        Subset(dataset, range(count)),
        batch_size=loader.batch_size,
        shuffle=loader.shuffle if hasattr(loader, "shuffle") else False,
        num_workers=0,
    )


def _make_sample_file(feature_path: Path, output_path: Path) -> None:
    with feature_path.open("rb") as handle:
        data = pickle.load(handle)
    test = data["test"]
    sample = {
        "text": np.asarray(test["text"][0]),
        "audio": np.asarray(test["audio"][0]),
        "vision": np.asarray(test["vision"][0]),
        "label": float(np.asarray(test["regression_labels"])[0]),
        "id": str(test.get("id", ["test_0"])[0]),
    }
    ensure_parent(output_path)
    with output_path.open("wb") as handle:
        pickle.dump(sample, handle, protocol=pickle.HIGHEST_PROTOCOL)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    args_cli = parser.parse_args()
    config = load_config(args_cli.config)
    cfg = config["video_sentiment"]
    logger = setup_logging(resolve_path(cfg["log_path"]), "train_video_sentiment")
    set_seed(int(cfg["train"]["seed"]))
    feature_path = ensure_mmsa_feature_file(
        resolve_path(cfg["source_dir"]),
        resolve_path(cfg["feature_path"]),
        int(cfg["feature_conversion"]["max_seq_len"]),
        int(cfg["feature_conversion"]["text_dim"]),
    )
    metadata = _load_feature_metadata(feature_path)
    checkpoint_path = resolve_path(cfg["checkpoint"])
    edict, MMDataLoader, AMIO, ATIO = _mmsa_imports()
    args = _build_args(cfg, feature_path, checkpoint_path, metadata["feature_dims"], metadata["seq_lens"])
    args["device"] = __import__("torch").device(str(args["device"]))
    logger.info("MMSA model=%s feature=%s metadata=%s", args.model_name, feature_path, metadata)
    dataloaders = MMDataLoader(args, int(cfg["train"]["num_workers"]))
    # The native loader is used by default.  Optional sample caps are useful for
    # CPU smoke runs without changing the full-data configuration.
    for split, key in (("train", "max_train_samples"), ("valid", "max_valid_samples"), ("test", "max_test_samples")):
        if cfg["train"].get(key):
            dataloaders[split] = _limit_loader(dataloaders[split], cfg["train"][key])
    model = AMIO(args).to(args.device)
    trainer = ATIO().getTrain(args)
    trainer.do_train(model, dataloaders)
    if not checkpoint_path.is_file():
        raise RuntimeError("MMSA trainer did not create a checkpoint")
    raw_state = __import__("torch").load(checkpoint_path, map_location="cpu")
    final_results = trainer.do_test(model, dataloaders["test"], mode="TEST")
    wrapped = {
        "state_dict": raw_state,
        "model_name": cfg["model"]["name"],
        "model_version": cfg["model"]["version"],
        "framework": cfg["model"]["framework"],
        "label_type": cfg["label_type"],
        "feature_dims": metadata["feature_dims"],
        "seq_lens": metadata["seq_lens"],
        "model_args": {key: value for key, value in dict(args).items() if key not in {"device", "model_save_path"}},
        "metrics": final_results,
        "config_path": config["_config_path"],
        "environment": environment_info(["MMSA", "pytorch-transformers", "nvidia-ml-py3"]),
    }
    __import__("torch").save(wrapped, checkpoint_path)
    write_json(resolve_path(cfg["metrics_path"]), final_results)
    write_json(resolve_path(cfg["environment_path"]), environment_info(["MMSA", "pytorch-transformers", "nvidia-ml-py3"]))
    _make_sample_file(feature_path, resolve_path(cfg["sample_path"]))
    logger.info("checkpoint=%s", checkpoint_path)
    logger.info("test_metrics=%s", json.dumps(final_results, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
