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
from collections import defaultdict
from datetime import UTC, date, timedelta
from decimal import Decimal
from typing import Any

import httpx
import structlog
import yfinance as yf
from sqlmodel import Session, select

from app.config import settings
from app.models.trade import Trade
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
        signed = trade.total_brl if trade.side == "buy" else -trade.total_brl
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


async def _cdi_index(start: date, end: date) -> dict[date, float]:
    url = (
        "https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados"
        f"?formato=json&dataInicial={start.strftime('%d/%m/%Y')}"
        f"&dataFinal={end.strftime('%d/%m/%Y')}"
    )
    out: dict[date, float] = {}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            rows = resp.json()
        level = 100.0
        for row in rows if isinstance(rows, list) else []:
            day, month, year = str(row.get("data", "")).split("/")
            level *= 1.0 + float(str(row.get("valor", "0")).replace(",", ".")) / 100.0
            out[date(int(year), int(month), int(day))] = level
    except Exception as exc:
        logger.warning("benchmark_cdi_failed", error=str(exc))
    return out


def _ibov_closes(start: date, end: date) -> dict[date, float]:
    try:
        hist = yf.Ticker("^BVSP").history(
            start=start.isoformat(), end=(end + timedelta(days=1)).isoformat()
        )
        return {ts.date(): float(close) for ts, close in hist["Close"].items()}
    except Exception as exc:
        logger.warning("benchmark_ibov_failed", error=str(exc))
        return {}


async def _btc_brl(start: date, end: date) -> dict[date, float]:
    days = max(2, (end - start).days + 1)
    headers = {}
    if settings.coingecko_api_key:
        headers["x-cg-demo-api-key"] = settings.coingecko_api_key
    try:
        async with httpx.AsyncClient(timeout=25, headers=headers) as client:
            resp = await client.get(
                f"{settings.coingecko_api_url}/coins/bitcoin/market_chart",
                params={"vs_currency": "brl", "days": min(days, 365), "interval": "daily"},
            )
            resp.raise_for_status()
            prices = resp.json().get("prices", [])
        out: dict[date, float] = {}
        for ts_ms, price in prices:
            out[date.fromtimestamp(ts_ms / 1000)] = float(price)
        return out
    except Exception as exc:
        logger.warning("benchmark_btc_failed", error=str(exc))
        return {}


def _normalized_at(series: dict[date, float], days: list[date]) -> list[float | None]:
    """Forward-fill the series onto the requested days, rebased to 100."""
    if not series:
        return [None] * len(days)
    sorted_days = sorted(series)
    base: float | None = None
    out: list[float | None] = []
    for day in days:
        candidates = [d for d in sorted_days if d <= day]
        if not candidates:
            out.append(None)
            continue
        value = series[candidates[-1]]
        if base is None:
            base = value
        out.append(round(value / base * 100.0, 2))
    return out


async def build_benchmark(session: Session, *, days: int = 365) -> dict[str, Any]:
    portfolio = _portfolio_index(session, days)
    if not portfolio:
        return {"series": [], "note": "São necessários ao menos 2 snapshots diários."}

    start, end = portfolio[0][0], portfolio[-1][0]
    snapshot_days = [d for d, _v in portfolio]

    cdi, btc = await asyncio.gather(_cdi_index(start, end), _btc_brl(start, end))
    ibov = await asyncio.to_thread(_ibov_closes, start, end)

    cdi_vals = _normalized_at(cdi, snapshot_days)
    ibov_vals = _normalized_at(ibov, snapshot_days)
    btc_vals = _normalized_at(btc, snapshot_days)

    series = [
        {
            "date": day.isoformat(),
            "portfolio": round(value, 2),
            "cdi": cdi_vals[i],
            "ibov": ibov_vals[i],
            "btc": btc_vals[i],
        }
        for i, (day, value) in enumerate(portfolio)
    ]
    return {"series": series}
