"""SQLite and PostgreSQL adapters for collected marketplace products."""

from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database.schema import (
    marketplace_products,
    product_briefs,
    product_keyframes,
    product_selections,
    reference_images,
    reference_profiles,
    reference_searches,
)

from .parsing import SOURCE, is_non_physical, money
from .references import ReferenceProfile


class ProductRepository(Protocol):
    async def upsert_listing(self, items: list[dict[str, Any]]) -> int: ...

    async def upsert_detail(self, detail: dict[str, Any]) -> None: ...

    async def queue(self, limit: int) -> list[str]: ...

    async def list_details(self) -> list[dict[str, Any]]: ...

    async def list_listing(self) -> list[dict[str, Any]]: ...

    async def get_detail(self, product_id: str) -> dict[str, Any] | None: ...

    async def select_product(self, product_id: str, product_type: str | None) -> None: ...

    async def selections(self) -> dict[str, str | None]: ...

    async def add_profile_if_missing(self, profile: ReferenceProfile) -> None: ...

    async def list_profiles(self) -> list[ReferenceProfile]: ...

    async def update_profile(self, profile: ReferenceProfile) -> bool: ...

    async def add_reference_images(
        self, product_type: str, query: str, pins: list[dict[str, str]]
    ) -> int: ...

    async def existing_image_ids(self, image_ids: list[str]) -> set[str]: ...

    async def fingerprints(self, product_type: str) -> list[dict[str, Any]]: ...

    async def images_without_fingerprint(self, limit: int) -> list[dict[str, Any]]: ...

    async def set_fingerprint(self, image_id: str, phash: str, embedding: list[float]) -> None: ...

    async def done_searches(self) -> set[tuple[str, str]]: ...

    async def list_reference_images(
        self, status: str | None, product_type: str | None
    ) -> list[dict[str, Any]]: ...

    async def set_image_status(self, image_id: str, status: str) -> bool: ...

    async def set_image_screening(
        self, image_id: str, screening: dict[str, Any], status: str | None
    ) -> None: ...

    async def save_brief(
        self, product_id: str, user_idea: str, brief: dict[str, Any], status: str
    ) -> None: ...

    async def get_brief(self, product_id: str) -> dict[str, Any] | None: ...

    async def list_briefs(self) -> list[dict[str, Any]]: ...

    async def save_keyframe(self, keyframe: dict[str, Any]) -> None: ...

    async def list_keyframes(self, product_id: str) -> list[dict[str, Any]]: ...

    async def set_keyframe_status(self, product_id: str, shot_index: int, status: str) -> bool: ...


def _sold(value: object) -> int | None:
    try:
        return int(str(value).replace(".", "").replace(",", ""))
    except ValueError:
        return None


def _queue_candidates(rows: list[dict[str, Any]], limit: int) -> list[str]:
    """Pick listing URLs without a captured detail: videos first, then best sellers."""
    eligible = []
    for item in rows:
        url = item.get("url") or ""
        sale = money(item.get("sale_price"), item.get("currency"))
        if "/pdp/" not in url or sale is None or sale < 1000 or is_non_physical(item.get("title")):
            continue
        eligible.append((not item.get("has_video"), -(_sold(item.get("sold_count")) or 0), url))
    eligible.sort()
    return [url for _, _, url in eligible[:limit]]


def _brief_record(
    product_id: str, user_idea: str, brief: dict[str, Any], status: str
) -> dict[str, Any]:
    return {"product_id": product_id, "user_idea": user_idea, "brief": brief, "status": status}


_KEYFRAME_COLUMNS = (
    "product_id",
    "shot_index",
    "status",
    "prompt",
    "image_path",
    "attempts",
    "error",
    "qa_problem",
)


def _keyframe_record(row: Any) -> dict[str, Any]:
    return dict(zip(_KEYFRAME_COLUMNS, row, strict=True))


