"""Writes from another site are refused; the app's own pages and header-less
callers (the consultant's curl, scripts) pass. POST /api/health has no route,
so a request that gets through answers 405 and a refused one 403."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_write_from_another_site_is_refused(site: str) -> None:
    resp = client.post("/api/health", headers={"Sec-Fetch-Site": site})
    assert resp.status_code == 403


@pytest.mark.parametrize("headers", [{}, {"Sec-Fetch-Site": "same-origin"}])
def test_own_pages_and_curl_get_through(headers: dict[str, str]) -> None:
    assert client.post("/api/health", headers=headers).status_code == 405


def test_reads_are_never_blocked() -> None:
    assert client.get("/api/health", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200
