"""Difference hash that recognises the same picture after resizing or recompression."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, UnidentifiedImageError

_SIDE = 8
MAX_DUPLICATE_DISTANCE = 5


def perceptual_hash(content: bytes) -> str | None:
    try:
        with Image.open(BytesIO(content)) as image:
            pixels = image.convert("L").resize((_SIDE + 1, _SIDE), Image.Resampling.LANCZOS)
            values = pixels.tobytes()
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    bits = 0
    for row in range(_SIDE):
        for column in range(_SIDE):
            index = row * (_SIDE + 1) + column
            bits = (bits << 1) | (values[index] > values[index + 1])
    return f"{bits:016x}"


def is_duplicate_hash(first: str, second: str) -> bool:
    return (int(first, 16) ^ int(second, 16)).bit_count() <= MAX_DUPLICATE_DISTANCE


__all__ = ["MAX_DUPLICATE_DISTANCE", "is_duplicate_hash", "perceptual_hash"]
