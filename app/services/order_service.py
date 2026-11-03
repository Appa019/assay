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

# The mandate allows exactly ONE fixed-income instrument (D29): the committee
# decides HOW MUCH, never WHICH. Until now that lived only as prompt text, and
# the very first sheet came back with four different CDBs — two of them TERM
# papers that lock the money for ~2 years, which is the opposite of dry powder.
# Ingest enforces it, so a drifting model cannot put a locked CDB in the book.
CANONICAL_CDB_TICKER = "CDB BRADESCO 100%CDI"

_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
_MACHINE_TAIL = re.compile(r"\n*-{3,}\s*\n+```json.*?```\s*", re.DOTALL)
_ANY_JSON_BLOCK = re.compile(r"```json.*?```", re.DOTALL)


def strip_machine_block(text: str) -> str:
    """Client-facing version of the closing summary.

    The machine-readable ``{"orders": [...]}`` block exists for ingestion,
    not for reading — the client asked for ONLY the clean allocation
    structure. Removes the trailing separator + json block (and any stray
    json fences), leaving the human part untouched.
    """
    if not text:
        return text
    cleaned = _MACHINE_TAIL.sub("\n", text)
    cleaned = _ANY_JSON_BLOCK.sub("", cleaned)
    return cleaned.strip()


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


def summarize_block(text: str, *, expected_total: Decimal | None = None) -> dict[str, Any]:
    """Deterministic health-check of the closing orders block.

    The templates DEMAND that the sheet sums to the contribution (±R$ 5) — but
    until now no machine ever verified it. Returns row counts, how many rows
    are actually ingestable, their BRL sum, and the relative deviation vs the
    expected total (None when no expectation). Powers the post-run validator
    and the mismatch notice.
    """
    rows = parse_orders_block(text or "")
    valid = 0
    total = Decimal("0")
    for row in rows:
        ticker = str(_first(row, "ticker", "symbol", "ativo") or "").strip()
        asset_class = _normalize_class(_first(row, "classe", "class", "asset_class"))
        amount = _to_decimal(_first(row, "valor_brl", "amount_brl", "total_brl", "valor"))
        if ticker and asset_class is not None and amount is not None and amount > 0:
            valid += 1
            total += amount
    deviation: float | None = None
    if expected_total is not None and expected_total > 0:
        deviation = float(abs(total - Decimal(expected_total)) / Decimal(expected_total))
    return {
        "rows": len(rows),
        "valid": valid,
        "total_brl": float(total),
        "deviation_pct": deviation,
    }


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
    fixed_income: Order | None = None
    for row in rows:
        ticker = str(_first(row, "ticker", "symbol", "ativo") or "").strip().upper()
        asset_class = _normalize_class(_first(row, "classe", "class", "asset_class"))
        amount = _to_decimal(_first(row, "valor_brl", "amount_brl", "total_brl", "valor"))
        if not ticker or asset_class is None or amount is None or amount <= 0:
            logger.warning("order_row_skipped", row=str(row)[:200])
            continue
        pct = _first(row, "pct", "pct_aporte", "pct_portfolio")
        amount = amount.quantize(Decimal("0.01"))

        if asset_class == AssetClass.FIXED_INCOME:
            # One instrument, so every RF line IS that instrument: rename it and
            # fold repeats into a single order instead of booking N lots of the
            # same paper. Target/stop are meaningless on a daily-liquidity CDB.
            if ticker != CANONICAL_CDB_TICKER:
                logger.warning(
                    "order_fixed_income_renamed", proposed=ticker, forced=CANONICAL_CDB_TICKER
                )
            if fixed_income is not None:
                fixed_income.amount_brl += amount
                if isinstance(pct, int | float):
                    fixed_income.pct_of_contribution = (
                        fixed_income.pct_of_contribution or 0.0
                    ) + float(pct)
                logger.info("order_fixed_income_merged", total=str(fixed_income.amount_brl))
                continue
            fixed_income = Order(
                contribution_id=contribution.id,
                ticker=CANONICAL_CDB_TICKER,
                asset_class=asset_class,
                amount_brl=amount,
                pct_of_contribution=float(pct) if isinstance(pct, int | float) else None,
                thesis=(str(_first(row, "tese_1_linha", "thesis", "tese") or "").strip() or None),
            )
            session.add(fixed_income)
            created.append(fixed_income)
            continue

        order = Order(
            contribution_id=contribution.id,
            ticker=ticker,
            asset_class=asset_class,
            amount_brl=amount,
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

    # Single transaction: asset + BUY trade + order flip commit together, so a
    # crash can never leave the lot persisted with the order still PENDING
    # (which would double the position on the retry).
    asset = portfolio_service.build_asset_with_trade(
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
