"""SQLite persistence for reusable Media Lab asset metadata."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..domain.assets import MediaAsset
from .asset_serialization import asset_from_dict, asset_to_dict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS media_lab_assets (
    asset_id TEXT PRIMARY KEY,
    media_kind TEXT NOT NULL,
    state TEXT NOT NULL,
    origin TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL,
    source_run_id TEXT,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_media_lab_assets_checksum
    ON media_lab_assets(checksum_sha256);
CREATE INDEX IF NOT EXISTS ix_media_lab_assets_source_run
    ON media_lab_assets(source_run_id);
"""


class SqliteMediaAssetRepository:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    async def save(self, asset: MediaAsset) -> None:
        self._connection.execute(
            "INSERT INTO media_lab_assets "
            "(asset_id, media_kind, state, origin, checksum_sha256, source_run_id, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(asset_id) DO UPDATE SET "
            "state=excluded.state, origin=excluded.origin, source_run_id=excluded.source_run_id, "
            "payload=excluded.payload",
            (
                asset.asset_id,
                asset.media_kind.value,
                asset.state.value,
                asset.origin.value,
                asset.checksum_sha256,
                asset.source_run_id,
                json.dumps(asset_to_dict(asset), ensure_ascii=False),
            ),
        )
        self._connection.commit()

    async def get(self, asset_id: str) -> MediaAsset | None:
        row = self._connection.execute(
            "SELECT payload FROM media_lab_assets WHERE asset_id = ?", (asset_id,)
        ).fetchone()
        return asset_from_dict(json.loads(row["payload"])) if row else None


__all__ = ["SqliteMediaAssetRepository"]
