"""Maintenance CLI for application backup and restore."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
from pathlib import Path
from time import monotonic

import httpx
from loguru import logger
from sqlalchemy import text

from ai_content.platform.backups import (
    BackupService,
    BackupValidationError,
    OffsiteBackupService,
)
from ai_content.platform.database import Database
from ai_content.platform.execution import PostgresExecutionOutbox
from ai_content.settings import ApplicationSettings

_SAFE_BACKUP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Back up and restore durable pilot data")
    subcommands = parser.add_subparsers(dest="command", required=True)

    create = subcommands.add_parser("create", help="Create and verify a new backup set")
    create.add_argument("--destination", type=Path, default=Path("/backups"))
    create.add_argument("--backup-id", required=True)
    create.add_argument("--source-revision")
    create.add_argument("--source-dirty", choices=("true", "false"))

    verify = subcommands.add_parser("verify", help="Verify backup files without restoring")
    verify.add_argument("--backup-set", type=Path, required=True)

    restore = subcommands.add_parser("restore", help="Restore into an empty database and bucket")
    restore.add_argument("--backup-set", type=Path, required=True)

    restored = subcommands.add_parser(
        "verify-restored", help="Compare a restored environment with its manifest"
    )
    restored.add_argument("--backup-set", type=Path, required=True)

    upload = subcommands.add_parser(
        "upload-offsite", help="Upload one verified backup set when off-site storage is enabled"
    )
    upload.add_argument("--backup-set", type=Path, required=True)

    download = subcommands.add_parser(
        "download-offsite", help="Download and verify one off-site backup set"
    )
    download.add_argument("--backup-id", required=True)
    download.add_argument("--destination", type=Path, default=Path("/backups"))

    recover = subcommands.add_parser(
        "recover-execution",
        help="Requeue active Celery commands after restoring into a fresh broker",
    )
    recover.add_argument("--backup-set", type=Path, required=True)

    http = subcommands.add_parser(
        "verify-http", help="Verify health and exact artifact bytes through the restored API"
    )
    http.add_argument("--backup-set", type=Path, required=True)
    http.add_argument("--base-url", default="http://api:8000")
    return parser


async def _run(args: argparse.Namespace) -> None:
    settings = ApplicationSettings()
    if args.command in {"upload-offsite", "download-offsite"}:
        storage = settings.backup_storage()
        if storage is None:
            logger.info("Off-site backup is disabled; no remote transfer was performed")
            return
        service = OffsiteBackupService(
            storage.build(),
            prefix=settings.backup_s3_prefix,
        )
        if args.command == "upload-offsite":
            manifest = await asyncio.to_thread(service.upload, args.backup_set)
        else:
            if not _SAFE_BACKUP_ID.fullmatch(args.backup_id):
                raise BackupValidationError("backup-id contains unsupported characters")
            manifest = await asyncio.to_thread(
                service.download,
                args.backup_id,
                args.destination / args.backup_id,
            )
        logger.info("Off-site backup {} verified", manifest.backup_id)
        return
    if settings.database_backend != "postgresql" or settings.database_url is None:
        raise BackupValidationError("Backup maintenance requires PostgreSQL settings")
    database_url = settings.database_url.get_secret_value()
    database = Database(database_url)
    service = BackupService(
        database,
        database_url,
        settings.object_storage(),
        execution_backend=settings.execution_backend,
    )
    try:
        if args.command == "create":
            if not _SAFE_BACKUP_ID.fullmatch(args.backup_id):
                raise BackupValidationError("backup-id contains unsupported characters")
            manifest = await service.create(
                args.destination,
                args.backup_id,
                source_revision=args.source_revision,
                source_dirty=(args.source_dirty == "true")
                if args.source_dirty is not None
                else None,
            )
        elif args.command == "verify":
            manifest = service.verify_files(args.backup_set)
        elif args.command == "restore":
            manifest = await service.restore(args.backup_set)
        elif args.command == "verify-restored":
            manifest = service.verify_files(args.backup_set)
            await service.verify_restored(manifest)
        elif args.command == "recover-execution":
            manifest = service.verify_files(args.backup_set)
            recovered = 0
            if manifest.execution_backend == "celery":
                recovered = await PostgresExecutionOutbox(
                    database.engine
                ).requeue_active_commands_after_restore()
            logger.info("Requeued {} active Celery commands after restore", recovered)
        else:
            manifest = service.verify_files(args.backup_set)
            await _verify_http(database, manifest, args.base_url)
        logger.info(
            "Backup {} verified: {} tables, {} objects, {} object bytes",
            manifest.backup_id,
            len(manifest.database_tables),
            manifest.object_count,
            manifest.object_bytes,
        )
    finally:
        await database.close()


def main() -> int:
    args = _parser().parse_args()
    try:
        asyncio.run(_run(args))
    except (BackupValidationError, ValueError, OSError) as error:
        logger.error("Backup maintenance failed: {}", error)
        return 1
    return 0


async def _verify_http(
    database: Database,
    manifest,
    base_url: str,
) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=15) as client:
        deadline = monotonic() + 60
        while True:
            try:
                ready = await client.get("/health/ready")
                ready.raise_for_status()
                break
            except httpx.HTTPError as error:
                if monotonic() >= deadline:
                    raise BackupValidationError(
                        "Restored API did not become ready in time"
                    ) from error
                await asyncio.sleep(1)
        async with database.engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT artifact_id, object_key, sha256, size_bytes "
                    "FROM platform.artifacts WHERE status = 'available' "
                    "ORDER BY artifact_id LIMIT 1"
                )
            )
            artifact = result.one_or_none()
        if artifact is None:
            logger.info("No available artifact exists; HTTP artifact verification was skipped")
            return
        artifact_id, object_key, checksum, size = artifact
        expected = next((item for item in manifest.objects if item.key == object_key), None)
        if expected is None or expected.sha256 != checksum or expected.size_bytes != size:
            raise BackupValidationError("Restored artifact is absent from the backup manifest")
        metadata = await client.get(f"/api/v1/artifacts/{artifact_id}")
        metadata.raise_for_status()
        content = await client.get(f"/api/v1/artifacts/{artifact_id}/content")
        content.raise_for_status()
        if hashlib.sha256(content.content).hexdigest() != checksum:
            raise BackupValidationError("Artifact HTTP response checksum does not match")
        if size:
            last = min(size - 1, 31)
            partial = await client.get(
                f"/api/v1/artifacts/{artifact_id}/content",
                headers={"Range": f"bytes=0-{last}"},
            )
            if partial.status_code != 206 or partial.content != content.content[: last + 1]:
                raise BackupValidationError("Artifact HTTP Range verification failed")


if __name__ == "__main__":
    raise SystemExit(main())
