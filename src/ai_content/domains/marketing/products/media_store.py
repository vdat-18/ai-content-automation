"""Where generated images, clips and audio live: object storage, with a local folder as working copy.

ffmpeg and the image code need real files, so every file is first written to the local folder.
With a remote store configured (SeaweedFS in Docker) each write is also uploaded, and a file that
is missing locally is downloaded again on demand, so the local folder can be lost safely.
"""

from __future__ import annotations

import asyncio
import mimetypes
import shutil
from pathlib import Path, PurePosixPath
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from ai_content.platform.artifacts.object_storage import sha256_file

KEY_PREFIX = "affiliate-media/"


class RemoteMedia(Protocol):
    def put(self, key: str, source: Path, content_type: str) -> None: ...

    def get(self, key: str, target: Path) -> bool: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...

    def delete_prefix(self, prefix: str) -> None: ...


class S3RemoteMedia:
    """Overwritable S3-compatible store (the artifact adapter is write-once, media is not)."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(
                connect_timeout=5,
                read_timeout=120,
                retries={"mode": "standard", "total_max_attempts": 3},
                s3={"addressing_style": "path"},
            ),
        )

    def put(self, key: str, source: Path, content_type: str) -> None:
        checksum, size = sha256_file(source)  # the backup checks every object against this
        with source.open("rb") as body:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body,
                ContentLength=size,
                ContentType=content_type,
                Metadata={"sha256": checksum},
            )

    def get(self, key: str, target: Path) -> bool:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                return False
            if error.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                return False
            raise
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        with response["Body"] as body, partial.open("wb") as out:
            while chunk := body.read(1024 * 1024):
                out.write(chunk)
        partial.replace(target)
        return True

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                return False
            raise
        return True

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def delete_prefix(self, prefix: str) -> None:
        pages = self._client.get_paginator("list_objects_v2").paginate(
            Bucket=self._bucket, Prefix=prefix
        )
        for page in pages:
            for item in page.get("Contents", []):
                self._client.delete_object(Bucket=self._bucket, Key=item["Key"])


def _relative(relative: str | Path) -> str:
    candidate = PurePosixPath(str(relative).replace("\\", "/"))
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ValueError("Media path must be relative without traversal")
    return candidate.as_posix()


class MediaStore:
    """Local working folder plus an optional remote copy of the same relative paths."""

    def __init__(self, root: Path, remote: RemoteMedia | None = None) -> None:
        self._root = Path(root)
        self._remote = remote

    @property
    def root(self) -> Path:
        return self._root

    def path(self, relative: str | Path) -> Path:
        return self._root / _relative(relative)

    def _key(self, relative: str | Path) -> str:
        return KEY_PREFIX + _relative(relative)

    @staticmethod
    def _content_type(relative: str | Path) -> str:
        return mimetypes.guess_type(str(relative))[0] or "application/octet-stream"

    async def push(self, relative: str | Path) -> None:
        """Upload a file that already exists in the local folder."""
        if self._remote is not None:
            await asyncio.to_thread(
                self._remote.put,
                self._key(relative),
                self.path(relative),
                self._content_type(relative),
            )

    async def write(self, relative: str | Path, content: bytes) -> Path:
        target = self.path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        await self.push(relative)
        return target

    async def fetch(self, relative: str | Path) -> Path | None:
        """The local path of the file, downloading it first when only the remote has it."""
        target = self.path(relative)
        if target.is_file():
            return target
        if self._remote is not None and await asyncio.to_thread(
            self._remote.get, self._key(relative), target
        ):
            return target
        return None

    async def fetch_first(self, relatives: list[str]) -> Path | None:
        for relative in relatives:
            found = await self.fetch(relative)
            if found is not None:
                return found
        return None

    async def read(self, relative: str | Path) -> bytes:
        found = await self.fetch(relative)
        if found is None:
            raise FileNotFoundError(str(relative))
        return found.read_bytes()

    async def exists(self, relative: str | Path) -> bool:
        if self.path(relative).is_file():
            return True
        return self._remote is not None and await asyncio.to_thread(
            self._remote.exists, self._key(relative)
        )

    async def remove_tree(self, relative: str | Path) -> None:
        """Delete a folder with everything in it, here and in the remote store."""
        shutil.rmtree(self.path(relative), ignore_errors=True)
        if self._remote is not None:
            prefix = self._key(relative).rstrip("/") + "/"
            await asyncio.to_thread(self._remote.delete_prefix, prefix)

    async def remove(self, relative: str | Path) -> None:
        self.path(relative).unlink(missing_ok=True)
        if self._remote is not None:
            await asyncio.to_thread(self._remote.delete, self._key(relative))
