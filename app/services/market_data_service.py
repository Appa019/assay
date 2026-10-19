"""Market data fetcher with multi-source fallbacks.

All public coroutines return best-effort data; on failure, they return None or a
dict with an ``error`` key plus a ``warnings`` list — never raise. The pipeline
captures warnings so the prompts know which fields to double-check via WebSearch.
"""

import asyncio
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
import structlog
import yfinance as yf

from app.config import settings

logger = structlog.get_logger()

# Brazilian Central Bank time-series codes
BCB_SELIC_META = 432
BCB_IPCA_12M = 13522
# 4389 = CDI annualized (% a.a., ~Selic). NOT 4391, which is the *monthly* CDI
# (% a.m.) and was injecting a wrong ~0.75 into the prompts.
BCB_CDI = 4389
# 12 = daily CDI (% a.d.) — used to compound fixed-income accrual per lot.
BCB_CDI_DAILY = 12
BCB_USD_BRL = 1


async def _fetch_bcb_series(series_id: int) -> Decimal | None:
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series_id}/dados/ultimos/1?formato=json"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list) and data:
                raw = data[-1].get("valor", "0")
                if isinstance(raw, str):
                    raw = raw.replace(",", ".")
                return Decimal(str(raw))
            logger.warning("bcb_empty_response", series=series_id)
    except Exception as exc:
        logger.warning("bcb_fetch_failed", series=series_id, error=str(exc))
    return None


async def get_cdi_accumulated_factor(start: date, end: date | None = None) -> float | None:
    """Compound daily CDI factor between two dates (BCB series 12).

    Returns e.g. 1.0123 for +1.23% over the window, or None on failure.
    Used to mark CDB lots to market: value = principal * factor ** (pct_cdi).
    """
    end = end or date.today()
    if start >= end:
        return 1.0
    url = (
        f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{BCB_CDI_DAILY}/dados"
        f"?formato=json&dataInicial={start.strftime('%d/%m/%Y')}"
        f"&dataFinal={end.strftime('%d/%m/%Y')}"
    )
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url)
            response.raise_for_status()
            rows = response.json()
        factor = 1.0
        for row in rows if isinstance(rows, list) else []:
            raw = str(row.get("valor", "0")).replace(",", ".")
            factor *= 1.0 + float(raw) / 100.0
        return factor
    except Exception as exc:
        logger.warning("cdi_accumulated_fetch_failed", error=str(exc))
        return None


async def get_macro_data() -> dict[str, Any]:
    selic, ipca, cdi, usd_brl = await asyncio.gather(
        _fetch_bcb_series(BCB_SELIC_META),
        _fetch_bcb_series(BCB_IPCA_12M),
        _fetch_bcb_series(BCB_CDI),
        _fetch_bcb_series(BCB_USD_BRL),
        return_exceptions=True,
    )

    def _to_float(v: Any) -> float | None:
        return float(v) if isinstance(v, Decimal) else None

    return {
        "selic": _to_float(selic),
        "ipca_12m": _to_float(ipca),
        "cdi": _to_float(cdi),
        "usd_brl": _to_float(usd_brl),
    }


async def get_ibovespa_snapshot() -> dict[str, Any]:
    def _fetch() -> dict[str, Any]:
        ticker = yf.Ticker("^BVSP")
        info = ticker.info
        hist = ticker.history(period="1mo")

        current = info.get("regularMarketPrice") or 0
        prev_close = info.get("regularMarketPreviousClose") or 0
        day_change = ((current - prev_close) / prev_close * 100) if prev_close else 0

        month_return = 0.0
        if len(hist) >= 2:
            first = float(hist["Close"].iloc[0])
            last = float(hist["Close"].iloc[-1])
            month_return = ((last - first) / first * 100) if first else 0

        return {
            "level": float(current) if current else None,
            "day_change_pct": round(day_change, 2),
            "month_return_pct": round(month_return, 2),
            "volume": info.get("regularMarketVolume"),
        }

    try:
        return await asyncio.wait_for(asyncio.to_thread(_fetch), timeout=15)
    except TimeoutError:
        logger.warning("ibovespa_fetch_timeout", timeout=15)
        return {}
    except Exception as exc:
        logger.warning("ibovespa_fetch_failed", error=str(exc))
        return {}


