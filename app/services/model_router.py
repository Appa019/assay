"""Pick the right model for each chat turn.

The consultant used to answer everything on opus at high effort. That is the
correct call for "devo trocar CDB por PETR4 agora?" and absurd for "oi" or
"anota 42 no mercado" — same cost, same minutes of latency, no extra value.

A tiny haiku triage classifies the message into three tiers. It adds roughly a
second to a turn that otherwise runs from ten seconds to minutes, and it is far
more robust than keyword rules, which break the moment the user phrases
something the way people actually talk. Anything that goes wrong in triage
falls through to BALANCED: routing must never be the reason a chat fails.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import structlog

from app.config import settings
from app.services import analysis_runner

logger = structlog.get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# Bare directory: no .mcp.json means no MCP servers boot, which is most of why
# this stays fast.
_WORKSPACE = _PROJECT_ROOT / "storage" / "router_workspace"


class Tier(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    DEEP = "deep"


@dataclass(frozen=True)
class Route:
    tier: Tier
    model: str
    effort: str
    reason: str


def _tier_settings(tier: Tier) -> tuple[str, str]:
    if tier is Tier.FAST:
        return settings.chat_fast_model, settings.chat_fast_effort
    if tier is Tier.DEEP:
        return settings.chat_deep_model, settings.chat_deep_effort
    return settings.chat_balanced_model, settings.chat_balanced_effort


def _route_for(tier: Tier, reason: str) -> Route:
    model, effort = _tier_settings(tier)
    return Route(tier=tier, model=model, effort=effort, reason=reason)


# Greetings, thanks and one-word acks never need a big model, and short-
# circuiting them removes the triage latency from exactly the turns where a
# second is most noticeable.
_TRIVIAL_RE = re.compile(
    r"^(oi+|ola|olá|eae|opa|bom dia|boa tarde|boa noite|tudo bem\??|"
    r"obrigad[oa]|valeu|vlw|ok|okay|blz|beleza|certo|entendi|show|"
    r"tchau|até|abraço)[!.?\s]*$",
    re.IGNORECASE,
)

# "gastei 42 no mercado" is the single most frequent message in the product and
# never needs more than the small model. A logging verb plus a number is a
# specific enough shape to skip triage entirely, which is worth ~6s every time.
_LOGGING_VERB_RE = re.compile(
    r"\b(gastei|paguei|comprei|torrei|recebi|ganhei|caiu|entrou|"
    r"anota|anote|lan[çc]a|registra|registre)\b",
    re.IGNORECASE,
)
_HAS_AMOUNT_RE = re.compile(r"\d")
# ...unless the sentence is actually about the portfolio, where "comprei" means
# an asset and the answer needs live market data.
_MARKET_RE = re.compile(
    r"\b(a[çc][ãa]o|a[çc][õo]es|ativo|carteira|aporte|investi|investir|"
    r"bitcoin|btc|eth|cripto|crypto|cdb|cdi|selic|ipca|tesouro|dividendo|"
    r"rebalance|tese|valuation|[a-z]{4}\d{1,2})\b",
    re.IGNORECASE,
)

_TRIAGE_PROMPT = """Classifique a dificuldade desta mensagem para um consultor financeiro.

Mensagem: "{text}"

Responda com UMA palavra, nada mais:

- `fast` — conversa curta, registrar um gasto/ganho, consultar um número que já
  existe (saldo, quanto gastei, qual meu patrimônio), pergunta factual simples.
- `balanced` — dúvida que pede explicação ou contexto, comparação simples,
  organizar finanças, entender um conceito, planejar o mês, **pedir opinião
  sobre os próprios gastos** ou sobre como o mês está indo.
- `deep` — decisão de investimento, análise de ativo ou carteira, tese de
  compra/venda, cenário macro, risco, tributação complexa, qualquer coisa que
  exija pesquisa na web ou dados de mercado ao vivo.

Uma palavra:"""


def _triage(text: str) -> Tier:
    _WORKSPACE.mkdir(parents=True, exist_ok=True)
    result = analysis_runner._run_claude_step(
        _TRIAGE_PROMPT.format(text=text[:1500]),
        resume_session_id=None,
        model=settings.chat_router_model,
        effort=settings.chat_router_effort,
        timeout=settings.chat_router_timeout,
        cwd=_WORKSPACE,
        transcript_tag=None,
    )
    answer = (result.result or "").strip().lower()
    for tier in (Tier.DEEP, Tier.BALANCED, Tier.FAST):
        if tier.value in answer:
            return tier
    raise ValueError(f"triagem devolveu algo inesperado: {answer[:60]!r}")


def route(text: str) -> Route:
    """Choose a model for this message. Never raises."""
    text = text.strip()

    if not settings.chat_router_enabled:
        return _route_for(Tier.DEEP, "roteador desligado")

    if len(text) <= 24 and _TRIVIAL_RE.match(text):
        return _route_for(Tier.FAST, "saudação")

    if (
        len(text) <= 120
        and _LOGGING_VERB_RE.search(text)
        and _HAS_AMOUNT_RE.search(text)
        and not _MARKET_RE.search(text)
    ):
        return _route_for(Tier.FAST, "lançamento no ledger")

    try:
        tier = _triage(text)
    except Exception as exc:  # noqa: BLE001 — triage is an optimisation, not a gate
        logger.warning("model_router_fallback", error=str(exc))
        return _route_for(Tier.BALANCED, "triagem falhou, usando o padrão")

    logger.info("model_router_pick", tier=tier.value, chars=len(text))
    return _route_for(tier, "triagem")
