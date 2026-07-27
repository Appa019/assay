from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.asset import (
    AssetCreate,
    AssetRead,
    AssetUpdate,
    PortfolioSummary,
    RefreshResult,
    SaleResult,
    SnapshotRead,
    TradeRead,
)
from app.services import portfolio_service, price_refresh_service

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("", response_model=PortfolioSummary)
async def get_portfolio(session: Session = Depends(get_session)) -> PortfolioSummary:
    return portfolio_service.get_portfolio_summary(session)


@router.get("/assets", response_model=list[AssetRead])
async def list_assets(session: Session = Depends(get_session)) -> list[AssetRead]:
    assets = portfolio_service.list_assets(session)
    return [AssetRead.model_validate(a, from_attributes=True) for a in assets]


@router.post("/assets", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
async def create_asset(payload: AssetCreate, session: Session = Depends(get_session)) -> AssetRead:
    asset = portfolio_service.create_asset(session, payload)
    return AssetRead.model_validate(asset, from_attributes=True)


@router.patch("/assets/{asset_id}", response_model=AssetRead)
async def update_asset(
    asset_id: UUID,
    payload: AssetUpdate,
    session: Session = Depends(get_session),
) -> AssetRead:
    try:
        asset = portfolio_service.update_asset(session, asset_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AssetRead.model_validate(asset, from_attributes=True)


@router.post("/assets/{asset_id}/sell", response_model=SaleResult)
async def sell_asset(asset_id: UUID, session: Session = Depends(get_session)) -> SaleResult:
    try:
        return portfolio_service.sell_asset(session, asset_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except portfolio_service.SellLockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/assets/{asset_id}", response_model=AssetRead)
async def delete_asset(asset_id: UUID, session: Session = Depends(get_session)) -> AssetRead:
    try:
        asset = portfolio_service.delete_asset(session, asset_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AssetRead.model_validate(asset, from_attributes=True)


@router.post("/refresh", response_model=RefreshResult)
async def refresh_prices(session: Session = Depends(get_session)) -> RefreshResult:
    """Mark every lot to market (stocks, crypto, CDB accrual). Best-effort."""
    result = await price_refresh_service.refresh_prices(session)
    return RefreshResult(**result)


@router.get("/history", response_model=list[SnapshotRead])
async def portfolio_history(
    days: int = Query(default=365, ge=1, le=3650),
    session: Session = Depends(get_session),
) -> list[SnapshotRead]:
    snapshots = portfolio_service.get_portfolio_history(session, days=days)
    return [SnapshotRead.model_validate(s, from_attributes=True) for s in snapshots]


@router.get("/trades", response_model=list[TradeRead])
async def list_trades(
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> list[TradeRead]:
    trades = portfolio_service.list_trades(session, limit=limit)
    return [TradeRead.model_validate(t, from_attributes=True) for t in trades]
