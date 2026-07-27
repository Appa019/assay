"""Structured orders: parse the committee's closing JSON and track execution.

The final synthesis step emits a machine-readable block::

    ```json
    {"orders": [{"ticker": "PETR4", "classe": "acoes_b3", "valor_brl": 1500,
                 "pct": 30, "preco_alvo": 38.5, "stop": 33.1,
                 "tese_1_linha": "..."}]}
    ```

``ingest_contribution_orders`` turns it into ``Order`` rows right after a run
completes (best-effort — a malformed block never fails the analysis).
``execute_order`` records what the user actually bought and creates the Asset
lot, inheriting the committee's thesis/target/stop, so weekly reviews and the
track record see WHY each position exists.
"""

import json
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import structlog
from sqlmodel import Session, select

from app.models.asset import AssetClass
from app.models.contribution import Contribution
from app.models.order import Order, OrderStatus
from app.schemas.asset import AssetCreate
from app.services import portfolio_service

logger = structlog.get_logger()

_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _normalize_class(raw: Any) -> AssetClass | None:
    """Tolerant class mapping — models paraphrase the canonical labels.

    A real haiku run emitted ``equity_b3``/``fixed_income_cdb``/
    ``crypto_stablecoin`` instead of the requested ``acoes_b3``/``cdb``/
    ``crypto``; substring matching keeps the sheet usable regardless.
    """
    value = str(raw or "").strip().lower()
    if not value:
        return None
    if "cdb" in value or "fixed" in value or "renda" in value or value == "rf":
        return AssetClass.FIXED_INCOME
    if "crypto" in value or "cripto" in value or "stable" in value:
        return AssetClass.CRYPTO
    if (
        "acoes" in value
        or "acao" in value
        or "equity" in value
        or "stock" in value
        or "b3" in value
    ):
        return AssetClass.STOCKS
    return None


def _first(row: dict[str, Any], *keys: str) -> Any:
    """First present-and-non-null value among synonym keys."""
    for key in keys:
        if row.get(key) is not None:
            return row[key]
    return None


def parse_orders_block(text: str) -> list[dict[str, Any]]:
    """Extract the LAST valid ``{"orders": [...]}`` json block from markdown."""
    for match in reversed(_JSON_BLOCK.findall(text or "")):
        try:
            data = json.loads(match)
        except json.JSONDecodeError:
            continue
        orders = data.get("orders")
        if isinstance(orders, list):
            return [o for o in orders if isinstance(o, dict)]
    return []


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def ingest_contribution_orders(session: Session, contribution: Contribution) -> list[Order]:
    """Create Order rows from a completed contribution's final summary.

    Idempotent: skipped entirely when the contribution already has orders.
    Best-effort: unparseable rows are logged and dropped.
    """
    existing = session.exec(
        select(Order).where(Order.contribution_id == contribution.id).limit(1)
    ).first()
    if existing is not None:
        return []

    rows = parse_orders_block(contribution.final_summary or "")
    created: list[Order] = []
    for row in rows:
        ticker = str(_first(row, "ticker", "symbol", "ativo") or "").strip().upper()
        asset_class = _normalize_class(_first(row, "classe", "class", "asset_class"))
        amount = _to_decimal(_first(row, "valor_brl", "amount_brl", "total_brl", "valor"))
        if not ticker or asset_class is None or amount is None or amount <= 0:
            logger.warning("order_row_skipped", row=str(row)[:200])
            continue
        pct = _first(row, "pct", "pct_aporte", "pct_portfolio")
        order = Order(
            contribution_id=contribution.id,
            ticker=ticker,
            asset_class=asset_class,
            amount_brl=amount.quantize(Decimal("0.01")),
            pct_of_contribution=float(pct) if isinstance(pct, int | float) else None,
            target_price=_to_decimal(
                _first(row, "preco_alvo", "target_31d_brl", "target_brl", "target")
            ),
            stop_price=_to_decimal(_first(row, "stop", "stop_loss_brl", "stop_loss")),
            thesis=(str(_first(row, "tese_1_linha", "thesis", "tese") or "").strip() or None),
        )
        session.add(order)
        created.append(order)
    if created:
        session.commit()
        for order in created:
            session.refresh(order)
    logger.info("orders_ingested", contribution_id=str(contribution.id), count=len(created))
    return created


def list_orders(session: Session, *, status: OrderStatus | None = None) -> list[Order]:
    stmt = select(Order).order_by(Order.created_at.desc())
    if status is not None:
        stmt = stmt.where(Order.status == status)
    return list(session.exec(stmt).all())


def pending_order_for_ticker(session: Session, ticker: str) -> Order | None:
    return session.exec(
        select(Order)
        .where(Order.ticker == ticker.upper())
        .where(Order.status == OrderStatus.PENDING)
        .order_by(Order.created_at)
    ).first()


def execute_order(
    session: Session,
    order_id: UUID,
    *,
    quantity: Decimal,
    price: Decimal,
) -> Order:
    """Mark an order executed and create the Asset lot it recommended."""
    order = session.get(Order, order_id)
    if order is None:
        raise LookupError(f"Order {order_id} not found")
    if order.status != OrderStatus.PENDING:
        raise ValueError(f"Ordem {order.ticker} já está {order.status}.")

    asset = portfolio_service.create_asset(
        session,
        AssetCreate(
            ticker=order.ticker,
            asset_class=order.asset_class,
            quantity=quantity,
            avg_price=price,
        ),
    )
    # Carry the committee's context onto the lot itself.
    asset.thesis = order.thesis
    asset.target_price = order.target_price
    asset.stop_price = order.stop_price
    session.add(asset)

    order.status = OrderStatus.EXECUTED
    order.executed_quantity = quantity
    order.executed_price = price
    order.executed_asset_id = asset.id
    order.executed_at = datetime.now(UTC)
    session.add(order)
    session.commit()
    session.refresh(order)
    logger.info("order_executed", ticker=order.ticker, quantity=str(quantity), price=str(price))
    return order


def skip_order(session: Session, order_id: UUID, *, reason: str | None = None) -> Order:
    order = session.get(Order, order_id)
    if order is None:
        raise LookupError(f"Order {order_id} not found")
    if order.status != OrderStatus.PENDING:
        raise ValueError(f"Ordem {order.ticker} já está {order.status}.")
    order.status = OrderStatus.SKIPPED
    if reason:
        order.thesis = f"{order.thesis or ''} [pulada: {reason}]".strip()
    session.add(order)
    session.commit()
    session.refresh(order)
    return order
