"""Typed object storage configuration shared by API and worker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .object_storage import ObjectStorage, S3ObjectStorage


@dataclass(frozen=True)
class ObjectStorageSettings:
    backend: Literal["filesystem", "s3"] = "filesystem"
    endpoint_url: str | None = None
    bucket: str = "aicontent-ai-artifacts"
    access_key: str | None = None
    secret_key: str | None = None
    region: str = "us-east-1"

    def build(self) -> ObjectStorage:
        if self.backend != "s3":
            raise ValueError("Filesystem object storage is constructed with an explicit path")
        assert self.endpoint_url is not None
        assert self.access_key is not None
        assert self.secret_key is not None
        return S3ObjectStorage(
            self.endpoint_url,
            self.bucket,
            self.access_key,
            self.secret_key,
            region=self.region,
        )


__all__ = ["ObjectStorageSettings"]
