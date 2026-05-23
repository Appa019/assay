from datetime import date, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.config import settings
from app.core.database import get_session
from app.models.contribution import Contribution

router = APIRouter(prefix="/api/cadence", tags=["cadence"])


class CadenceStatus(BaseModel):
    last_contribution_date: date | None
    next_contribution_date: date
    days_until_next: int
    interval_days: int
    is_due: bool
    is_overdue: bool


@router.get("", response_model=CadenceStatus)
async def get_cadence(session: Session = Depends(get_session)) -> CadenceStatus:
    last = session.exec(
        select(Contribution).order_by(Contribution.created_at.desc()).limit(1)
    ).first()

    today = date.today()
    interval = settings.contribution_interval_days

    if last is None:
        return CadenceStatus(
            last_contribution_date=None,
            next_contribution_date=today,
            days_until_next=0,
            interval_days=interval,
            is_due=True,
            is_overdue=False,
        )

    last_date = last.created_at.date()
    next_date = last_date + timedelta(days=interval)
    days_until_next = (next_date - today).days

    return CadenceStatus(
        last_contribution_date=last_date,
        next_contribution_date=next_date,
        days_until_next=days_until_next,
        interval_days=interval,
        is_due=days_until_next <= 0,
        is_overdue=days_until_next < -3,
    )
