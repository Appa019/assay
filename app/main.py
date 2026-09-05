from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.database import init_db
from app.routers import (
    cadence,
    cashflow,
    chat,
    contributions,
    macro,
    notifications,
    orders,
    portfolio,
    push,
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
    except Exception:  # noqa: BLE001 — cleanup must never block startup
        logger.warning("chat_orphan_reconcile_failed", exc_info=True)
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

app.include_router(portfolio.router)
app.include_router(contributions.router)
app.include_router(macro.router)
app.include_router(cadence.router)
app.include_router(reports.router)
app.include_router(orders.router)
app.include_router(tax.router)
app.include_router(cashflow.router)
app.include_router(chat.router)
app.include_router(push.router)
app.include_router(notifications.router)


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "version": "0.4.0"}
