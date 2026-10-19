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


# --- macro delta mode -------------------------------------------------------


def _delta_context(age_days: int | None) -> dict:
    ctx = _sample_context(date(2026, 9, 6))
    return pg.build_render_context(
        contribution_id="cid-delta",
        amount_brl=5000.0,
        contribution_date=date(2026, 9, 6),
        portfolio_total=10000.0,
        weekly_review_age_days=age_days,
        allocation_current=ctx["allocation_current"],
        allocation_target=ctx["allocation_target"],
        allocation_deviation=ctx["allocation_deviation"],
        assets=[],
        macro=ctx["macro"],
        ibovespa=ctx["ibovespa"],
        crypto_global=ctx["crypto_global"],
        fear_greed_index=60,
        warnings=[],
        captured_at="2026-09-06T00:00:00Z",
    )


def _macro_prompt(context: dict) -> str:
    return next(p["content"] for p in pg.render_all_prompts(context) if p["prompt_order"] == 1)


def test_fresh_weekly_review_switches_meeting_one_to_delta_mode() -> None:
    """The expensive 11-round macro is skipped when the committee just did it."""
    body = _macro_prompt(_delta_context(2))
    assert "MODO DELTA" in body
    assert "ORÇAMENTO DE PESQUISA" in body
    assert "há 2 dia(s)" in body


def test_stale_or_missing_weekly_review_keeps_the_full_macro() -> None:
    for age in (None, 30):
        body = _macro_prompt(_delta_context(age))
        assert "MODO DELTA" not in body
        assert "CAST DO GIC (12 personas simultâneas)" in body


def test_delta_mode_can_be_turned_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "macro_delta_enabled", False)
    assert "MODO DELTA" not in _macro_prompt(_delta_context(1))


def test_delta_prompt_keeps_the_contract_the_next_meetings_read() -> None:
    """Meetings 2-5 parse these keys out of meeting #1 — the short form must
    still emit every one of them or the chain breaks downstream."""
    body = _macro_prompt(_delta_context(3))
    for key in (
        "final_tactical_brl",
        "final_tactical_pct",
        "juros_e_cdb",
        "cdb_postura",
        "setores_b3",
        "top3_ow",
        "bottom3_uw",
        "tilt_dominante",
        "digital_assets",
        "narrativas_top",
        "split_btc_eth_core_vs_alts_pct",
        "top_of_mind",
        "pre_mortem_gic",
        "viola_tolerancia_dd_pre",
    ):
        assert key in body, key


def test_delta_prompt_is_far_smaller_than_the_full_macro() -> None:
    assert len(_macro_prompt(_delta_context(2))) < len(_macro_prompt(_delta_context(None))) / 2


def test_committee_rules_that_keep_the_numbers_honest() -> None:
    """Quality fixes from D44: each one replaced a computation that produced a
    number without information (or blocked the wrong stocks)."""
    macro, selection, equity, crypto, decision = (
        p["content"] for p in pg.render_all_prompts(_sample_context(date(2026, 7, 27)))
    )
    # Risk parity with a zero-vol CDB inside is 100% CDB by construction.
    assert "SLEEVE DE RISCO" in macro
    assert "TED spread" not in macro  # discontinued with LIBOR
    # Banks fail EBITDA/Altman filters for the wrong reason.
    assert "Financeiras" in selection and "FINANCEIRAS" in equity
    # Held names with an intact thesis get an incremental DD, not a new memo.
    assert "reforco" in selection and "DD INCREMENTAL" in equity and "DD INCREMENTAL" in crypto
    assert "2% do patrimônio" in selection
    # Long-only retail sheet: no options, pair trades or institutional algos.
    for gone in ("Greeks", "pair_trades", "VWAP", "iv_rv_options_analysis"):
        assert gone not in decision, gone
    assert "pair_trade" not in equity
    # A stop inside the sell lock cannot be executed.
    assert "não de venda" in decision and "não de venda" in equity
