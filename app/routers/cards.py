from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.card import CardCreate, CardRead, CardUpdate, InvoiceRead
from app.services import card_service

router = APIRouter(prefix="/api/cards", tags=["cards"])


def _read(session: Session, card_id: UUID) -> CardRead:
    """One card's CardRead. Summaries are computed for every card (a handful,
    two queries each), so pick this one out of the list."""
    for item in card_service.card_summaries(session):
        if item.id == card_id:
            return item
    raise HTTPException(status_code=404, detail="Cartão não encontrado")


@router.get("", response_model=list[CardRead])
async def list_cards(session: Session = Depends(get_session)) -> list[CardRead]:
    """Every card with its open invoice and the last closed one (computed)."""
    return card_service.card_summaries(session)


@router.post("", response_model=CardRead, status_code=status.HTTP_201_CREATED)
async def create_card(data: CardCreate, session: Session = Depends(get_session)) -> CardRead:
    """Register a card. The first one becomes the default automatically."""
    try:
        card = card_service.create_card(session, data)
    except card_service.CardNameTakenError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _read(session, card.id)


@router.patch("/{card_id}", response_model=CardRead)
async def update_card(
    card_id: UUID, data: CardUpdate, session: Session = Depends(get_session)
) -> CardRead:
    try:
        card = card_service.update_card(session, card_id, data)
    except card_service.CardNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except card_service.CardNameTakenError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except card_service.CardRuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _read(session, card.id)


@router.delete("/{card_id}", response_model=CardRead)
async def delete_card(card_id: UUID, session: Session = Depends(get_session)) -> CardRead:
    """Remove a card nothing references. 409 while ledger rows still point at it."""
    snapshot = _read(session, card_id)  # 404 before touching anything
    try:
        card_service.delete_card(session, card_id)
    except card_service.CardInUseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return snapshot


@router.get("/{card_id}/invoices", response_model=list[InvoiceRead])
async def list_invoices(
    card_id: UUID, months: int = 6, session: Session = Depends(get_session)
) -> list[InvoiceRead]:
    """Invoice history, oldest first, ending on the open one (1–24 months)."""
    try:
        card = card_service.get_card(session, card_id)
    except card_service.CardNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return card_service.invoices(session, card, months=max(1, min(months, 24)))