class SqliteProductRepository:
    def __init__(self, path: Path) -> None:
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS marketplace_products (
                product_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                title TEXT,
                sold_count INTEGER,
                has_video INTEGER NOT NULL DEFAULT 0,
                listing TEXT,
                detail TEXT,
                detail_captured_at TEXT
            )
            """
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS product_selections ("
            "product_id TEXT PRIMARY KEY, product_type TEXT)"
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS reference_profiles ("
            "product_type TEXT PRIMARY KEY, keywords TEXT NOT NULL, "
            "status TEXT NOT NULL DEFAULT 'draft')"
        )
        with contextlib.suppress(sqlite3.OperationalError):
            self._connection.execute("ALTER TABLE reference_profiles DROP COLUMN exclude_keywords")
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS reference_images ("
            "image_id TEXT PRIMARY KEY, product_type TEXT NOT NULL, query TEXT NOT NULL, "
            "image_url TEXT NOT NULL, pin_url TEXT, title TEXT, status TEXT NOT NULL DEFAULT 'pending')"
        )
        with contextlib.suppress(sqlite3.OperationalError):
            self._connection.execute("ALTER TABLE reference_images ADD COLUMN screening TEXT")
        for column in ("phash TEXT", "embedding TEXT", "duplicate_of TEXT"):
            with contextlib.suppress(sqlite3.OperationalError):
                self._connection.execute(f"ALTER TABLE reference_images ADD COLUMN {column}")
        self._connection.execute(
            "UPDATE reference_images SET status='live' WHERE status IN ('new', 'approved')"
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS product_briefs ("
            "product_id TEXT PRIMARY KEY, user_idea TEXT NOT NULL DEFAULT '', "
            "brief TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft')"
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS product_keyframes ("
            "product_id TEXT NOT NULL, shot_index INTEGER NOT NULL, status TEXT NOT NULL, "
            "prompt TEXT NOT NULL DEFAULT '', image_path TEXT, attempts INTEGER NOT NULL DEFAULT 0, "
            "error TEXT, qa_problem TEXT NOT NULL DEFAULT '', PRIMARY KEY (product_id, shot_index))"
        )
        with contextlib.suppress(sqlite3.OperationalError):
            self._connection.execute(
                "ALTER TABLE product_keyframes ADD COLUMN qa_problem TEXT NOT NULL DEFAULT ''"
            )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS reference_searches ("
            "product_type TEXT NOT NULL, query TEXT NOT NULL, PRIMARY KEY (product_type, query))"
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    async def upsert_listing(self, items: list[dict[str, Any]]) -> int:
        for item in items:
            self._connection.execute(
                """INSERT INTO marketplace_products
                   (product_id, source, title, sold_count, has_video, listing)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(product_id) DO UPDATE SET
                     title=excluded.title, sold_count=excluded.sold_count,
                     has_video=excluded.has_video, listing=excluded.listing""",
                (
                    item["product_id"],
                    SOURCE,
                    item.get("title"),
                    _sold(item.get("sold_count")),
                    int(bool(item.get("has_video"))),
                    json.dumps(item, ensure_ascii=False),
                ),
            )
        self._connection.commit()
        return len(items)

    async def upsert_detail(self, detail: dict[str, Any]) -> None:
        self._connection.execute(
            """INSERT INTO marketplace_products
               (product_id, source, title, sold_count, detail, detail_captured_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(product_id) DO UPDATE SET
                 title=excluded.title, sold_count=excluded.sold_count,
                 detail=excluded.detail, detail_captured_at=excluded.detail_captured_at""",
            (
                detail["product_id"],
                SOURCE,
                detail.get("title"),
                _sold(detail.get("sold_count")),
                json.dumps(detail, ensure_ascii=False),
                datetime.now(UTC).isoformat(),
            ),
        )
        self._connection.commit()

    async def queue(self, limit: int) -> list[str]:
        rows = self._connection.execute(
            "SELECT listing FROM marketplace_products WHERE detail IS NULL AND listing IS NOT NULL"
        ).fetchall()
        return _queue_candidates([json.loads(row[0]) for row in rows], limit)

    async def list_details(self) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT detail FROM marketplace_products WHERE detail IS NOT NULL ORDER BY product_id"
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    async def list_listing(self) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT listing FROM marketplace_products WHERE listing IS NOT NULL ORDER BY product_id"
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    async def get_detail(self, product_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT detail FROM marketplace_products WHERE product_id=? AND detail IS NOT NULL",
            (product_id,),
        ).fetchone()
        return json.loads(row[0]) if row else None

    async def select_product(self, product_id: str, product_type: str | None) -> None:
        self._connection.execute(
            "INSERT INTO product_selections (product_id, product_type) VALUES (?, ?) "
            "ON CONFLICT(product_id) DO UPDATE SET product_type=excluded.product_type",
            (product_id, product_type),
        )
        self._connection.commit()

    async def selections(self) -> dict[str, str | None]:
        rows = self._connection.execute(
            "SELECT product_id, product_type FROM product_selections"
        ).fetchall()
        return {row[0]: row[1] for row in rows}

    async def add_profile_if_missing(self, profile: ReferenceProfile) -> None:
        self._connection.execute(
            "INSERT OR IGNORE INTO reference_profiles "
            "(product_type, keywords, status) VALUES (?, ?, ?)",
            (
                profile.product_type,
                json.dumps(profile.keywords, ensure_ascii=False),
                profile.status,
            ),
        )
        self._connection.commit()

    async def list_profiles(self) -> list[ReferenceProfile]:
        rows = self._connection.execute(
            "SELECT product_type, keywords, status FROM reference_profiles ORDER BY product_type"
        ).fetchall()
        return [ReferenceProfile(r[0], json.loads(r[1]), r[2]) for r in rows]

    async def update_profile(self, profile: ReferenceProfile) -> bool:
        cursor = self._connection.execute(
            "UPDATE reference_profiles SET keywords=?, status=? WHERE product_type=?",
            (
                json.dumps(profile.keywords, ensure_ascii=False),
                profile.status,
                profile.product_type,
            ),
        )
        self._connection.commit()
        return cursor.rowcount > 0

    async def add_reference_images(
        self, product_type: str, query: str, pins: list[dict[str, str]]
    ) -> int:
        before = self._connection.total_changes
        self._connection.executemany(
            "INSERT OR IGNORE INTO reference_images "
            "(image_id, product_type, query, image_url, pin_url, title, status, "
            "phash, embedding, duplicate_of) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    pin["image_id"],
                    product_type,
                    query,
                    pin["image_url"],
                    pin["pin_url"],
                    pin["title"],
                    pin.get("status", "pending"),
                    pin.get("phash"),
                    json.dumps(pin["embedding"]) if pin.get("embedding") else None,
                    pin.get("duplicate_of"),
                )
                for pin in pins
            ],
        )
        added = self._connection.total_changes - before
        self._connection.execute(
            "INSERT OR IGNORE INTO reference_searches (product_type, query) VALUES (?, ?)",
            (product_type, query),
        )
        self._connection.commit()
        return added

    async def done_searches(self) -> set[tuple[str, str]]:
        rows = self._connection.execute("SELECT product_type, query FROM reference_searches")
        return {(row[0], row[1]) for row in rows}

    async def list_reference_images(
        self, status: str | None, product_type: str | None
    ) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT image_id, product_type, query, image_url, pin_url, title, status, screening "
            "FROM reference_images WHERE (? IS NULL OR status=?) AND (? IS NULL OR product_type=?) "
            "ORDER BY rowid",
            (status, status, product_type, product_type),
        ).fetchall()
        keys = ("image_id", "product_type", "query", "image_url", "pin_url", "title", "status")
        return [
            {
                **dict(zip(keys, row[:7], strict=True)),
                "screening": json.loads(row[7]) if row[7] else None,
            }
            for row in rows
        ]

    async def set_image_screening(
        self, image_id: str, screening: dict[str, Any], status: str | None
    ) -> None:
        self._connection.execute(
            "UPDATE reference_images SET screening=?, status=COALESCE(?, status) WHERE image_id=?",
            (json.dumps(screening, ensure_ascii=False), status, image_id),
        )
        self._connection.commit()

    async def set_image_status(self, image_id: str, status: str) -> bool:
        cursor = self._connection.execute(
            "UPDATE reference_images SET status=? WHERE image_id=?", (status, image_id)
        )
        self._connection.commit()
        return cursor.rowcount > 0

    async def save_brief(
        self, product_id: str, user_idea: str, brief: dict[str, Any], status: str
    ) -> None:
        self._connection.execute(
            "INSERT INTO product_briefs (product_id, user_idea, brief, status) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(product_id) DO UPDATE SET user_idea=excluded.user_idea, "
            "brief=excluded.brief, status=excluded.status",
            (product_id, user_idea, json.dumps(brief, ensure_ascii=False), status),
        )
        self._connection.commit()

    async def get_brief(self, product_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT product_id, user_idea, brief, status FROM product_briefs WHERE product_id=?",
            (product_id,),
        ).fetchone()
        return _brief_record(row[0], row[1], json.loads(row[2]), row[3]) if row else None

    async def list_briefs(self) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT product_id, user_idea, brief, status FROM product_briefs ORDER BY product_id"
        ).fetchall()
        return [_brief_record(r[0], r[1], json.loads(r[2]), r[3]) for r in rows]

    async def save_keyframe(self, keyframe: dict[str, Any]) -> None:
        self._connection.execute(
            "INSERT INTO product_keyframes "
            "(product_id, shot_index, status, prompt, image_path, attempts, error, qa_problem) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(product_id, shot_index) DO UPDATE SET "
            "status=excluded.status, prompt=excluded.prompt, image_path=excluded.image_path, "
            "attempts=excluded.attempts, error=excluded.error, qa_problem=excluded.qa_problem",
            tuple(keyframe[column] for column in _KEYFRAME_COLUMNS),
        )
        self._connection.commit()

    async def list_keyframes(self, product_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_KEYFRAME_COLUMNS)} FROM product_keyframes "
            "WHERE product_id=? ORDER BY shot_index",
            (product_id,),
        ).fetchall()
        return [_keyframe_record(row) for row in rows]

    async def set_keyframe_status(self, product_id: str, shot_index: int, status: str) -> bool:
        cursor = self._connection.execute(
            "UPDATE product_keyframes SET status=? WHERE product_id=? AND shot_index=?",
            (status, product_id, shot_index),
        )
        self._connection.commit()
        return cursor.rowcount > 0

    async def existing_image_ids(self, image_ids: list[str]) -> set[str]:
        if not image_ids:
            return set()
        marks = ",".join("?" * len(image_ids))
        rows = self._connection.execute(
            f"SELECT image_id FROM reference_images WHERE image_id IN ({marks})", image_ids
        )
        return {row[0] for row in rows}

    async def fingerprints(self, product_type: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT image_id, phash, embedding FROM reference_images "
            "WHERE product_type=? AND phash IS NOT NULL",
            (product_type,),
        ).fetchall()
        return [
            {"image_id": r[0], "phash": r[1], "embedding": json.loads(r[2]) if r[2] else None}
            for r in rows
        ]

    async def images_without_fingerprint(self, limit: int) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT image_id, image_url FROM reference_images "
            "WHERE phash IS NULL AND status != 'duplicate' LIMIT ?",
            (limit,),
        ).fetchall()
        return [{"image_id": r[0], "image_url": r[1]} for r in rows]

    async def set_fingerprint(self, image_id: str, phash: str, embedding: list[float]) -> None:
        self._connection.execute(
            "UPDATE reference_images SET phash=?, embedding=? WHERE image_id=?",
            (phash, json.dumps(embedding), image_id),
        )
        self._connection.commit()


class PostgresProductRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def upsert_listing(self, items: list[dict[str, Any]]) -> int:
        async with self._engine.begin() as connection:
            for item in items:
                values = {
                    "product_id": item["product_id"],
                    "source": SOURCE,
                    "title": item.get("title"),
                    "sold_count": _sold(item.get("sold_count")),
                    "has_video": bool(item.get("has_video")),
                    "listing": item,
                }
                statement = insert(marketplace_products).values(**values)
                statement = statement.on_conflict_do_update(
                    index_elements=["product_id"],
                    set_={key: value for key, value in values.items() if key != "product_id"}
                    | {"updated_at": func.now()},
                )
                await connection.execute(statement)
        return len(items)

    async def upsert_detail(self, detail: dict[str, Any]) -> None:
        values = {
            "product_id": detail["product_id"],
            "source": SOURCE,
            "title": detail.get("title"),
            "sold_count": _sold(detail.get("sold_count")),
            "detail": detail,
            "detail_captured_at": datetime.now(UTC),
        }
        statement = insert(marketplace_products).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["product_id"],
            set_={key: value for key, value in values.items() if key != "product_id"}
            | {"updated_at": func.now()},
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def queue(self, limit: int) -> list[str]:
        statement = select(marketplace_products.c.listing).where(
            marketplace_products.c.detail.is_(None), marketplace_products.c.listing.is_not(None)
        )
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement)).scalars().all()
        return _queue_candidates(list(rows), limit)

    async def list_details(self) -> list[dict[str, Any]]:
        statement = (
            select(marketplace_products.c.detail)
            .where(marketplace_products.c.detail.is_not(None))
            .order_by(marketplace_products.c.product_id)
        )
        async with self._engine.connect() as connection:
            return list((await connection.execute(statement)).scalars().all())

    async def list_listing(self) -> list[dict[str, Any]]:
        statement = (
            select(marketplace_products.c.listing)
            .where(marketplace_products.c.listing.is_not(None))
            .order_by(marketplace_products.c.product_id)
        )
        async with self._engine.connect() as connection:
            return list((await connection.execute(statement)).scalars().all())

    async def get_detail(self, product_id: str) -> dict[str, Any] | None:
        statement = select(marketplace_products.c.detail).where(
            marketplace_products.c.product_id == product_id,
            marketplace_products.c.detail.is_not(None),
        )
        async with self._engine.connect() as connection:
            return (await connection.execute(statement)).scalar_one_or_none()

    async def select_product(self, product_id: str, product_type: str | None) -> None:
        statement = insert(product_selections).values(
            product_id=product_id, product_type=product_type
        )
        statement = statement.on_conflict_do_update(
            index_elements=["product_id"],
            set_={"product_type": product_type, "updated_at": func.now()},
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def selections(self) -> dict[str, str | None]:
        statement = select(product_selections.c.product_id, product_selections.c.product_type)
        async with self._engine.connect() as connection:
            return {row[0]: row[1] for row in (await connection.execute(statement)).all()}

    async def add_profile_if_missing(self, profile: ReferenceProfile) -> None:
        statement = (
            insert(reference_profiles)
            .values(
                product_type=profile.product_type,
                keywords=profile.keywords,
                status=profile.status,
            )
            .on_conflict_do_nothing(index_elements=["product_type"])
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def list_profiles(self) -> list[ReferenceProfile]:
        statement = select(
            reference_profiles.c.product_type,
            reference_profiles.c.keywords,
            reference_profiles.c.status,
        ).order_by(reference_profiles.c.product_type)
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement)).all()
        return [ReferenceProfile(r[0], list(r[1]), r[2]) for r in rows]

    async def update_profile(self, profile: ReferenceProfile) -> bool:
        statement = (
            reference_profiles.update()
            .where(reference_profiles.c.product_type == profile.product_type)
            .values(
                keywords=profile.keywords,
                status=profile.status,
                updated_at=func.now(),
            )
        )
        async with self._engine.begin() as connection:
            return (await connection.execute(statement)).rowcount > 0

    async def add_reference_images(
        self, product_type: str, query: str, pins: list[dict[str, str]]
    ) -> int:
        added = 0
        async with self._engine.begin() as connection:
            if pins:
                statement = (
                    insert(reference_images)
                    .values(
                        [
                            {
                                "image_id": pin["image_id"],
                                "product_type": product_type,
                                "query": query,
                                "image_url": pin["image_url"],
                                "pin_url": pin["pin_url"],
                                "title": pin["title"],
                                "status": pin.get("status", "pending"),
                                "phash": pin.get("phash"),
                                "embedding": pin.get("embedding"),
                                "duplicate_of": pin.get("duplicate_of"),
                            }
                            for pin in pins
                        ]
                    )
                    .on_conflict_do_nothing(index_elements=["image_id"])
                )
                inserted = await connection.execute(
                    statement.returning(reference_images.c.image_id)
                )
                added = len(inserted.all())
            await connection.execute(
                insert(reference_searches)
                .values(product_type=product_type, query=query)
                .on_conflict_do_nothing()
            )
        return added

    async def done_searches(self) -> set[tuple[str, str]]:
        statement = select(reference_searches.c.product_type, reference_searches.c.query)
        async with self._engine.connect() as connection:
            return {(row[0], row[1]) for row in (await connection.execute(statement)).all()}

    async def list_reference_images(
        self, status: str | None, product_type: str | None
    ) -> list[dict[str, Any]]:
        statement = select(reference_images).order_by(reference_images.c.created_at)
        if status is not None:
            statement = statement.where(reference_images.c.status == status)
        if product_type is not None:
            statement = statement.where(reference_images.c.product_type == product_type)
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        keys = (
            "image_id",
            "product_type",
            "query",
            "image_url",
            "pin_url",
            "title",
            "status",
            "screening",
        )
        return [{key: row[key] for key in keys} for row in rows]

    async def set_image_status(self, image_id: str, status: str) -> bool:
        statement = (
            reference_images.update()
            .where(reference_images.c.image_id == image_id)
            .values(status=status, updated_at=func.now())
        )
        async with self._engine.begin() as connection:
            return (await connection.execute(statement)).rowcount > 0

    async def set_image_screening(
        self, image_id: str, screening: dict[str, Any], status: str | None
    ) -> None:
        values: dict[str, Any] = {"screening": screening, "updated_at": func.now()}
        if status is not None:
            values["status"] = status
        statement = (
            reference_images.update()
            .where(reference_images.c.image_id == image_id)
            .values(**values)
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def save_brief(
        self, product_id: str, user_idea: str, brief: dict[str, Any], status: str
    ) -> None:
        values = {
            "product_id": product_id,
            "user_idea": user_idea,
            "brief": brief,
            "status": status,
        }
        statement = insert(product_briefs).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["product_id"],
            set_={key: value for key, value in values.items() if key != "product_id"}
            | {"updated_at": func.now()},
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def get_brief(self, product_id: str) -> dict[str, Any] | None:
        statement = select(
            product_briefs.c.product_id,
            product_briefs.c.user_idea,
            product_briefs.c.brief,
            product_briefs.c.status,
        ).where(product_briefs.c.product_id == product_id)
        async with self._engine.connect() as connection:
            row = (await connection.execute(statement)).one_or_none()
        return _brief_record(*row) if row else None

    async def list_briefs(self) -> list[dict[str, Any]]:
        statement = select(
            product_briefs.c.product_id,
            product_briefs.c.user_idea,
            product_briefs.c.brief,
            product_briefs.c.status,
        ).order_by(product_briefs.c.product_id)
        async with self._engine.connect() as connection:
            return [_brief_record(*row) for row in (await connection.execute(statement)).all()]

    async def save_keyframe(self, keyframe: dict[str, Any]) -> None:
        values = {column: keyframe[column] for column in _KEYFRAME_COLUMNS}
        statement = insert(product_keyframes).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["product_id", "shot_index"],
            set_={k: v for k, v in values.items() if k not in ("product_id", "shot_index")}
            | {"updated_at": func.now()},
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def list_keyframes(self, product_id: str) -> list[dict[str, Any]]:
        statement = (
            select(*(product_keyframes.c[column] for column in _KEYFRAME_COLUMNS))
            .where(product_keyframes.c.product_id == product_id)
            .order_by(product_keyframes.c.shot_index)
        )
        async with self._engine.connect() as connection:
            return [_keyframe_record(row) for row in (await connection.execute(statement)).all()]

    async def set_keyframe_status(self, product_id: str, shot_index: int, status: str) -> bool:
        statement = (
            product_keyframes.update()
            .where(
                product_keyframes.c.product_id == product_id,
                product_keyframes.c.shot_index == shot_index,
            )
            .values(status=status, updated_at=func.now())
            .returning(product_keyframes.c.shot_index)
        )
        async with self._engine.begin() as connection:
            return (await connection.execute(statement)).first() is not None

    async def existing_image_ids(self, image_ids: list[str]) -> set[str]:
        if not image_ids:
            return set()
        statement = select(reference_images.c.image_id).where(
            reference_images.c.image_id.in_(image_ids)
        )
        async with self._engine.connect() as connection:
            return set((await connection.execute(statement)).scalars().all())

    async def fingerprints(self, product_type: str) -> list[dict[str, Any]]:
        statement = select(
            reference_images.c.image_id, reference_images.c.phash, reference_images.c.embedding
        ).where(
            reference_images.c.product_type == product_type, reference_images.c.phash.is_not(None)
        )
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement)).all()
        return [{"image_id": r[0], "phash": r[1], "embedding": r[2]} for r in rows]

    async def images_without_fingerprint(self, limit: int) -> list[dict[str, Any]]:
        statement = (
            select(reference_images.c.image_id, reference_images.c.image_url)
            .where(reference_images.c.phash.is_(None), reference_images.c.status != "duplicate")
            .limit(limit)
        )
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement)).all()
        return [{"image_id": r[0], "image_url": r[1]} for r in rows]

    async def set_fingerprint(self, image_id: str, phash: str, embedding: list[float]) -> None:
        statement = (
            reference_images.update()
            .where(reference_images.c.image_id == image_id)
            .values(phash=phash, embedding=embedding, updated_at=func.now())
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)