# Common B3 suffixes to try, in order. We need fallbacks because Yahoo sometimes
# only indexes one variation (e.g. PETR4.SA works, PETR4 does not).
_B3_SUFFIXES = (".SA", ".SAO", "")


async def get_stock_fundamentals(ticker: str) -> dict[str, Any]:
    """Best-effort fetch with suffix fallbacks. Always returns a dict."""
    warnings: list[str] = []
    original = ticker.upper().strip()
    candidates: list[str] = []
    if "." in original:
        candidates.append(original)
    else:
        for suffix in _B3_SUFFIXES:
            candidates.append(f"{original}{suffix}" if suffix else original)

    def _try_one(symbol: str) -> dict[str, Any] | None:
        try:
            stock = yf.Ticker(symbol)
            info = stock.info or {}
            if not info or info.get("regularMarketPrice") is None:
                return None
            hist = stock.history(period="3mo")
            rsi = _calculate_rsi(hist["Close"]) if len(hist) > 14 else None
            return_30d: float | None = None
            if len(hist) >= 22:
                recent = float(hist["Close"].iloc[-1])
                past = float(hist["Close"].iloc[-22])
                if past:
                    return_30d = round(((recent - past) / past * 100), 2)

            return {
                "resolved_symbol": symbol,
                "price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "currency": info.get("currency"),
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "peg_ratio": info.get("pegRatio"),
                "price_to_book": info.get("priceToBook"),
                "roe": _pct(info.get("returnOnEquity")),
                "ebitda_margin": _pct(info.get("ebitdaMargins")),
                "profit_margin": _pct(info.get("profitMargins")),
                "debt_to_equity": info.get("debtToEquity"),
                "current_ratio": info.get("currentRatio"),
                "dividend_yield": _yield_pct(info.get("dividendYield")),
                "payout_ratio": _pct(info.get("payoutRatio")),
                "market_cap": info.get("marketCap"),
                "enterprise_value": info.get("enterpriseValue"),
                "avg_volume_20d": info.get("averageVolume"),
                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                "rsi_14": rsi,
                "return_30d_pct": return_30d,
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "long_name": info.get("longName") or info.get("shortName"),
                "country": info.get("country"),
            }
        except Exception as exc:
            warnings.append(f"yfinance {symbol}: {exc}")
            return None

    resolved: dict[str, Any] | None = None
    for candidate in candidates:
        try:
            data = await asyncio.wait_for(asyncio.to_thread(_try_one, candidate), timeout=12)
        except TimeoutError:
            warnings.append(f"yfinance {candidate}: timeout 12s")
            continue
        if data is not None:
            resolved = data
            break

    if resolved is None:
        return {
            "ticker": original,
            "error": "ticker_not_found",
            "warnings": warnings or [f"Could not resolve {original} on yfinance"],
            "hint": "Validate ticker via WebSearch (B3 listings) or use a search engine to find the correct symbol.",
        }

    resolved["ticker"] = original
    resolved["warnings"] = warnings
    return resolved


