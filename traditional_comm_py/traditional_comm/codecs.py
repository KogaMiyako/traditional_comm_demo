from __future__ import annotations

from dataclasses import dataclass
import zlib


@dataclass(frozen=True)
class EncodedPayload:
    codec: str
    container: str
    payload: bytes


def _check_bytes(value: bytes, label: str) -> None:
    if not isinstance(value, bytes):
        raise TypeError(f"{label} must be bytes")


def encode_payload(kind: str, data: bytes) -> EncodedPayload:
    _check_bytes(data, "data")
    if kind == "text":
        return EncodedPayload("utf8", "txt", data)
    if kind == "image":
        return EncodedPayload("ppm-deflate", "ppm", zlib.compress(data, level=6))
    if kind == "video":
        return EncodedPayload("tvid-deflate", "tvid", zlib.compress(data, level=6))
    raise ValueError(f"unsupported media kind: {kind}")


def decode_payload(kind: str, payload: bytes) -> bytes:
    _check_bytes(payload, "payload")
    if kind == "text":
        return bytes(payload)
    if kind in {"image", "video"}:
        return zlib.decompress(payload)
    raise ValueError(f"unsupported media kind: {kind}")


def codec_info(kind: str) -> dict:
    values = {
        "text": {"codec": "utf8", "container": "txt", "lossless": True},
        "image": {"codec": "ppm-deflate", "container": "ppm", "lossless": True},
        "video": {"codec": "tvid-deflate", "container": "tvid", "lossless": True},
    }
    try:
        return values[kind].copy()
    except KeyError as exc:
        raise ValueError(f"unsupported media kind: {kind}") from exc
