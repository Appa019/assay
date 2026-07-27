from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

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

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, v: str) -> str:
        return v.strip().upper()


class AssetUpdate(BaseModel):
    name: str | None = None
    quantity: Decimal | None = Field(default=None, gt=0)
    avg_price: Decimal | None = Field(default=None, gt=0)
    current_price: Decimal | None = Field(default=None, ge=0)
    thesis: str | None = Field(default=None, max_length=2000)
    target_price: Decimal | None = Field(default=None, ge=0)
    stop_price: Decimal | None = Field(default=None, ge=0)


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
    assets: list[AssetRead]


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
