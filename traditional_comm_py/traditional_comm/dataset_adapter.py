from __future__ import annotations

import pickle
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_CIFAR_BATCHES = {
    "train": [f"data_batch_{index}" for index in range(1, 6)],
    "test": ["test_batch"],
}


def _mapping_value(mapping: dict[Any, Any], key: str, default: Any = None) -> Any:
    if key in mapping:
        return mapping[key]
    byte_key = key.encode("ascii")
    return mapping.get(byte_key, default)


def _decode_label_name(value: Any) -> str | None:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if value is None:
        return None
    return str(value)


def _row_bytes(row: Any) -> bytes:
    if isinstance(row, bytes):
        return row
    if isinstance(row, bytearray):
        return bytes(row)
    if hasattr(row, "tobytes"):
        return row.tobytes()
    if hasattr(row, "tolist"):
        return bytes(row.tolist())
    return bytes(row)


def _cifar_row_to_ppm(row: Any, width: int = 32, height: int = 32) -> bytes:
    raw = _row_bytes(row)
    plane_size = width * height
    expected_size = plane_size * 3
    if len(raw) != expected_size:
        raise ValueError(f"CIFAR-10 image must contain {expected_size} bytes, got {len(raw)}")
    red = raw[:plane_size]
    green = raw[plane_size : plane_size * 2]
    blue = raw[plane_size * 2 :]
    pixels = bytearray(expected_size)
    for offset in range(plane_size):
        pixel_offset = offset * 3
        pixels[pixel_offset] = red[offset]
        pixels[pixel_offset + 1] = green[offset]
        pixels[pixel_offset + 2] = blue[offset]
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    return header + bytes(pixels)


@dataclass(frozen=True)
class Cifar10Sample:
    dataset: str
    split: str
    index: int
    label: int
    label_name: str | None
    ppm_bytes: bytes

    @property
    def sample_id(self) -> str:
        return f"cifar10-{self.split}-{self.index:05d}"


class Cifar10Dataset:
    """Lazy reader for the official CIFAR-10 Python batch format."""

    def __init__(self, root: str | Path, split: str = "test", samples_per_file: int = 10000):
        self.root = Path(root).resolve()
        if split not in _CIFAR_BATCHES:
            raise ValueError(f"unsupported CIFAR-10 split: {split}")
        self.split = split
        self.batch_paths = [self.root / name for name in _CIFAR_BATCHES[split]]
        missing = [str(path) for path in self.batch_paths if not path.is_file()]
        if missing:
            raise FileNotFoundError("missing CIFAR-10 batch files: " + ", ".join(missing))
        self.samples_per_file = int(samples_per_file)
        if self.samples_per_file <= 0:
            raise ValueError("samples_per_file must be positive")
        self.label_names = self._load_label_names()

    def __len__(self) -> int:
        return len(self.batch_paths) * self.samples_per_file

    def _load_label_names(self) -> list[str] | None:
        metadata_path = self.root / "batches.meta"
        if not metadata_path.is_file():
            return None
        try:
            with metadata_path.open("rb") as handle:
                metadata = pickle.load(handle, encoding="bytes")
        except (ModuleNotFoundError, ImportError):
            return None
        names = _mapping_value(metadata, "label_names")
        if names is None:
            return None
        return [_decode_label_name(name) or "" for name in names]

    def _load_batch(self, batch_path: Path) -> tuple[Any, list[int]]:
        try:
            with batch_path.open("rb") as handle:
                batch = pickle.load(handle, encoding="bytes")
        except (ModuleNotFoundError, ImportError) as exc:
            raise RuntimeError(
                "读取 CIFAR-10 需要 numpy。请在 semcom-py 环境中执行 "
                "conda install numpy，或重新创建 environment.yml 环境。"
            ) from exc
        data = _mapping_value(batch, "data")
        labels = _mapping_value(batch, "labels")
        if data is None or labels is None:
            raise ValueError(f"invalid CIFAR-10 batch file: {batch_path}")
        return data, list(labels)

    def get(self, index: int) -> Cifar10Sample:
        if index < 0 or index >= len(self):
            raise IndexError(f"CIFAR-10 index out of range: {index}")
        batch_index, row_index = divmod(index, self.samples_per_file)
        data, labels = self._load_batch(self.batch_paths[batch_index])
        if row_index >= len(data) or row_index >= len(labels):
            raise IndexError(f"CIFAR-10 batch does not contain index {row_index}")
        label = int(labels[row_index])
        label_name = self.label_names[label] if self.label_names and label < len(self.label_names) else None
        return Cifar10Sample(
            dataset="cifar10",
            split=self.split,
            index=index,
            label=label,
            label_name=label_name,
            ppm_bytes=_cifar_row_to_ppm(data[row_index]),
        )


def select_cifar10_sample(
    root: str | Path,
    split: str = "test",
    mode: str = "random",
    seed: int | None = 100,
    index: int | None = None,
    samples_per_file: int = 10000,
) -> Cifar10Sample:
    dataset = Cifar10Dataset(root, split=split, samples_per_file=samples_per_file)
    if index is not None:
        selected_index = int(index)
    elif mode == "random":
        selected_index = random.Random(seed).randrange(len(dataset))
    elif mode in {"first", "sequential", "index"}:
        selected_index = 0
    else:
        raise ValueError(f"unsupported CIFAR-10 selection mode: {mode}")
    return dataset.get(selected_index)


def materialize_cifar10_sample(sample: Cifar10Sample, output_dir: str | Path) -> Path:
    output_path = Path(output_dir).resolve() / f"{sample.sample_id}.ppm"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not output_path.is_file():
        output_path.write_bytes(sample.ppm_bytes)
    return output_path
