from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlmodel import Session, select

from app.models.asset import Asset, AssetClass
from app.models.contribution import Contribution, ContributionStatus
from app.models.order import OrderStatus
from app.services import order_service

_SUMMARY = """\
## Folha de ordens

| Ativo | Classe | R$ |
|---|---|---|
| PETR4 | acoes_b3 | 1500 |

```json
{"orders": [
  {"ticker": "PETR4", "classe": "acoes_b3", "valor_brl": 1500, "pct": 30,
   "preco_alvo": 45.0, "stop": 33.0, "tese_1_linha": "Petróleo barato"},
  {"ticker": "BTC", "classe": "crypto", "valor_brl": 2000, "pct": 40,
   "preco_alvo": null, "stop": null, "tese_1_linha": "Reserva de valor"},
  {"ticker": "CDB-BTG", "classe": "cdb", "valor_brl": 1500, "pct": 30,
   "preco_alvo": null, "stop": null, "tese_1_linha": "Dry powder"},
  {"ticker": "", "classe": "acoes_b3", "valor_brl": 999}
]}
```
"""


def _completed_contribution(session: Session) -> Contribution:
    contribution = Contribution(
        amount_brl=Decimal("5000"),
        status=ContributionStatus.COMPLETED,
        final_summary=_SUMMARY,
        completed_at=datetime.now(UTC),
    )
    session.add(contribution)
    session.commit()
    session.refresh(contribution)
    return contribution


def test_parse_orders_block_takes_last_valid_block() -> None:
    rows = order_service.parse_orders_block(_SUMMARY)
    assert len(rows) == 4  # invalid row filtered later, at ingest
    assert rows[0]["ticker"] == "PETR4"


def test_ingest_is_idempotent_and_filters_bad_rows(session: Session) -> None:
    contribution = _completed_contribution(session)
    created = order_service.ingest_contribution_orders(session, contribution)
    assert [o.ticker for o in created] == ["PETR4", "BTC", "CDB-BTG"]
    assert created[0].asset_class == AssetClass.STOCKS
    assert created[0].target_price == Decimal("45.0")
    assert created[2].asset_class == AssetClass.FIXED_INCOME
    # Second ingest: no duplicates.
    assert order_service.ingest_contribution_orders(session, contribution) == []


def test_execute_order_creates_asset_with_committee_context(session: Session) -> None:
    contribution = _completed_contribution(session)
    orders = order_service.ingest_contribution_orders(session, contribution)
    petr = next(o for o in orders if o.ticker == "PETR4")

    executed = order_service.execute_order(
        session, petr.id, quantity=Decimal("40"), price=Decimal("37.80")
    )
    assert executed.status == OrderStatus.EXECUTED
    assert executed.executed_price == Decimal("37.80")

    asset = session.exec(select(Asset).where(Asset.ticker == "PETR4")).one()
    assert asset.thesis == "Petróleo barato"
    assert asset.target_price == Decimal("45.0")
    assert asset.stop_price == Decimal("33.0")

    with pytest.raises(ValueError):  # can't execute twice
        order_service.execute_order(session, petr.id, quantity=Decimal("1"), price=Decimal("1"))


_MODEL_DIALECT_SUMMARY = """\
```json
{"orders": [
  {"ticker": "ITUB4", "class": "equity_b3", "total_brl": 212.7,
   "pct_portfolio": 41.5, "stop_loss_brl": 38.5, "target_31d_brl": 43.5,
   "thesis": "Banco barato"},
  {"symbol": "BTC", "class": "crypto", "amount_brl": 61.49,
   "stop_loss_usd": 57000, "thesis": "Reserva de valor"},
  {"ticker": "BTG_CDB_120CDI_180D", "class": "fixed_income_cdb",
   "amount_brl": 147.92},
  {"symbol": "USDC", "class": "crypto_stablecoin", "amount_brl": 20.5}
]}
```
"""


def test_ingest_tolerates_model_field_dialects(session: Session) -> None:
    """Regression from a REAL haiku run: the closing block used symbol/class/
    amount_brl synonyms and the strict parser dropped every row."""
    contribution = Contribution(
        amount_brl=Decimal("100"),
        status=ContributionStatus.COMPLETED,
        final_summary=_MODEL_DIALECT_SUMMARY,
    )
    session.add(contribution)
    session.commit()
    session.refresh(contribution)

    created = order_service.ingest_contribution_orders(session, contribution)
    assert [o.ticker for o in created] == ["ITUB4", "BTC", "BTG_CDB_120CDI_180D", "USDC"]
    itub = created[0]
    assert itub.asset_class == AssetClass.STOCKS
    assert itub.amount_brl == Decimal("212.70")
    assert itub.target_price == Decimal("43.5")
    assert itub.stop_price == Decimal("38.5")
    assert itub.thesis == "Banco barato"
    assert itub.pct_of_contribution == 41.5
    assert created[1].asset_class == AssetClass.CRYPTO
    assert created[2].asset_class == AssetClass.FIXED_INCOME
    assert created[3].asset_class == AssetClass.CRYPTO  # stablecoin bucket


def test_pending_order_lookup_and_skip(session: Session) -> None:
    contribution = _completed_contribution(session)
    order_service.ingest_contribution_orders(session, contribution)
    order = order_service.pending_order_for_ticker(session, "btc")
    assert order is not None and order.ticker == "BTC"
    skipped = order_service.skip_order(session, order.id, reason="sem liquidez na exchange")
    assert skipped.status == OrderStatus.SKIPPED
    assert order_service.pending_order_for_ticker(session, "BTC") is None