async def get_crypto_metrics(coin_id: str) -> dict[str, Any]:
    """Fetch from CoinGecko with id-search fallback."""
    coin_id = coin_id.lower().strip()
    warnings: list[str] = []
    headers = {}
    if settings.coingecko_api_key:
        headers["x-cg-demo-api-key"] = settings.coingecko_api_key

    async def _get_coin(coin: str) -> dict[str, Any] | None:
        url = (
            f"{settings.coingecko_api_url}/coins/{coin}"
            "?localization=false&tickers=false&community_data=false"
            "&developer_data=false&sparkline=false"
        )
        try:
            async with httpx.AsyncClient(timeout=15, headers=headers) as client:
                response = await client.get(url)
                if response.status_code == 404:
                    warnings.append(f"CoinGecko 404 for id '{coin}'")
                    return None
                if response.status_code == 429:
                    warnings.append(f"CoinGecko rate limit (429) on '{coin}'")
                    logger.warning("coingecko_rate_limit", coin=coin)
                    return None
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            warnings.append(f"CoinGecko error {coin}: {exc}")
            return None

    data = await _get_coin(coin_id)

    # Fallback: search by query if id lookup failed
    if data is None:
        try:
            async with httpx.AsyncClient(timeout=10, headers=headers) as client:
                search = await client.get(
                    f"{settings.coingecko_api_url}/search",
                    params={"query": coin_id},
                )
                if search.status_code == 200:
                    payload = search.json()
                    coins = payload.get("coins", [])
                    if coins:
                        resolved_id = coins[0].get("id")
                        if resolved_id and resolved_id != coin_id:
                            warnings.append(f"Resolved '{coin_id}' to '{resolved_id}' via search")
                            data = await _get_coin(resolved_id)
                            coin_id = resolved_id
        except Exception as exc:
            warnings.append(f"CoinGecko search error: {exc}")

    if data is None:
        return {
            "ticker": coin_id,
            "error": "coin_not_found",
            "warnings": warnings,
            "hint": "Use WebSearch to find the correct CoinGecko id (e.g. 'bitcoin', 'ethereum').",
        }

    market = data.get("market_data", {})
    return {
        "ticker": coin_id,
        "resolved_id": data.get("id"),
        "name": data.get("name"),
        "symbol": (data.get("symbol") or "").upper(),
        "price_brl": market.get("current_price", {}).get("brl"),
        "price_usd": market.get("current_price", {}).get("usd"),
        "market_cap_usd": market.get("market_cap", {}).get("usd"),
        "market_cap_rank": data.get("market_cap_rank"),
        "fully_diluted_valuation_usd": market.get("fully_diluted_valuation", {}).get("usd"),
        "total_volume_24h_usd": market.get("total_volume", {}).get("usd"),
        "circulating_supply": market.get("circulating_supply"),
        "total_supply": market.get("total_supply"),
        "max_supply": market.get("max_supply"),
        "ath_usd": market.get("ath", {}).get("usd"),
        "ath_change_pct": market.get("ath_change_percentage", {}).get("usd"),
        "atl_usd": market.get("atl", {}).get("usd"),
        "atl_change_pct": market.get("atl_change_percentage", {}).get("usd"),
        "change_24h_pct": market.get("price_change_percentage_24h"),
        "change_7d_pct": market.get("price_change_percentage_7d"),
        "change_30d_pct": market.get("price_change_percentage_30d"),
        "change_60d_pct": market.get("price_change_percentage_60d"),
        "change_200d_pct": market.get("price_change_percentage_200d"),
        "change_1y_pct": market.get("price_change_percentage_1y"),
        "categories": data.get("categories", []),
        "platforms": data.get("platforms", {}),
        "warnings": warnings,
    }


async def get_btc_dominance() -> dict[str, Any]:
    headers = {}
    if settings.coingecko_api_key:
        headers["x-cg-demo-api-key"] = settings.coingecko_api_key
    try:
        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            response = await client.get(f"{settings.coingecko_api_url}/global")
            response.raise_for_status()
            data = response.json().get("data", {})
        return {
            "btc_dominance": round(data.get("market_cap_percentage", {}).get("btc", 0), 2),
            "eth_dominance": round(data.get("market_cap_percentage", {}).get("eth", 0), 2),
            "total_market_cap_usd": data.get("total_market_cap", {}).get("usd"),
            "total_volume_24h_usd": data.get("total_volume", {}).get("usd"),
            "market_cap_change_24h_pct": data.get("market_cap_change_percentage_24h_usd"),
            "active_cryptocurrencies": data.get("active_cryptocurrencies"),
            "markets": data.get("markets"),
        }
    except Exception as exc:
        logger.warning("btc_dominance_fetch_failed", error=str(exc))
        return {}


async def get_fear_greed_index() -> int | None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get("https://api.alternative.me/fng/?limit=1")
            response.raise_for_status()
            data = response.json()
            if data.get("data"):
                return int(data["data"][0]["value"])
    except Exception as exc:
        logger.warning("fear_greed_fetch_failed", error=str(exc))
    return None


