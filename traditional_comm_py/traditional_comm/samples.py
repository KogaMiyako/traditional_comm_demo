from __future__ import annotations

from pathlib import Path


def parse_ppm(data: bytes) -> dict:
    """Parse a binary P6 PPM image and return its dimensions and RGB bytes."""
    if not data.startswith(b"P6"):
        raise ValueError("unsupported PPM magic")
    index = 0
    tokens: list[bytes] = []
    while len(tokens) < 4:
        while index < len(data) and data[index] in b" \t\r\n":
            index += 1
        if index < len(data) and data[index] == ord("#"):
            newline = data.find(b"\n", index)
            if newline < 0:
                raise ValueError("invalid PPM comment")
            index = newline + 1
            continue
        start = index
        while index < len(data) and data[index] not in b" \t\r\n#":
            index += 1
        if start == index:
            raise ValueError("invalid PPM header")
        tokens.append(data[start:index])
        if index < len(data) and data[index] == ord("#"):
            newline = data.find(b"\n", index)
            if newline < 0:
                raise ValueError("invalid PPM comment")
            index = newline + 1
        elif index < len(data):
            if data[index] == ord("\r") and index + 1 < len(data) and data[index + 1] == ord("\n"):
                index += 2
            else:
                index += 1
    magic, width_value, height_value, max_value = tokens
    if magic != b"P6":
        raise ValueError("unsupported PPM magic")
    width, height, max_value_int = int(width_value), int(height_value), int(max_value)
    if width <= 0 or height <= 0 or max_value_int != 255:
        raise ValueError("unsupported PPM dimensions or color depth")
    pixels = data[index:]
    expected = width * height * 3
    if len(pixels) != expected:
        raise ValueError(f"invalid PPM pixel data: expected {expected}, got {len(pixels)}")
    return {
        "width": width,
        "height": height,
        "max_value": max_value_int,
        "pixel_bytes": pixels,
        "pixel_offset": index,
    }


def create_rgb_frame(width: int, height: int, frame_index: int = 0, total_frames: int = 1) -> bytes:
    pixels = bytearray(width * height * 3)
    phase = int(frame_index / max(total_frames, 1) * 255)
    for y in range(height):
        for x in range(width):
            offset = (y * width + x) * 3
            pixels[offset] = (int(x * 255 / max(width - 1, 1)) + phase) % 256
            pixels[offset + 1] = (int(y * 255 / max(height - 1, 1)) + phase * 2) % 256
            pixels[offset + 2] = ((x + y + phase) * 3) % 256
    return bytes(pixels)


def create_ppm(width: int, height: int, frame_index: int = 0, total_frames: int = 1) -> bytes:
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    return header + create_rgb_frame(width, height, frame_index, total_frames)


def create_tvid(width: int, height: int, fps: int, frame_count: int) -> bytes:
    header = f"TVID1\n{width} {height} {fps} {frame_count}\n".encode("ascii")
    frames = b"".join(
        create_rgb_frame(width, height, frame, frame_count)
        for frame in range(frame_count)
    )
    return header + frames


def parse_tvid(data: bytes) -> dict:
    first_break = data.find(b"\n")
    second_break = data.find(b"\n", first_break + 1)
    if first_break < 0 or second_break < 0:
        raise ValueError("invalid TVID header")
    if data[:first_break].decode("ascii") != "TVID1":
        raise ValueError("unsupported TVID magic")
    values = data[first_break + 1 : second_break].decode("ascii").split()
    if len(values) != 4:
        raise ValueError("invalid TVID metadata")
    width, height, fps, frame_count = map(int, values)
    frame_size = width * height * 3
    payload = data[second_break + 1 :]
    expected = frame_size * frame_count
    if min(width, height, frame_count) <= 0 or len(payload) != expected:
        raise ValueError("invalid TVID frame data")
    return {
        "width": width,
        "height": height,
        "fps": fps,
        "frame_count": frame_count,
        "frame_size": frame_size,
        "header_bytes": second_break + 1,
    }


def generate_samples(output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    text_path = output_dir / "sample.txt"
    text_path.write_text(
        "传统通信本地测试样本\n"
        "This is a small UTF-8 text sample for the local baseline.\n"
        "内容2：常规通信链路先在单系统内跑通。\n",
        encoding="utf-8",
    )
    image_path = output_dir / "sample.ppm"
    image_path.write_bytes(create_ppm(160, 90))
    video_path = output_dir / "sample.tvid"
    video_path.write_bytes(create_tvid(160, 90, 10, 12))
    return {"text": text_path, "image": image_path, "video": video_path}
