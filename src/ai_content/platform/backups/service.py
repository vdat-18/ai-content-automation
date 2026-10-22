"""Create, validate and restore one coherent PostgreSQL and S3 backup set."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from loguru import logger
from sqlalchemy import text
from sqlalchemy.engine import make_url

from ai_content.platform.artifacts import ObjectStorageSettings
from ai_content.platform.artifacts.object_storage import normalize_object_key
from ai_content.platform.database import Database

from .models import BackupManifest, DatabaseTableInventory, ObjectInventory

_MANIFEST = "manifest.json"
_MANIFEST_CHECKSUM = "manifest.sha256"
_OBJECTS = "objects"
_DUMP = "postgres.dump"
_SCHEMAS = ("marketing", "platform", "public")


class BackupValidationError(RuntimeError):
    """Raised when a backup or restore invariant is not satisfied."""


class BackupService:
    def __init__(
        self,
        database: Database,
        database_url: str,
        object_storage: ObjectStorageSettings,
        *,
        execution_backend: str | None = None,
    ) -> None:
        if object_storage.backend != "s3":
            raise ValueError("Backup requires the S3 object storage backend")
        self._database = database
        self._database_url = database_url
        self._storage = object_storage
        self._execution_backend = execution_backend
        self._s3 = boto3.client(
            "s3",
            endpoint_url=object_storage.endpoint_url,
            aws_access_key_id=object_storage.access_key,
            aws_secret_access_key=object_storage.secret_key,
            region_name=object_storage.region,
            config=Config(
                connect_timeout=5,
                read_timeout=60,
                retries={"mode": "standard", "total_max_attempts": 2},
                s3={"addressing_style": "path"},
            ),
        )

    async def create(
        self,
        destination: Path,
        backup_id: str,
        *,
        source_revision: str | None = None,
        source_dirty: bool | None = None,
    ) -> BackupManifest:
        final = destination / backup_id
        pending = destination / f".{backup_id}.partial"
        if final.exists() or pending.exists():
            raise BackupValidationError("Backup destination already exists")
        destination.mkdir(parents=True, exist_ok=True)
        pending.mkdir()
        try:
            before = await self.database_inventory()
            await asyncio.to_thread(self._dump_database, pending / _DUMP)
            objects = await asyncio.to_thread(self._download_objects, pending / _OBJECTS)
            after = await self.database_inventory()
            if before != after:
                raise BackupValidationError("Database changed while the backup was running")
            await self._validate_artifact_catalog(objects)
            dump_sha256, dump_size = _sha256_file(pending / _DUMP)
            manifest = BackupManifest(
                backup_id=backup_id,
                created_at=datetime.now(UTC).isoformat(),
                source_revision=source_revision,
                source_dirty=source_dirty,
                alembic_revision=await self._alembic_revision(),
                execution_backend=self._execution_backend,
                database_dump_size_bytes=dump_size,
                database_dump_sha256=dump_sha256,
                database_tables=after,
                bucket=self._storage.bucket,
                objects=objects,
                object_count=len(objects),
                object_bytes=sum(item.size_bytes for item in objects),
            )
            _write_manifest(pending, manifest)
            self.verify_files(pending)
            pending.replace(final)
            logger.info(
                "Backup {} completed with {} database tables and {} objects",
                backup_id,
                len(after),
                len(objects),
            )
            return manifest
        except Exception:
            shutil.rmtree(pending, ignore_errors=True)
            raise

    @staticmethod
    def verify_files(backup_set: Path) -> BackupManifest:
        manifest_path = backup_set / _MANIFEST
        checksum_path = backup_set / _MANIFEST_CHECKSUM
        if not manifest_path.is_file() or not checksum_path.is_file():
            raise BackupValidationError("Backup manifest or checksum is missing")
        expected_manifest_hash = checksum_path.read_text(encoding="ascii").strip()
        manifest_hash, _ = _sha256_file(manifest_path)
        if manifest_hash != expected_manifest_hash:
            raise BackupValidationError("Backup manifest checksum does not match")
        manifest = BackupManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        dump_path = _backup_file_path(backup_set, manifest.database_dump_file)
        dump_hash, dump_size = _sha256_file(dump_path)
        if (
            dump_hash != manifest.database_dump_sha256
            or dump_size != manifest.database_dump_size_bytes
        ):
            raise BackupValidationError("PostgreSQL dump checksum does not match")
        for item in manifest.objects:
            path = _object_path(backup_set / _OBJECTS, item.key)
            checksum, size = _sha256_file(path)
            if checksum != item.sha256 or size != item.size_bytes:
                raise BackupValidationError(f"Object backup does not match manifest: {item.key}")
        return manifest

    async def restore(self, backup_set: Path) -> BackupManifest:
        manifest = self.verify_files(backup_set)
        await self._require_clean_database()
        await asyncio.to_thread(self._require_empty_bucket)
        await asyncio.to_thread(
            self._restore_database,
            _backup_file_path(backup_set, manifest.database_dump_file),
        )
        await asyncio.to_thread(self._upload_objects, backup_set / _OBJECTS, manifest.objects)
        await self.verify_restored(manifest)
        logger.info("Restore {} completed and matched its inventory", manifest.backup_id)
        return manifest

    async def verify_restored(self, manifest: BackupManifest) -> None:
        current = await self.database_inventory()
        if current != manifest.database_tables:
            raise BackupValidationError("Restored database inventory does not match the backup")
        objects = await asyncio.to_thread(self._remote_inventory)
        if objects != manifest.objects:
            raise BackupValidationError("Restored object inventory does not match the backup")
        await self._validate_artifact_catalog(objects)

    async def database_inventory(self) -> tuple[DatabaseTableInventory, ...]:
        async with self._database.engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT table_schema, table_name FROM information_schema.tables "
                    "WHERE table_type = 'BASE TABLE' AND table_schema = ANY(:schemas) "
                    "ORDER BY table_schema, table_name"
                ),
                {"schemas": list(_SCHEMAS)},
            )
            tables = result.all()
            inventory: list[DatabaseTableInventory] = []
            preparer = connection.dialect.identifier_preparer
            for schema_name, table_name in tables:
                qualified = f"{preparer.quote_schema(schema_name)}.{preparer.quote(table_name)}"
                rows = await connection.stream(
                    text(
                        f"SELECT to_jsonb(row_data)::text FROM {qualified} AS row_data "
                        "ORDER BY to_jsonb(row_data)::text"
                    )
                )
                digest = hashlib.sha256()
                count = 0
                async for row in rows:
                    digest.update(row[0].encode("utf-8"))
                    digest.update(b"\n")
                    count += 1
                inventory.append(
                    DatabaseTableInventory(
                        schema_name=schema_name,
                        table_name=table_name,
                        row_count=count,
                        sha256=digest.hexdigest(),
                    )
                )
        return tuple(inventory)

    async def _alembic_revision(self) -> str | None:
        async with self._database.engine.connect() as connection:
            result = await connection.execute(text("SELECT version_num FROM alembic_version"))
        row = result.one_or_none()
        return str(row[0]) if row is not None else None

    async def _require_clean_database(self) -> None:
        inventory = await self.database_inventory()
        if inventory:
            raise BackupValidationError("Restore target database is not clean")

    def _require_empty_bucket(self) -> None:
        response = self._s3.list_objects_v2(Bucket=self._storage.bucket, MaxKeys=1)
        if response.get("KeyCount", 0):
            raise BackupValidationError("Restore target object bucket is not empty")

    def _dump_database(self, target: Path) -> None:
        command = [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-acl",
            "--file",
            str(target),
            _database_name(self._database_url),
        ]
        _run_postgres_command(command, self._database_url)

    def _restore_database(self, source: Path) -> None:
        command = [
            "pg_restore",
            "--exit-on-error",
            "--no-owner",
            "--no-acl",
            "--dbname",
            _database_name(self._database_url),
            str(source),
        ]
        _run_postgres_command(command, self._database_url)

    def _download_objects(self, root: Path) -> tuple[ObjectInventory, ...]:
        root.mkdir()
        inventory: list[ObjectInventory] = []
        for summary in self._list_objects():
            key = normalize_object_key(str(summary["Key"]))
            response = self._s3.get_object(Bucket=self._storage.bucket, Key=key)
            metadata = response.get("Metadata", {})
            expected = metadata.get("sha256")
            if not expected:
                response["Body"].close()
                raise BackupValidationError(f"Object is missing SHA-256 metadata: {key}")
            path = _object_path(root, key)
            path.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            try:
                with path.open("wb") as target:
                    while chunk := response["Body"].read(1024 * 1024):
                        target.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
            finally:
                response["Body"].close()
            if digest.hexdigest() != expected or size != int(response["ContentLength"]):
                raise BackupValidationError(f"Downloaded object failed verification: {key}")
            inventory.append(
                ObjectInventory(
                    key=key,
                    size_bytes=size,
                    content_type=response.get("ContentType", "application/octet-stream"),
                    sha256=expected,
                )
            )
        return tuple(sorted(inventory, key=lambda item: item.key))

    def _remote_inventory(self) -> tuple[ObjectInventory, ...]:
        inventory: list[ObjectInventory] = []
        for summary in self._list_objects():
            key = normalize_object_key(str(summary["Key"]))
            response = self._s3.head_object(Bucket=self._storage.bucket, Key=key)
            checksum = response.get("Metadata", {}).get("sha256")
            if not checksum:
                raise BackupValidationError(f"Object is missing SHA-256 metadata: {key}")
            inventory.append(
                ObjectInventory(
                    key=key,
                    size_bytes=int(response["ContentLength"]),
                    content_type=response.get("ContentType", "application/octet-stream"),
                    sha256=checksum,
                )
            )
        return tuple(sorted(inventory, key=lambda item: item.key))

    def _upload_objects(
        self,
        root: Path,
        objects: tuple[ObjectInventory, ...],
    ) -> None:
        for item in objects:
            path = _object_path(root, item.key)
            try:
                with path.open("rb") as source:
                    self._s3.put_object(
                        Bucket=self._storage.bucket,
                        Key=item.key,
                        Body=source,
                        ContentLength=item.size_bytes,
                        ContentType=item.content_type,
                        Metadata={"sha256": item.sha256},
                        IfNoneMatch="*",
                    )
            except ClientError as error:
                raise BackupValidationError(f"Could not restore object: {item.key}") from error

    def _list_objects(self) -> list[Mapping[str, object]]:
        objects: list[Mapping[str, object]] = []
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._storage.bucket):
            objects.extend(page.get("Contents", []))
        return objects

    async def _validate_artifact_catalog(
        self,
        objects: tuple[ObjectInventory, ...],
    ) -> None:
        by_key = {item.key: item for item in objects}
        async with self._database.engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT bucket, object_key, size_bytes, sha256 FROM platform.artifacts "
                    "WHERE status = 'available' ORDER BY object_key"
                )
            )
            rows = result.all()
        for bucket, key, size, checksum in rows:
            item = by_key.get(key)
            if (
                bucket != self._storage.bucket
                or item is None
                or item.size_bytes != size
                or item.sha256 != checksum
            ):
                raise BackupValidationError(
                    f"Artifact catalog does not match object storage: {key}"
                )


def _object_path(root: Path, key: str) -> Path:
    normalized = normalize_object_key(key)
    target = root.joinpath(*normalized.split("/"))
    resolved_root = root.resolve()
    resolved_target = target.resolve()
    if not resolved_target.is_relative_to(resolved_root):
        raise BackupValidationError("Object key escapes the backup directory")
    return target


def _backup_file_path(root: Path, relative: str) -> Path:
    normalized = normalize_object_key(relative)
    target = root.joinpath(*normalized.split("/"))
    if not target.resolve().is_relative_to(root.resolve()):
        raise BackupValidationError("Backup file escapes the backup directory")
    return target


def _database_name(database_url: str) -> str:
    database = make_url(database_url).database
    if not database:
        raise BackupValidationError("Database URL does not include a database name")
    return database


def _run_postgres_command(command: list[str], database_url: str) -> None:
    url = make_url(database_url)
    environment = os.environ.copy()
    if url.host:
        environment["PGHOST"] = url.host
    if url.port:
        environment["PGPORT"] = str(url.port)
    if url.username:
        environment["PGUSER"] = url.username
    if url.password:
        environment["PGPASSWORD"] = url.password
    result = subprocess.run(
        command,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        message = (
            result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "unknown error"
        )
        raise BackupValidationError(f"PostgreSQL maintenance command failed: {message}")


def _sha256_file(path: Path) -> tuple[str, int]:
    if not path.is_file():
        raise BackupValidationError(f"Backup file is missing: {path.name}")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _write_manifest(directory: Path, manifest: BackupManifest) -> None:
    path = directory / _MANIFEST
    payload = json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True)
    path.write_text(f"{payload}\n", encoding="utf-8")
    checksum, _ = _sha256_file(path)
    (directory / _MANIFEST_CHECKSUM).write_text(f"{checksum}\n", encoding="ascii")


__all__ = ["BackupService", "BackupValidationError"]