async def enrich_stock_candidates(tickers: list[str]) -> list[dict[str, Any]]:
    if not tickers:
        return []
    sem = asyncio.Semaphore(3)

    async def _fetch(ticker: str) -> dict[str, Any]:
        async with sem:
            return await get_stock_fundamentals(ticker)

    return await asyncio.gather(*[_fetch(t) for t in tickers])


async def enrich_crypto_candidates(coin_ids: list[str]) -> list[dict[str, Any]]:
    if not coin_ids:
        return []
    sem = asyncio.Semaphore(2)

    async def _fetch(coin_id: str) -> dict[str, Any]:
        async with sem:
            return await get_crypto_metrics(coin_id)

    return await asyncio.gather(*[_fetch(c) for c in coin_ids])


# Short-lived cache: every dashboard refresh hits /api/macro, and each build
# fans out to BCB + Yahoo + CoinGecko + alternative.me. TTL keeps us far away
# from their rate limits without ever serving stale-by-minutes data.
_context_cache: dict[str, Any] = {"at": 0.0, "value": None}
_context_lock = asyncio.Lock()


async def build_full_context(*, force: bool = False) -> dict[str, Any]:
    async with _context_lock:
        age = time.monotonic() - _context_cache["at"]
        if not force and _context_cache["value"] is not None and age < settings.market_cache_ttl:
            return _context_cache["value"]
        context = await _build_full_context_uncached()
        _context_cache["at"] = time.monotonic()
        _context_cache["value"] = context
        return context


async def _build_full_context_uncached() -> dict[str, Any]:
    macro, ibov, btc_dom, fear_greed = await asyncio.gather(
        get_macro_data(),
        get_ibovespa_snapshot(),
        get_btc_dominance(),
        get_fear_greed_index(),
        return_exceptions=True,
    )

    warnings: list[str] = []

    def _safe(value: Any, fallback: Any, name: str) -> Any:
        if isinstance(value, Exception):
            warnings.append(f"{name}: {value}")
            return fallback
        return value

    macro_data = _safe(macro, {}, "macro")
    # A BCB outage returns nulls, not an exception: without this line the app
    # showed four dashes under "qualquer dado faltante será sinalizado" and
    # the prompts carried no warning at all (2026-10-18, BCB API down).
    missing = [
        label
        for key, label in (
            ("selic", "Selic"),
            ("ipca_12m", "IPCA 12m"),
            ("cdi", "CDI"),
            ("usd_brl", "USD/BRL"),
        )
        if isinstance(macro_data, dict) and macro_data.get(key) is None
    ]
    if missing:
        warnings.append(f"BCB sem resposta: {', '.join(missing)} sem dado (pesquisar ao vivo)")

    context = {
        "macro": macro_data,
        "ibovespa": _safe(ibov, {}, "ibovespa"),
        "crypto_global": _safe(btc_dom, {}, "crypto_global"),
        "fear_greed_index": _safe(fear_greed, None, "fear_greed"),
        "captured_at": datetime.now(UTC).isoformat(),
        "sources": {
            "macro": "BCB / api.bcb.gov.br",
            "ibovespa": "Yahoo Finance (^BVSP)",
            "crypto_global": "CoinGecko /global",
            "fear_greed": "alternative.me/fng",
        },
        "warnings": warnings,
    }

    logger.info("market_context_built", warnings=len(warnings))
    return context


def _calculate_rsi(prices: Any, period: int = 14) -> float | None:
    try:
        delta = prices.diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        value = float(rsi.iloc[-1])
        return round(value, 1) if value == value else None
    except Exception:
        return None


def _pct(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 100, 2)


def _yield_pct(value: float | None) -> float | None:
    """Normalize a yield that may come as fraction (0.065) or percent (6.5).

    Recent yfinance versions return ``dividendYield`` already in percent;
    older ones returned a fraction — multiplying blindly inflated it 100x.
    B3 yields above 100% don't exist, so >1.5 is safely "already percent".
    """
    if value is None:
        return None
    return round(value if value > 1.5 else value * 100, 2)
