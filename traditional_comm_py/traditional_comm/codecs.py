from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil
import subprocess
import sys

from .samples import parse_ppm, parse_tvid


@dataclass(frozen=True)
class EncodedPayload:
    codec: str
    container: str
    payload: bytes
    metadata: dict = field(default_factory=dict)


def _check_bytes(value: bytes, label: str) -> None:
    if not isinstance(value, bytes):
        raise TypeError(f"{label} must be bytes")


def _find_binary(name: str) -> str:
    """Find a binary in PATH or in the active Conda environment."""
    candidates = []
    located = shutil.which(name)
    if located:
        candidates.append(Path(located))

    environment_dir = Path(sys.executable).resolve().parent
    candidates.extend(
        [
            environment_dir / name,
            environment_dir / f"{name}.exe",
            environment_dir / "Library" / "bin" / name,
            environment_dir / "Library" / "bin" / f"{name}.exe",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError(
        f"{name} not found. Install it in the semcom-py environment with "
        "conda install -c conda-forge ffmpeg."
    )


def _run_ffmpeg(arguments: list[str], input_data: bytes) -> bytes:
    command = [_find_binary("ffmpeg"), "-hide_banner", "-loglevel", "error", *arguments]
    completed = subprocess.run(
        command,
        input=input_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=120,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"FFmpeg failed ({completed.returncode}): {message}")
    return completed.stdout


def _encode_image(data: bytes, options: dict) -> EncodedPayload:
    source = parse_ppm(data)
    quality = int(options.get("jpeg_quality", 3))
    if not 2 <= quality <= 31:
        raise ValueError("jpeg_quality must be between 2 and 31")
    payload = _run_ffmpeg(
        [
            "-f",
            "image2pipe",
            "-vcodec",
            "ppm",
            "-i",
            "pipe:0",
            "-frames:v",
            "1",
            "-q:v",
            str(quality),
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ],
        data,
    )
    return EncodedPayload(
        codec="jpeg",
        container="jpg",
        payload=payload,
        metadata={
            "width": source["width"],
            "height": source["height"],
            "encoder": "ffmpeg:mjpeg",
            "parameters": {"jpeg_quality": quality},
            "lossless": False,
        },
    )


def _encode_video(data: bytes, options: dict) -> EncodedPayload:
    source = parse_tvid(data)
    if source["width"] % 2 or source["height"] % 2:
        raise ValueError("H.264 yuv420p requires even video width and height")
    crf = int(options.get("h264_crf", 23))
    preset = str(options.get("h264_preset", "ultrafast"))
    if not 0 <= crf <= 51:
        raise ValueError("h264_crf must be between 0 and 51")
    raw_frames = data[source["header_bytes"] :]
    payload = _run_ffmpeg(
        [
            "-f",
            "rawvideo",
            "-pixel_format",
            "rgb24",
            "-video_size",
            f"{source['width']}x{source['height']}",
            "-framerate",
            str(source["fps"]),
            "-i",
            "pipe:0",
            "-frames:v",
            str(source["frame_count"]),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+frag_keyframe+empty_moov",
            "-f",
            "mp4",
            "pipe:1",
        ],
        raw_frames,
    )
    return EncodedPayload(
        codec="h264",
        container="mp4",
        payload=payload,
        metadata={
            "width": source["width"],
            "height": source["height"],
            "fps": source["fps"],
            "frame_count": source["frame_count"],
            "encoder": "ffmpeg:libx264",
            "parameters": {"h264_crf": crf, "h264_preset": preset},
            "lossless": False,
        },
    )


def encode_payload(kind: str, data: bytes, options: dict | None = None) -> EncodedPayload:
    _check_bytes(data, "data")
    options = options or {}
    if kind == "text":
        return EncodedPayload(
            "utf8",
            "txt",
            data,
            {"encoder": "python:utf-8", "lossless": True, "parameters": {}},
        )
    if kind == "image":
        return _encode_image(data, options)
    if kind == "video":
        return _encode_video(data, options)
    raise ValueError(f"unsupported media kind: {kind}")


def _decode_image(payload: bytes) -> bytes:
    return _run_ffmpeg(
        [
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "-i",
            "pipe:0",
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "ppm",
            "pipe:1",
        ],
        payload,
    )


def _decode_video(payload: bytes, metadata: dict) -> bytes:
    width = int(metadata["width"])
    height = int(metadata["height"])
    fps = int(metadata["fps"])
    expected_frames = int(metadata["frame_count"])
    raw_frames = _run_ffmpeg(
        [
            "-i",
            "pipe:0",
            "-map",
            "0:v:0",
            "-an",
            "-frames:v",
            str(expected_frames),
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        payload,
    )
    frame_size = width * height * 3
    if not raw_frames or len(raw_frames) % frame_size:
        raise RuntimeError("decoded video does not contain complete RGB frames")
    frame_count = len(raw_frames) // frame_size
    header = f"TVID1\n{width} {height} {fps} {frame_count}\n".encode("ascii")
    return header + raw_frames


def decode_payload(kind: str, payload: bytes, metadata: dict | None = None) -> bytes:
    _check_bytes(payload, "payload")
    if kind == "text":
        return bytes(payload)
    if kind == "image":
        return _decode_image(payload)
    if kind == "video":
        if metadata is None:
            raise ValueError("video decoding requires codec metadata")
        return _decode_video(payload, metadata)
    raise ValueError(f"unsupported media kind: {kind}")


def codec_info(kind: str) -> dict:
    values = {
        "text": {"codec": "utf8", "container": "txt", "lossless": True},
        "image": {"codec": "jpeg", "container": "jpg", "lossless": False},
        "video": {"codec": "h264", "container": "mp4", "lossless": False},
    }
    try:
        return values[kind].copy()
    except KeyError as exc:
        raise ValueError(f"unsupported media kind: {kind}") from exc
