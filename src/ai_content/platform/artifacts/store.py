"""Filesystem artifact store primitive.

Knows nothing about Marketing/Creative records; callers decide layout and
content. Domain objects never call this store directly.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


class ArtifactStore:
    """Writes and reads artifacts under a root directory."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def path(self, *parts: str) -> Path:
        """Resolve a path inside the store without allowing path traversal."""
        root = self._root.resolve()
        target = root.joinpath(*parts).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"Artifact path escapes configured root: {target}")
        return target

    def write_text(self, content: str, *parts: str) -> Path:
        """Write a UTF-8 text artifact and return its path."""
        return self.write_bytes(content.encode("utf-8"), *parts)

    def write_bytes(self, content: bytes, *parts: str) -> Path:
        """Write a binary artifact and return its path."""
        target = self.path(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as pending:
                temporary = Path(pending.name)
                pending.write(content)
                pending.flush()
                os.fsync(pending.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return target

    def copy_file(self, source: Path, *parts: str) -> Path:
        """Copy a file into the store atomically without loading it into memory."""
        target = self.path(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with (
                source.open("rb") as source_file,
                tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as pending,
            ):
                temporary = Path(pending.name)
                while chunk := source_file.read(1024 * 1024):
                    pending.write(chunk)
                pending.flush()
                os.fsync(pending.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return target

    def read_text(self, *parts: str) -> str | None:
        """Read a text artifact, or None when it does not exist."""
        target = self.path(*parts)
        if not target.is_file():
            return None
        return target.read_text(encoding="utf-8")

    def exists(self, *parts: str) -> bool:
        return self.path(*parts).exists()


__all__ = ["ArtifactStore"]
