"""Bounded CSV source adapter for GMC export files."""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from ..domain.models import GmcIngestionSpec, SourceDescriptor
from ..ports.interfaces import SourceReadError


class CsvGmcSource:
    """Inspect and stream one local CSV without loading the file into memory."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def inspect(self, specification: GmcIngestionSpec) -> SourceDescriptor:
        try:
            digest = hashlib.sha256()
            with self._path.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
            with self._path.open("r", encoding="utf-8-sig", newline="") as source:
                reader = csv.reader(source)
                columns = tuple(next(reader))
        except (OSError, StopIteration, UnicodeError, csv.Error) as exc:
            raise SourceReadError(f"Cannot inspect GMC source {specification.source_ref}") from exc
        return SourceDescriptor(
            source_ref=specification.source_ref,
            checksum_sha256=digest.hexdigest(),
            size_bytes=self._path.stat().st_size,
            columns=columns,
            observed_at=datetime.now(UTC),
        )

    def iter_rows(self, chunk_size: int) -> Iterator[tuple[int, dict[str, str]]]:
        del chunk_size  # csv.DictReader is already row-streaming and memory bounded.
        try:
            with self._path.open("r", encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source)
                if reader.fieldnames is None:
                    raise SourceReadError("GMC source has no header")
                for row_number, row in enumerate(reader, start=2):
                    yield row_number, {key: value or "" for key, value in row.items() if key}
        except (OSError, UnicodeError, csv.Error) as exc:
            raise SourceReadError("Cannot stream GMC source") from exc
