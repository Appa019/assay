"""Web Push to the installed PWA — the phone buzzes when Assay has news.

Standard Web Push (RFC 8291/8292): the payload is encrypted end to end with
the subscription's own keys, so Apple/Google only relay opaque bytes — nothing
readable leaves the VPN. VAPID keys are generated once on first use and live
in ``storage/webpush/`` (gitignored, survives deploys); there is nothing to
configure by hand.

First (and so far only) producer: the consultant finishing a reply that was
asked through the site — an opus/max turn takes minutes and nobody stares at
a spinner that long.
"""

import json
from pathlib import Path

import structlog
from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid, b64urlencode
from pywebpush import WebPushException, webpush
from sqlmodel import Session, select

from app.core.database import engine
from app.models.push_subscription import PushSubscription

logger = structlog.get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_KEY_DIR = _PROJECT_ROOT / "storage" / "webpush"
_PRIVATE_PEM = _KEY_DIR / "vapid_private.pem"
_PUBLIC_KEY = _KEY_DIR / "vapid_public.txt"

# Contact claim required by the push services; a syntactically valid mailto
# is all they check. Single-user private app — nothing routes here.
_VAPID_SUB = "mailto:assay@raspberrypi.local"

_TTL_SECONDS = 3600  # a stale "reply ready" ping is worthless after an hour


def _public_key_from_pem(pem: bytes) -> str:
    vapid = Vapid.from_pem(pem)
    return b64urlencode(
        vapid.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )


def get_public_key() -> str:
    """The VAPID application server key (base64url), generating it on first use."""
    if _PRIVATE_PEM.exists():
        return _public_key_from_pem(_PRIVATE_PEM.read_bytes())
    _KEY_DIR.mkdir(parents=True, exist_ok=True)
    vapid = Vapid()
    vapid.generate_keys()
    pem = vapid.private_pem()
    _PRIVATE_PEM.write_bytes(pem)
    _PRIVATE_PEM.chmod(0o600)
    public = _public_key_from_pem(pem)
    _PUBLIC_KEY.write_text(public, encoding="utf-8")
    logger.info("webpush_vapid_generated")
    return public


def save_subscription(session: Session, endpoint: str, p256dh: str, auth: str) -> None:
    """Upsert: the endpoint is the device identity, re-subscribing replaces it."""
    row = session.get(PushSubscription, endpoint)
    if row is None:
        row = PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth)
    else:
        row.p256dh = p256dh
        row.auth = auth
    session.add(row)
    session.commit()
    logger.info("webpush_subscribed", endpoint=endpoint[:60])


def delete_subscription(session: Session, endpoint: str) -> bool:
    row = session.get(PushSubscription, endpoint)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    logger.info("webpush_unsubscribed", endpoint=endpoint[:60])
    return True


def subscription_count() -> int:
    with Session(engine) as session:
        return len(session.exec(select(PushSubscription)).all())


def notify(title: str, body: str, url: str = "/consultor") -> int:
    """Push to every subscribed device. Best-effort: returns the sent count.

    A push service answering 404/410 means the subscription is gone (app
    removed, permission revoked) — the row is deleted so dead endpoints don't
    accumulate. Any other failure is logged and swallowed: a missed buzz must
    never break the turn that triggered it.
    """
    try:
        payload = json.dumps({"title": title, "body": body[:400], "url": url})
        with Session(engine) as session:
            subscriptions = list(session.exec(select(PushSubscription)).all())
            if not subscriptions:
                return 0
            if not _PRIVATE_PEM.exists():
                get_public_key()
            sent = 0
            for sub in subscriptions:
                try:
                    webpush(
                        subscription_info={
                            "endpoint": sub.endpoint,
                            "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                        },
                        data=payload,
                        vapid_private_key=str(_PRIVATE_PEM),
                        # Fresh dict per call: pywebpush mutates it to add the
                        # per-push-service `aud` claim.
                        vapid_claims={"sub": _VAPID_SUB},
                        ttl=_TTL_SECONDS,
                    )
                    sent += 1
                except WebPushException as exc:
                    status = getattr(exc.response, "status_code", None)
                    if status in (404, 410):
                        session.delete(sub)
                        session.commit()
                        logger.info("webpush_subscription_gone", endpoint=sub.endpoint[:60])
                    else:
                        logger.warning("webpush_send_failed", status=status, error=str(exc)[:200])
            return sent
    except Exception:  # noqa: BLE001 — notifications are extras, never blockers
        logger.warning("webpush_notify_failed", exc_info=True)
        return 0
