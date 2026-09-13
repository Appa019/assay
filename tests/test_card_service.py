"""Credit cards: the single-default rule and how a ledger entry resolves to a
card (auto / explicit off-card / by name)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlmodel import Session

from app.models.cashflow import CashflowEntry, CashflowKind, CashflowWallet
from app.schemas.card import CardCreate, CardUpdate
from app.services import card_service


def _card(
    name: str = "Nubank", closing: int = 25, due: int = 3, default: bool = False
) -> CardCreate:
    return CardCreate(name=name, closing_day=closing, due_day=due, is_default=default)


# --- CRUD + default ------------------------------------------------------------


def test_first_card_becomes_default_even_if_not_asked(session: Session) -> None:
    card = card_service.create_card(session, _card(default=False))
    assert card.is_default is True


def test_second_default_demotes_the_first(session: Session) -> None:
    first = card_service.create_card(session, _card("Nubank"))
    second = card_service.create_card(session, _card("Itaú", default=True))
    session.refresh(first)
    assert first.is_default is False
    assert second.is_default is True
    assert card_service.default_card(session).id == second.id


def test_duplicate_name_is_rejected_after_fold(session: Session) -> None:
    card_service.create_card(session, _card("Itaú"))
    with pytest.raises(card_service.CardNameTakenError):
        card_service.create_card(session, _card("  itau "))


def test_update_promotes_and_refuses_to_unset_the_only_default(session: Session) -> None:
    first = card_service.create_card(session, _card("Nubank"))
    second = card_service.create_card(session, _card("Itaú"))
    card_service.update_card(session, second.id, CardUpdate(is_default=True))
    session.refresh(first)
    assert first.is_default is False
    with pytest.raises(card_service.CardRuleError):
        card_service.update_card(session, second.id, CardUpdate(is_default=False))


def test_update_changes_days_and_name(session: Session) -> None:
    card = card_service.create_card(session, _card())
    updated = card_service.update_card(
        session, card.id, CardUpdate(name="Nu", closing_day=10, due_day=17)
    )
    assert (updated.name, updated.closing_day, updated.due_day) == ("Nu", 10, 17)


def test_delete_refuses_a_card_with_entries(session: Session) -> None:
    card = card_service.create_card(session, _card())
    session.add(
        CashflowEntry(
            kind=CashflowKind.EXPENSE,
            amount_brl=Decimal("10"),
            occurred_on=date(2026, 9, 1),
            card_id=card.id,
        )
    )
    session.commit()
    with pytest.raises(card_service.CardInUseError):
        card_service.delete_card(session, card.id)


def test_delete_default_promotes_the_oldest_remaining(session: Session) -> None:
    first = card_service.create_card(session, _card("Nubank"))
    second = card_service.create_card(session, _card("Itaú"))
    third = card_service.create_card(session, _card("XP"))
    card_service.delete_card(session, first.id)
    session.refresh(second)
    session.refresh(third)
    assert second.is_default is True
    assert third.is_default is False


def test_get_unknown_card_raises(session: Session) -> None:
    from uuid import uuid4

    with pytest.raises(card_service.CardNotFoundError):
        card_service.get_card(session, uuid4())


# --- resolve_card ----------------------------------------------------------------


def test_resolve_auto_uses_default_for_expense_from_conta(session: Session) -> None:
    card = card_service.create_card(session, _card())
    resolved = card_service.resolve_card(
        session, None, kind=CashflowKind.EXPENSE, wallet=CashflowWallet.CONTA
    )
    assert resolved is not None and resolved.id == card.id


@pytest.mark.parametrize("raw", [None, "", "auto"])
def test_resolve_auto_without_cards_is_none(session: Session, raw: str | None) -> None:
    assert (
        card_service.resolve_card(
            session, raw, kind=CashflowKind.EXPENSE, wallet=CashflowWallet.CONTA
        )
        is None
    )


@pytest.mark.parametrize(
    ("kind", "wallet"),
    [
        (CashflowKind.INCOME, CashflowWallet.CONTA),
        (CashflowKind.EXPENSE, CashflowWallet.VR),
        (CashflowKind.EXPENSE, CashflowWallet.VA),
    ],
)
def test_resolve_auto_never_puts_income_or_benefit_on_a_card(
    session: Session, kind: CashflowKind, wallet: CashflowWallet
) -> None:
    card_service.create_card(session, _card())
    assert card_service.resolve_card(session, None, kind=kind, wallet=wallet) is None


@pytest.mark.parametrize("raw", ["none", "nenhum", "PIX", "débito", "dinheiro", "conta"])
def test_resolve_explicit_off_card_words(session: Session, raw: str) -> None:
    card_service.create_card(session, _card())
    assert (
        card_service.resolve_card(
            session, raw, kind=CashflowKind.EXPENSE, wallet=CashflowWallet.CONTA
        )
        is None
    )


def test_resolve_by_name_folds_case_and_accents(session: Session) -> None:
    card_service.create_card(session, _card("Nubank"))
    itau = card_service.create_card(session, _card("Itaú"))
    resolved = card_service.resolve_card(
        session, "ITAU", kind=CashflowKind.EXPENSE, wallet=CashflowWallet.CONTA
    )
    assert resolved is not None and resolved.id == itau.id


def test_resolve_unknown_name_raises_instead_of_falling_back(session: Session) -> None:
    card_service.create_card(session, _card())
    with pytest.raises(card_service.UnknownCardError):
        card_service.resolve_card(
            session, "bradesco", kind=CashflowKind.EXPENSE, wallet=CashflowWallet.CONTA
        )


def test_resolve_named_card_on_income_or_benefit_is_a_rule_error(session: Session) -> None:
    card_service.create_card(session, _card())
    with pytest.raises(card_service.CardRuleError):
        card_service.resolve_card(
            session, "nubank", kind=CashflowKind.INCOME, wallet=CashflowWallet.CONTA
        )
    with pytest.raises(card_service.CardRuleError):
        card_service.resolve_card(
            session, "nubank", kind=CashflowKind.EXPENSE, wallet=CashflowWallet.VR
        )
