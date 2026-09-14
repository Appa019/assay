from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlmodel import Session

from app.models.cashflow import CashflowKind
from app.schemas.card import CardCreate
from app.schemas.recurrence import RecurrenceCreate, RecurrenceUpdate
from app.services import card_service, recurrence_service


def _rent(day: int = 10, **over: object) -> RecurrenceCreate:
    payload: dict[str, object] = {
        "kind": CashflowKind.EXPENSE,
        "amount_brl": Decimal("2200.00"),
        "category": "  Moradia ",
        "description": "aluguel",
        "day_of_month": day,
        "starts_on": date(2026, 1, 1),
    }
    payload.update(over)
    return RecurrenceCreate(**payload)  # type: ignore[arg-type]


def test_create_normalizes_category_and_defaults(session: Session) -> None:
    rec = recurrence_service.create(session, _rent())
    assert rec.category == "moradia"
    assert rec.active is True
    assert rec.ends_on is None
    assert rec.card_id is None


def test_create_defaults_start_to_the_first_of_the_month(session: Session) -> None:
    # Registering on the 13th a rent due on the 10th must still count THIS
    # month — a default of today would drop it and open the forecast broken.
    rec = recurrence_service.create(session, _rent(starts_on=None))
    assert rec.starts_on == date.today().replace(day=1)


def test_income_never_lands_on_a_card(session: Session) -> None:
    card_service.create_card(session, CardCreate(name="Nubank", closing_day=25, due_day=5))
    rec = recurrence_service.create(
        session,
        _rent(kind=CashflowKind.INCOME, category="salario", amount_brl=Decimal("8000")),
    )
    assert rec.card_id is None


def test_expense_defaults_to_the_default_card(session: Session) -> None:
    card = card_service.create_card(session, CardCreate(name="Nubank", closing_day=25, due_day=5))
    rec = recurrence_service.create(session, _rent(category="assinatura", card="auto"))
    assert rec.card_id == card.id


def test_unknown_card_raises(session: Session) -> None:
    with pytest.raises(card_service.UnknownCardError):
        recurrence_service.create(session, _rent(card="Itau"))


def test_update_changes_value_and_end(session: Session) -> None:
    rec = recurrence_service.create(session, _rent())
    updated = recurrence_service.update(
        session,
        rec.id,
        RecurrenceUpdate(amount_brl=Decimal("2400.00"), ends_on=date(2026, 12, 31)),
    )
    assert float(updated.amount_brl) == 2400.0
    assert updated.ends_on == date(2026, 12, 31)
    assert updated.description == "aluguel"  # untouched fields survive


def test_update_can_deactivate_without_deleting(session: Session) -> None:
    rec = recurrence_service.create(session, _rent())
    assert (
        recurrence_service.update(session, rec.id, RecurrenceUpdate(active=False)).active is False
    )
    assert recurrence_service.list_all(session, active_only=True) == []
    assert len(recurrence_service.list_all(session)) == 1


def test_delete_and_missing_id(session: Session) -> None:
    rec = recurrence_service.create(session, _rent())
    assert recurrence_service.delete(session, rec.id).id == rec.id
    with pytest.raises(recurrence_service.RecurrenceNotFoundError):
        recurrence_service.delete(session, rec.id)
    with pytest.raises(recurrence_service.RecurrenceNotFoundError):
        recurrence_service.get(session, uuid4())


def test_occurrence_clamps_to_a_short_month(session: Session) -> None:
    rec = recurrence_service.create(session, _rent(day=31))
    assert recurrence_service.occurrence_on(rec, 2026, 2) == date(2026, 2, 28)
    assert recurrence_service.occurrence_on(rec, 2026, 3) == date(2026, 3, 31)
    assert recurrence_service.occurrence_on(rec, 2028, 2) == date(2028, 2, 29)


def test_occurrences_respect_start_end_and_active(session: Session) -> None:
    recurrence_service.create(session, _rent(starts_on=date(2026, 3, 15)))
    hits = recurrence_service.occurrences_in_month(session, 2026, 3)
    assert hits == []  # day 10 is before the 15th it started

    assert len(recurrence_service.occurrences_in_month(session, 2026, 4)) == 1

    ended = recurrence_service.create(
        session, _rent(day=5, category="lazer", ends_on=date(2026, 4, 30))
    )
    assert len(recurrence_service.occurrences_in_month(session, 2026, 4)) == 2
    assert len(recurrence_service.occurrences_in_month(session, 2026, 5)) == 1

    recurrence_service.update(session, ended.id, RecurrenceUpdate(ends_on=None, active=False))
    assert len(recurrence_service.occurrences_in_month(session, 2026, 5)) == 1
