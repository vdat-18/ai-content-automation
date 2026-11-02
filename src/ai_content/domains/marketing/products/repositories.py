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

from ai_content.platform.database.schema import marketplace_products

from .parsing import SOURCE, money


class ProductRepository(Protocol):
    async def upsert_listing(self, items: list[dict[str, Any]]) -> int: ...

    async def upsert_detail(self, detail: dict[str, Any]) -> None: ...

    async def queue(self, limit: int) -> list[str]: ...

    async def list_details(self) -> list[dict[str, Any]]: ...

    async def list_listing(self) -> list[dict[str, Any]]: ...

    async def get_detail(self, product_id: str) -> dict[str, Any] | None: ...


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
        if "/pdp/" not in url or sale is None or sale < 1000:
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
