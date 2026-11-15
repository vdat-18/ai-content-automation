"""PostgreSQL adapter for collected marketplace products."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database.schema import (
    marketplace_products,
    product_briefs,
    product_clips,
    product_events,
    product_keyframes,
    product_pipeline_runs,
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

    async def fingerprints(self, product_type: str | None = None) -> list[dict[str, Any]]: ...

    async def images_without_fingerprint(self, limit: int) -> list[dict[str, Any]]: ...

    async def set_fingerprint(self, image_id: str, phash: str, embedding: list[float]) -> None: ...

    async def text_embeddings(self) -> dict[str, dict[str, Any]]: ...

    async def set_text_embedding(self, image_id: str, model: str, vector: list[float]) -> None: ...

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

    async def save_clip(self, clip: dict[str, Any]) -> None: ...

    async def list_clips(self, product_id: str) -> list[dict[str, Any]]: ...

    async def add_event(
        self, product_id: str, step: str, shot_index: int | None, status: str, message: str
    ) -> None: ...

    async def list_events(self, product_id: str, limit: int = 300) -> list[dict[str, Any]]: ...

    async def delete_product(self, product_id: str) -> bool: ...

    async def clear_work(self, product_id: str) -> None: ...

    async def save_run(self, product_id: str, status: str, message: str) -> None: ...

    async def get_run(self, product_id: str) -> dict[str, str] | None: ...

    async def interrupt_runs(self) -> int: ...


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


_PRODUCT_OWNED_TABLES = (
    "product_selections",
    "product_briefs",
    "product_keyframes",
    "product_clips",
    "product_events",
    "product_pipeline_runs",
)
# What is made for a product, as opposed to the product itself and its person
_WORK_TABLES = ("product_briefs", "product_keyframes", "product_clips", "product_pipeline_runs")
INTERRUPTED_RUN = (
    "The server restarted while this was running. Run it again: what is already made is kept."
)
_EVENT_COLUMNS = ("id", "at", "step", "shot_index", "status", "message")


def _event_record(row: Any) -> dict[str, Any]:
    record = dict(zip(_EVENT_COLUMNS, row, strict=True))
    record["at"] = str(
        record["at"].isoformat() if hasattr(record["at"], "isoformat") else record["at"]
    )
    return record


_CLIP_COLUMNS = (
    "product_id",
    "shot_index",
    "status",
    "job_id",
    "job_model",
    "video_path",
    "seconds",
    "attempts",
    "error",
    "qa_problem",
)


def _clip_record(row: Any) -> dict[str, Any]:
    return dict(zip(_CLIP_COLUMNS, row, strict=True))


def _keyframe_record(row: Any) -> dict[str, Any]:
    return dict(zip(_KEYFRAME_COLUMNS, row, strict=True))


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
            marketplace_products.c.detail.is_(None),
            marketplace_products.c.listing.is_not(None),
            marketplace_products.c.deleted.is_(False),
        )
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement)).scalars().all()
        return _queue_candidates(list(rows), limit)

    async def list_details(self) -> list[dict[str, Any]]:
        statement = (
            select(marketplace_products.c.detail)
            .where(
                marketplace_products.c.detail.is_not(None),
                marketplace_products.c.deleted.is_(False),
            )
            .order_by(marketplace_products.c.product_id)
        )
        async with self._engine.connect() as connection:
            return list((await connection.execute(statement)).scalars().all())

    async def list_listing(self) -> list[dict[str, Any]]:
        statement = (
            select(marketplace_products.c.listing)
            .where(
                marketplace_products.c.listing.is_not(None),
                marketplace_products.c.deleted.is_(False),
            )
            .order_by(marketplace_products.c.product_id)
        )
        async with self._engine.connect() as connection:
            return list((await connection.execute(statement)).scalars().all())

    async def get_detail(self, product_id: str) -> dict[str, Any] | None:
        statement = select(marketplace_products.c.detail).where(
            marketplace_products.c.product_id == product_id,
            marketplace_products.c.detail.is_not(None),
            marketplace_products.c.deleted.is_(False),
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

    async def save_clip(self, clip: dict[str, Any]) -> None:
        values = {column: clip[column] for column in _CLIP_COLUMNS}
        statement = insert(product_clips).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["product_id", "shot_index"],
            set_={k: v for k, v in values.items() if k not in ("product_id", "shot_index")}
            | {"updated_at": func.now()},
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def list_clips(self, product_id: str) -> list[dict[str, Any]]:
        statement = (
            select(*(product_clips.c[column] for column in _CLIP_COLUMNS))
            .where(product_clips.c.product_id == product_id)
            .order_by(product_clips.c.shot_index)
        )
        async with self._engine.connect() as connection:
            return [_clip_record(row) for row in (await connection.execute(statement)).all()]

    async def add_event(
        self, product_id: str, step: str, shot_index: int | None, status: str, message: str
    ) -> None:
        statement = insert(product_events).values(
            product_id=product_id,
            step=step,
            shot_index=shot_index,
            status=status,
            message=message,
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def list_events(self, product_id: str, limit: int = 300) -> list[dict[str, Any]]:
        columns = ("id", "at", "step", "shot_index", "status", "message")
        statement = (
            select(*(product_events.c[column] for column in columns))
            .where(product_events.c.product_id == product_id)
            .order_by(product_events.c.id.desc())
            .limit(limit)
        )
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement)).all()
        return [_event_record(row) for row in reversed(rows)]

    async def delete_product(self, product_id: str) -> bool:
        """Hide the product for good and drop everything made from it."""
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(marketplace_products)
                .where(
                    marketplace_products.c.product_id == product_id,
                    marketplace_products.c.deleted.is_(False),
                )
                .values(deleted=True)
            )
            for table in (
                product_selections,
                product_briefs,
                product_keyframes,
                product_clips,
                product_events,
                product_pipeline_runs,
            ):
                await connection.execute(delete(table).where(table.c.product_id == product_id))
        return bool(result.rowcount)

    async def clear_work(self, product_id: str) -> None:
        """Drop the script, images and clips of a product, so it can be made again."""
        async with self._engine.begin() as connection:
            for table in (product_briefs, product_keyframes, product_clips, product_pipeline_runs):
                await connection.execute(delete(table).where(table.c.product_id == product_id))

    async def save_run(self, product_id: str, status: str, message: str) -> None:
        statement = insert(product_pipeline_runs).values(
            product_id=product_id, status=status, message=message
        )
        statement = statement.on_conflict_do_update(
            index_elements=["product_id"],
            set_={"status": status, "message": message, "updated_at": func.now()},
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def get_run(self, product_id: str) -> dict[str, str] | None:
        statement = select(product_pipeline_runs.c.status, product_pipeline_runs.c.message).where(
            product_pipeline_runs.c.product_id == product_id
        )
        async with self._engine.connect() as connection:
            row = (await connection.execute(statement)).one_or_none()
        return {"status": row[0], "step": "", "message": row[1]} if row else None

    async def interrupt_runs(self) -> int:
        statement = (
            update(product_pipeline_runs)
            .where(product_pipeline_runs.c.status == "running")
            .values(status="interrupted", message=INTERRUPTED_RUN, updated_at=func.now())
        )
        async with self._engine.begin() as connection:
            return (await connection.execute(statement)).rowcount

    async def existing_image_ids(self, image_ids: list[str]) -> set[str]:
        if not image_ids:
            return set()
        statement = select(reference_images.c.image_id).where(
            reference_images.c.image_id.in_(image_ids)
        )
        async with self._engine.connect() as connection:
            return set((await connection.execute(statement)).scalars().all())

    async def fingerprints(self, product_type: str | None = None) -> list[dict[str, Any]]:
        statement = select(
            reference_images.c.image_id, reference_images.c.phash, reference_images.c.embedding
        ).where(reference_images.c.phash.is_not(None))
        if product_type is not None:
            statement = statement.where(reference_images.c.product_type == product_type)
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement)).all()
        return [{"image_id": r[0], "phash": r[1], "embedding": r[2]} for r in rows]

    async def images_without_fingerprint(self, limit: int) -> list[dict[str, Any]]:
        statement = (
            select(
                reference_images.c.image_id, reference_images.c.image_url, reference_images.c.status
            )
            .where(reference_images.c.phash.is_(None), reference_images.c.status != "duplicate")
            .limit(limit)
        )
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement)).all()
        return [{"image_id": r[0], "image_url": r[1], "status": r[2]} for r in rows]

    async def text_embeddings(self) -> dict[str, dict[str, Any]]:
        statement = select(reference_images.c.image_id, reference_images.c.text_embedding).where(
            reference_images.c.text_embedding.is_not(None)
        )
        async with self._engine.connect() as connection:
            rows = (await connection.execute(statement)).all()
        return {row[0]: row[1] for row in rows}

    async def set_text_embedding(self, image_id: str, model: str, vector: list[float]) -> None:
        statement = (
            reference_images.update()
            .where(reference_images.c.image_id == image_id)
            .values(text_embedding={"model": model, "vector": vector}, updated_at=func.now())
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)

    async def set_fingerprint(self, image_id: str, phash: str, embedding: list[float]) -> None:
        statement = (
            reference_images.update()
            .where(reference_images.c.image_id == image_id)
            .values(phash=phash, embedding=embedding, updated_at=func.now())
        )
        async with self._engine.begin() as connection:
            await connection.execute(statement)
