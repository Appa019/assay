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


def test_pending_order_lookup_and_skip(session: Session) -> None:
    contribution = _completed_contribution(session)
    order_service.ingest_contribution_orders(session, contribution)
    order = order_service.pending_order_for_ticker(session, "btc")
    assert order is not None and order.ticker == "BTC"
    skipped = order_service.skip_order(session, order.id, reason="sem liquidez na exchange")
    assert skipped.status == OrderStatus.SKIPPED
    assert order_service.pending_order_for_ticker(session, "BTC") is None
