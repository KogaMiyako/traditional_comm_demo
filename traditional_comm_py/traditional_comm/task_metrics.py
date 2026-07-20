from __future__ import annotations

import math

from .samples import parse_ppm, parse_tvid


def _psnr(source_pixels: bytes, output_pixels: bytes) -> float | None:
    if len(source_pixels) != len(output_pixels) or not source_pixels:
        return None
    squared_error = sum(
        (source_value - output_value) ** 2
        for source_value, output_value in zip(source_pixels, output_pixels)
    )
    mse = squared_error / len(source_pixels)
    if mse == 0:
        return 99.0
    return round(10 * math.log10((255**2) / mse), 3)


def quality_metrics(kind: str, source: bytes, output: bytes) -> dict:
    """Calculate the media quality metrics used by reconstruction tasks."""
    if kind == "image":
        source_info = parse_ppm(source)
        output_info = parse_ppm(output)
        if (source_info["width"], source_info["height"]) != (
            output_info["width"],
            output_info["height"],
        ):
            return {"psnr": None, "ssim": None, "lpips": None}
        return {
            "psnr": _psnr(source_info["pixel_bytes"], output_info["pixel_bytes"]),
            "ssim": None,
            "lpips": None,
        }
    if kind == "video":
        source_info = parse_tvid(source)
        output_info = parse_tvid(output)
        same_shape = (
            source_info["width"] == output_info["width"]
            and source_info["height"] == output_info["height"]
            and source_info["frame_count"] == output_info["frame_count"]
        )
        if not same_shape:
            return {"psnr": None, "ssim": None, "lpips": None}
        return {
            "psnr": _psnr(
                source[source_info["header_bytes"] :],
                output[output_info["header_bytes"] :],
            ),
            "ssim": None,
            "lpips": None,
        }
    return {"psnr": None, "ssim": None, "lpips": None}
