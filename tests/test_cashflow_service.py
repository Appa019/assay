from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlmodel import Session

from app.models.cashflow import CashflowKind, CashflowSource, CashflowWallet
from app.schemas.cashflow import CashflowCreate
from app.services import cashflow_service


def _entry(
    kind: CashflowKind = CashflowKind.EXPENSE,
    amount: str = "50.00",
    category: str = "mercado",
    occurred_on: date | None = None,
) -> CashflowCreate:
    return CashflowCreate(
        kind=kind,
        amount_brl=Decimal(amount),
        category=category,
        occurred_on=occurred_on,
        source=CashflowSource.BOT,
    )


def test_add_entry_normalizes_category_and_defaults_date(session: Session) -> None:
    entry = cashflow_service.add_entry(session, _entry(category="  Mercado "))
    assert entry.category == "mercado"
    assert entry.occurred_on == date.today()
    assert entry.source == CashflowSource.BOT


def test_add_entry_blank_category_falls_back_to_outros(session: Session) -> None:
    entry = cashflow_service.add_entry(session, _entry(category="   "))
    assert entry.category == "outros"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Saúde", "saude"),  # accent fold — the classifier used to emit these
        ("Salário", "salario"),
        ("educação", "educacao"),
        ("assinaturas", "assinatura"),  # alias: plural variant
        ("casa", "moradia"),  # alias: the classifier's old name for it
        ("freelance", "freela"),
        ("alimentação", "mercado"),
        ("categoria nova", "categoria nova"),  # free-form stays allowed
    ],
)
def test_normalize_category_folds_accents_and_aliases(raw: str, expected: str) -> None:
    """Regression: the consultant and the classifier carried DIVERGENT category
    vocabularies ("saúde" vs "saude"), splitting the monthly summary in two."""
    assert cashflow_service.normalize_category(raw) == expected


def test_same_category_from_both_doors_lands_in_one_bucket(session: Session) -> None:
    cashflow_service.add_entry(session, _entry(category="saúde", amount="100.00"))
    cashflow_service.add_entry(session, _entry(category="saude", amount="35.50"))
    summary = cashflow_service.month_summary(session)
    saude = [c for c in summary.by_category if c.category == "saude"]
    assert len(saude) == 1
    assert saude[0].count == 2
    assert saude[0].total_brl == 135.5


def test_list_entries_filters_by_month_and_kind(session: Session) -> None:
    cashflow_service.add_entry(session, _entry(occurred_on=date(2026, 7, 10)))
    cashflow_service.add_entry(
        session, _entry(kind=CashflowKind.INCOME, amount="1000", occurred_on=date(2026, 7, 31))
    )
    cashflow_service.add_entry(session, _entry(occurred_on=date(2026, 6, 30)))

    july = cashflow_service.list_entries(session, month="2026-07")
    assert len(july) == 2
    incomes = cashflow_service.list_entries(session, month="2026-07", kind=CashflowKind.INCOME)
    assert len(incomes) == 1
    assert incomes[0].kind == CashflowKind.INCOME


def test_list_entries_rejects_bad_month(session: Session) -> None:
    with pytest.raises(ValueError):
        cashflow_service.list_entries(session, month="2026-13")


def test_month_summary_totals_and_categories(session: Session) -> None:
    when = date(2026, 7, 15)
    cashflow_service.add_entry(session, _entry(amount="30", occurred_on=when))
    cashflow_service.add_entry(session, _entry(amount="20", occurred_on=when))
    cashflow_service.add_entry(
        session, _entry(amount="12.50", category="transporte", occurred_on=when)
    )
    cashflow_service.add_entry(
        session,
        _entry(kind=CashflowKind.INCOME, amount="1000", category="salario", occurred_on=when),
    )

    summ = cashflow_service.month_summary(session, "2026-07")
    assert summ.expense_brl == pytest.approx(62.50)
    assert summ.income_brl == pytest.approx(1000.0)
    assert summ.net_brl == pytest.approx(937.50)
    assert summ.entries == 4
    top = summ.by_category[0]
    assert (top.kind, top.category, top.total_brl) == (CashflowKind.INCOME, "salario", 1000.0)
    mercado = next(c for c in summ.by_category if c.category == "mercado")
    assert mercado.total_brl == pytest.approx(50.0)
    assert mercado.count == 2


def test_delete_entry_and_missing(session: Session) -> None:
    entry = cashflow_service.add_entry(session, _entry())
    cashflow_service.delete_entry(session, entry.id)
    assert cashflow_service.list_entries(session) == []
    with pytest.raises(cashflow_service.CashflowNotFoundError):
        cashflow_service.delete_entry(session, uuid4())


