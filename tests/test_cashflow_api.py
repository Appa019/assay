"""Ledger endpoints with a card in the picture: card names on reads, the
card filter, 422 on a bad card and the whole-purchase delete."""

from collections.abc import Iterator

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


def _card(client: TestClient) -> str:
    response = client.post("/api/cards", json={"name": "Nubank", "closing_day": 25, "due_day": 3})
    assert response.status_code == 201
    return response.json()["id"]


def _post(client: TestClient, **overrides: object) -> dict:
    payload = {
        "kind": "expense",
        "amount_brl": 300,
        "category": "lazer",
        "occurred_on": "2026-09-10",
    }
    payload.update(overrides)
    response = client.post("/api/cashflow", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_reads_carry_the_card_name(client: TestClient) -> None:
    card_id = _card(client)
    created = _post(client)
    assert created["card_id"] == card_id
    assert created["card_name"] == "Nubank"
    listed = client.get("/api/cashflow?month=2026-09").json()
    assert listed[0]["card_name"] == "Nubank"
    pix = _post(client, card="pix")
    assert pix["card_id"] is None and pix["card_name"] is None


def test_card_filter(client: TestClient) -> None:
    card_id = _card(client)
    _post(client)
    _post(client, card="pix", amount_brl=5)
    assert len(client.get(f"/api/cashflow?month=2026-09&card_id={card_id}").json()) == 1
    assert len(client.get("/api/cashflow?month=2026-09").json()) == 2


def test_unknown_card_and_installments_without_card_are_422(client: TestClient) -> None:
    unknown = client.post(
        "/api/cashflow", json={"kind": "expense", "amount_brl": 10, "card": "itau"}
    )
    assert unknown.status_code == 422
    assert "não cadastrado" in unknown.json()["detail"]
    parcelled = client.post(
        "/api/cashflow", json={"kind": "expense", "amount_brl": 10, "installments": 3}
    )
    assert parcelled.status_code == 422


def test_named_card_on_income_is_422(client: TestClient) -> None:
    _card(client)
    response = client.post(
        "/api/cashflow", json={"kind": "income", "amount_brl": 10, "card": "nubank"}
    )
    assert response.status_code == 422


@pytest.mark.parametrize("installments", [0, 49])
def test_installments_out_of_bounds_is_422(client: TestClient, installments: int) -> None:
    response = client.post(
        "/api/cashflow",
        json={"kind": "expense", "amount_brl": 10, "installments": installments},
    )
    assert response.status_code == 422


def test_installment_group_delete(client: TestClient) -> None:
    _card(client)
    first = _post(client, installments=3)
    assert first["installment_no"] == 1 and first["installment_count"] == 3
    group = first["installment_group"]
    assert group is not None
    response = client.delete(f"/api/cashflow/groups/{group}")
    assert response.status_code == 200 and response.json() == {"deleted": 3}
    assert client.delete(f"/api/cashflow/groups/{group}").status_code == 404
    assert client.get("/api/cashflow?month=2026-09").json() == []


def test_summary_exposes_card_expense(client: TestClient) -> None:
    _card(client)
    _post(client, amount_brl=100)
    _post(client, amount_brl=40, card="pix")
    summary = client.get("/api/cashflow/summary?month=2026-09").json()
    assert summary["expense_brl"] == 140.0
    assert summary["card_expense_brl"] == 100.0
