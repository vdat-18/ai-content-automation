"""Migrate legacy filesystem artifacts into configured object storage."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from ai_content.platform.artifacts import (
    ArtifactService,
    PostgresArtifactCatalog,
)
from ai_content.platform.artifacts.object_storage import sha256_file
from ai_content.platform.database import Database
from ai_content.settings import ApplicationSettings


@dataclass(frozen=True)
class MigrationReport:
    files: int
    bytes: int
    inventory_sha256: str


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def inventory(root: Path) -> tuple[tuple[Path, str, str, int], ...]:
    resolved = root.resolve()
    if not resolved.is_dir():
        raise ValueError("Artifact migration source must be an existing directory")
    items = []
    for source in sorted(path for path in resolved.rglob("*") if path.is_file()):
        checksum, size = sha256_file(source)
        items.append((source, source.relative_to(resolved).as_posix(), checksum, size))
    return tuple(items)


def summarize(items: tuple[tuple[Path, str, str, int], ...]) -> MigrationReport:
    digest = hashlib.sha256()
    for _source, relative, checksum, size in items:
        digest.update(f"{relative}\0{checksum}\0{size}\n".encode())
    return MigrationReport(len(items), sum(item[3] for item in items), digest.hexdigest())


async def migrate(
    source: Path,
    *,
    dry_run: bool,
    settings: ApplicationSettings | None = None,
) -> MigrationReport:
    items = inventory(source)
    report = summarize(items)
    if dry_run:
        return report
    runtime_settings = settings or ApplicationSettings()
    if runtime_settings.database_url is None:
        raise ValueError("AIC_AI_DATABASE_URL is required for artifact migration")
    database_url = runtime_settings.database_url.get_secret_value()
    storage_settings = runtime_settings.object_storage()
    if storage_settings.backend != "s3":
        raise ValueError("Artifact migration requires the S3 object storage backend")
    database = Database(database_url)
    service = ArtifactService(
        PostgresArtifactCatalog(database.engine),
        storage_settings.build(),
        storage_settings.bucket,
    )
    try:
        await service.publish_tree(
            source,
            owner_type="legacy_migration",
            owner_id=report.inventory_sha256,
        )
    finally:
        await database.close()
    return report


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    report = asyncio.run(migrate(args.source, dry_run=args.dry_run, settings=ApplicationSettings()))
    logger.info(
        "Artifact migration inventory files={} bytes={} sha256={}",
        report.files,
        report.bytes,
        report.inventory_sha256,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["MigrationReport", "inventory", "main", "migrate", "summarize"]
