"""Image payload shared by Media Asset ports and services."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImageBinary:
    content: bytes
    extension: str
    content_type: str
