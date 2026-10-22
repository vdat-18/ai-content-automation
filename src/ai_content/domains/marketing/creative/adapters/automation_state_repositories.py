"""PostgreSQL persistence for concurrent Creative automation workflow state."""

from __future__ import annotations

import json

from pydantic import TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ai_content.domains.marketing.creative.ports.automation_workflow import (
    MarketingCreativeAutomationState,
)
from ai_content.platform.database.schema import creative_automation_states

_STATE_ADAPTER = TypeAdapter(MarketingCreativeAutomationState)


class PostgresMarketingCreativeAutomationStateRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    def reference(self, request_id: str) -> str:
        return f"postgresql:marketing.creative_automation_states/{request_id}"

    async def save(self, state: MarketingCreativeAutomationState) -> str:
        payload = json.loads(_STATE_ADAPTER.dump_json(state))
        async with self._engine.begin() as connection:
            if state.revision == 0:
                created = (
                    await connection.execute(
                        insert(creative_automation_states)
                        .values(
                            request_id=state.request_id,
                            status=state.status.value,
                            revision=state.revision,
                            payload=payload,
                            created_at=state.created_at,
                            updated_at=state.updated_at,
                        )
                        .on_conflict_do_nothing(
                            index_elements=[creative_automation_states.c.request_id]
                        )
                        .returning(creative_automation_states.c.request_id)
                    )
                ).scalar_one_or_none()
                if created is None:
                    existing = (
                        (
                            await connection.execute(
                                select(
                                    creative_automation_states.c.revision,
                                    creative_automation_states.c.payload,
                                ).where(creative_automation_states.c.request_id == state.request_id)
                            )
                        )
                        .mappings()
                        .one()
                    )
                    if existing["revision"] != 0 or existing["payload"] != payload:
                        raise ValueError("Creative automation state was updated concurrently")
            else:
                result = await connection.execute(
                    update(creative_automation_states)
                    .where(
                        creative_automation_states.c.request_id == state.request_id,
                        creative_automation_states.c.revision == state.revision - 1,
                    )
                    .values(
                        status=state.status.value,
                        revision=state.revision,
                        payload=payload,
                        updated_at=state.updated_at,
                    )
                )
                if result.rowcount != 1:
                    existing = (
                        (
                            await connection.execute(
                                select(
                                    creative_automation_states.c.revision,
                                    creative_automation_states.c.payload,
                                ).where(creative_automation_states.c.request_id == state.request_id)
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if (
                        existing is None
                        or existing["revision"] != state.revision
                        or existing["payload"] != payload
                    ):
                        raise ValueError("Creative automation state was updated concurrently")
        return self.reference(state.request_id)

    async def get(self, request_id: str) -> MarketingCreativeAutomationState | None:
        async with self._engine.connect() as connection:
            payload = (
                await connection.execute(
                    select(creative_automation_states.c.payload).where(
                        creative_automation_states.c.request_id == request_id
                    )
                )
            ).scalar_one_or_none()
        return _STATE_ADAPTER.validate_python(payload) if payload is not None else None


__all__ = ["PostgresMarketingCreativeAutomationStateRepository"]
