from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.asset import AssetClass
from app.models.trade import TradeSide


class AssetCreate(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=32)
    name: str | None = Field(default=None, max_length=128)
    asset_class: AssetClass
    quantity: Decimal = Field(..., gt=0)
    avg_price: Decimal = Field(..., gt=0)
    current_price: Decimal | None = Field(default=None, ge=0)
    entry_date: date | None = None
    held_abroad: bool = False

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, v: str) -> str:
        return v.strip().upper()

    @model_validator(mode="after")
    def _abroad_only_for_crypto(self) -> "AssetCreate":
        if self.held_abroad and self.asset_class != AssetClass.CRYPTO:
            raise ValueError("held_abroad só vale para crypto (ações e CDB são do Brasil)")
        return self


class AssetUpdate(BaseModel):
    # No quantity/avg_price: those move only through a buy or a sell, so the
    # Trade ledger, the benchmark flows and realized P&L stay true.
    name: str | None = None
    current_price: Decimal | None = Field(default=None, ge=0)
    thesis: str | None = Field(default=None, max_length=2000)
    target_price: Decimal | None = Field(default=None, ge=0)
    stop_price: Decimal | None = Field(default=None, ge=0)
    # Fixing a lot registered at the wrong place; applies to its future sales.
    held_abroad: bool | None = None


class AssetRead(BaseModel):
    id: UUID
    ticker: str
    name: str | None
    asset_class: AssetClass
    quantity: float
    avg_price: float
    current_price: float | None
    thesis: str | None = None
    target_price: float | None = None
    stop_price: float | None = None
    entry_date: date
    held_abroad: bool = False
    # Sell lock resolved by the backend (per class, per lot): total days the lot
    # must be held and how many are left. Clients render these instead of
    # re-deriving the rule.
    lock_days_total: int = 0
    lock_days_left: int = 0
    created_at: datetime
    updated_at: datetime


class AllocationBreakdown(BaseModel):
    total_value: float = 0.0
    fixed_income: float = 0.0
    stocks: float = 0.0
    crypto: float = 0.0
    fixed_income_pct: float = 0.0
    stocks_pct: float = 0.0
    crypto_pct: float = 0.0


class PortfolioSummary(BaseModel):
    total_value: float
    allocation: AllocationBreakdown
    target_allocation: dict[str, float]
    deviation: dict[str, float]
    # Sell lock per class, in days (0 = daily liquidity). Part of the mandate,
    # like the targets above, so clients state the rule without hardcoding it.
    holding_lock_days: dict[str, int]
    assets: list[AssetRead]


class SellPayload(BaseModel):
    """Real execution data for a sale. Both optional: omitted price falls back
    to the marked price, omitted quantity sells the whole lot."""

    price: Decimal | None = Field(default=None, gt=0)
    quantity: Decimal | None = Field(default=None, gt=0)


class SaleResult(BaseModel):
    ticker: str
    quantity: float
    price: float
    sale_value: float
    asset_class: AssetClass
    message: str


class TradeRead(BaseModel):
    id: UUID
    ticker: str
    name: str | None
    asset_class: AssetClass
    side: TradeSide
    quantity: float
    price: float
    total_brl: float
    realized_pnl_brl: float | None
    realized_pnl_pct: float | None
    lot_entry_date: date | None
    executed_at: datetime


class SnapshotRead(BaseModel):
    snapshot_date: date
    total_value: float
    fixed_income: float
    stocks: float
    crypto: float


class RefreshResult(BaseModel):
    updated: int
    warnings: list[str]
