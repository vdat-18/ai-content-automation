"""Vendor-neutral object storage contracts and adapters."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


class ObjectStorageError(RuntimeError):
    """Base error for an object storage operation."""


class ObjectNotFoundError(ObjectStorageError):
    """Raised when an object does not exist."""


class ObjectConflictError(ObjectStorageError):
    """Raised when an immutable key already contains different content."""


@dataclass(frozen=True)
class ObjectMetadata:
    key: str
    size_bytes: int
    content_type: str
    sha256: str


@dataclass
class ObjectDownload:
    stream: BinaryIO
    metadata: ObjectMetadata
    content_length: int
    content_range: str | None = None


class ObjectStorage(Protocol):
    def check(self) -> None: ...

    def put_file(
        self,
        key: str,
        source: Path,
        *,
        content_type: str,
        sha256: str,
    ) -> ObjectMetadata: ...

    def stat(self, key: str) -> ObjectMetadata: ...

    def open(
        self,
        key: str,
        *,
        start: int | None = None,
        end: int | None = None,
    ) -> Iterator[ObjectDownload]: ...


def normalize_object_key(key: str) -> str:
    """Normalize an untrusted key and reject traversal or absolute paths."""
    candidate = PurePosixPath(key.replace("\\", "/"))
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ValueError("Object key must be a relative path without traversal")
    normalized = candidate.as_posix()
    if not normalized:
        raise ValueError("Object key must not be empty")
    return normalized


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


class FilesystemObjectStorage:
    """Object storage contract backed by one local directory for tests."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        root = self._root.resolve()
        target = root.joinpath(*PurePosixPath(normalize_object_key(key)).parts).resolve()
        if not target.is_relative_to(root):
            raise ValueError("Object key escapes configured root")
        return target

    def check(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        if not self._root.is_dir():
            raise ObjectStorageError("Object storage root is unavailable")

    def put_file(
        self,
        key: str,
        source: Path,
        *,
        content_type: str,
        sha256: str,
    ) -> ObjectMetadata:
        target = self._path(key)
        existing = self._metadata(target, key, content_type) if target.is_file() else None
        if existing is not None:
            if existing.sha256 == sha256:
                return existing
            raise ObjectConflictError("Immutable object key already contains different content")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        digest = hashlib.sha256()
        size = 0
        try:
            with (
                source.open("rb") as source_file,
                tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as pending,
            ):
                temporary = Path(pending.name)
                while chunk := source_file.read(1024 * 1024):
                    pending.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                pending.flush()
                os.fsync(pending.fileno())
            if digest.hexdigest() != sha256:
                raise ObjectStorageError("Source checksum changed during upload")
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self._metadata_path(target).write_text(f"{content_type}\n{sha256}\n", encoding="utf-8")
        return ObjectMetadata(normalize_object_key(key), size, content_type, sha256)

    def stat(self, key: str) -> ObjectMetadata:
        target = self._path(key)
        if not target.is_file():
            raise ObjectNotFoundError("Object does not exist")
        metadata_path = self._metadata_path(target)
        legacy_metadata_path = target.with_suffix(f"{target.suffix}.metadata")
        content_type = "application/octet-stream"
        if metadata_path.is_file():
            content_type = metadata_path.read_text(encoding="utf-8").splitlines()[0]
        elif legacy_metadata_path.is_file():
            content_type = legacy_metadata_path.read_text(encoding="utf-8").splitlines()[0]
        return self._metadata(target, key, content_type)

    @staticmethod
    def _metadata_path(target: Path) -> Path:
        name_hash = hashlib.sha256(target.name.encode()).hexdigest()[:12]
        return target.parent / f".{name_hash}.meta"

    @contextmanager
    def open(
        self,
        key: str,
        *,
        start: int | None = None,
        end: int | None = None,
    ) -> Iterator[ObjectDownload]:
        metadata = self.stat(key)
        source = self._path(key).open("rb")
        try:
            first, last = _resolve_range(metadata.size_bytes, start, end)
            source.seek(first)
            length = last - first + 1
            yield ObjectDownload(
                _BoundedReader(source, length),
                metadata,
                length,
                f"bytes {first}-{last}/{metadata.size_bytes}"
                if start is not None or end is not None
                else None,
            )
        finally:
            source.close()

    @staticmethod
    def _metadata(path: Path, key: str, content_type: str) -> ObjectMetadata:
        checksum, size = sha256_file(path)
        return ObjectMetadata(normalize_object_key(key), size, content_type, checksum)


class S3ObjectStorage:
    """S3-compatible adapter with immutable conditional writes."""

    def __init__(
        self,
        endpoint_url: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        *,
        region: str = "us-east-1",
    ) -> None:
        self.bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(
                connect_timeout=5,
                read_timeout=30,
                retries={"mode": "standard", "total_max_attempts": 2},
                s3={"addressing_style": "path"},
            ),
        )

    def check(self) -> None:
        self._client.head_bucket(Bucket=self.bucket)

    def put_file(
        self,
        key: str,
        source: Path,
        *,
        content_type: str,
        sha256: str,
    ) -> ObjectMetadata:
        normalized = normalize_object_key(key)
        size = source.stat().st_size
        try:
            with source.open("rb") as body:
                self._client.put_object(
                    Bucket=self.bucket,
                    Key=normalized,
                    Body=body,
                    ContentLength=size,
                    ContentType=content_type,
                    Metadata={"sha256": sha256},
                    IfNoneMatch="*",
                )
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status not in {409, 412}:
                raise ObjectStorageError("Object upload failed") from error
            existing = self.stat(normalized)
            if existing.sha256 != sha256 or existing.size_bytes != size:
                raise ObjectConflictError(
                    "Immutable object key already contains different content"
                ) from error
            return existing
        uploaded = self.stat(normalized)
        if uploaded.sha256 != sha256 or uploaded.size_bytes != size:
            raise ObjectStorageError("Uploaded object failed checksum verification")
        return uploaded

    def stat(self, key: str) -> ObjectMetadata:
        normalized = normalize_object_key(key)
        try:
            response = self._client.head_object(Bucket=self.bucket, Key=normalized)
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                raise ObjectNotFoundError("Object does not exist") from error
            raise ObjectStorageError("Object metadata lookup failed") from error
        checksum = response.get("Metadata", {}).get("sha256")
        if not checksum:
            raise ObjectStorageError("Object is missing its SHA-256 metadata")
        return ObjectMetadata(
            normalized,
            int(response["ContentLength"]),
            response.get("ContentType", "application/octet-stream"),
            checksum,
        )

    @contextmanager
    def open(
        self,
        key: str,
        *,
        start: int | None = None,
        end: int | None = None,
    ) -> Iterator[ObjectDownload]:
        metadata = self.stat(key)
        first, last = _resolve_range(metadata.size_bytes, start, end)
        request: dict[str, object] = {"Bucket": self.bucket, "Key": metadata.key}
        if start is not None or end is not None:
            request["Range"] = f"bytes={first}-{last}"
        try:
            response = self._client.get_object(**request)
        except ClientError as error:
            raise ObjectStorageError("Object download failed") from error
        body = response["Body"]
        try:
            yield ObjectDownload(
                body,
                metadata,
                int(response["ContentLength"]),
                response.get("ContentRange"),
            )
        finally:
            body.close()


class _BoundedReader:
    def __init__(self, source: BinaryIO, remaining: int) -> None:
        self._source = source
        self._remaining = remaining

    def read(self, size: int = -1) -> bytes:
        if self._remaining <= 0:
            return b""
        requested = self._remaining if size < 0 else min(size, self._remaining)
        content = self._source.read(requested)
        self._remaining -= len(content)
        return content


def _resolve_range(size: int, start: int | None, end: int | None) -> tuple[int, int]:
    if size <= 0:
        return 0, -1
    first = 0 if start is None else start
    last = size - 1 if end is None else min(end, size - 1)
    if first < 0 or first >= size or last < first:
        raise ValueError("Requested byte range is not satisfiable")
    return first, last


def iter_download(download: ObjectDownload, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    while chunk := download.stream.read(chunk_size):
        yield chunk


__all__ = [
    "FilesystemObjectStorage",
    "ObjectConflictError",
    "ObjectDownload",
    "ObjectMetadata",
    "ObjectNotFoundError",
    "ObjectStorage",
    "ObjectStorageError",
    "S3ObjectStorage",
    "iter_download",
    "normalize_object_key",
    "sha256_file",
]
