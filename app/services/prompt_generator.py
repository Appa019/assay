"""Render the 5-prompt meeting sequence for a contribution from captured context."""

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
            "crypto on-chain, CDB/juros, quant, risco) define tese macro Brasil + Global, mapa "
            "setorial, narrativas crypto, Black-Litterman e a alocação tática do aporte por classe "
            "(CDB / Ações B3 / Crypto)."
        ),
    },
    {
        "order": 2,
        "key": PromptKey.SELECTION,
        "template": "02_research_selection.j2",
        "title": "Reunião nº 2 — Universo, Filtros e Seleção",
        "description": (
            "Define o universo investível, monta long lists, aplica filtros (quant + forense + "
            "técnico) e SELECIONA a shortlist (5-8 ações B3 + 3-5 cryptos). Finaliza a fatia de CDB "
            "com credit analysis do banco emissor (Basel III, FGC, %CDI pós-IR)."
        ),
    },
    {
        "order": 3,
        "key": PromptKey.EQUITY,
        "template": "03_equity_diligence.j2",
        "title": "Reunião nº 3 — Due Diligence de Ações B3",
        "description": (
            "Memo completo por ação selecionada: investment thesis, valuation triangulada "
            "(DCF 3-estágios + Reverse DCF + CCA + Precedent + LBO + SOTP), forense "
            "(Piotroski/Altman/Beneish/Sloan/Dechow), Capital Allocation, técnica institucional, "
            "factor exposure, bull/base/bear e sizing."
        ),
    },
    {
        "order": 4,
        "key": PromptKey.CRYPTO,
        "template": "04_crypto_diligence.j2",
        "title": "Reunião nº 4 — Due Diligence de Crypto",
        "description": (
            "Memo completo por cripto selecionada: tese, tokenomics + unlocks, on-chain "
            "institucional (MVRV-Z/NUPL/SOPR/…), derivativos (Coinglass), dev activity, técnica, "
            "bull/base/bear e sizing."
        ),
    },
    {
        "order": 5,
        "key": PromptKey.DECISION,
        "template": "05_decision_orders.j2",
        "title": "Reunião nº 5 — Risco, Sentimento e Ordens Finais",
        "description": (
            "CIO + CRO + Sentiment + Trader validam a shortlist contra risco (VaR/CVaR/EVT), "
            "stress 8 cenários, sentimento e imposto; materializam o CDB e geram a folha de ordens "
            "executiva (ticker, qtd, preço-alvo, stop, targets, algoritmo) pronta para operar."
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


def _date_context(ref: date) -> dict[str, Any]:
    """Dynamic calendar variables for the templates.

    Templates used to hardcode DI tenors, fiscal years and earnings quarters;
    those fossilize (e.g. asking to quote an already-expired DI jan/26). All
    date-anchored references now derive from the contribution date.
    """
    year = ref.year
    quarter = (ref.month - 1) // 3 + 1
    # Two most recently COMPLETED quarters (earnings that actually exist).
    completed: list[str] = []
    q, y = quarter - 1, year
    for _ in range(2):
        if q < 1:
            q, y = 4, y - 1
        completed.append(f"{q}T{y}")
        q -= 1
    completed.reverse()
    # Liquid DI futures: Jan maturities 1, 2, 3 and 5 years out.
    di_years = (year + 1, year + 2, year + 3, year + 5)
    di_tenors = " · ".join(f"DI jan/{y % 100:02d}" for y in di_years)
    return {
        "current_year": year,
        "next_year": year + 1,
        "last_year": year - 1,
        "current_quarter": f"{quarter}T{year}",
        "last_quarters_search": " ".join(completed),
        "di_tenors": di_tenors,
        "target_years_search": f"{year} {year + 1}",
    }


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
        **_date_context(contribution_date),
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
    """Render the 5 prompts in order. Returns rows ready for persistence."""
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
