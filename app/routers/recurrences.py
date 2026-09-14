from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.core.database import get_session
from app.models.recurrence import Recurrence
from app.schemas.recurrence import RecurrenceCreate, RecurrenceRead, RecurrenceUpdate
from app.services import card_service, recurrence_service

router = APIRouter(prefix="/api/recurrences", tags=["recurrences"])


def _reads(session: Session, rows: list[Recurrence]) -> list[RecurrenceRead]:
    """RecurrenceRead rows with the card name attached — one card lookup for
    the whole list instead of a query per row."""
    names = {card.id: card.name for card in card_service.list_cards(session)}
    out: list[RecurrenceRead] = []
    for row in rows:
        read = RecurrenceRead.model_validate(row, from_attributes=True)
        read.card_name = names.get(row.card_id) if row.card_id is not None else None
        out.append(read)
    return out


@router.get("", response_model=list[RecurrenceRead])
async def list_recurrences(
    active_only: bool = False, session: Session = Depends(get_session)
) -> list[RecurrenceRead]:
    """Every monthly commitment. `active_only=true` hides the cancelled ones."""
    return _reads(session, recurrence_service.list_all(session, active_only=active_only))


@router.post("", response_model=RecurrenceRead, status_code=status.HTTP_201_CREATED)
async def create_recurrence(
    data: RecurrenceCreate, session: Session = Depends(get_session)
) -> RecurrenceRead:
    """Register a monthly commitment (salary, rent, subscription, financing).

    A blank `card` means off-card; name one to attach it. `card` unknown or
    misused → 422.
    """
    try:
        recurrence = recurrence_service.create(session, data)
    except (card_service.UnknownCardError, card_service.CardRuleError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _reads(session, [recurrence])[0]


@router.patch("/{recurrence_id}", response_model=RecurrenceRead)
async def update_recurrence(
    recurrence_id: UUID, data: RecurrenceUpdate, session: Session = Depends(get_session)
) -> RecurrenceRead:
    """Change an amount, a day or an end date. Omitted fields stay put;
    `ends_on: null` reopens a commitment that had an end date."""
    try:
        recurrence = recurrence_service.update(session, recurrence_id, data)
    except recurrence_service.RecurrenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (card_service.UnknownCardError, card_service.CardRuleError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _reads(session, [recurrence])[0]


@router.delete("/{recurrence_id}", response_model=RecurrenceRead)
async def delete_recurrence(
    recurrence_id: UUID, session: Session = Depends(get_session)
) -> RecurrenceRead:
    """Drop a commitment for good. To keep the history, PATCH `active: false`."""
    try:
        recurrence = recurrence_service.get(session, recurrence_id)
    except recurrence_service.RecurrenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    snapshot = _reads(session, [recurrence])[0]
    recurrence_service.delete(session, recurrence_id)
    return snapshot
