import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.database import get_session
from app.models.cashflow import CashflowEntry, CashflowKind, CashflowWallet
from app.schemas.cashflow import (
    CashflowCreate,
    CashflowRead,
    CashflowSummary,
    MonthTotals,
    WalletBalance,
)
from app.services import card_service, cashflow_service, classifier_service

router = APIRouter(prefix="/api/cashflow", tags=["cashflow"])

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _validate_month(month: str | None) -> None:
    if month is not None and not _MONTH_RE.match(month):
        raise HTTPException(status_code=422, detail="Mês deve estar no formato YYYY-MM")


class CashflowClassify(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)


def _reads(session: Session, entries: list[CashflowEntry]) -> list[CashflowRead]:
    """CashflowRead rows with the card name attached — ONE card lookup for
    the whole page instead of a query per row."""
    names = {card.id: card.name for card in card_service.list_cards(session)}
    out: list[CashflowRead] = []
    for entry in entries:
        read = CashflowRead.model_validate(entry, from_attributes=True)
        read.card_name = names.get(entry.card_id) if entry.card_id is not None else None
        out.append(read)
    return out


class GroupDeleted(BaseModel):
    deleted: int


@router.post("", response_model=CashflowRead, status_code=status.HTTP_201_CREATED)
async def create_entry(
    data: CashflowCreate, session: Session = Depends(get_session)
) -> CashflowRead:
    """Register one expense or income line. A purchase in N installments
    creates N rows and returns the first; `card` unknown or misused → 422."""
    try:
        entry = cashflow_service.add_entry(session, data)
    except (card_service.UnknownCardError, card_service.CardRuleError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _reads(session, [entry])[0]


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
    card_id: UUID | None = None,
    limit: int = 100,
    session: Session = Depends(get_session),
) -> list[CashflowRead]:
    _validate_month(month)
    entries = cashflow_service.list_entries(
        session,
        month=month,
        kind=kind,
        wallet=wallet,
        card_id=card_id,
        limit=max(1, min(limit, 1000)),
    )
    return _reads(session, entries)


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


@router.delete("/groups/{group_id}", response_model=GroupDeleted)
async def delete_group(group_id: UUID, session: Session = Depends(get_session)) -> GroupDeleted:
    """Delete a whole installment purchase (every monthly row of the group)."""
    try:
        return GroupDeleted(deleted=cashflow_service.delete_group(session, group_id))
    except cashflow_service.CashflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{entry_id}", response_model=CashflowRead)
async def delete_entry(entry_id: UUID, session: Session = Depends(get_session)) -> CashflowRead:
    try:
        entry = cashflow_service.delete_entry(session, entry_id)
    except cashflow_service.CashflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _reads(session, [entry])[0]
