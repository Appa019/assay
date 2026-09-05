from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.core.database import get_session
from app.models.notification import NotificationKind, NotificationLevel
from app.services import notification_center

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationRead(BaseModel):
    id: UUID
    kind: NotificationKind
    level: NotificationLevel
    title: str
    body: str
    url: str | None
    read_at: datetime | None
    created_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationRead]
    unread: int


@router.get("", response_model=NotificationList)
async def list_notifications(
    limit: int = 50,
    unread_only: bool = False,
    session: Session = Depends(get_session),
) -> NotificationList:
    """The app inbox. Everything the system has to say lands here."""
    rows = notification_center.list_notifications(
        session, limit=min(limit, 200), unread_only=unread_only
    )
    return NotificationList(
        items=[NotificationRead.model_validate(r, from_attributes=True) for r in rows],
        unread=notification_center.unread_count(session),
    )


@router.post("/{notification_id}/read", response_model=NotificationRead)
async def mark_read(
    notification_id: UUID, session: Session = Depends(get_session)
) -> NotificationRead:
    try:
        record = notification_center.mark_read(session, notification_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return NotificationRead.model_validate(record, from_attributes=True)


@router.post("/read-all")
async def mark_all_read(session: Session = Depends(get_session)) -> dict[str, int]:
    return {"marked": notification_center.mark_all_read(session)}
