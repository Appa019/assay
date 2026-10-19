import asyncio

import pytest

from app.services import market_data_service as mds


def test_bcb_outage_becomes_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """The BCB API answering nothing used to look like a clean snapshot."""

    async def macro() -> dict:
        return {"selic": None, "ipca_12m": None, "cdi": 14.9, "usd_brl": None}

    async def anything() -> dict:
        return {}

    async def fear_greed() -> int:
        return 50

    monkeypatch.setattr(mds, "get_macro_data", macro)
    monkeypatch.setattr(mds, "get_ibovespa_snapshot", anything)
    monkeypatch.setattr(mds, "get_btc_dominance", anything)
    monkeypatch.setattr(mds, "get_fear_greed_index", fear_greed)
    context = asyncio.run(mds._build_full_context_uncached())
    assert any("Selic, IPCA 12m, USD/BRL" in w for w in context["warnings"])
