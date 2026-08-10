from datetime import date

import pytest

from app.services import prompt_generator as pg


def _sample_context(when: date) -> dict:
    return pg.build_render_context(
        contribution_id="cid-1",
        amount_brl=5000.0,
        contribution_date=when,
        portfolio_total=10000.0,
        allocation_current={"fixed_income_pct": 30, "stocks_pct": 40, "crypto_pct": 30},
        allocation_target={"fixed_income": 35, "stocks": 40, "crypto": 25},
        allocation_deviation={"fixed_income": -5, "stocks": 0, "crypto": 5},
        assets=[],
        macro={"selic": 15.0, "ipca_12m": 5.3, "cdi": 14.9, "usd_brl": 5.5},
        ibovespa={"level": 140000, "day_change_pct": 0.5, "month_return_pct": 2.0},
        crypto_global={"btc_dominance": 55.0},
        fear_greed_index=60,
        warnings=[],
        captured_at="2026-07-27T00:00:00Z",
    )


def test_all_templates_render_without_leftover_jinja() -> None:
    prompts = pg.render_all_prompts(_sample_context(date(2026, 7, 27)))
    assert len(prompts) == 5
    for p in prompts:
        assert "{{" not in p["content"] and "{%" not in p["content"]
        assert len(p["content"]) > 3000


def test_dynamic_dates_are_injected() -> None:
    prompts = pg.render_all_prompts(_sample_context(date(2026, 7, 27)))
    macro, _sel, equity, crypto, decision = (p["content"] for p in prompts)
    assert "DI jan/27" in macro and "jan/26" not in macro
    assert "1T2026 2T2026" in equity  # last completed earnings quarters
    assert "2026 2027" in decision  # sell-side target-year search
    assert "./out/cid-1/etapa_04.json" in crypto  # cross-meeting persistence


def test_quarter_rollover_at_year_boundary() -> None:
    ctx = pg._date_context(date(2026, 1, 15))
    # In Q1, the two most recent COMPLETED quarters are last year's Q3/Q4.
    assert ctx["last_quarters_search"] == "3T2025 4T2025"
    assert ctx["di_tenors"].startswith("DI jan/27")


def test_fixed_income_mandate_is_a_single_fixed_instrument() -> None:
    """D29: the committee decides HOW MUCH goes to CDB, never WHICH CDB."""
    macro, selection, _equity, _crypto, decision = (
        p["content"] for p in pg.render_all_prompts(_sample_context(date(2026, 7, 27)))
    )
    for content in (macro, selection, decision):
        assert "Bradesco" in content
        # No hunting for issuers, rates or term deposits.
        assert "bancos médios" not in content
        assert "melhores taxas" not in content
        assert "110-125% CDI" not in content


def test_render_context_validates_amount() -> None:
    with pytest.raises(ValueError):
        pg.build_render_context(
            contribution_id="x",
            amount_brl=0,
            contribution_date=date.today(),
            portfolio_total=0,
            allocation_current={},
            allocation_target={},
            allocation_deviation={},
            assets=[],
            macro={},
            ibovespa={},
            crypto_global={},
            fear_greed_index=None,
            warnings=[],
            captured_at="now",
        )