def test_identical_entry_within_the_window_is_not_duplicated(session: Session) -> None:
    """The consultant sometimes re-POSTs after missing the first response."""
    payload = CashflowCreate(
        kind=CashflowKind.EXPENSE,
        amount_brl=Decimal("48.00"),
        category="mercado",
        description="cupom do mercado",
    )
    first = cashflow_service.add_entry(session, payload)
    second = cashflow_service.add_entry(session, payload)

    assert second.id == first.id
    assert len(cashflow_service.list_entries(session)) == 1


def test_a_different_amount_still_creates_a_second_entry(session: Session) -> None:
    base = {"kind": CashflowKind.EXPENSE, "category": "mercado", "description": "pão"}
    cashflow_service.add_entry(session, CashflowCreate(amount_brl=Decimal("10.00"), **base))
    cashflow_service.add_entry(session, CashflowCreate(amount_brl=Decimal("11.00"), **base))

    assert len(cashflow_service.list_entries(session)) == 2


# --- wallets (conta / vr / va) ----------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("VR", CashflowWallet.VR),
        (" va ", CashflowWallet.VA),
        ("Vale Refeição", CashflowWallet.VR),
        ("vale-alimentacao", CashflowWallet.VA),
        ("pix", CashflowWallet.CONTA),
        ("Salário", CashflowWallet.CONTA),
        ("", CashflowWallet.CONTA),
        (None, CashflowWallet.CONTA),
        ("cartao", CashflowWallet.CONTA),  # no longer an alias: a card is a card, not a wallet
        ("cartao misterioso", CashflowWallet.CONTA),  # unknown degrades to conta
    ],
)
def test_normalize_wallet_folds_onto_closed_vocabulary(
    raw: str | None, expected: CashflowWallet
) -> None:
    """Wallets are a CLOSED vocabulary: a typo must degrade to "conta" (the
    pre-wallet behaviour), never mint a fourth balance."""
    assert cashflow_service.normalize_wallet(raw) == expected


def test_add_entry_stores_normalized_wallet(session: Session) -> None:
    entry = cashflow_service.add_entry(
        session,
        CashflowCreate(
            kind=CashflowKind.EXPENSE,
            amount_brl=Decimal("35.00"),
            category="restaurante",
            wallet="Vale Refeição",
        ),
    )
    assert entry.wallet == CashflowWallet.VR


def test_same_line_on_a_different_wallet_is_not_a_duplicate(session: Session) -> None:
    """Lunch on the VR and an identical pix expense minutes apart are two
    different movements — the dedupe window must see the wallet."""
    base = {
        "kind": CashflowKind.EXPENSE,
        "amount_brl": Decimal("42.00"),
        "category": "mercado",
        "description": "feira",
    }
    first = cashflow_service.add_entry(session, CashflowCreate(wallet="va", **base))
    second = cashflow_service.add_entry(session, CashflowCreate(wallet="conta", **base))
    assert first.id != second.id
    assert len(cashflow_service.list_entries(session)) == 2


def test_list_entries_filters_by_wallet(session: Session) -> None:
    cashflow_service.add_entry(session, _entry(amount="10"))
    vr = cashflow_service.add_entry(
        session,
        CashflowCreate(
            kind=CashflowKind.EXPENSE,
            amount_brl=Decimal("35.00"),
            category="restaurante",
            wallet="vr",
        ),
    )
    only_vr = cashflow_service.list_entries(session, wallet=CashflowWallet.VR)
    assert [e.id for e in only_vr] == [vr.id]


def test_month_summary_breaks_down_by_wallet(session: Session) -> None:
    """Salary + VR credit + VR lunch: totals keep counting everything, but
    by_wallet must expose the investable (conta) slice on its own."""
    when = date(2026, 7, 15)
    cashflow_service.add_entry(
        session,
        CashflowCreate(
            kind=CashflowKind.INCOME,
            amount_brl=Decimal("8400"),
            category="salario",
            occurred_on=when,
        ),
    )
    cashflow_service.add_entry(
        session,
        CashflowCreate(
            kind=CashflowKind.INCOME,
            amount_brl=Decimal("700"),
            category="salario",
            occurred_on=when,
            wallet="vr",
        ),
    )
    cashflow_service.add_entry(
        session,
        CashflowCreate(
            kind=CashflowKind.EXPENSE,
            amount_brl=Decimal("35"),
            category="restaurante",
            occurred_on=when,
            wallet="vr",
        ),
    )

    summ = cashflow_service.month_summary(session, "2026-07")
    assert summ.income_brl == pytest.approx(9100.0)
    by = {w.wallet: w for w in summ.by_wallet}
    assert by[CashflowWallet.CONTA].net_brl == pytest.approx(8400.0)
    assert by[CashflowWallet.VR].income_brl == pytest.approx(700.0)
    assert by[CashflowWallet.VR].expense_brl == pytest.approx(35.0)
    assert by[CashflowWallet.VR].net_brl == pytest.approx(665.0)
    # Fixed conta → vr → va order, so prompts and UIs render deterministically.
    assert [w.wallet for w in summ.by_wallet] == [CashflowWallet.CONTA, CashflowWallet.VR]


