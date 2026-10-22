"""PostgreSQL persistence for Creative intake runs."""

from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.platform.database import PostgresJsonStore
from ai_content.platform.database.schema import creative_intake_runs

from ..domain.models import CreativeIntakeRun
from .serialization import run_from_dict, run_to_dict


class PostgresCreativeIntakeRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._store = PostgresJsonStore(engine, creative_intake_runs, run_from_dict)

    def close(self) -> None:
        self._store.close()

    async def save(self, run: CreativeIntakeRun) -> None:
        await self._store.upsert(
            {
                "run_id": run.run_id,
                "source_run_id": run.source_run_id,
                "source_checksum": run.source_checksum_sha256,
                "state": run.state.value,
                "brand_id": run.context.brand_id,
                "sku_id": run.context.sku_id,
                "payload": run_to_dict(run),
            },
            ("state", "payload"),
        )

    async def get(self, run_id: str) -> CreativeIntakeRun | None:
        return await self._store.get(creative_intake_runs.c.run_id, run_id)

    async def get_by_source_run_id(self, source_run_id: str) -> CreativeIntakeRun | None:
        return await self._store.get(creative_intake_runs.c.source_run_id, source_run_id)

    async def get_by_task_source_run_id(self, source_run_id: str) -> CreativeIntakeRun | None:
        for run in await self.list():
            if run.release is not None and run.release.source_run_id == source_run_id:
                return run
        return None

    async def list(self) -> list[CreativeIntakeRun]:
        return await self._store.list()


__all__ = ["PostgresCreativeIntakeRepository"]
