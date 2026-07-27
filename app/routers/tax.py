from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.core.database import get_session
from app.services import tax_service

router = APIRouter(prefix="/api/tax", tags=["tax"])


@router.get("/{year}")
async def year_report(year: int, session: Session = Depends(get_session)) -> dict:
    """Simplified IR map: monthly DARF per class + year-end positions."""
    if not 2020 <= year <= date.today().year:
        raise HTTPException(status_code=422, detail="Ano fora do intervalo suportado")
    return tax_service.build_year_report(session, year)
