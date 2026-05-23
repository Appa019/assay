from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.database import get_session
from app.models.report import Report, ReportKind

router = APIRouter(prefix="/api/reports", tags=["reports"])


class ReportListItem(BaseModel):
    id: UUID
    kind: ReportKind
    title: str
    cost_usd: float
    created_at: datetime


class ReportRead(BaseModel):
    id: UUID
    kind: ReportKind
    title: str
    content: str
    cost_usd: float
    session_id: str | None
    steps: list[dict[str, Any]] | None
    created_at: datetime


@router.get("", response_model=list[ReportListItem])
async def list_reports(
    kind: ReportKind | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
) -> list[ReportListItem]:
    stmt = select(Report).order_by(Report.created_at.desc()).limit(limit)
    if kind is not None:
        stmt = (
            select(Report)
            .where(Report.kind == kind)
            .order_by(Report.created_at.desc())
            .limit(limit)
        )
    return [
        ReportListItem(
            id=r.id,
            kind=r.kind,
            title=r.title,
            cost_usd=r.cost_usd,
            created_at=r.created_at,
        )
        for r in session.exec(stmt).all()
    ]


@router.get("/{report_id}", response_model=ReportRead)
async def get_report(report_id: UUID, session: Session = Depends(get_session)) -> ReportRead:
    report = session.get(Report, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return ReportRead(
        id=report.id,
        kind=report.kind,
        title=report.title,
        content=report.content,
        cost_usd=report.cost_usd,
        session_id=report.session_id,
        steps=report.steps,
        created_at=report.created_at,
    )
