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
