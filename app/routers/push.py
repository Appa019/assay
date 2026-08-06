from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.database import get_session
from app.services import webpush_service

router = APIRouter(prefix="/api/push", tags=["push"])


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(..., min_length=1, max_length=256)
    auth: str = Field(..., min_length=1, max_length=64)


class SubscriptionIn(BaseModel):
    """Exactly what ``PushSubscription.toJSON()`` produces in the browser."""

    endpoint: str = Field(..., min_length=1, max_length=1024)
    keys: SubscriptionKeys


class EndpointIn(BaseModel):
    endpoint: str = Field(..., min_length=1, max_length=1024)


@router.get("/vapid-public-key")
async def vapid_public_key() -> dict[str, str]:
    """The application server key the browser needs to subscribe."""
    return {"key": webpush_service.get_public_key()}


@router.post("/subscriptions", status_code=status.HTTP_201_CREATED)
async def subscribe(data: SubscriptionIn, session: Session = Depends(get_session)) -> dict:
    webpush_service.save_subscription(session, data.endpoint, data.keys.p256dh, data.keys.auth)
    return {"ok": True}


@router.delete("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(data: EndpointIn, session: Session = Depends(get_session)) -> None:
    if not webpush_service.delete_subscription(session, data.endpoint):
        raise HTTPException(status_code=404, detail="Inscrição não encontrada")


@router.post("/test")
def send_test() -> dict[str, int]:
    """Fire a real push to every device — the settings page's proof button.

    Sync route on purpose: pywebpush does blocking HTTP to the push service,
    and the threadpool keeps it off the event loop.
    """
    sent = webpush_service.notify(
        "Assay", "Notificações funcionando. É assim que aviso quando o consultor responder."
    )
    return {"sent": sent}
