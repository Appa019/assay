from app.services.market_data_service import _pct, _yield_pct


def test_pct_scales_fractions() -> None:
    assert _pct(0.155) == 15.5
    assert _pct(None) is None


def test_yield_pct_handles_both_scales() -> None:
    # Old yfinance: fraction → scale up. New yfinance: already percent → keep.
    assert _yield_pct(0.065) == 6.5
    assert _yield_pct(6.5) == 6.5
    assert _yield_pct(None) is None
    assert _yield_pct(12.4) == 12.4  # never 1240%
