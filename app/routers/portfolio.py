from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.asset import (
    AssetCreate,
    AssetRead,
    AssetUpdate,
    PortfolioSummary,
    SaleResult,
)
from app.services import portfolio_service

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


@router.delete("/assets/{asset_id}", response_model=AssetRead)
async def delete_asset(asset_id: UUID, session: Session = Depends(get_session)) -> AssetRead:
    try:
        asset = portfolio_service.delete_asset(session, asset_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AssetRead.model_validate(asset, from_attributes=True)
