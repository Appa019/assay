from datetime import datetime
from typing import Any

from pydantic import BaseModel


class MacroIndicators(BaseModel):
    selic: float | None = None
    ipca_12m: float | None = None
    cdi: float | None = None
    usd_brl: float | None = None


class IbovespaSnapshot(BaseModel):
    level: float | None = None
    day_change_pct: float | None = None
    month_return_pct: float | None = None
    volume: float | None = None


class CryptoGlobal(BaseModel):
    btc_dominance: float | None = None
    eth_dominance: float | None = None
    total_market_cap_usd: float | None = None
    total_volume_24h_usd: float | None = None
    market_cap_change_24h_pct: float | None = None


class MacroSnapshot(BaseModel):
    macro: MacroIndicators
    ibovespa: IbovespaSnapshot
    crypto_global: CryptoGlobal
    fear_greed_index: int | None = None
    captured_at: datetime
    sources: dict[str, Any] = {}
    warnings: list[str] = []


class PortfolioAssetForPrompt(BaseModel):
    ticker: str
    name: str | None
    asset_class: str
    quantity: float
    avg_price: float
    current_price: float | None
    total_value: float
    pnl_pct: float | None
    days_in_portfolio: int
