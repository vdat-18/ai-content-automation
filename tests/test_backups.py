import hashlib

import pytest

from ai_content.platform.artifacts import ObjectStorageSettings
from ai_content.platform.backups.service import BackupService, BackupValidationError


class _Body:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def read(self, size: int) -> bytes:
        chunk, self._content = self._content[:size], self._content[size:]
        return chunk

    def close(self) -> None:
        pass


class _Paginator:
    def __init__(self, objects: dict[str, tuple[bytes, dict[str, str]]]) -> None:
        self._objects = objects

    def paginate(self, **_: object) -> list[dict[str, object]]:
        return [{"Contents": [{"Key": key} for key in self._objects]}]


class _S3:
    def __init__(self, objects: dict[str, tuple[bytes, dict[str, str]]]) -> None:
        self._objects = objects

    def get_paginator(self, _: str) -> _Paginator:
        return _Paginator(self._objects)

    def get_object(self, *, Key: str, **_: object) -> dict[str, object]:  # noqa: N803
        content, metadata = self._objects[Key]
        return {
            "Body": _Body(content),
            "Metadata": metadata,
            "ContentLength": len(content),
            "ContentType": "video/mp4",
        }


def _service(objects: dict[str, tuple[bytes, dict[str, str]]]) -> BackupService:
    storage = ObjectStorageSettings(
        backend="s3", endpoint_url="http://s3", access_key="k", secret_key="s"
    )
    service = BackupService(None, "postgresql://u:p@h/d", storage)  # type: ignore[arg-type]
    service._s3 = _S3(objects)  # type: ignore[assignment]
    return service


def test_an_object_without_a_recorded_checksum_is_backed_up_with_its_real_one(tmp_path) -> None:
    media = b"clip stored before the checksum was recorded"
    service = _service({"affiliate-media/clips/p/shot_0.mp4": (media, {})})
    [item] = service._download_objects(tmp_path / "objects")
    assert item.sha256 == hashlib.sha256(media).hexdigest()
    assert (tmp_path / "objects" / "affiliate-media/clips/p/shot_0.mp4").read_bytes() == media


def test_a_recorded_checksum_that_does_not_match_the_bytes_fails_the_backup(tmp_path) -> None:
    service = _service({"affiliate-media/a.mp4": (b"bytes", {"sha256": "0" * 64})})
    with pytest.raises(BackupValidationError, match="failed verification"):
        service._download_objects(tmp_path / "objects")
