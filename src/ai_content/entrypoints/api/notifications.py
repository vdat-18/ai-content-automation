"""Durable notification endpoints for actionable workspace events."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from ai_content.platform.notifications import Notification, NotificationRepository

from .dependencies import get_notification_repository
from .schemas.notifications import NotificationListResponse, NotificationResponse

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    unread_only: bool = Query(default=False),
    scope_type: str | None = Query(default=None),
    scope_id: str | None = Query(default=None),
    repository: NotificationRepository = Depends(get_notification_repository),
) -> NotificationListResponse:
    records = await repository.list(scope_type=scope_type, scope_id=scope_id)
    unread = sum(record.read_at is None for record in records)
    if unread_only:
        records = [record for record in records if record.read_at is None]
    return NotificationListResponse(
        items=[_response(record) for record in records],
        total=len(records),
        unread=unread,
    )


@router.post("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: str,
    repository: NotificationRepository = Depends(get_notification_repository),
) -> NotificationResponse:
    try:
        record = await repository.mark_read(notification_id, datetime.now(UTC))
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return _response(record)


def _response(record: Notification) -> NotificationResponse:
    return NotificationResponse(
        notification_id=record.notification_id,
        scope_type=record.scope_type,
        scope_id=record.scope_id,
        kind=record.kind,
        title=record.title,
        detail=record.detail,
        action_path=record.action_path,
        read_at=record.read_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
        payload=record.payload,
    )


__all__ = ["router"]
