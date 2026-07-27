from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401 — register all tables on the metadata
from app.models.asset import Asset, AssetClass


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})

    # Mirror production PRAGMAs: FK enforcement changes delete semantics, and a
    # test engine without it would hide ordering bugs (it did, once).
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


@pytest.fixture()
def stock_locked(session: Session) -> Asset:
    """A stock lot bought 5 days ago — still inside the 30-day lock."""
    asset = Asset(
        ticker="PETR4",
        asset_class=AssetClass.STOCKS,
        quantity=Decimal("100"),
        avg_price=Decimal("38.50"),
        current_price=Decimal("40.00"),
        entry_date=date.today() - timedelta(days=5),
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@pytest.fixture()
def stock_unlocked(session: Session) -> Asset:
    """A stock lot bought 45 days ago — past the lock."""
    asset = Asset(
        ticker="VALE3",
        asset_class=AssetClass.STOCKS,
        quantity=Decimal("50"),
        avg_price=Decimal("60.00"),
        current_price=Decimal("66.00"),
        entry_date=date.today() - timedelta(days=45),
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@pytest.fixture()
def cdb(session: Session) -> Asset:
    asset = Asset(
        ticker="CDB-ITAU",
        asset_class=AssetClass.FIXED_INCOME,
        quantity=Decimal("1"),
        avg_price=Decimal("5000.00"),
        current_price=Decimal("5010.00"),
        entry_date=date.today() - timedelta(days=2),
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@pytest.fixture()
def isolated_runner_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Point every filesystem side-effect of analysis_runner at tmp_path."""
    from app.services import analysis_runner as ar

    monkeypatch.setattr(ar, "WORKSPACE", tmp_path / "workspace")
    monkeypatch.setattr(ar, "_RUN_LOCK_DIR", tmp_path / "locks")
    monkeypatch.setattr(ar, "_TRANSCRIPT_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(ar, "_sleep", lambda _s: None)
    return tmp_path
