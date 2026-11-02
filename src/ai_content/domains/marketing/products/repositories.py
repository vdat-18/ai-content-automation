"""SQLite and PostgreSQL adapters for collected marketplace products."""

from __future__ import annotations

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
    product_selections,
    reference_profiles,
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
            "exclude_keywords TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft')"
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
            "(product_type, keywords, exclude_keywords, status) VALUES (?, ?, ?, ?)",
            (
                profile.product_type,
                json.dumps(profile.keywords, ensure_ascii=False),
                json.dumps(profile.exclude_keywords, ensure_ascii=False),
                profile.status,
            ),
        )
        self._connection.commit()

    async def list_profiles(self) -> list[ReferenceProfile]:
        rows = self._connection.execute(
            "SELECT product_type, keywords, exclude_keywords, status "
            "FROM reference_profiles ORDER BY product_type"
        ).fetchall()
        return [ReferenceProfile(r[0], json.loads(r[1]), json.loads(r[2]), r[3]) for r in rows]

    async def update_profile(self, profile: ReferenceProfile) -> bool:
        cursor = self._connection.execute(
            "UPDATE reference_profiles SET keywords=?, exclude_keywords=?, status=? "
            "WHERE product_type=?",
            (
                json.dumps(profile.keywords, ensure_ascii=False),
                json.dumps(profile.exclude_keywords, ensure_ascii=False),
                profile.status,
                profile.product_type,
            ),
        )
        self._connection.commit()
        return cursor.rowcount > 0


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
                exclude_keywords=profile.exclude_keywords,
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
            reference_profiles.c.exclude_keywords,
            reference_profiles.c.status,
        ).order_by(reference_profiles.c.product_type)
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement)).all()
        return [ReferenceProfile(r[0], list(r[1]), list(r[2]), r[3]) for r in rows]

    async def update_profile(self, profile: ReferenceProfile) -> bool:
        statement = (
            reference_profiles.update()
            .where(reference_profiles.c.product_type == profile.product_type)
            .values(
                keywords=profile.keywords,
                exclude_keywords=profile.exclude_keywords,
                status=profile.status,
                updated_at=func.now(),
            )
        )
        async with self._engine.begin() as connection:
            return (await connection.execute(statement)).rowcount > 0
