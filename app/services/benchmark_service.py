"""Portfolio performance vs CDI, IBOV and BTC.

The portfolio series is a time-weighted return (TWR) built from the daily
snapshots, neutralizing external flows with the trade ledger: buys inject
money into the tracked pool and sale proceeds leave it (the system holds no
cash), so raw total_value would look like "performance" every time the user
deposits. Daily return: r_t = (V_t − F_t − V_{t−1}) / (V_{t−1} + F_t), flows
assumed at the start of the day.

Benchmarks: CDI compounded from the BCB daily series, IBOV closes from
Yahoo, BTC/BRL from CoinGecko — all normalized to 100 at the first common
date, forward-filled onto snapshot dates (weekends/holidays).
"""

import asyncio
from bisect import bisect_right
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import structlog
import yfinance as yf
from sqlmodel import Session, select

from app.config import settings
from app.models.trade import Trade, TradeSide
from app.services import portfolio_service

logger = structlog.get_logger()


def _portfolio_index(session: Session, days: int) -> list[tuple[date, float]]:
    snapshots = portfolio_service.get_portfolio_history(session, days=days)
    if len(snapshots) < 2:
        return []

    flows: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
    trades = session.exec(select(Trade)).all()
    for trade in trades:
        local_day = (
            (
                trade.executed_at
                if trade.executed_at.tzinfo
                else trade.executed_at.replace(tzinfo=UTC)
            )
            .astimezone()
            .date()
        )
        signed = trade.total_brl if trade.side == TradeSide.BUY else -trade.total_brl
        flows[local_day] += signed

    index: list[tuple[date, float]] = [(snapshots[0].snapshot_date, 100.0)]
    for prev, cur in zip(snapshots, snapshots[1:], strict=False):
        # Flows on every day since the previous snapshot belong to this leg.
        leg_flow = Decimal("0")
        day = prev.snapshot_date + timedelta(days=1)
        while day <= cur.snapshot_date:
            leg_flow += flows.get(day, Decimal("0"))
            day += timedelta(days=1)
        base = float(prev.total_value + leg_flow)
        if base <= 0:
            r = 0.0
        else:
            r = (float(cur.total_value) - float(prev.total_value + leg_flow)) / base
        index.append((cur.snapshot_date, index[-1][1] * (1.0 + r)))
    return index


def _compound_cdi_rows(rows: Any) -> dict[date, float]:
    """Compound the BCB daily series into an index, tolerating malformed rows.

    One bad row must cost one data point — not the entire CDI line (which is
    what happened when the parse ran unguarded inside the request handler).
    """
    out: dict[date, float] = {}
    level = 100.0
    for row in rows if isinstance(rows, list) else []:
        try:
            day, month, year = str(row.get("data", "")).split("/")
            level *= 1.0 + float(str(row.get("valor", "0")).replace(",", ".")) / 100.0
            out[date(int(year), int(month), int(day))] = level
        except (ValueError, AttributeError, TypeError) as exc:
            logger.warning("benchmark_cdi_bad_row", row=str(row)[:80], error=str(exc))
    return out


async def _cdi_index(start: date, end: date) -> dict[date, float]:
    url = (
        "https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados"
        f"?formato=json&dataInicial={start.strftime('%d/%m/%Y')}"
        f"&dataFinal={end.strftime('%d/%m/%Y')}"
    )
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            rows = resp.json()
    except Exception as exc:
        logger.warning("benchmark_cdi_failed", error=str(exc))
        return {}
    return _compound_cdi_rows(rows)


def _ibov_closes(start: date, end: date) -> dict[date, float]:
    try:
        hist = yf.Ticker("^BVSP").history(
            start=start.isoformat(), end=(end + timedelta(days=1)).isoformat()
        )
        out: dict[date, float] = {}
        for ts, close in hist["Close"].items():
            # yfinance stamps rows in the exchange tz; convert explicitly so a
            # UTC-indexed frame can never land a close on the wrong day.
            when = ts.tz_convert("America/Sao_Paulo") if ts.tzinfo else ts
            out[when.date()] = float(close)
        return out
    except Exception as exc:
        logger.warning("benchmark_ibov_failed", error=str(exc))
        return {}


