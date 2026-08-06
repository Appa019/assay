"""/gasto and /ganho argument parsing — wallet tokens ride along with the
category hashtag and the free-text description."""

from decimal import Decimal

import scripts.telegram_bot as bot


def test_parse_cashflow_defaults_to_conta() -> None:
    amount, category, description, wallet = bot._parse_cashflow(["42,90", "pão", "#mercado"])
    assert amount == Decimal("42.90")
    assert category == "mercado"
    assert description == "pão"
    assert wallet == "conta"


def test_parse_cashflow_picks_up_vr_token() -> None:
    amount, category, description, wallet = bot._parse_cashflow(
        ["35", "almoço", "#restaurante", "vr"]
    )
    assert amount == Decimal("35")
    assert category == "restaurante"
    assert description == "almoço"
    assert wallet == "vr"


def test_parse_cashflow_wallet_token_is_case_insensitive() -> None:
    amount, category, description, wallet = bot._parse_cashflow(["800", "VA"])
    assert amount == Decimal("800")
    assert description is None
    assert wallet == "va"


def test_parse_cashflow_wallet_token_position_does_not_matter() -> None:
    _, _, description, wallet = bot._parse_cashflow(["12", "vr", "café", "da", "tarde"])
    assert description == "café da tarde"
    assert wallet == "vr"
