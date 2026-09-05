from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.core.database import get_session
from app.models.order import Order, OrderStatus
from app.schemas.order import OrderExecute, OrderRead, OrderSkip, TicketLineRead
from app.services import order_service, order_sizing

router = APIRouter(prefix="/api/orders", tags=["orders"])


def _to_read(order: Order) -> OrderRead:
    """Attach the derived broker ticket to the stored order."""
    payload = OrderRead.model_validate(order, from_attributes=True)
    payload.ticket = [
        TicketLineRead(
            ticker=line.ticker,
            quantity=float(line.quantity),
            price=float(line.price),
            book=line.book,
            total_brl=float(line.total_brl),
        )
        for line in order_sizing.ticket_lines(
            ticker=order.ticker,
            asset_class=order.asset_class,
            amount_brl=order.amount_brl,
            quantity=order.suggested_quantity,
            price=order.reference_price,
        )
    ]
    return payload


@router.get("", response_model=list[OrderRead])
async def list_orders(
    status: OrderStatus | None = None,
    session: Session = Depends(get_session),
) -> list[OrderRead]:
    orders = order_service.list_orders(session, status=status)
    return [_to_read(o) for o in orders]


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
    return _to_read(order)


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
    return _to_read(order)
