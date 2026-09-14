"""Monthly commitments — salary, rent, a subscription, a financing.

Configuration, not ledger. Nothing here writes a ``CashflowEntry``: the
forecast reads these rows and projects them, so editing an amount corrects
every month at once (and the ``/extrato`` keeps showing only money that
actually moved). Registered exclusively by the consultant over chat.
"""

from calendar import monthrange
from datetime import date
from uuid import UUID

import structlog
from sqlmodel import Session, col, select

from app.models.cashflow import CashflowKind, CashflowWallet
from app.models.recurrence import Recurrence
from app.schemas.recurrence import RecurrenceCreate, RecurrenceUpdate
from app.services import card_service
from app.services.cashflow_service import normalize_category, normalize_wallet

logger = structlog.get_logger()


class RecurrenceNotFoundError(LookupError):
    """No recurrence with that id."""


def _resolve_card(
    raw: str | None, session: Session, *, kind: CashflowKind, wallet: CashflowWallet
) -> UUID | None:
    """Which card a recurrence sits on.

    Unlike a one-off purchase, a blank ``card`` here means OFF card rather
    than "the default card": a monthly commitment is typically a boleto or a
    pix, and the client is stating a stable fact the consultant can be
    explicit about ("assinatura no Nubank"). Naming a card still goes through
    ``card_service.resolve_card``, the single source of name resolution.
    """
    if raw is None or not raw.strip():
        return None
    card = card_service.resolve_card(session, raw, kind=kind, wallet=wallet)
    return card.id if card is not None else None


def create(session: Session, data: RecurrenceCreate) -> Recurrence:
    """Register a commitment.

    ``starts_on`` defaults to the FIRST day of the current month, not today:
    someone registering the rent on the 13th means "this is my rent", and a
    default of today would silently drop the current month for every
    commitment whose day has already passed — the forecast would open with a
    broken first column. Double counting is not the risk it looks like: a rent
    already in the ledger settles the commitment through the matching rule.
    """
    wallet = normalize_wallet(data.wallet)
    recurrence = Recurrence(
        kind=data.kind,
        amount_brl=data.amount_brl,
        category=normalize_category(data.category),
        description=(data.description or "").strip() or None,
        day_of_month=data.day_of_month,
        wallet=wallet,
        card_id=_resolve_card(data.card, session, kind=data.kind, wallet=wallet),
        starts_on=data.starts_on or date.today().replace(day=1),
        ends_on=data.ends_on,
    )
    session.add(recurrence)
    session.commit()
    session.refresh(recurrence)
    logger.info(
        "recurrence_created",
        kind=str(recurrence.kind),
        category=recurrence.category,
        amount=float(recurrence.amount_brl),
        day=recurrence.day_of_month,
    )
    return recurrence


def get(session: Session, recurrence_id: UUID) -> Recurrence:
    recurrence = session.get(Recurrence, recurrence_id)
    if recurrence is None:
        raise RecurrenceNotFoundError(f"Recorrência {recurrence_id} não encontrada")
    return recurrence


def list_all(session: Session, *, active_only: bool = False) -> list[Recurrence]:
    stmt = select(Recurrence)
    if active_only:
        stmt = stmt.where(col(Recurrence.active).is_(True))
    stmt = stmt.order_by(Recurrence.kind, Recurrence.day_of_month, Recurrence.created_at)
    return list(session.exec(stmt).all())


def update(session: Session, recurrence_id: UUID, data: RecurrenceUpdate) -> Recurrence:
    recurrence = get(session, recurrence_id)
    fields = data.model_dump(exclude_unset=True)

    if "wallet" in fields and fields["wallet"] is not None:
        recurrence.wallet = normalize_wallet(fields["wallet"])
    if "category" in fields and fields["category"] is not None:
        recurrence.category = normalize_category(fields["category"])
    if "description" in fields:
        recurrence.description = (fields["description"] or "").strip() or None
    for name in ("amount_brl", "day_of_month", "starts_on", "active"):
        if name in fields and fields[name] is not None:
            setattr(recurrence, name, fields[name])
    # ends_on is the one field whose explicit null is meaningful: it reopens a
    # commitment that had been given an end date.
    if "ends_on" in fields:
        recurrence.ends_on = fields["ends_on"]
    if "card" in fields:
        recurrence.card_id = _resolve_card(
            fields["card"], session, kind=recurrence.kind, wallet=recurrence.wallet
        )

    session.add(recurrence)
    session.commit()
    session.refresh(recurrence)
    return recurrence


def delete(session: Session, recurrence_id: UUID) -> Recurrence:
    recurrence = get(session, recurrence_id)
    session.delete(recurrence)
    session.commit()
    return recurrence


def occurrence_on(recurrence: Recurrence, year: int, month: int) -> date:
    """The day this commitment falls in (year, month), clamped to the month's
    length — day 31 lands on the 28th, 29th or 30th, never spills over."""
    return date(year, month, min(recurrence.day_of_month, monthrange(year, month)[1]))


def occurrences_in_month(session: Session, year: int, month: int) -> list[tuple[Recurrence, date]]:
    """Every active commitment falling in (year, month), earliest day first.

    A commitment is in the month when its (clamped) day sits inside the
    ``starts_on``/``ends_on`` window — that is what makes a financing stop
    weighing on the forecast the month after its last payment.
    """
    hits: list[tuple[Recurrence, date]] = []
    for recurrence in list_all(session, active_only=True):
        day = occurrence_on(recurrence, year, month)
        if day < recurrence.starts_on:
            continue
        if recurrence.ends_on is not None and day > recurrence.ends_on:
            continue
        hits.append((recurrence, day))
    return sorted(hits, key=lambda pair: (pair[1], pair[0].created_at))