def test_wallet_balances_accumulate_across_months(session: Session) -> None:
    """ "Quanto ainda tenho de VR?" spans months — benefit credit rolls over."""
    cashflow_service.add_entry(
        session,
        CashflowCreate(
            kind=CashflowKind.INCOME,
            amount_brl=Decimal("700"),
            category="salario",
            occurred_on=date(2026, 6, 1),
            wallet="vr",
        ),
    )
    cashflow_service.add_entry(
        session,
        CashflowCreate(
            kind=CashflowKind.EXPENSE,
            amount_brl=Decimal("200"),
            category="restaurante",
            occurred_on=date(2026, 7, 10),
            wallet="vr",
        ),
    )

    balances = cashflow_service.wallet_balances(session)
    assert [b.wallet for b in balances] == [CashflowWallet.VR]
    assert balances[0].balance_brl == pytest.approx(500.0)
    assert balances[0].entries == 2


# --- credit card on an entry ----------------------------------------------------

from uuid import UUID  # noqa: E402

from app.schemas.card import CardCreate  # noqa: E402
from app.services import card_service  # noqa: E402


def _nubank(session: Session, closing: int = 25, due: int = 3):  # noqa: ANN202
    return card_service.create_card(
        session, CardCreate(name="Nubank", closing_day=closing, due_day=due)
    )


def test_expense_from_conta_lands_on_the_default_card(session: Session) -> None:
    card = _nubank(session)
    entry = cashflow_service.add_entry(session, _entry())
    assert entry.card_id == card.id
    assert entry.wallet == CashflowWallet.CONTA  # the money still leaves the account
    assert entry.installment_no is None and entry.installment_group is None


def test_explicit_pix_stays_off_the_card(session: Session) -> None:
    _nubank(session)
    entry = cashflow_service.add_entry(
        session, CashflowCreate(kind=CashflowKind.EXPENSE, amount_brl=Decimal("10"), card="pix")
    )
    assert entry.card_id is None


def test_benefit_and_income_never_get_a_card(session: Session) -> None:
    _nubank(session)
    vr = cashflow_service.add_entry(
        session, CashflowCreate(kind=CashflowKind.EXPENSE, amount_brl=Decimal("35"), wallet="vr")
    )
    salary = cashflow_service.add_entry(
        session, CashflowCreate(kind=CashflowKind.INCOME, amount_brl=Decimal("8400"))
    )
    assert vr.card_id is None and salary.card_id is None


def test_unknown_card_name_is_refused(session: Session) -> None:
    _nubank(session)
    with pytest.raises(card_service.UnknownCardError):
        cashflow_service.add_entry(
            session,
            CashflowCreate(kind=CashflowKind.EXPENSE, amount_brl=Decimal("10"), card="itau"),
        )


def test_summary_reports_card_spend_separately(session: Session) -> None:
    _nubank(session)
    on = date(2026, 9, 10)
    cashflow_service.add_entry(session, _entry(amount="100.00", occurred_on=on))
    cashflow_service.add_entry(
        session,
        CashflowCreate(
            kind=CashflowKind.EXPENSE, amount_brl=Decimal("40"), card="pix", occurred_on=on
        ),
    )
    summary = cashflow_service.month_summary(session, "2026-09")
    assert summary.expense_brl == 140.0
    assert summary.card_expense_brl == 100.0


def test_list_entries_filters_by_card(session: Session) -> None:
    card = _nubank(session)
    cashflow_service.add_entry(session, _entry(amount="100.00"))
    cashflow_service.add_entry(
        session, CashflowCreate(kind=CashflowKind.EXPENSE, amount_brl=Decimal("40"), card="pix")
    )
    assert len(cashflow_service.list_entries(session, card_id=card.id)) == 1
    assert len(cashflow_service.list_entries(session, card_id=UUID(int=0))) == 0
