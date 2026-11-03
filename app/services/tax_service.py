"""Brazilian personal income-tax report over the trade ledger (simplified).

Rules applied (swing trade, pessoa física):
- Ações B3: vendas do mês ≤ R$ 20.000 → ganho isento; acima, 15% sobre o
  ganho líquido do mês, compensando prejuízos acumulados de meses anteriores.
- Crypto em exchange NACIONAL (ou autocustódia de residente): ganho de capital
  mensal. Vendas do mês ≤ R$ 35.000 (inclusive) → isento; acima, cada venda com
  ganho é tributada SEPARADAMENTE pelas faixas progressivas (15% até R$ 5M …
  22,5%), DARF 4600. Prejuízo NÃO compensa: nem com outra venda do mês, nem
  com meses seguintes (P&R IRPF 2026, perguntas 583, 574 e 653).
- Crypto em exchange no EXTERIOR, desde 2024: Lei 14.754/2023 — 15% sobre o
  resultado do ANO, pago na Declaração de Ajuste Anual (sem DARF mensal, sem
  isenção, fora da soma dos R$ 35 mil). Perdas abatem ganhos do mesmo ano e o
  que sobrar passa para os anos seguintes (art. 9º). Antes de 2024 o lote no
  exterior seguia o regime nacional. Fontes e decisões: docs/12-decisoes.md D51.
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
# Lei 8.981/1995 art. 21 (Lei 13.259/2016): rate per SLICE of the gain.
CAPITAL_GAINS_BRACKETS: tuple[tuple[Decimal | None, Decimal], ...] = (
    (Decimal("5000000"), Decimal("0.15")),
    (Decimal("10000000"), Decimal("0.175")),
    (Decimal("30000000"), Decimal("0.20")),
    (None, Decimal("0.225")),
)
ABROAD_RATE = Decimal("0.15")  # Lei 14.754/2023 art. 2º §1º
ABROAD_REGIME_START_YEAR = 2024  # Lei 14.754/2023 art. 47
DARF_MINIMUM = Decimal("10")


def _cdb_regressive_rate(days_held: int) -> float:
    if days_held <= 180:
        return 22.5
    if days_held <= 360:
        return 20.0
    if days_held <= 720:
        return 17.5
    return 15.0


def progressive_capital_gains_tax(gain: Decimal) -> Decimal:
    """Ganho de capital tax on ONE sale: each slice of the gain at its rate."""
    tax = Decimal("0")
    floor = Decimal("0")
    for ceiling, rate in CAPITAL_GAINS_BRACKETS:
        top = gain if ceiling is None else min(gain, ceiling)
        if top <= floor:
            break
        tax += (top - floor) * rate
        floor = top
    return tax.quantize(Decimal("0.01"))


def _is_abroad_regime(trade: Trade) -> bool:
    return (
        trade.asset_class == AssetClass.CRYPTO
        and trade.held_abroad
        and _month_key(trade.executed_at)[0] >= ABROAD_REGIME_START_YEAR
    )


def _abroad_year(sells: list[Trade], year: int) -> dict[str, Any]:
    """Lei 14.754 annual result for foreign-exchange crypto, with loss carry."""
    by_year: dict[int, Decimal] = defaultdict(Decimal)
    for t in sells:
        if _is_abroad_regime(t):
            by_year[_month_key(t.executed_at)[0]] += t.realized_pnl_brl or Decimal("0")
    carry = Decimal("0")
    out: dict[str, Any] = {}
    for y in range(ABROAD_REGIME_START_YEAR, year + 1):
        net = by_year.get(y, Decimal("0"))
        used = Decimal("0")
        tax = Decimal("0")
        if net < 0:
            carry += -net
        else:
            used = min(carry, net)
            carry -= used
            tax = ((net - used) * ABROAD_RATE).quantize(Decimal("0.01"))
        out = {
            "net_gain_brl": float(net),
            "loss_carry_used_brl": float(used),
            "tax_due_brl": float(tax),
        }
    return {
        "sales_brl": float(
            sum(
                (
                    t.total_brl
                    for t in sells
                    if _is_abroad_regime(t) and _month_key(t.executed_at)[0] == year
                ),
                Decimal("0"),
            )
        ),
        "net_gain_brl": out.get("net_gain_brl", 0.0),
        "loss_carry_used_brl": out.get("loss_carry_used_brl", 0.0),
        "tax_due_brl": out.get("tax_due_brl", 0.0),
        "loss_carryforward_brl": float(carry),
        "paid_in": f"Declaração de Ajuste Anual {year + 1}",
    }


def _month_key(dt: datetime) -> tuple[int, int]:
    local = (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone()
    return (local.year, local.month)


def _local_date(dt: datetime) -> date:
    """Local calendar date for a stored UTC-naive timestamp.

    A late-evening sale (21h+ in Brazil) is already "tomorrow" in UTC; taking
    ``.date()`` raw would shift days_held by one — exactly at the 180/360/720
    boundaries where the CDB rate changes bracket.
    """
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone().date()


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

    # Only stocks carry losses month to month; national crypto never does.
    stock_carry = Decimal("0")
    months_out: list[dict[str, Any]] = []
    total_darf = Decimal("0")

    for key in sorted(monthly):
        month_year, month = key
        if month_year > year:
            break
        row: dict[str, Any] = {"month": f"{month_year:04d}-{month:02d}"}
        include = month_year == year

        stocks = monthly[key].get(AssetClass.STOCKS, [])
        sales = sum((t.total_brl for t in stocks), Decimal("0"))
        gain = sum(
            (t.realized_pnl_brl for t in stocks if t.realized_pnl_brl is not None),
            Decimal("0"),
        )
        exempt = sales <= STOCKS_EXEMPT_SALES_MONTH
        tax_due = Decimal("0")
        carry_used = Decimal("0")
        if gain < 0:
            # Losses always accumulate, exempt month or not.
            stock_carry += -gain
        elif not exempt and gain > 0:
            carry_used = min(stock_carry, gain)
            stock_carry -= carry_used
            tax_due = ((gain - carry_used) * CAPITAL_GAINS_RATE).quantize(Decimal("0.01"))
        row["stocks"] = _class_row(sales, gain, exempt, carry_used, tax_due)
        if include:
            total_darf += tax_due

        # National crypto: the R$ 35k test sums every national sale of the
        # month; above it each gaining sale is taxed on its own and losses
        # offset nothing (P&R 583).
        crypto = [t for t in monthly[key].get(AssetClass.CRYPTO, []) if not _is_abroad_regime(t)]
        sales = sum((t.total_brl for t in crypto), Decimal("0"))
        gain = sum((t.realized_pnl_brl or Decimal("0") for t in crypto), Decimal("0"))
        exempt = sales <= CRYPTO_EXEMPT_SALES_MONTH
        tax_due = Decimal("0")
        if not exempt:
            tax_due = sum(
                (
                    progressive_capital_gains_tax(t.realized_pnl_brl)
                    for t in crypto
                    if t.realized_pnl_brl is not None and t.realized_pnl_brl > 0
                ),
                Decimal("0"),
            )
        row["crypto"] = _class_row(sales, gain, exempt, Decimal("0"), tax_due)
        if include:
            total_darf += tax_due

        cdb_trades = monthly[key].get(AssetClass.FIXED_INCOME, [])
        if cdb_trades:
            row["fixed_income_info"] = [
                {
                    "ticker": t.ticker,
                    "income_brl": float(t.realized_pnl_brl or 0),
                    "days_held": (
                        (_local_date(t.executed_at) - t.lot_entry_date).days
                        if t.lot_entry_date
                        else None
                    ),
                    "withheld_rate_pct": (
                        _cdb_regressive_rate((_local_date(t.executed_at) - t.lot_entry_date).days)
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
        "loss_carryforward_brl": {"stocks": float(stock_carry)},
        "crypto_abroad": _abroad_year(sells, year),
        "year_end_positions": _year_end_positions(session, year),
        "notes": [
            "Apuração simplificada (swing trade PF): confira com seu contador.",
            "Ações: isenção sobre VENDAS ≤ R$ 20k/mês; prejuízo compensa meses seguintes.",
            "Crypto nacional: isenção sobre VENDAS ≤ R$ 35k/mês; acima, cada venda com "
            "ganho paga sozinha e prejuízo não compensa.",
            "Crypto em exchange no exterior: 15% sobre o resultado do ano, na declaração "
            "anual (Lei 14.754/2023); perdas abatem ganhos do ano e dos anos seguintes.",
            "CDB: IR retido na fonte pela instituição (informativo).",
            "DARF < R$ 10 não é paga — acumula para o mês seguinte.",
        ],
    }


def _class_row(
    sales: Decimal, gain: Decimal, exempt: bool, carry_used: Decimal, tax_due: Decimal
) -> dict[str, Any]:
    return {
        "sales_brl": float(sales),
        "net_gain_brl": float(gain),
        "exempt": exempt,
        "loss_carry_used_brl": float(carry_used),
        "tax_due_brl": float(tax_due),
        "darf_below_minimum": bool(Decimal("0") < tax_due < DARF_MINIMUM),
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
