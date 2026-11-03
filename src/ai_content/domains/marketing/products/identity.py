"""Stable identity of a Pinterest image across the sizes the CDN serves."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

PIN_SIZE_DIR = re.compile(r"^/(?:\d+x\d*|originals)/")


def media_source_fingerprint(url: str) -> str:
    """Hash an image URL so every size of the same Pinterest image maps to one id."""
    parsed = urlsplit(url.strip())
    path = PIN_SIZE_DIR.sub("/size/", parsed.path, 1)
    return hashlib.sha256(f"{parsed.scheme}://{parsed.netloc}{path}".encode()).hexdigest()
