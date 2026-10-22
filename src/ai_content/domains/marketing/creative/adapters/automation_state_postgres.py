"""PostgreSQL persistence for selected-SKU Creative automation state."""

from __future__ import annotations

from dataclasses import replace

from pydantic import TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.domains.marketing.creative.ports.automation_workflow import (
    MarketingCreativeAutomationState,
)
from ai_content.platform.database.schema import marketing_creative_automation_states


class MarketingCreativeAutomationStateConflictError(RuntimeError):
    """Raised when another request persisted a newer automation state."""


class PostgresMarketingCreativeAutomationStateRepository:
    """Persist state with optimistic concurrency instead of mutable local files."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._adapter = TypeAdapter(MarketingCreativeAutomationState)

    async def get(self, request_id: str) -> MarketingCreativeAutomationState | None:
        statement = select(marketing_creative_automation_states.c.payload).where(
            marketing_creative_automation_states.c.request_id == request_id
        )
        async with self._engine.connect() as connection:
            payload = (await connection.execute(statement)).scalar_one_or_none()
        return self._adapter.validate_python(payload) if payload is not None else None

    async def create(
        self,
        state: MarketingCreativeAutomationState,
    ) -> MarketingCreativeAutomationState:
        if state.revision != 0:
            raise ValueError("New Creative automation state must start at revision zero")
        statement = (
            insert(marketing_creative_automation_states)
            .values(**_values(state))
            .on_conflict_do_nothing(
                index_elements=[marketing_creative_automation_states.c.request_id]
            )
        )
        async with self._engine.begin() as connection:
            result = await connection.execute(statement)
        if result.rowcount == 1:
            return state
        existing = await self.get(state.request_id)
        if existing is None:
            raise RuntimeError("Creative automation state was not persisted")
        return existing

    async def save(
        self, state: MarketingCreativeAutomationState
    ) -> MarketingCreativeAutomationState:
        updated = replace(state, revision=state.revision + 1)
        statement = (
            update(marketing_creative_automation_states)
            .where(
                marketing_creative_automation_states.c.request_id == state.request_id,
                marketing_creative_automation_states.c.revision == state.revision,
            )
            .values(**_values(updated))
        )
        async with self._engine.begin() as connection:
            result = await connection.execute(statement)
        if result.rowcount != 1:
            raise MarketingCreativeAutomationStateConflictError(
                "Creative automation changed before this update could be saved"
            )
        return updated


def _values(state: MarketingCreativeAutomationState) -> dict[str, object]:
    return {
        "request_id": state.request_id,
        "package_id": state.package_id,
        "package_ref": state.package_ref,
        "route": state.route,
        "status": state.status.value,
        "revision": state.revision,
        "payload": TypeAdapter(MarketingCreativeAutomationState).dump_python(state, mode="json"),
        "created_at": state.created_at,
        "updated_at": state.updated_at,
    }


__all__ = [
    "MarketingCreativeAutomationStateConflictError",
    "PostgresMarketingCreativeAutomationStateRepository",
]
