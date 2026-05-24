"""Render the 3-prompt sequence for a contribution, based on captured context."""

from datetime import date
from pathlib import Path
from typing import Any

import structlog
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.models.contribution import PromptKey

logger = structlog.get_logger()

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "agents_prompts"

_env = Environment(
    loader=FileSystemLoader(str(PROMPTS_DIR)),
    autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
    undefined=StrictUndefined,
    trim_blocks=False,
    lstrip_blocks=False,
)


_PROMPT_DEFINITIONS = [
    {
        "order": 1,
        "key": PromptKey.MACRO,
        "template": "01_macro_strategy.j2",
        "title": "Reunião nº 1 — Macro, Setores e Alocação Tática",
        "description": (
            "Comitê multipersona (economista-chefe, estrategista global, alocação, setorial B3, "
            "crypto, risco, quant) define tese macro Brasil + Global, mapa setorial, narrativas crypto, "
            "matriz de risco e a alocação tática do aporte (% e R$ por classe)."
        ),
    },
    {
        "order": 2,
        "key": PromptKey.RESEARCH,
        "template": "02_research_diligence.j2",
        "title": "Reunião nº 2 — Screening e Due Diligence Profunda",
        "description": (
            "Time de Equity Research (cíclicos / defensivos / commodities) e Crypto Research valida tickers, "
            "filtra universo (liquidez, market cap, governança), faz deep due diligence em 5-8 ações + 3-5 crypto "
            "com fundamentos, valuation, tokenomics e position sizing por ativo."
        ),
    },
    {
        "order": 3,
        "key": PromptKey.DECISION,
        "template": "03_decision_orders.j2",
        "title": "Reunião nº 3 — Risco, Sentimento e Ordens Finais",
        "description": (
            "CIO + CRO + Head of Sentiment + Trader Sênior validam shortlist contra risco e sentimento, "
            "definem produtos de Renda Fixa, e geram a folha de ordens executiva: ticker, qtd, preço alvo, "
            "stop, target 31d/90d, algoritmo de execução (VWAP/TWAP/POV/Limit) — pronto para o cliente operar."
        ),
    },
]


def _format_brl(value: Any) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return str(value)
    integer, decimals = f"{amount:,.2f}".split(".")
    return f"{integer.replace(',', '.')},{decimals}"


def build_render_context(
    *,
    contribution_id: str,
    amount_brl: float,
    contribution_date: date,
    portfolio_total: float,
    allocation_current: dict[str, float],
    allocation_target: dict[str, float],
    allocation_deviation: dict[str, float],
    assets: list[dict[str, Any]],
    macro: dict[str, Any],
    ibovespa: dict[str, Any],
    crypto_global: dict[str, Any],
    fear_greed_index: int | None,
    warnings: list[str],
    captured_at: str,
    candidate_stocks: list[dict[str, Any]] | None = None,
    candidate_cryptos: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not contribution_id:
        raise ValueError("contribution_id é obrigatório no render context")
    if amount_brl is None or amount_brl <= 0:
        raise ValueError(f"amount_brl deve ser > 0; recebido {amount_brl!r}")
    if contribution_date is None:
        raise ValueError("contribution_date é obrigatório no render context")
    if not captured_at:
        raise ValueError("captured_at é obrigatório no render context")

    return {
        "contribution_id": contribution_id,
        "contribution_date": contribution_date.isoformat(),
        "amount_brl": amount_brl,
        "amount_brl_formatted": _format_brl(amount_brl),
        "portfolio_total": portfolio_total,
        "portfolio_total_formatted": _format_brl(portfolio_total),
        "allocation_current": _NamespaceLike(allocation_current),
        "allocation_target": allocation_target,
        "allocation_deviation": _NamespaceLike(allocation_deviation),
        "assets": assets,
        "macro": _NamespaceLike(macro),
        "ibovespa": _NamespaceLike(ibovespa),
        "crypto_global": _NamespaceLike(crypto_global),
        "fear_greed_index": fear_greed_index,
        "captured_at": captured_at,
        "warnings": warnings or [],
        "candidate_stocks": candidate_stocks,
        "candidate_cryptos": candidate_cryptos,
    }


class _NamespaceLike(dict):
    """Dict that also supports attribute access — lets templates use macro.selic."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            return None


def render_all_prompts(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Render the 3 prompts in order. Returns rows ready for persistence."""
    out: list[dict[str, Any]] = []
    for definition in _PROMPT_DEFINITIONS:
        template = _env.get_template(definition["template"])
        content = template.render(**context)
        out.append(
            {
                "prompt_order": definition["order"],
                "prompt_key": definition["key"],
                "title": definition["title"],
                "description": definition["description"],
                "content": content,
            }
        )
    logger.info("prompts_rendered", count=len(out))
    return out
