"""Convert the uploaded legacy MISA MOSEI pickles to MMSA's feature schema."""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any, Dict

import numpy as np

from .runtime import ensure_parent


def _token_features(token_ids: np.ndarray, dim: int) -> np.ndarray:
    """Create deterministic compact token features without downloading a BERT.

    The uploaded legacy files contain integerized tokens rather than BERT
    vectors.  A fixed sinusoidal/hash projection preserves token identity and
    sequence order while keeping the MMSA LF-DNN input small and reproducible.
    """

    ids = token_ids.astype(np.float32).reshape(-1, 1)
    columns = np.arange(1, dim + 1, dtype=np.float32).reshape(1, -1)
    values = np.sin(ids * columns * 0.017) + np.cos((ids + columns) * 0.013)
    return values.astype(np.float32)


def _convert_split(items, max_seq_len: int, text_dim: int) -> Dict[str, Any]:
    n = len(items)
    text = np.zeros((n, max_seq_len, text_dim), dtype=np.float32)
    audio = np.zeros((n, max_seq_len, 74), dtype=np.float32)
    vision = np.zeros((n, max_seq_len, 35), dtype=np.float32)
    audio_lengths, vision_lengths, ids, raw_text, labels = [], [], [], [], []
    for index, item in enumerate(items):
        (token_ids, visual_features, acoustic_features, words), label, sample_id = item
        token_ids = np.asarray(token_ids).reshape(-1)
        visual_features = np.asarray(visual_features, dtype=np.float32)
        acoustic_features = np.asarray(acoustic_features, dtype=np.float32)
        length = min(max_seq_len, len(token_ids), visual_features.shape[0], acoustic_features.shape[0])
        if length:
            text[index, :length] = _token_features(token_ids[:length], text_dim)
            vision[index, :length] = visual_features[:length]
            audio[index, :length] = acoustic_features[:length]
        audio_lengths.append(length)
        vision_lengths.append(length)
        ids.append(str(sample_id))
        raw_text.append(" ".join(str(word) for word in words[:length]))
        labels.append(float(np.asarray(label).reshape(-1)[0]))
    labels_array = np.asarray(labels, dtype=np.float32).reshape(-1, 1)
    return {
        "raw_text": raw_text,
        "audio": audio,
        "vision": vision,
        "id": ids,
        "text": text,
        "text_bert": np.zeros((n, 3, max_seq_len), dtype=np.float32),
        "audio_lengths": np.asarray(audio_lengths, dtype=np.int32),
        "vision_lengths": np.asarray(vision_lengths, dtype=np.int32),
        "annotations": raw_text,
        "classification_labels": ((labels_array > 0).astype(np.int64) + (labels_array >= 0).astype(np.int64)),
        "regression_labels": labels_array,
    }


def ensure_mmsa_feature_file(source_dir: Path, output_path: Path, max_seq_len: int, text_dim: int) -> Path:
    """Return an MMSA feature file, converting the legacy upload once if needed."""

    if output_path.is_file():
        return output_path
    split_paths = {
        "train": source_dir / "train.pkl",
        "valid": source_dir / "dev.pkl",
        "test": source_dir / "test.pkl",
    }
    missing = [str(path) for path in split_paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing legacy MOSEI split files: " + ", ".join(missing))
    converted = {}
    for split, path in split_paths.items():
        with path.open("rb") as handle:
            source_items = pickle.load(handle)
        if not isinstance(source_items, list):
            raise ValueError(f"legacy MOSEI split {path} is not a list")
        converted[split] = _convert_split(source_items, max_seq_len, text_dim)
    ensure_parent(output_path)
    with output_path.open("wb") as handle:
        pickle.dump(converted, handle, protocol=pickle.HIGHEST_PROTOCOL)
    return output_path
