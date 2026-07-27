"""Brazilian personal income-tax report over the trade ledger (simplified).

Rules applied (swing trade, pessoa física):
- Ações B3: vendas do mês ≤ R$ 20.000 → ganho isento; acima, 15% sobre o
  ganho líquido do mês, compensando prejuízos acumulados de meses anteriores.
- Crypto: vendas do mês ≤ R$ 35.000 → isento; acima, 15% sobre o ganho
  (faixas maiores existem acima de R$ 5M — fora da escala deste sistema),
  com a mesma compensação de prejuízos.
- CDB: IR retido NA FONTE pela instituição (tabela regressiva) — reportado
  aqui apenas como informativo, com a alíquota estimada pelo prazo do lote.
- DARF mínima de R$ 10: valores menores acumulam para o mês seguinte (nota).

NÃO cobre: day-trade, JCP/dividendos, custos operacionais/corretagem, e
eventos societários. É um mapa para a declaração, não a declaração.
"""

from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlmodel import Session, select

from app.models.asset import AssetClass
from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.trade import Trade, TradeSide
from app.services import portfolio_service

logger = structlog.get_logger()

STOCKS_EXEMPT_SALES_MONTH = Decimal("20000")
CRYPTO_EXEMPT_SALES_MONTH = Decimal("35000")
CAPITAL_GAINS_RATE = Decimal("0.15")
DARF_MINIMUM = Decimal("10")


def _cdb_regressive_rate(days_held: int) -> float:
    if days_held <= 180:
        return 22.5
    if days_held <= 360:
        return 20.0
    if days_held <= 720:
        return 17.5
    return 15.0


def _month_key(dt: datetime) -> tuple[int, int]:
    local = (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone()
    return (local.year, local.month)


def build_year_report(session: Session, year: int) -> dict[str, Any]:
    """Monthly capital-gains breakdown + year-end positions for one year."""
    sells = list(
        session.exec(
            select(Trade).where(Trade.side == TradeSide.SELL).order_by(Trade.executed_at)
        ).all()
    )

    # Group sells per month per class, walking the WHOLE ledger so loss
    # carryforward from earlier years reaches the requested one correctly.
    monthly: dict[tuple[int, int], dict[AssetClass, list[Trade]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for trade in sells:
        monthly[_month_key(trade.executed_at)][trade.asset_class].append(trade)

    carry: dict[AssetClass, Decimal] = {
        AssetClass.STOCKS: Decimal("0"),
        AssetClass.CRYPTO: Decimal("0"),
    }
    months_out: list[dict[str, Any]] = []
    total_darf = Decimal("0")

    for key in sorted(monthly):
        month_year, month = key
        if month_year > year:
            break
        row: dict[str, Any] = {"month": f"{month_year:04d}-{month:02d}"}
        include = month_year == year

        for asset_class, exempt_limit, label in (
            (AssetClass.STOCKS, STOCKS_EXEMPT_SALES_MONTH, "stocks"),
            (AssetClass.CRYPTO, CRYPTO_EXEMPT_SALES_MONTH, "crypto"),
        ):
            trades = monthly[key].get(asset_class, [])
            sales = sum((t.total_brl for t in trades), Decimal("0"))
            gain = sum(
                (t.realized_pnl_brl for t in trades if t.realized_pnl_brl is not None),
                Decimal("0"),
            )
            exempt = sales <= exempt_limit
            tax_due = Decimal("0")
            carry_used = Decimal("0")
            if gain < 0:
                # Losses always accumulate, exempt month or not.
                carry[asset_class] += -gain
            elif not exempt and gain > 0:
                carry_used = min(carry[asset_class], gain)
                carry[asset_class] -= carry_used
                taxable = gain - carry_used
                tax_due = (taxable * CAPITAL_GAINS_RATE).quantize(Decimal("0.01"))
            row[label] = {
                "sales_brl": float(sales),
                "net_gain_brl": float(gain),
                "exempt": exempt,
                "loss_carry_used_brl": float(carry_used),
                "tax_due_brl": float(tax_due),
                "darf_below_minimum": bool(Decimal("0") < tax_due < DARF_MINIMUM),
            }
            if include:
                total_darf += tax_due

        cdb_trades = monthly[key].get(AssetClass.FIXED_INCOME, [])
        if cdb_trades:
            row["fixed_income_info"] = [
                {
                    "ticker": t.ticker,
                    "income_brl": float(t.realized_pnl_brl or 0),
                    "days_held": (
                        (t.executed_at.date() - t.lot_entry_date).days if t.lot_entry_date else None
                    ),
                    "withheld_rate_pct": (
                        _cdb_regressive_rate((t.executed_at.date() - t.lot_entry_date).days)
                        if t.lot_entry_date
                        else None
                    ),
                }
                for t in cdb_trades
            ]
        if include:
            months_out.append(row)

    return {
        "year": year,
        "months": months_out,
        "total_darf_brl": float(total_darf),
        "loss_carryforward_brl": {
            "stocks": float(carry[AssetClass.STOCKS]),
            "crypto": float(carry[AssetClass.CRYPTO]),
        },
        "year_end_positions": _year_end_positions(session, year),
        "notes": [
            "Apuração simplificada (swing trade PF): confira com seu contador.",
            "Ações: isenção sobre VENDAS ≤ R$ 20k/mês; crypto: ≤ R$ 35k/mês.",
            "CDB: IR retido na fonte pela instituição (informativo).",
            "DARF < R$ 10 não é paga — acumula para o mês seguinte.",
        ],
    }


def _year_end_positions(session: Session, year: int) -> list[dict[str, Any]]:
    """Bens e direitos: positions on 31/12 (snapshot) or current if this year."""
    cutoff = date(year, 12, 31)
    snapshot = session.exec(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.snapshot_date <= cutoff)
        .where(PortfolioSnapshot.snapshot_date >= date(year, 12, 1))
        .order_by(PortfolioSnapshot.snapshot_date.desc())
    ).first()
    if snapshot is not None and snapshot.assets:
        return [
            {
                "ticker": a.get("ticker"),
                "asset_class": a.get("asset_class"),
                "quantity": a.get("quantity"),
                "cost_basis_brl": round((a.get("quantity") or 0) * (a.get("avg_price") or 0), 2),
            }
            for a in snapshot.assets
        ]
    if year == date.today().year:
        return [
            {
                "ticker": r["ticker"],
                "asset_class": r["asset_class"],
                "quantity": r["quantity"],
                "cost_basis_brl": round(r["quantity"] * r["avg_price"], 2),
            }
            for r in portfolio_service.build_portfolio_snapshot(session)
        ]
    return []
