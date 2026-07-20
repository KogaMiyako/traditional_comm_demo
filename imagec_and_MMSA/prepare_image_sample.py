"""Materialize one uploaded CIFAR-10 test image for interface verification."""

from __future__ import annotations

import argparse
import pickle

import numpy as np
from PIL import Image

from traditional_comm_py.runtime import load_config, resolve_path, ensure_parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    config = load_config(args.config)
    cfg = config["image_classification"]
    data_root = resolve_path(cfg["data_root"])
    with (data_root / "test_batch").open("rb") as handle:
        batch = pickle.load(handle, encoding="latin1")
    image = np.asarray(batch["data"][0], dtype=np.uint8).reshape(3, 32, 32).transpose(1, 2, 0)
    output = resolve_path(cfg["sample_path"])
    ensure_parent(output)
    Image.fromarray(image).save(output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
