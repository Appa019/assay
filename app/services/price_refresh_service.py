"""Mark every portfolio lot to market.

Stocks come from Yahoo (B3 ``.SA`` fallbacks), crypto from CoinGecko (id
resolved via search when the ticker isn't already an id), and CDB/fixed income
accrues by the compounded daily CDI (BCB series 12) from the lot's entry date.

Without this the whole system is blind: ``Asset.current_price`` starts equal
to ``avg_price`` and nothing else ever updates it, so P&L reads ~0% forever.
Run via cron (scripts/refresh_prices.py), the API (POST /api/portfolio/refresh)
and before every review snapshot.
"""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
import structlog
import yfinance as yf
from sqlmodel import Session, select

from app.config import settings
from app.models.asset import Asset, AssetClass
from app.services import market_data_service

logger = structlog.get_logger()

_B3_SUFFIXES = (".SA", ".SAO")

# Ticker symbol → CoinGecko id for the majors, so we skip a search round-trip.
_COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "LINK": "chainlink",
    "MATIC": "matic-network",
    "POL": "polygon-ecosystem-token",
    "ARB": "arbitrum",
    "OP": "optimism",
    "USDC": "usd-coin",
    "USDT": "tether",
    "USDE": "ethena-usde",
}


def _fetch_stock_price(ticker: str) -> float | None:
    """Last price via yfinance, trying B3 suffixes. Blocking — call in a thread."""
    symbols = [ticker] if "." in ticker else [f"{ticker}{s}" for s in _B3_SUFFIXES] + [ticker]
    for symbol in symbols:
        try:
            info = yf.Ticker(symbol).fast_info
            price = info.get("last_price") or info.get("lastPrice")
            if price:
                return float(price)
        except Exception:
            continue
    return None


async def _stock_price(ticker: str) -> float | None:
    try:
        return await asyncio.wait_for(asyncio.to_thread(_fetch_stock_price, ticker), timeout=15)
    except TimeoutError:
        return None


async def _resolve_coingecko_id(client: httpx.AsyncClient, ticker: str) -> str | None:
    mapped = _COINGECKO_IDS.get(ticker.upper())
    if mapped:
        return mapped
    try:
        resp = await client.get(f"{settings.coingecko_api_url}/search", params={"query": ticker})
        resp.raise_for_status()
        coins = resp.json().get("coins", [])
        # Prefer an exact symbol match; fall back to the top result.
        for coin in coins:
            if str(coin.get("symbol", "")).upper() == ticker.upper():
                return coin.get("id")
        return coins[0].get("id") if coins else None
    except Exception as exc:
        logger.warning("coingecko_resolve_failed", ticker=ticker, error=str(exc))
        return None


async def _crypto_prices_brl(tickers: list[str]) -> dict[str, float]:
    """Batch BRL prices for crypto tickers via CoinGecko /simple/price."""
    if not tickers:
        return {}
    headers = {}
    if settings.coingecko_api_key:
        headers["x-cg-demo-api-key"] = settings.coingecko_api_key
    out: dict[str, float] = {}
    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        ids: dict[str, str] = {}
        for ticker in tickers:
            coin_id = await _resolve_coingecko_id(client, ticker)
            if coin_id:
                ids[ticker] = coin_id
        if not ids:
            return {}
        try:
            resp = await client.get(
                f"{settings.coingecko_api_url}/simple/price",
                params={"ids": ",".join(ids.values()), "vs_currencies": "brl"},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("coingecko_simple_price_failed", error=str(exc))
            return {}
    for ticker, coin_id in ids.items():
        price = (data.get(coin_id) or {}).get("brl")
        if price:
            out[ticker] = float(price)
    return out


async def _cdb_price(asset: Asset, factor_cache: dict[date, float | None]) -> float | None:
    """Accrued value per unit: entry price compounded by CDI since entry."""
    if asset.entry_date not in factor_cache:
        factor_cache[asset.entry_date] = await market_data_service.get_cdi_accumulated_factor(
            asset.entry_date
        )
    factor = factor_cache[asset.entry_date]
    if factor is None:
        return None
    effective = 1.0 + (factor - 1.0) * (settings.cdb_pct_cdi / 100.0)
    return float(asset.avg_price) * effective


async def refresh_prices(session: Session) -> dict[str, Any]:
    """Update ``current_price`` of every asset. Best-effort per asset.

    Returns ``{"updated": n, "warnings": [...]}`` — an asset whose source
    fails keeps its previous price and adds a warning.
    """
    assets = list(session.exec(select(Asset)).all())
    warnings: list[str] = []
    updated = 0

    crypto_tickers = sorted({a.ticker for a in assets if a.asset_class == AssetClass.CRYPTO})
    crypto_prices = await _crypto_prices_brl(crypto_tickers)
    cdi_factor_cache: dict[date, float | None] = {}

    for asset in assets:
        price: float | None = None
        if asset.asset_class == AssetClass.STOCKS:
            price = await _stock_price(asset.ticker)
        elif asset.asset_class == AssetClass.CRYPTO:
            price = crypto_prices.get(asset.ticker)
        else:  # fixed income: accrue by CDI
            price = await _cdb_price(asset, cdi_factor_cache)

        if price is None:
            warnings.append(f"{asset.ticker}: preço indisponível (mantido o anterior)")
            continue
        asset.current_price = Decimal(str(round(price, 8)))
        asset.updated_at = datetime.now(UTC)
        session.add(asset)
        updated += 1

    session.commit()
    logger.info("prices_refreshed", updated=updated, warnings=len(warnings))
    return {"updated": updated, "warnings": warnings}
