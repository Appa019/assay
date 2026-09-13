"""HTTP surface of the card registry: status codes and the embedded invoices."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.database import get_session
from app.main import app
from app.models.cashflow import CashflowEntry, CashflowKind


@pytest.fixture()
def client(session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _create(client: TestClient, name: str = "Nubank", closing: int = 25, due: int = 3) -> dict:
    response = client.post(
        "/api/cards", json={"name": name, "closing_day": closing, "due_day": due}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_and_list_embed_the_open_invoice(client: TestClient) -> None:
    created = _create(client)
    assert created["is_default"] is True
    assert created["open_invoice"]["status"] == "open"
    assert created["last_closed_invoice"] is None
    listed = client.get("/api/cards").json()
    assert [c["name"] for c in listed] == ["Nubank"]


def test_duplicate_name_is_409(client: TestClient) -> None:
    _create(client)
    response = client.post("/api/cards", json={"name": "nubank", "closing_day": 1, "due_day": 10})
    assert response.status_code == 409


def test_day_out_of_range_is_422(client: TestClient) -> None:
    response = client.post("/api/cards", json={"name": "X", "closing_day": 32, "due_day": 3})
    assert response.status_code == 422


def test_blank_name_is_422(client: TestClient) -> None:
    response = client.post("/api/cards", json={"name": "   ", "closing_day": 1, "due_day": 3})
    assert response.status_code == 422


def test_patch_default_and_refuse_unsetting_it(client: TestClient) -> None:
    first = _create(client, "Nubank")
    second = _create(client, "Itaú")
    promoted = client.patch(f"/api/cards/{second['id']}", json={"is_default": True})
    assert promoted.status_code == 200 and promoted.json()["is_default"] is True
    assert client.get("/api/cards").json()[0]["is_default"] is False  # Nubank demoted
    refused = client.patch(f"/api/cards/{second['id']}", json={"is_default": False})
    assert refused.status_code == 422
    assert client.patch(f"/api/cards/{first['id']}", json={"name": "Itaú"}).status_code == 409


def test_delete_in_use_is_409_and_unknown_is_404(client: TestClient, session: Session) -> None:
    card = _create(client)
    session.add(
        CashflowEntry(
            kind=CashflowKind.EXPENSE,
            amount_brl=Decimal("10"),
            occurred_on=date(2026, 9, 1),
            card_id=UUID(card["id"]),
        )
    )
    session.commit()
    assert client.delete(f"/api/cards/{card['id']}").status_code == 409
    assert client.delete("/api/cards/00000000-0000-0000-0000-000000000000").status_code == 404


def test_delete_unused_card_returns_it(client: TestClient) -> None:
    card = _create(client)
    response = client.delete(f"/api/cards/{card['id']}")
    assert response.status_code == 200
    assert response.json()["name"] == "Nubank"
    assert client.get("/api/cards").json() == []


def test_invoices_history_is_oldest_first_and_capped(client: TestClient) -> None:
    card = _create(client)
    history = client.get(f"/api/cards/{card['id']}/invoices?months=3").json()
    assert len(history) == 3
    assert history[0]["closes_on"] < history[-1]["closes_on"]
    assert history[-1]["status"] == "open"
    assert len(client.get(f"/api/cards/{card['id']}/invoices?months=99").json()) == 24
    assert client.get("/api/cards/00000000-0000-0000-0000-000000000000/invoices").status_code == 404
