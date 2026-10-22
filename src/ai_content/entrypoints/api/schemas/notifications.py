"""API contracts for durable workspace notifications."""

from datetime import datetime

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    notification_id: str
    scope_type: str
    scope_id: str
    kind: str
    title: str
    detail: str
    action_path: str | None
    read_at: datetime | None
    created_at: datetime
    updated_at: datetime
    payload: dict[str, object] | None


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int
    unread: int


__all__ = ["NotificationListResponse", "NotificationResponse"]
