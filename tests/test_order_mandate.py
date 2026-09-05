"""The mandate has exactly one fixed-income instrument, enforced at ingest.

Until 2026-09-05 this rule existed only as prompt text, and the first sheet the
committee ever produced broke it: four different CDBs, two of them TERM papers
locking the money for about two years. Prompt instructions drift; ingest does
not.
"""

from decimal import Decimal

from sqlmodel import Session, select

from app.models.asset import AssetClass
from app.models.contribution import Contribution, ContributionStatus
from app.models.order import Order
from app.services import order_service


def _contribution(session: Session, summary: str) -> Contribution:
    contribution = Contribution(
        amount_brl=Decimal("20000"),
        status=ContributionStatus.COMPLETED,
        final_summary=summary,
    )
    session.add(contribution)
    session.commit()
    session.refresh(contribution)
    return contribution


def _sheet(rows: str) -> str:
    return f'Folha final.\n\n```json\n{{"orders": [{rows}]}}\n```'


def test_the_august_sheet_collapses_to_one_cdb(session: Session) -> None:
    """The real regression: four issuers, two of them term paper, one aporte."""
    contribution = _contribution(
        session,
        _sheet(
            '{"ticker": "CDB SOFISA 105% CDI", "classe": "renda_fixa", "valor_brl": 3000},'
            '{"ticker": "CDB ITAU 100% CDI", "classe": "renda_fixa", "valor_brl": 2000},'
            '{"ticker": "CDB DAYCOVAL 113% CDI 2A", "classe": "renda_fixa", "valor_brl": 2500},'
            '{"ticker": "CDB BTG 112% CDI 2A", "classe": "renda_fixa", "valor_brl": 1557.75}'
        ),
    )
    created = order_service.ingest_contribution_orders(session, contribution)

    assert len(created) == 1
    assert created[0].ticker == order_service.CANONICAL_CDB_TICKER
    # Nothing is lost: the four amounts are summed into the single instrument.
    assert created[0].amount_brl == Decimal("9057.75")


def test_a_single_off_mandate_cdb_is_renamed(session: Session) -> None:
    contribution = _contribution(
        session,
        _sheet('{"ticker": "CDB NUBANK 102% CDI", "classe": "renda_fixa", "valor_brl": 5000}'),
    )
    created = order_service.ingest_contribution_orders(session, contribution)
    assert [o.ticker for o in created] == [order_service.CANONICAL_CDB_TICKER]
    assert created[0].amount_brl == Decimal("5000")


def test_fixed_income_carries_no_target_or_stop(session: Session) -> None:
    """A daily-liquidity CDB has no price to target or stop out of; keeping the
    committee's numbers would arm a meaningless alert."""
    contribution = _contribution(
        session,
        _sheet(
            '{"ticker": "CDB X", "classe": "renda_fixa", "valor_brl": 5000,'
            ' "preco_alvo": 1.05, "stop": 0.98}'
        ),
    )
    created = order_service.ingest_contribution_orders(session, contribution)
    assert created[0].target_price is None
    assert created[0].stop_price is None


def test_percentages_of_merged_lines_are_summed(session: Session) -> None:
    contribution = _contribution(
        session,
        _sheet(
            '{"ticker": "CDB A", "classe": "renda_fixa", "valor_brl": 3000, "pct": 15},'
            '{"ticker": "CDB B", "classe": "renda_fixa", "valor_brl": 2000, "pct": 10}'
        ),
    )
    created = order_service.ingest_contribution_orders(session, contribution)
    assert created[0].pct_of_contribution == 25.0


def test_stocks_and_crypto_are_untouched(session: Session) -> None:
    """The rule is about fixed income only — nothing else gets rewritten or
    merged, including two lines of the same class."""
    contribution = _contribution(
        session,
        _sheet(
            '{"ticker": "PETR4", "classe": "acoes_b3", "valor_brl": 3000,'
            ' "preco_alvo": 40.0, "stop": 33.0},'
            '{"ticker": "VALE3", "classe": "acoes_b3", "valor_brl": 2000},'
            '{"ticker": "BTC", "classe": "crypto", "valor_brl": 1600},'
            '{"ticker": "ETH", "classe": "crypto", "valor_brl": 990}'
        ),
    )
    created = order_service.ingest_contribution_orders(session, contribution)
    assert [o.ticker for o in created] == ["PETR4", "VALE3", "BTC", "ETH"]
    assert created[0].target_price == Decimal("40.0")
    assert created[0].stop_price == Decimal("33.0")


def test_mixed_sheet_keeps_order_and_folds_only_rf(session: Session) -> None:
    contribution = _contribution(
        session,
        _sheet(
            '{"ticker": "CDB SOFISA", "classe": "renda_fixa", "valor_brl": 4000},'
            '{"ticker": "PETR4", "classe": "acoes_b3", "valor_brl": 3000},'
            '{"ticker": "CDB ITAU", "classe": "renda_fixa", "valor_brl": 1000}'
        ),
    )
    created = order_service.ingest_contribution_orders(session, contribution)
    stored = list(session.exec(select(Order)).all())

    assert len(stored) == 2
    rf = next(o for o in created if o.asset_class == AssetClass.FIXED_INCOME)
    assert rf.ticker == order_service.CANONICAL_CDB_TICKER
    assert rf.amount_brl == Decimal("5000")
    assert any(o.ticker == "PETR4" for o in created)
