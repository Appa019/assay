from datetime import UTC, date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.database import get_session
from app.models.contribution import Contribution

router = APIRouter(prefix="/api/cadence", tags=["cadence"])


class CadenceStatus(BaseModel):
    """Informational only — contributions are ad-hoc, there is no fixed cycle."""

    last_contribution_date: date | None
    days_since_last: int | None
    total_contributions: int


@router.get("", response_model=CadenceStatus)
async def get_cadence(session: Session = Depends(get_session)) -> CadenceStatus:
    last = session.exec(
        select(Contribution).order_by(Contribution.created_at.desc()).limit(1)
    ).first()
    total = session.exec(select(func.count(Contribution.id))).one()

    if last is None:
        return CadenceStatus(
            last_contribution_date=None, days_since_last=None, total_contributions=0
        )

    # created_at is stored as (naive) UTC; convert to the machine's local zone
    # before taking the calendar date, or late-evening aportes show "yesterday".
    created = last.created_at if last.created_at.tzinfo else last.created_at.replace(tzinfo=UTC)
    last_date = created.astimezone().date()
    return CadenceStatus(
        last_contribution_date=last_date,
        days_since_last=(date.today() - last_date).days,
        total_contributions=int(total or 0),
    )
