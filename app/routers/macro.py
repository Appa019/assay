from typing import Any

from fastapi import APIRouter

from app.services import market_data_service

router = APIRouter(prefix="/api/macro", tags=["macro"])


@router.get("")
async def get_macro_snapshot() -> dict[str, Any]:
    """Best-effort macro snapshot used to preview the data injected into prompts."""
    return await market_data_service.build_full_context()
