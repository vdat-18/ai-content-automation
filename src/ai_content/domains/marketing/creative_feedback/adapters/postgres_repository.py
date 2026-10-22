"""PostgreSQL persistence for Creative feedback runs."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database import PostgresJsonStore
from ai_content.platform.database.schema import creative_feedback_runs

from ..domain.models import CreativeFeedbackRun
from .serialization import run_from_dict, run_to_dict


class PostgresCreativeFeedbackRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._store = PostgresJsonStore(engine, creative_feedback_runs, run_from_dict)

    def close(self) -> None:
        self._store.close()

    async def save(self, run: CreativeFeedbackRun) -> None:
        await self._store.upsert(
            {
                "run_id": run.run_id,
                "source_run_id": run.source_run_id,
                "source_checksum": run.source_checksum_sha256,
                "creative_version_id": run.release.creative_version_id,
                "state": run.state.value,
                "payload": run_to_dict(run),
            },
            ("state", "payload"),
        )

    async def get(self, run_id: str) -> CreativeFeedbackRun | None:
        return await self._store.get(creative_feedback_runs.c.run_id, run_id)

    async def get_by_source_run_id(self, source_run_id: str) -> CreativeFeedbackRun | None:
        return await self._store.get(creative_feedback_runs.c.source_run_id, source_run_id)

    async def list(self) -> list[CreativeFeedbackRun]:
        return await self._store.list()

    async def list_approved_memory(
        self,
        *,
        brand_id: str,
        sku_id: str,
        limit: int = 20,
    ) -> list[CreativeFeedbackRun]:
        runs = await self._store.list()
        return [
            run
            for run in runs
            if run.decision is not None
            and run.decision.value == "approve"
            and run.release.brand_id == brand_id
            and run.release.sku_id == sku_id
        ][:limit]


__all__ = ["PostgresCreativeFeedbackRepository"]
