"""Recurrence CRUD and the forecast endpoint — the surface the consultant
drives and the screen reads."""

from collections.abc import Iterator
from datetime import date

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


def _post(client: TestClient, **overrides: object) -> dict:
    payload: dict[str, object] = {
        "kind": "expense",
        "amount_brl": 2200,
        "category": "Moradia",
        "description": "aluguel",
        "day_of_month": 10,
    }
    payload.update(overrides)
    response = client.post("/api/recurrences", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_normalizes_and_defaults(client: TestClient) -> None:
    created = _post(client)
    assert created["category"] == "moradia"
    assert created["active"] is True
    assert created["card_id"] is None
    assert created["starts_on"] == date.today().replace(day=1).isoformat()


def test_card_name_rides_along(client: TestClient) -> None:
    client.post("/api/cards", json={"name": "Nubank", "closing_day": 25, "due_day": 5})
    created = _post(client, category="assinatura", amount_brl=49.9, card="auto")
    assert created["card_name"] == "Nubank"


def test_unknown_card_is_422(client: TestClient) -> None:
    response = client.post(
        "/api/recurrences",
        json={"kind": "expense", "amount_brl": 10, "category": "lazer", "card": "Itau"},
    )
    assert response.status_code == 422


def test_patch_updates_and_missing_is_404(client: TestClient) -> None:
    created = _post(client)
    response = client.patch(
        f"/api/recurrences/{created['id']}", json={"amount_brl": 2400, "ends_on": "2026-12-31"}
    )
    assert response.status_code == 200
    assert response.json()["amount_brl"] == 2400.0
    assert response.json()["ends_on"] == "2026-12-31"
    assert response.json()["description"] == "aluguel"

    missing = client.patch(
        "/api/recurrences/00000000-0000-0000-0000-000000000000", json={"amount_brl": 1}
    )
    assert missing.status_code == 404


def test_active_only_filter_and_delete(client: TestClient) -> None:
    created = _post(client)
    client.patch(f"/api/recurrences/{created['id']}", json={"active": False})
    assert client.get("/api/recurrences?active_only=true").json() == []
    assert len(client.get("/api/recurrences").json()) == 1

    assert client.delete(f"/api/recurrences/{created['id']}").status_code == 200
    assert client.get("/api/recurrences").json() == []
    assert client.delete(f"/api/recurrences/{created['id']}").status_code == 404


def test_forecast_has_one_entry_per_month_and_sums_commitments(client: TestClient) -> None:
    _post(client, kind="income", amount_brl=8000, category="salario", day_of_month=5)
    _post(client, starts_on="2020-01-01")

    body = client.get("/api/cashflow/forecast?months=3").json()
    assert len(body["months"]) == 3
    assert body["has_commitments"] is True
    assert body["total_income_brl"] == 24000.0
    assert body["total_expense_brl"] == 6600.0
    assert body["total_net_brl"] == 17400.0
    assert body["months"][0]["is_current"] is True
    assert {line["origin"] for line in body["months"][1]["lines"]} == {"recurring"}


def test_forecast_is_empty_and_clamped_without_commitments(client: TestClient) -> None:
    body = client.get("/api/cashflow/forecast?months=99").json()
    assert body["has_commitments"] is False
    assert len(body["months"]) == 24  # clamped, never unbounded
    assert body["total_net_brl"] == 0.0
