from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.core.database import init_db
from app.routers import (
    cadence,
    cards,
    cashflow,
    chat,
    contributions,
    macro,
    notifications,
    orders,
    portfolio,
    push,
    recurrences,
    reports,
    tax,
)
from app.services import chat_service

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        chat_service.reconcile_orphan_turns()
        # Drains whatever the last process left queued — a message waiting for
        # the usage window to reopen outlives the restart and is answered
        # without the client resending it.
        chat_service.start_queue_worker()
    except Exception:  # noqa: BLE001 — cleanup must never block startup
        logger.warning("chat_queue_startup_failed", exc_info=True)
    logger.info("app_started", db=settings.sqlite_path)
    yield
    logger.info("app_stopped")


app = FastAPI(
    title="Investimentos Manual",
    description="Ad-hoc contributions with a 5-meeting AI investment committee, fully local.",
    version="0.4.0",
    lifespan=lifespan,
)


allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
if settings.frontend_url and settings.frontend_url not in allowed_origins:
    allowed_origins.append(settings.frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@app.middleware("http")
async def refuse_cross_site_writes(request: Request, call_next):  # noqa: ANN001, ANN201
    """No login here: the tailnet is the only gate. A page on any other site,
    open in the phone's browser, could still POST here (a no-cors fetch or a
    form skips CORS) and start a committee run or plant a push subscription.
    Browsers stamp Sec-Fetch-Site and pages cannot forge it; the consultant's
    curl and the scripts send none and pass."""
    site = request.headers.get("sec-fetch-site")
    if request.method not in _SAFE_METHODS and site not in (None, "same-origin", "none"):
        return JSONResponse({"detail": "Pedido de outro site recusado."}, status_code=403)
    return await call_next(request)


app.include_router(portfolio.router)
app.include_router(contributions.router)
app.include_router(macro.router)
app.include_router(cadence.router)
app.include_router(reports.router)
app.include_router(orders.router)
app.include_router(tax.router)
app.include_router(cashflow.router)
app.include_router(cards.router)
app.include_router(recurrences.router)
app.include_router(chat.router)
app.include_router(push.router)
app.include_router(notifications.router)


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "version": "0.4.0"}
