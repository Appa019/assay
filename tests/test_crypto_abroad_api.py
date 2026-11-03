"""HTTP path of the held_abroad flag: lot → sell → IR report."""

from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.database import get_session
from app.main import app


@pytest.fixture()
def client(session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _lot(client: TestClient, **extra: object) -> dict:
    body = {
        "ticker": "BTC",
        "asset_class": "crypto",
        "quantity": 1,
        "avg_price": 10000,
        "entry_date": (date.today() - timedelta(days=30)).isoformat(),
        **extra,
    }
    return client.post("/api/portfolio/assets", json=body)


def test_abroad_sale_reaches_the_annual_block_not_the_darf(client: TestClient) -> None:
    lot = _lot(client, held_abroad=True)
    assert lot.status_code == 201, lot.text
    assert lot.json()["held_abroad"] is True
    sold = client.post(f"/api/portfolio/assets/{lot.json()['id']}/sell", json={"price": 50000})
    assert sold.status_code == 200, sold.text

    report = client.get(f"/api/tax/{date.today().year}").json()
    assert report["total_darf_brl"] == 0.0
    assert report["crypto_abroad"]["tax_due_brl"] == 6000.0  # 40k gain × 15%
    assert all(m["crypto"]["sales_brl"] == 0.0 for m in report["months"])


def test_default_lot_is_national(client: TestClient) -> None:
    lot = _lot(client)
    assert lot.json()["held_abroad"] is False


def test_abroad_flag_on_a_stock_is_rejected(client: TestClient) -> None:
    assert _lot(client, asset_class="stocks", ticker="PETR4", held_abroad=True).status_code == 422
    stock = _lot(client, asset_class="stocks", ticker="PETR4").json()
    patched = client.patch(f"/api/portfolio/assets/{stock['id']}", json={"held_abroad": True})
    assert patched.status_code == 422
