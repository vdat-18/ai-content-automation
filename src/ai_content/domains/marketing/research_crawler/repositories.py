"""SQLite and PostgreSQL persistence for research crawl jobs and records."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import TypeAdapter
from sqlalchemy import String, and_, delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database.schema import (
    research_crawl_jobs,
    research_record_versions,
    research_records,
    research_reference_products,
    research_reference_uses,
    research_run_records,
)
from ai_content.platform.execution import EnqueueCommand
from ai_content.platform.execution.celery_scheduler import enqueue_celery_command

from .brand_context import brand_alias_keys
from .identity import research_record_content_hash, research_record_key
from .models import (
    ResearchClassification,
    ResearchCrawlJob,
    ResearchCrawlRecord,
    ResearchMediaAsset,
    ResearchRecordPage,
    ResearchRecordQuery,
    ResearchRecordUpsertSummary,
    ResearchRecordVersion,
    ResearchReviewStatus,
    ResearchScreening,
    StoredResearchRecord,
)

_JOB_ADAPTER = TypeAdapter(ResearchCrawlJob)
_RECORD_ADAPTER = TypeAdapter(StoredResearchRecord)
_VERSION_ADAPTER = TypeAdapter(ResearchRecordVersion)
_ACTIVE_STATUSES = ("queued", "pending", "running", "retry_wait")


class SqliteResearchCrawlRepository:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS research_crawl_jobs (
                job_id TEXT PRIMARY KEY,
                workspace_id TEXT,
                brand_id TEXT,
                project_id TEXT,
                source_url TEXT,
                crawl_fingerprint TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_research_crawl_jobs_created
                ON research_crawl_jobs(created_at DESC);
            CREATE TABLE IF NOT EXISTS research_records (
                record_key TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                brand_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                external_id TEXT NOT NULL,
                record_type TEXT NOT NULL,
                title TEXT,
                text TEXT NOT NULL,
                status TEXT,
                advertiser TEXT,
                destination_domain TEXT,
                screening_status TEXT NOT NULL DEFAULT 'kept',
                review_status TEXT NOT NULL DEFAULT 'pending_review',
                reviewer_alias TEXT,
                reviewed_at TEXT,
                review_reason TEXT,
                has_images INTEGER NOT NULL,
                has_videos INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                latest_run_id TEXT NOT NULL,
                version_count INTEGER NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                UNIQUE(workspace_id, brand_id, platform, external_id)
            );
            CREATE INDEX IF NOT EXISTS idx_research_records_scope_seen
                ON research_records(workspace_id, brand_id, last_seen_at DESC);
            CREATE TABLE IF NOT EXISTS research_record_versions (
                version_id TEXT PRIMARY KEY,
                record_key TEXT NOT NULL,
                job_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                UNIQUE(record_key, content_hash)
            );
            CREATE TABLE IF NOT EXISTS research_run_records (
                job_id TEXT NOT NULL,
                record_key TEXT NOT NULL,
                disposition TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                PRIMARY KEY(job_id, record_key)
            );
            CREATE TABLE IF NOT EXISTS research_reference_products (
                record_key TEXT NOT NULL,
                product_id TEXT NOT NULL,
                match_kind TEXT NOT NULL,
                confidence REAL NOT NULL,
                PRIMARY KEY(record_key, product_id)
            );
            CREATE INDEX IF NOT EXISTS idx_research_reference_products_product
                ON research_reference_products(product_id);
            CREATE TABLE IF NOT EXISTS research_reference_uses (
                record_key TEXT NOT NULL,
                media_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                used_at TEXT NOT NULL,
                PRIMARY KEY(record_key, media_id, batch_id)
            );
            """
        )
        self._ensure_job_columns()
        self._ensure_record_columns()
        self._connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_research_crawl_jobs_active_fingerprint
                ON research_crawl_jobs(crawl_fingerprint)
                WHERE crawl_fingerprint IS NOT NULL
                  AND status IN ('queued', 'pending', 'running', 'retry_wait')
            """
        )
        self._connection.commit()

    def _ensure_job_columns(self) -> None:
        columns = {
            str(row["name"])
            for row in self._connection.execute("PRAGMA table_info(research_crawl_jobs)")
        }
        for name in ("workspace_id", "brand_id", "project_id", "source_url", "crawl_fingerprint"):
            if name not in columns:
                self._connection.execute(f"ALTER TABLE research_crawl_jobs ADD COLUMN {name} TEXT")

    def _ensure_record_columns(self) -> None:
        columns = {
            str(row["name"])
            for row in self._connection.execute("PRAGMA table_info(research_records)")
        }
        definitions = {
            "screening_status": "TEXT NOT NULL DEFAULT 'kept'",
            "review_status": "TEXT NOT NULL DEFAULT 'pending_review'",
            "reviewer_alias": "TEXT",
            "reviewed_at": "TEXT",
            "review_reason": "TEXT",
            "deleted_at": "TEXT",
        }
        for name, definition in definitions.items():
            if name not in columns:
                self._connection.execute(
                    f"ALTER TABLE research_records ADD COLUMN {name} {definition}"
                )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_research_records_review_status "
            "ON research_records(review_status)"
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_research_records_screening_status "
            "ON research_records(screening_status)"
        )

    async def create(self, job: ResearchCrawlJob) -> ResearchCrawlJob:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO research_crawl_jobs(
                    job_id, workspace_id, brand_id, project_id, source_url,
                    crawl_fingerprint, status, created_at, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    job.workspace_id,
                    job.brand_id,
                    job.project_id,
                    job.source_url,
                    job.crawl_fingerprint,
                    job.status,
                    job.created_at.isoformat(),
                    _dump(job),
                ),
            )
        return job

    async def create_with_command(
        self, _job: ResearchCrawlJob, _command: EnqueueCommand
    ) -> ResearchCrawlJob:
        raise ValueError("Atomic Celery scheduling requires PostgreSQL")

    async def save(self, job: ResearchCrawlJob) -> None:
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE research_crawl_jobs
                SET status = ?, crawl_fingerprint = ?, payload = ?
                WHERE job_id = ?
                """,
                (job.status, job.crawl_fingerprint, _dump(job), job.job_id),
            )
        if cursor.rowcount != 1:
            raise ValueError("Research crawl job does not exist")

    async def get(self, job_id: str) -> ResearchCrawlJob | None:
        row = self._connection.execute(
            "SELECT payload FROM research_crawl_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return _JOB_ADAPTER.validate_json(row["payload"]) if row is not None else None

    async def list(self, *, limit: int = 100) -> list[ResearchCrawlJob]:
        rows = self._connection.execute(
            "SELECT payload FROM research_crawl_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_JOB_ADAPTER.validate_json(row["payload"]) for row in rows]

    async def find_active_by_fingerprint(self, fingerprint: str) -> ResearchCrawlJob | None:
        row = self._connection.execute(
            """
            SELECT payload FROM research_crawl_jobs
            WHERE crawl_fingerprint = ? AND status IN ('queued', 'pending', 'running', 'retry_wait')
            ORDER BY created_at DESC LIMIT 1
            """,
            (fingerprint,),
        ).fetchone()
        return _JOB_ADAPTER.validate_json(row["payload"]) if row is not None else None

    async def upsert_records(
        self,
        job: ResearchCrawlJob,
        classifications: dict[str, ResearchClassification] | None = None,
        screenings: dict[str, ResearchScreening] | None = None,
        *,
        records: list[ResearchCrawlRecord] | None = None,
    ) -> ResearchRecordUpsertSummary:
        if job.result is None:
            return ResearchRecordUpsertSummary()
        records_to_store = records if records is not None else job.result.records
        counters = {"created": 0, "updated": 0, "unchanged": 0}
        observed_at = job.updated_at
        with self._connection:
            for record in records_to_store:
                key = research_record_key(
                    workspace_id=job.workspace_id,
                    brand_id=job.brand_id,
                    platform=job.result.platform,
                    external_id=record.record_id,
                )
                content_hash = research_record_content_hash(record)
                existing = self._connection.execute(
                    "SELECT payload, content_hash, version_count FROM research_records WHERE record_key = ?",
                    (key,),
                ).fetchone()
                disposition = (
                    "new"
                    if existing is None
                    else ("unchanged" if existing["content_hash"] == content_hash else "updated")
                )
                counters[{"new": "created"}.get(disposition, disposition)] += 1
                first_seen = (
                    observed_at
                    if existing is None
                    else _RECORD_ADAPTER.validate_json(existing["payload"]).first_seen_at
                )
                version_count = 1 if existing is None else int(existing["version_count"])
                if disposition == "updated":
                    version_count += 1
                stored = _stored_record(
                    job,
                    record,
                    key,
                    content_hash,
                    first_seen,
                    observed_at,
                    version_count,
                    _RECORD_ADAPTER.validate_json(existing["payload"])
                    if existing is not None
                    else None,
                    (classifications or {}).get(record.record_id),
                    (screenings or {}).get(record.record_id),
                )
                self._connection.execute(
                    """
                    INSERT INTO research_records(
                        record_key, workspace_id, brand_id, platform, external_id,
                        record_type, title, text, status, advertiser, destination_domain,
                        screening_status, review_status, reviewer_alias, reviewed_at, review_reason,
                        has_images, has_videos, content_hash, latest_run_id, version_count,
                        first_seen_at, last_seen_at, payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(record_key) DO UPDATE SET
                        record_type=excluded.record_type, title=excluded.title, text=excluded.text,
                        status=excluded.status, advertiser=excluded.advertiser,
                        destination_domain=excluded.destination_domain,
                        screening_status=excluded.screening_status,
                        review_status=excluded.review_status, reviewer_alias=excluded.reviewer_alias,
                        reviewed_at=excluded.reviewed_at, review_reason=excluded.review_reason,
                        has_images=excluded.has_images, has_videos=excluded.has_videos,
                        content_hash=excluded.content_hash, latest_run_id=excluded.latest_run_id,
                        version_count=excluded.version_count, last_seen_at=excluded.last_seen_at,
                        payload=excluded.payload
                    """,
                    _stored_values(stored),
                )
                if disposition != "unchanged":
                    version = _version(stored, job.job_id, record, observed_at)
                    self._connection.execute(
                        """
                        INSERT OR IGNORE INTO research_record_versions(
                            version_id, record_key, job_id, content_hash, observed_at, payload
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            version.version_id,
                            version.record_key,
                            version.job_id,
                            version.content_hash,
                            version.observed_at.isoformat(),
                            _VERSION_ADAPTER.dump_json(version).decode(),
                        ),
                    )
                self._connection.execute(
                    """
                    INSERT INTO research_run_records(job_id, record_key, disposition, observed_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(job_id, record_key) DO UPDATE SET
                        disposition=excluded.disposition, observed_at=excluded.observed_at
                    """,
                    (job.job_id, key, disposition, observed_at.isoformat()),
                )
        return ResearchRecordUpsertSummary(
            saved=sum(counters.values()),
            created=counters["created"],
            updated=counters["updated"],
            unchanged=counters["unchanged"],
        )

    async def backfill_records(self) -> int:
        existing = int(
            self._connection.execute("SELECT count(*) FROM research_records").fetchone()[0]
        )
        if existing:
            return 0
        rows = self._connection.execute(
            "SELECT payload FROM research_crawl_jobs WHERE status = 'completed' ORDER BY created_at"
        ).fetchall()
        saved = 0
        for row in rows:
            job = _JOB_ADAPTER.validate_json(row["payload"])
            saved += (await self.upsert_records(job)).saved
        return saved

    async def search_records(self, query: ResearchRecordQuery) -> ResearchRecordPage:
        clauses: list[str] = ["r.deleted_at IS NULL"]
        parameters: list[object] = []
        for column, value in (
            ("workspace_id", query.workspace_id),
            ("platform", query.platform),
            ("status", query.status),
        ):
            if value:
                clauses.append(f"r.{column} = ?")
                parameters.append(value)
        if query.brand_id:
            aliases = sorted(brand_alias_keys(query.brand_id))
            placeholders = ", ".join("?" for _alias in aliases)
            clauses.append(
                "lower(replace(replace(replace(replace(r.brand_id, '-', ''), '_', ''), "
                f"' ', ''), ':', '')) IN ({placeholders})"
            )
            parameters.extend(aliases)
        if query.review_status:
            clauses.append("r.review_status = ?")
            parameters.append(query.review_status)
        if query.screening_status in {"auto_filtered", "unavailable"}:
            clauses.append("r.screening_status = ?")
            parameters.append(query.screening_status)
        elif query.screening_status == "visible":
            clauses.append("r.screening_status = ?")
            parameters.append("kept")
        if query.project_id:
            clauses.append(
                """EXISTS (
                    SELECT 1 FROM research_run_records rr
                    JOIN research_crawl_jobs j ON j.job_id = rr.job_id
                    WHERE rr.record_key = r.record_key AND j.project_id = ?
                )"""
            )
            parameters.append(query.project_id)
        if query.media_type == "image":
            clauses.append("r.has_images = 1 AND r.has_videos = 0")
        elif query.media_type == "video":
            clauses.append("r.has_videos = 1 AND r.has_images = 0")
        elif query.media_type == "mixed":
            clauses.append("r.has_images = 1 AND r.has_videos = 1")
        elif query.media_type == "none":
            clauses.append("r.has_images = 0 AND r.has_videos = 0")
        if query.media_status != "all":
            clauses.append("r.payload LIKE ?")
            parameters.append(
                {
                    "available": '%"status":"available"%',
                    "failed": '%"status":"failed"%',
                    "source_only": '%"media_assets":[]%',
                }[query.media_status]
            )
        if query.category:
            clauses.append("r.payload LIKE ?")
            parameters.append(f'%"product_category":"{query.category}"%')
        if query.product_id:
            clauses.append(
                "EXISTS (SELECT 1 FROM research_reference_products p "
                "WHERE p.record_key = r.record_key AND p.product_id = ?)"
            )
            parameters.append(query.product_id)
        if query.query:
            clauses.append("(lower(r.title) LIKE ? OR lower(r.text) LIKE ?)")
            value = f"%{query.query.lower()}%"
            parameters.extend((value, value))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total = int(
            self._connection.execute(
                f"SELECT count(*) FROM research_records r {where}", parameters
            ).fetchone()[0]
        )
        order = {
            "last_seen_desc": "r.last_seen_at DESC, r.record_key",
            "first_seen_desc": "r.first_seen_at DESC, r.record_key",
            "title_asc": "r.title COLLATE NOCASE, r.record_key",
        }[query.sort]
        rows = self._connection.execute(
            f"SELECT r.payload FROM research_records r {where} ORDER BY {order} LIMIT ? OFFSET ?",
            (*parameters, query.page_size, (query.page - 1) * query.page_size),
        ).fetchall()
        return ResearchRecordPage(
            items=[_RECORD_ADAPTER.validate_json(row["payload"]) for row in rows],
            total=total,
            page=query.page,
            page_size=query.page_size,
        )

    async def get_record(self, record_key: str) -> StoredResearchRecord | None:
        row = self._connection.execute(
            "SELECT payload FROM research_records WHERE record_key = ? AND deleted_at IS NULL",
            (record_key,),
        ).fetchone()
        return _RECORD_ADAPTER.validate_json(row["payload"]) if row is not None else None

    async def save_record_enrichment(
        self,
        record_key: str,
        *,
        media_assets: list[ResearchMediaAsset] | None = None,
        classification: ResearchClassification | None = None,
        screening: ResearchScreening | None = None,
    ) -> StoredResearchRecord:
        stored = await self.get_record(record_key)
        if stored is None:
            raise ValueError("Research record does not exist")
        updates: dict[str, object] = {}
        if media_assets is not None:
            updates["media_assets"] = media_assets
            updates["media_content_hash"] = _media_content_hash(media_assets)
        if classification is not None:
            updates["classification"] = classification
        if screening is not None:
            updates["screening"] = screening
            updates["screening_status"] = _screening_status(screening)
        enriched = stored.model_copy(update=updates)
        with self._connection:
            self._connection.execute(
                "UPDATE research_records SET screening_status = ?, payload = ? WHERE record_key = ?",
                (
                    enriched.screening_status,
                    _RECORD_ADAPTER.dump_json(enriched).decode(),
                    record_key,
                ),
            )
            if screening is not None:
                self._connection.execute(
                    "DELETE FROM research_reference_products WHERE record_key = ?", (record_key,)
                )
                self._connection.executemany(
                    "INSERT INTO research_reference_products VALUES (?, ?, ?, ?)",
                    [
                        (record_key, product_id, kind, confidence)
                        for product_id, kind, confidence in _product_links(screening)
                    ],
                )
        return enriched

    async def record_reference_uses(self, reference_ids: tuple[str, ...], batch_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connection:
            self._connection.executemany(
                "INSERT OR IGNORE INTO research_reference_uses VALUES (?, ?, ?, ?)",
                [(*_split_reference(item), batch_id, now) for item in reference_ids],
            )

    async def reference_use_counts(self, record_keys: tuple[str, ...]) -> dict[str, int]:
        if not record_keys:
            return {}
        marks = ", ".join("?" for _key in record_keys)
        rows = self._connection.execute(
            "SELECT record_key, count(*) AS uses FROM research_reference_uses "
            f"WHERE record_key IN ({marks}) GROUP BY record_key",
            record_keys,
        ).fetchall()
        return {row["record_key"]: int(row["uses"]) for row in rows}

    async def review_records(
        self,
        record_keys: tuple[str, ...],
        *,
        review_status: ResearchReviewStatus,
        reviewer_alias: str | None,
        review_reason: str | None,
    ) -> list[StoredResearchRecord]:
        keys = tuple(dict.fromkeys(record_keys))
        if not keys:
            raise ValueError("At least one research record is required")
        placeholders = ", ".join("?" for _ in keys)
        with self._connection:
            rows = self._connection.execute(
                f"SELECT record_key, payload FROM research_records "
                f"WHERE record_key IN ({placeholders}) AND deleted_at IS NULL",
                keys,
            ).fetchall()
            by_key = {str(row["record_key"]): row for row in rows}
            if len(by_key) != len(keys):
                raise ValueError("One or more research records do not exist")
            reviewed_at = datetime.now(UTC) if review_status != "pending_review" else None
            reviews: dict[str, StoredResearchRecord] = {}
            for key in keys:
                stored = _RECORD_ADAPTER.validate_json(by_key[key]["payload"])
                _require_reviewable(stored)
                reviewed = stored.model_copy(
                    update={
                        "review_status": review_status,
                        "reviewer_alias": reviewer_alias if reviewed_at is not None else None,
                        "reviewed_at": reviewed_at,
                        "review_reason": review_reason if reviewed_at is not None else None,
                    }
                )
                self._connection.execute(
                    "UPDATE research_records SET review_status = ?, reviewer_alias = ?, reviewed_at = ?, "
                    "review_reason = ?, payload = ? WHERE record_key = ?",
                    (
                        reviewed.review_status,
                        reviewed.reviewer_alias,
                        reviewed.reviewed_at.isoformat() if reviewed.reviewed_at else None,
                        reviewed.review_reason,
                        _RECORD_ADAPTER.dump_json(reviewed).decode(),
                        key,
                    ),
                )
                reviews[key] = reviewed
        return [reviews[key] for key in keys]

    async def delete_records(self, record_keys: tuple[str, ...]) -> int:
        keys = tuple(dict.fromkeys(record_keys))
        if not keys:
            raise ValueError("At least one research record is required")
        placeholders = ", ".join("?" for _ in keys)
        with self._connection:
            rows = self._connection.execute(
                f"SELECT record_key FROM research_records "
                f"WHERE record_key IN ({placeholders}) AND deleted_at IS NULL",
                keys,
            ).fetchall()
            existing = {str(row["record_key"]) for row in rows}
            if len(existing) != len(keys):
                raise ValueError("One or more research records do not exist")
            for key in keys:
                if self._sqlite_creative_uses_record(key):
                    raise ValueError(
                        "Research reference is already used by Creative and cannot be deleted"
                    )
            deleted_at = datetime.now(UTC).isoformat()
            cursor = self._connection.execute(
                f"UPDATE research_records SET deleted_at = ? "
                f"WHERE record_key IN ({placeholders}) AND deleted_at IS NULL",
                (deleted_at, *keys),
            )
        return cursor.rowcount

    def _sqlite_creative_uses_record(self, record_key: str) -> bool:
        tables = {
            str(row["name"])
            for row in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        for table in ("creative_automation_jobs", "creative_automation_states"):
            if table not in tables:
                continue
            row = self._connection.execute(
                f"SELECT 1 FROM {table} WHERE instr(payload, ?) > 0 LIMIT 1",
                (record_key,),
            ).fetchone()
            if row is not None:
                return True
        return False

    async def list_record_versions(self, record_key: str) -> list[ResearchRecordVersion]:
        rows = self._connection.execute(
            """
            SELECT payload FROM research_record_versions
            WHERE record_key = ? ORDER BY observed_at DESC
            """,
            (record_key,),
        ).fetchall()
        return [_VERSION_ADAPTER.validate_json(row["payload"]) for row in rows]

    def close(self) -> None:
        self._connection.close()


class PostgresResearchCrawlRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(self, job: ResearchCrawlJob) -> ResearchCrawlJob:
        async with self._engine.begin() as connection:
            await connection.execute(insert(research_crawl_jobs).values(**_job_values(job)))
        return job

    async def create_with_command(
        self, job: ResearchCrawlJob, command: EnqueueCommand
    ) -> ResearchCrawlJob:
        async with self._engine.begin() as connection:
            queued_command, _ = await enqueue_celery_command(connection, command, job.created_at)
            queued = job.model_copy(
                update={
                    "command_id": queued_command.command_id,
                    "status": queued_command.status.value,
                    "updated_at": queued_command.updated_at,
                }
            )
            await connection.execute(insert(research_crawl_jobs).values(**_job_values(queued)))
        return queued

    async def save(self, job: ResearchCrawlJob) -> None:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(research_crawl_jobs)
                .where(research_crawl_jobs.c.job_id == job.job_id)
                .values(
                    status=job.status,
                    command_id=job.command_id,
                    crawl_fingerprint=job.crawl_fingerprint,
                    payload=_JOB_ADAPTER.dump_python(job, mode="json"),
                    updated_at=job.updated_at,
                )
            )
        if result.rowcount != 1:
            raise ValueError("Research crawl job does not exist")

    async def get(self, job_id: str) -> ResearchCrawlJob | None:
        async with self._engine.connect() as connection:
            payload = (
                await connection.execute(
                    select(research_crawl_jobs.c.payload).where(
                        research_crawl_jobs.c.job_id == job_id
                    )
                )
            ).scalar_one_or_none()
        return _JOB_ADAPTER.validate_python(payload) if payload is not None else None

    async def list(self, *, limit: int = 100) -> list[ResearchCrawlJob]:
        async with self._engine.connect() as connection:
            payloads = (
                (
                    await connection.execute(
                        select(research_crawl_jobs.c.payload)
                        .order_by(research_crawl_jobs.c.created_at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [_JOB_ADAPTER.validate_python(payload) for payload in payloads]

    async def find_active_by_fingerprint(self, fingerprint: str) -> ResearchCrawlJob | None:
        async with self._engine.connect() as connection:
            payload = (
                await connection.execute(
                    select(research_crawl_jobs.c.payload)
                    .where(
                        research_crawl_jobs.c.crawl_fingerprint == fingerprint,
                        research_crawl_jobs.c.status.in_(_ACTIVE_STATUSES),
                    )
                    .order_by(research_crawl_jobs.c.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        return _JOB_ADAPTER.validate_python(payload) if payload is not None else None

    async def upsert_records(
        self,
        job: ResearchCrawlJob,
        classifications: dict[str, ResearchClassification] | None = None,
        screenings: dict[str, ResearchScreening] | None = None,
        *,
        records: list[ResearchCrawlRecord] | None = None,
    ) -> ResearchRecordUpsertSummary:
        if job.result is None:
            return ResearchRecordUpsertSummary()
        records_to_store = records if records is not None else job.result.records
        counters = {"created": 0, "updated": 0, "unchanged": 0}
        observed_at = job.updated_at
        async with self._engine.begin() as connection:
            for record in records_to_store:
                key = research_record_key(
                    workspace_id=job.workspace_id,
                    brand_id=job.brand_id,
                    platform=job.result.platform,
                    external_id=record.record_id,
                )
                content_hash = research_record_content_hash(record)
                existing_payload = (
                    await connection.execute(
                        select(research_records.c.payload)
                        .where(research_records.c.record_key == key)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                existing = (
                    _RECORD_ADAPTER.validate_python(existing_payload)
                    if existing_payload is not None
                    else None
                )
                disposition = (
                    "new"
                    if existing is None
                    else ("unchanged" if existing.content_hash == content_hash else "updated")
                )
                counters[{"new": "created"}.get(disposition, disposition)] += 1
                version_count = 1 if existing is None else existing.version_count
                if disposition == "updated":
                    version_count += 1
                stored = _stored_record(
                    job,
                    record,
                    key,
                    content_hash,
                    observed_at if existing is None else existing.first_seen_at,
                    observed_at,
                    version_count,
                    existing,
                    (classifications or {}).get(record.record_id),
                    (screenings or {}).get(record.record_id),
                )
                values = _postgres_record_values(stored)
                await connection.execute(
                    insert(research_records)
                    .values(**values)
                    .on_conflict_do_update(
                        index_elements=[research_records.c.record_key],
                        set_={key: value for key, value in values.items() if key != "record_key"},
                    )
                )
                if disposition != "unchanged":
                    version = _version(stored, job.job_id, record, observed_at)
                    await connection.execute(
                        insert(research_record_versions)
                        .values(
                            version_id=version.version_id,
                            record_key=version.record_key,
                            job_id=version.job_id,
                            content_hash=version.content_hash,
                            payload=_VERSION_ADAPTER.dump_python(version, mode="json"),
                            observed_at=version.observed_at,
                        )
                        .on_conflict_do_nothing()
                    )
                await connection.execute(
                    insert(research_run_records)
                    .values(
                        job_id=job.job_id,
                        record_key=key,
                        disposition=disposition,
                        observed_at=observed_at,
                    )
                    .on_conflict_do_update(
                        index_elements=[
                            research_run_records.c.job_id,
                            research_run_records.c.record_key,
                        ],
                        set_={"disposition": disposition, "observed_at": observed_at},
                    )
                )
        return ResearchRecordUpsertSummary(
            saved=sum(counters.values()),
            created=counters["created"],
            updated=counters["updated"],
            unchanged=counters["unchanged"],
        )

    async def backfill_records(self) -> int:
        async with self._engine.connect() as connection:
            existing = int(
                (
                    await connection.execute(select(func.count()).select_from(research_records))
                ).scalar_one()
            )
            if existing:
                return 0
            payloads = (
                (
                    await connection.execute(
                        select(research_crawl_jobs.c.payload)
                        .where(research_crawl_jobs.c.status == "completed")
                        .order_by(research_crawl_jobs.c.created_at)
                    )
                )
                .scalars()
                .all()
            )
        saved = 0
        for payload in payloads:
            saved += (await self.upsert_records(_JOB_ADAPTER.validate_python(payload))).saved
        return saved

    async def search_records(self, query: ResearchRecordQuery) -> ResearchRecordPage:
        conditions = [research_records.c.deleted_at.is_(None)]
        for column, value in (
            (research_records.c.workspace_id, query.workspace_id),
            (research_records.c.platform, query.platform),
            (research_records.c.status, query.status),
        ):
            if value:
                conditions.append(column == value)
        if query.brand_id:
            normalized_brand = func.regexp_replace(
                func.lower(research_records.c.brand_id),
                "[^a-z0-9]+",
                "",
                "g",
            )
            conditions.append(normalized_brand.in_(sorted(brand_alias_keys(query.brand_id))))
        if query.review_status:
            conditions.append(research_records.c.review_status == query.review_status)

        if query.screening_status in {"auto_filtered", "unavailable"}:
            conditions.append(research_records.c.screening_status == query.screening_status)
        elif query.screening_status == "visible":
            conditions.append(research_records.c.screening_status == "kept")
        if query.project_id:
            conditions.append(
                exists(
                    select(research_run_records.c.job_id)
                    .select_from(
                        research_run_records.join(
                            research_crawl_jobs,
                            research_crawl_jobs.c.job_id == research_run_records.c.job_id,
                        )
                    )
                    .where(
                        research_run_records.c.record_key == research_records.c.record_key,
                        research_crawl_jobs.c.project_id == query.project_id,
                    )
                )
            )
        if query.media_type == "image":
            conditions.extend(
                (research_records.c.has_images.is_(True), research_records.c.has_videos.is_(False))
            )
        elif query.media_type == "video":
            conditions.extend(
                (research_records.c.has_videos.is_(True), research_records.c.has_images.is_(False))
            )
        elif query.media_type == "mixed":
            conditions.extend(
                (research_records.c.has_images.is_(True), research_records.c.has_videos.is_(True))
            )
        elif query.media_type == "none":
            conditions.extend(
                (research_records.c.has_images.is_(False), research_records.c.has_videos.is_(False))
            )
        if query.media_status != "all":
            conditions.append(
                research_records.c.payload.cast(String).ilike(
                    {
                        "available": '%"status": "available"%',
                        "failed": '%"status": "failed"%',
                        "source_only": '%"media_assets": []%',
                    }[query.media_status]
                )
            )
        if query.category:
            conditions.append(
                research_records.c.payload.cast(String).ilike(
                    f'%"product_category": "{query.category}"%'
                )
            )
        if query.product_id:
            conditions.append(
                exists(
                    select(research_reference_products.c.record_key).where(
                        research_reference_products.c.record_key == research_records.c.record_key,
                        research_reference_products.c.product_id == query.product_id,
                    )
                )
            )
        if query.query:
            value = f"%{query.query}%"
            conditions.append(
                or_(research_records.c.title.ilike(value), research_records.c.text.ilike(value))
            )
        condition = and_(*conditions) if conditions else None
        base = select(research_records.c.payload)
        count = select(func.count()).select_from(research_records)
        if condition is not None:
            base = base.where(condition)
            count = count.where(condition)
        order = {
            "last_seen_desc": (
                research_records.c.last_seen_at.desc(),
                research_records.c.record_key,
            ),
            "first_seen_desc": (
                research_records.c.first_seen_at.desc(),
                research_records.c.record_key,
            ),
            "title_asc": (
                research_records.c.title.asc().nullslast(),
                research_records.c.record_key,
            ),
        }[query.sort]
        base = (
            base.order_by(*order).limit(query.page_size).offset((query.page - 1) * query.page_size)
        )
        async with self._engine.connect() as connection:
            total = int((await connection.execute(count)).scalar_one())
            payloads = (await connection.execute(base)).scalars().all()
        return ResearchRecordPage(
            items=[_RECORD_ADAPTER.validate_python(payload) for payload in payloads],
            total=total,
            page=query.page,
            page_size=query.page_size,
        )

    async def get_record(self, record_key: str) -> StoredResearchRecord | None:
        async with self._engine.connect() as connection:
            payload = (
                await connection.execute(
                    select(research_records.c.payload).where(
                        research_records.c.record_key == record_key,
                        research_records.c.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
        return _RECORD_ADAPTER.validate_python(payload) if payload is not None else None

    async def save_record_enrichment(
        self,
        record_key: str,
        *,
        media_assets: list[ResearchMediaAsset] | None = None,
        classification: ResearchClassification | None = None,
        screening: ResearchScreening | None = None,
    ) -> StoredResearchRecord:
        stored = await self.get_record(record_key)
        if stored is None:
            raise ValueError("Research record does not exist")
        updates: dict[str, object] = {}
        if media_assets is not None:
            updates["media_assets"] = media_assets
            updates["media_content_hash"] = _media_content_hash(media_assets)
        if classification is not None:
            updates["classification"] = classification
        if screening is not None:
            updates["screening"] = screening
            updates["screening_status"] = _screening_status(screening)
        enriched = stored.model_copy(update=updates)
        async with self._engine.begin() as connection:
            await connection.execute(
                update(research_records)
                .where(research_records.c.record_key == record_key)
                .values(
                    screening_status=enriched.screening_status,
                    payload=_RECORD_ADAPTER.dump_python(enriched, mode="json"),
                )
            )
            if screening is not None:
                await connection.execute(
                    delete(research_reference_products).where(
                        research_reference_products.c.record_key == record_key
                    )
                )
                links = [
                    {
                        "record_key": record_key,
                        "product_id": product_id,
                        "match_kind": kind,
                        "confidence": confidence,
                    }
                    for product_id, kind, confidence in _product_links(screening)
                ]
                if links:
                    await connection.execute(insert(research_reference_products), links)
        return enriched

    async def record_reference_uses(self, reference_ids: tuple[str, ...], batch_id: str) -> None:
        rows = [
            {
                "record_key": record_key,
                "media_id": media_id,
                "batch_id": batch_id,
                "used_at": datetime.now(UTC),
            }
            for record_key, media_id in map(_split_reference, reference_ids)
        ]
        if not rows:
            return
        async with self._engine.begin() as connection:
            await connection.execute(insert(research_reference_uses).on_conflict_do_nothing(), rows)

    async def reference_use_counts(self, record_keys: tuple[str, ...]) -> dict[str, int]:
        if not record_keys:
            return {}
        async with self._engine.connect() as connection:
            rows = await connection.execute(
                select(research_reference_uses.c.record_key, func.count())
                .where(research_reference_uses.c.record_key.in_(record_keys))
                .group_by(research_reference_uses.c.record_key)
            )
            return {key: int(count) for key, count in rows}

    async def review_records(
        self,
        record_keys: tuple[str, ...],
        *,
        review_status: ResearchReviewStatus,
        reviewer_alias: str | None,
        review_reason: str | None,
    ) -> list[StoredResearchRecord]:
        keys = tuple(dict.fromkeys(record_keys))
        if not keys:
            raise ValueError("At least one research record is required")
        async with self._engine.begin() as connection:
            rows = (
                await connection.execute(
                    select(research_records.c.record_key, research_records.c.payload)
                    .where(
                        research_records.c.record_key.in_(keys),
                        research_records.c.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
            ).all()
            payloads = {str(row.record_key): row.payload for row in rows}
            if len(payloads) != len(keys):
                raise ValueError("One or more research records do not exist")
            reviewed_at = datetime.now(UTC) if review_status != "pending_review" else None
            reviews: dict[str, StoredResearchRecord] = {}
            for key in keys:
                stored = _RECORD_ADAPTER.validate_python(payloads[key])
                _require_reviewable(stored)
                reviewed = stored.model_copy(
                    update={
                        "review_status": review_status,
                        "reviewer_alias": reviewer_alias if reviewed_at is not None else None,
                        "reviewed_at": reviewed_at,
                        "review_reason": review_reason if reviewed_at is not None else None,
                    }
                )
                await connection.execute(
                    update(research_records)
                    .where(research_records.c.record_key == key)
                    .values(
                        review_status=reviewed.review_status,
                        reviewer_alias=reviewed.reviewer_alias,
                        reviewed_at=reviewed.reviewed_at,
                        review_reason=reviewed.review_reason,
                        payload=_RECORD_ADAPTER.dump_python(reviewed, mode="json"),
                    )
                )
                reviews[key] = reviewed
        return [reviews[key] for key in keys]

    async def delete_records(self, record_keys: tuple[str, ...]) -> int:
        from ai_content.platform.database.schema import (
            creative_automation_jobs,
            creative_automation_states,
            marketing_creative_automation_states,
        )

        keys = tuple(dict.fromkeys(record_keys))
        if not keys:
            raise ValueError("At least one research record is required")
        async with self._engine.begin() as connection:
            rows = (
                (
                    await connection.execute(
                        select(research_records.c.record_key)
                        .where(
                            research_records.c.record_key.in_(keys),
                            research_records.c.deleted_at.is_(None),
                        )
                        .with_for_update()
                    )
                )
                .scalars()
                .all()
            )
            if len(set(rows)) != len(keys):
                raise ValueError("One or more research records do not exist")
            for key in keys:
                for table in (
                    creative_automation_jobs,
                    creative_automation_states,
                    marketing_creative_automation_states,
                ):
                    used = (
                        await connection.execute(
                            select(table.c.payload)
                            .where(func.strpos(table.c.payload.cast(String), key) > 0)
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    if used is not None:
                        raise ValueError(
                            "Research reference is already used by Creative and cannot be deleted"
                        )
            result = await connection.execute(
                update(research_records)
                .where(
                    research_records.c.record_key.in_(keys),
                    research_records.c.deleted_at.is_(None),
                )
                .values(deleted_at=datetime.now(UTC))
            )
        return result.rowcount

    async def list_record_versions(self, record_key: str) -> list[ResearchRecordVersion]:
        async with self._engine.connect() as connection:
            payloads = (
                (
                    await connection.execute(
                        select(research_record_versions.c.payload)
                        .where(research_record_versions.c.record_key == record_key)
                        .order_by(research_record_versions.c.observed_at.desc())
                    )
                )
                .scalars()
                .all()
            )
        return [_VERSION_ADAPTER.validate_python(payload) for payload in payloads]

    def close(self) -> None:
        """The composition root owns the shared database engine."""


def _job_values(job: ResearchCrawlJob) -> dict[str, object]:
    return {
        "job_id": job.job_id,
        "workspace_id": job.workspace_id,
        "brand_id": job.brand_id,
        "project_id": job.project_id,
        "source_url": job.source_url,
        "crawl_fingerprint": job.crawl_fingerprint,
        "status": job.status,
        "command_id": job.command_id,
        "payload": _JOB_ADAPTER.dump_python(job, mode="json"),
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _stored_record(
    job: ResearchCrawlJob,
    record: ResearchCrawlRecord,
    key: str,
    content_hash: str,
    first_seen_at: datetime,
    last_seen_at: datetime,
    version_count: int,
    existing: StoredResearchRecord | None = None,
    classification: ResearchClassification | None = None,
    screening: ResearchScreening | None = None,
) -> StoredResearchRecord:
    if job.result is None:
        raise ValueError("Completed crawl result is required")
    destination = next(
        (
            urlsplit(link["url"]).hostname
            for link in record.links
            if urlsplit(link["url"]).hostname
            and not (urlsplit(link["url"]).hostname or "").endswith("facebook.com")
        ),
        None,
    )
    status = record.metadata.get("status")
    screening_status, stored_screening = _screening_fields(
        existing,
        content_hash,
        screening,
    )
    return StoredResearchRecord(
        record_key=key,
        workspace_id=job.workspace_id,
        brand_id=job.brand_id,
        platform=job.result.platform,
        external_id=record.record_id,
        record_type=record.record_type,
        title=record.title,
        text=record.text,
        source_url=record.source_url,
        status=str(status) if status else None,
        advertiser=record.title,
        destination_domain=destination,
        metadata=record.metadata,
        links=record.links,
        image_urls=record.image_urls,
        video_urls=record.video_urls,
        media_assets=(
            existing.media_assets
            if existing is not None and existing.content_hash == content_hash
            else []
        ),
        classification=(
            classification
            if classification is not None
            else (
                existing.classification
                if existing is not None and existing.content_hash == content_hash
                else None
            )
        ),
        screening_status=screening_status,
        screening=stored_screening,
        review_status=(
            existing.review_status
            if existing is not None
            and existing.content_hash == content_hash
            and screening_status == "kept"
            else "pending_review"
        ),
        media_content_hash=(
            existing.media_content_hash
            if existing is not None and existing.content_hash == content_hash
            else ""
        ),
        reviewer_alias=(
            existing.reviewer_alias
            if existing is not None
            and existing.content_hash == content_hash
            and screening_status == "kept"
            else None
        ),
        reviewed_at=(
            existing.reviewed_at
            if existing is not None
            and existing.content_hash == content_hash
            and screening_status == "kept"
            else None
        ),
        review_reason=(
            existing.review_reason
            if existing is not None
            and existing.content_hash == content_hash
            and screening_status == "kept"
            else None
        ),
        content_hash=content_hash,
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
        latest_run_id=job.job_id,
        version_count=version_count,
    )


def _screening_fields(
    existing: StoredResearchRecord | None,
    content_hash: str,
    screening: ResearchScreening | None,
) -> tuple[str, ResearchScreening | None]:
    if screening is None:
        if existing is not None and existing.content_hash == content_hash:
            return existing.screening_status, existing.screening
        return "unavailable", None
    return _screening_status(screening), screening


def _product_links(screening: ResearchScreening) -> list[tuple[str, str, float]]:
    """Product matches of a kept reference; filtered references link to nothing."""
    if screening.status != "completed" or not screening.usable or screening.profile is None:
        return []
    return [
        (match.product_id, match.match_kind, match.confidence)
        for match in screening.profile.product_matches
    ]


def _split_reference(reference_id: str) -> tuple[str, str]:
    """Split `research:<record_key>:<media_id>` into its record key and media id."""
    _prefix, record_key, media_id = reference_id.split(":", 2)
    return record_key, media_id


def _screening_status(screening: ResearchScreening) -> str:
    if screening.status == "failed":
        return "unavailable"
    return "kept" if screening.usable else "auto_filtered"


def _require_reviewable(stored: StoredResearchRecord) -> None:
    if stored.screening_status != "kept":
        raise ValueError("Only references accepted by automatic analysis can be reviewed")
    if not any(
        asset.status == "available" and asset.artifact_ref and asset.sha256
        for asset in stored.media_assets
    ):
        raise ValueError("Research media must be captured before it can be reviewed")


def _media_content_hash(media_assets: list[ResearchMediaAsset]) -> str:
    values = sorted(
        f"{asset.media_kind}:{asset.sha256}"
        for asset in media_assets
        if asset.status == "available" and asset.sha256
    )
    return hashlib.sha256("\n".join(values).encode()).hexdigest() if values else ""


def _version(
    stored: StoredResearchRecord,
    job_id: str,
    record: ResearchCrawlRecord,
    observed_at: datetime,
) -> ResearchRecordVersion:
    return ResearchRecordVersion(
        version_id=f"version_{stored.record_key.removeprefix('record_')}_{stored.content_hash[:12]}",
        record_key=stored.record_key,
        job_id=job_id,
        content_hash=stored.content_hash,
        record=record,
        observed_at=observed_at,
    )


def _postgres_record_values(record: StoredResearchRecord) -> dict[str, object]:
    return {
        "record_key": record.record_key,
        "workspace_id": record.workspace_id,
        "brand_id": record.brand_id,
        "platform": record.platform,
        "external_id": record.external_id,
        "record_type": record.record_type,
        "title": record.title,
        "text": record.text,
        "status": record.status,
        "advertiser": record.advertiser,
        "destination_domain": record.destination_domain,
        "screening_status": record.screening_status,
        "review_status": record.review_status,
        "reviewer_alias": record.reviewer_alias,
        "reviewed_at": record.reviewed_at,
        "review_reason": record.review_reason,
        "has_images": bool(record.image_urls),
        "has_videos": bool(record.video_urls),
        "content_hash": record.content_hash,
        "latest_run_id": record.latest_run_id,
        "version_count": record.version_count,
        "first_seen_at": record.first_seen_at,
        "last_seen_at": record.last_seen_at,
        "payload": _RECORD_ADAPTER.dump_python(record, mode="json"),
        "updated_at": record.last_seen_at,
    }


def _stored_values(record: StoredResearchRecord) -> tuple[object, ...]:
    return (
        record.record_key,
        record.workspace_id,
        record.brand_id,
        record.platform,
        record.external_id,
        record.record_type,
        record.title,
        record.text,
        record.status,
        record.advertiser,
        record.destination_domain,
        record.screening_status,
        record.review_status,
        record.reviewer_alias,
        record.reviewed_at.isoformat() if record.reviewed_at else None,
        record.review_reason,
        int(bool(record.image_urls)),
        int(bool(record.video_urls)),
        record.content_hash,
        record.latest_run_id,
        record.version_count,
        record.first_seen_at.isoformat(),
        record.last_seen_at.isoformat(),
        _RECORD_ADAPTER.dump_json(record).decode(),
    )


def _dump(job: ResearchCrawlJob) -> str:
    return _JOB_ADAPTER.dump_json(job).decode()


__all__ = ["PostgresResearchCrawlRepository", "SqliteResearchCrawlRepository"]
