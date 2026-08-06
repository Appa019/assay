import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.database import get_session
from app.models.cashflow import CashflowKind, CashflowWallet
from app.schemas.cashflow import (
    CashflowCreate,
    CashflowRead,
    CashflowSummary,
    MonthTotals,
    WalletBalance,
)
from app.services import cashflow_service, classifier_service

router = APIRouter(prefix="/api/cashflow", tags=["cashflow"])

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _validate_month(month: str | None) -> None:
    if month is not None and not _MONTH_RE.match(month):
        raise HTTPException(status_code=422, detail="Mês deve estar no formato YYYY-MM")


class CashflowClassify(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)


@router.post("", response_model=CashflowRead, status_code=status.HTTP_201_CREATED)
async def create_entry(
    data: CashflowCreate, session: Session = Depends(get_session)
) -> CashflowRead:
    """Register one expense or income line in the personal ledger."""
    entry = cashflow_service.add_entry(session, data)
    return CashflowRead.model_validate(entry, from_attributes=True)


@router.post("/classify", response_model=CashflowCreate)
def classify_entry(payload: CashflowClassify) -> CashflowCreate:
    """Parse free text into a DRAFT entry. Writes nothing.

    Returning a draft rather than saving keeps a misread sentence out of the
    ledger: the client shows what the model understood and the user confirms.

    Deliberately sync (no ``async``): the classifier blocks on a subprocess for
    up to 90s, and a sync route runs on the threadpool — an async one would
    freeze the whole event loop (chat polling included) for the duration.
    """
    try:
        return classifier_service.classify(payload.text)
    except classifier_service.ClassificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("", response_model=list[CashflowRead])
async def list_entries(
    month: str | None = None,
    kind: CashflowKind | None = None,
    wallet: CashflowWallet | None = None,
    limit: int = 100,
    session: Session = Depends(get_session),
) -> list[CashflowRead]:
    _validate_month(month)
    entries = cashflow_service.list_entries(
        session, month=month, kind=kind, wallet=wallet, limit=max(1, min(limit, 1000))
    )
    return [CashflowRead.model_validate(e, from_attributes=True) for e in entries]


@router.get("/summary", response_model=CashflowSummary)
async def summary(
    month: str | None = None, session: Session = Depends(get_session)
) -> CashflowSummary:
    """Monthly totals (income, expense, net) grouped by category."""
    _validate_month(month)
    return cashflow_service.month_summary(session, month)


@router.get("/wallets", response_model=list[WalletBalance])
async def wallets(session: Session = Depends(get_session)) -> list[WalletBalance]:
    """All-time balance per wallet — how much VR/VA credit is still unspent."""
    return cashflow_service.wallet_balances(session)


@router.get("/history", response_model=list[MonthTotals])
async def history(months: int = 6, session: Session = Depends(get_session)) -> list[MonthTotals]:
    """Totals per month, oldest first — the trend behind the current month."""
    return cashflow_service.month_history(session, months)


@router.delete("/{entry_id}", response_model=CashflowRead)
async def delete_entry(entry_id: UUID, session: Session = Depends(get_session)) -> CashflowRead:
    try:
        entry = cashflow_service.delete_entry(session, entry_id)
    except cashflow_service.CashflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CashflowRead.model_validate(entry, from_attributes=True)
