from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.core.database import get_session
from app.models.order import OrderStatus
from app.schemas.order import OrderExecute, OrderRead, OrderSkip
from app.services import order_service

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.get("", response_model=list[OrderRead])
async def list_orders(
    status: OrderStatus | None = None,
    session: Session = Depends(get_session),
) -> list[OrderRead]:
    orders = order_service.list_orders(session, status=status)
    return [OrderRead.model_validate(o, from_attributes=True) for o in orders]


@router.post("/{order_id}/execute", response_model=OrderRead)
async def execute_order(
    order_id: UUID,
    payload: OrderExecute,
    session: Session = Depends(get_session),
) -> OrderRead:
    """Record the real fill and create the Asset lot (thesis/targets carried)."""
    try:
        order = order_service.execute_order(
            session, order_id, quantity=payload.quantity, price=payload.price
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return OrderRead.model_validate(order, from_attributes=True)


@router.post("/{order_id}/skip", response_model=OrderRead)
async def skip_order(
    order_id: UUID,
    payload: OrderSkip,
    session: Session = Depends(get_session),
) -> OrderRead:
    try:
        order = order_service.skip_order(session, order_id, reason=payload.reason)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return OrderRead.model_validate(order, from_attributes=True)