async def _btc_brl(start: date, end: date) -> dict[date, float]:
    """Daily BTC/BRL points covering [start, end], keyed by UTC day.

    Uses the RANGE endpoint with explicit timestamps: the plain
    ``market_chart?days=N`` window is anchored at NOW, so whenever the last
    snapshot lagged today the series missed its leading days entirely (and
    ``date.fromtimestamp`` shifted the midnight-UTC points one day back in
    BRT). Granularity is hourly for short ranges — bucketing per UTC day and
    keeping the last point gives the daily close either way.
    """
    start = max(start, end - timedelta(days=365))  # free-tier range ceiling
    frm = int(datetime(start.year, start.month, start.day, tzinfo=UTC).timestamp())
    to = int(datetime(end.year, end.month, end.day, 23, 59, 59, tzinfo=UTC).timestamp())
    headers = {}
    if settings.coingecko_api_key:
        headers["x-cg-demo-api-key"] = settings.coingecko_api_key
    try:
        async with httpx.AsyncClient(timeout=25, headers=headers) as client:
            resp = await client.get(
                f"{settings.coingecko_api_url}/coins/bitcoin/market_chart/range",
                params={"vs_currency": "brl", "from": frm, "to": to},
            )
            resp.raise_for_status()
            prices = resp.json().get("prices", [])
        out: dict[date, float] = {}
        for ts_ms, price in prices:
            out[datetime.fromtimestamp(ts_ms / 1000, tz=UTC).date()] = float(price)
        return out
    except Exception as exc:
        logger.warning("benchmark_btc_failed", error=str(exc))
        return {}


def _ffill_at(series: dict[date, float], days: list[date]) -> list[float | None]:
    """Forward-fill RAW series values onto the requested days (no rebasing)."""
    if not series:
        return [None] * len(days)
    sorted_days = sorted(series)
    out: list[float | None] = []
    for day in days:
        i = bisect_right(sorted_days, day)
        out.append(series[sorted_days[i - 1]] if i else None)
    return out


def _first_common_index(columns: list[list[float | None]]) -> int:
    """First position where every NON-EMPTY column has a value.

    Rebasing each line at its own first datapoint made "100" mean a different
    date per series — one shared base keeps the comparison honest. A series
    that failed entirely (all None) is ignored rather than blocking the rest.
    """
    non_empty = [c for c in columns if any(v is not None for v in c)]
    if not non_empty:
        return 0
    for i in range(len(non_empty[0])):
        if all(c[i] is not None for c in non_empty):
            return i
    return 0


def _rebase(values: list[float | None], base_index: int) -> list[float | None]:
    base = values[base_index] if 0 <= base_index < len(values) else None
    if not base:
        return [None] * len(values)
    return [round(v / base * 100.0, 2) if v is not None else None for v in values]


async def build_benchmark(session: Session, *, days: int = 365) -> dict[str, Any]:
    portfolio = _portfolio_index(session, days)
    if not portfolio:
        return {"series": [], "note": "São necessários ao menos 2 snapshots diários."}

    start, end = portfolio[0][0], portfolio[-1][0]
    snapshot_days = [d for d, _v in portfolio]

    cdi, btc = await asyncio.gather(_cdi_index(start, end), _btc_brl(start, end))
    ibov = await asyncio.to_thread(_ibov_closes, start, end)

    port_vals: list[float | None] = [v for _d, v in portfolio]
    cdi_vals = _ffill_at(cdi, snapshot_days)
    ibov_vals = _ffill_at(ibov, snapshot_days)
    btc_vals = _ffill_at(btc, snapshot_days)

    base_index = _first_common_index([port_vals, cdi_vals, ibov_vals, btc_vals])
    port_r = _rebase(port_vals, base_index)
    cdi_r = _rebase(cdi_vals, base_index)
    ibov_r = _rebase(ibov_vals, base_index)
    btc_r = _rebase(btc_vals, base_index)

    series = [
        {
            "date": day.isoformat(),
            "portfolio": port_r[i],
            "cdi": cdi_r[i],
            "ibov": ibov_r[i],
            "btc": btc_r[i],
        }
        for i, day in enumerate(snapshot_days)
    ]
    return {"series": series, "base_date": snapshot_days[base_index].isoformat()}
