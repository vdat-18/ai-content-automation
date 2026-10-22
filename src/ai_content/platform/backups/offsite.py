"""Immutable transfer of verified backup sets to object storage."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path, PurePosixPath

from ai_content.platform.artifacts.object_storage import (
    ObjectStorage,
    iter_download,
    normalize_object_key,
    sha256_file,
)

from .models import BackupManifest
from .service import BackupService, BackupValidationError


class OffsiteBackupService:
    def __init__(self, storage: ObjectStorage, *, prefix: str = "aicontent-backups") -> None:
        self._storage = storage
        self._prefix = normalize_object_key(prefix).rstrip("/")

    def upload(self, backup_set: Path) -> BackupManifest:
        manifest = BackupService.verify_files(backup_set)
        self._storage.check()
        files = ["manifest.json", "manifest.sha256", manifest.database_dump_file]
        files.extend(
            PurePosixPath("objects", normalize_object_key(item.key)).as_posix()
            for item in manifest.objects
        )
        for relative in files:
            source = backup_set.joinpath(*PurePosixPath(relative).parts)
            checksum, _ = sha256_file(source)
            self._storage.put_file(
                self._key(manifest.backup_id, relative),
                source,
                content_type=_content_type(relative),
                sha256=checksum,
            )
        return manifest

    def download(self, backup_id: str, destination: Path) -> BackupManifest:
        if destination.exists():
            raise BackupValidationError("Off-site download destination already exists")
        pending = destination.with_name(f".{destination.name}.partial")
        if pending.exists():
            raise BackupValidationError("Off-site partial download already exists")
        pending.mkdir(parents=True)
        try:
            self._download_file(backup_id, "manifest.sha256", pending / "manifest.sha256")
            self._download_file(backup_id, "manifest.json", pending / "manifest.json")
            manifest = BackupManifest.model_validate_json(
                (pending / "manifest.json").read_text(encoding="utf-8")
            )
            if manifest.backup_id != backup_id:
                raise BackupValidationError("Off-site manifest backup ID does not match")
            self._download_file(
                backup_id,
                manifest.database_dump_file,
                pending / manifest.database_dump_file,
            )
            for item in manifest.objects:
                relative = PurePosixPath("objects", normalize_object_key(item.key)).as_posix()
                self._download_file(backup_id, relative, pending.joinpath(*relative.split("/")))
            BackupService.verify_files(pending)
            os.replace(pending, destination)
            return manifest
        except Exception:
            shutil.rmtree(pending, ignore_errors=True)
            raise

    def _download_file(self, backup_id: str, relative: str, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.partial")
        digest = hashlib.sha256()
        with self._storage.open(self._key(backup_id, relative)) as download:
            with temporary.open("xb") as destination:
                for chunk in iter_download(download):
                    destination.write(chunk)
                    digest.update(chunk)
            if digest.hexdigest() != download.metadata.sha256:
                raise BackupValidationError("Off-site object checksum does not match metadata")
        os.replace(temporary, target)

    def _key(self, backup_id: str, relative: str) -> str:
        return normalize_object_key(
            PurePosixPath(self._prefix, backup_id, relative.replace("\\", "/")).as_posix()
        )


def _content_type(relative: str) -> str:
    if relative.endswith(".json"):
        return "application/json"
    if relative.endswith(".sha256"):
        return "text/plain"
    return "application/octet-stream"
