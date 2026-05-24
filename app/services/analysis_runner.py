"""Drive the full analysis cycle through the Claude Code CLI, headless.

Runs every rendered prompt of a contribution, in order, inside a single
Claude session (so each meeting inherits the previous meetings' context,
exactly like pasting them one after another by hand) and then asks for a
consolidated "where to invest and how much" summary.

The model runs with ``--dangerously-skip-permissions`` so it can use
WebSearch / WebFetch / Bash without prompting, and ``--effort max`` for the
deepest reasoning. Each step is persisted as it finishes, so progress is
observable step by step via the normal contribution read endpoint.
"""

import json
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from sqlmodel import Session, select

from app.config import settings
from app.models.contribution import Contribution, ContributionPrompt, ContributionStatus
from app.models.report import Report, ReportKind
from app.services import telegram_service

logger = structlog.get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Persistent, isolated workspace for the autonomous agent. Its CLAUDE.md is
# auto-loaded by every headless run (standing orders) and MEMORY.md is the
# agent's own cross-run memory. Tools it builds live here and survive runs.
WORKSPACE = _PROJECT_ROOT / "storage" / "agent_workspace"

DEFAULT_MODEL = settings.agent_model
DEFAULT_EFFORT = settings.agent_effort
# Opus at max effort on a ~110k-char prompt with live web research is slow;
# give each step plenty of headroom (seconds).
DEFAULT_STEP_TIMEOUT = 2400

# Standing orders for the agent — written to WORKSPACE/CLAUDE.md every run so
# updates here propagate. {min_holding_days} is filled at write time.
_STANDING_ORDERS = """\
# Agente de Investimentos — Ordens Permanentes

Você é, em multipersona, uma MESA DE INVESTIMENTOS COMPLETA nível
**Goldman Sachs + J.P. Morgan** (research + portfolio strategy + risk + trading),
combinando GS GIR, JPM Global Research/Private Bank, Morgan Stanley GIC,
Bridgewater e AQR. Atue como um time inteiro de profissionais sênior, não como um
analista só. Rigor máximo institucional, sempre.

## Carta branca total (sem pedir permissão)
- LIBERDADE TOTAL para pesquisar QUALQUER fonte: preços, notícias, relatórios
  sell-side, filings/CVM/RI, dados on-chain, derivativos, funding, macro, papers.
  Use WebSearch, WebFetch e seus MCPs à vontade.
- Você TEM os melhores MCPs já carregados (use-os quando ajudarem):
  · **sequential-thinking** — raciocínio estruturado profundo;
  · **playwright** — navegador real para sites com JS (dashboards, on-chain, RI);
  · **fetch** — extrair páginas/filings em markdown;
  · **filesystem** — navegar/ler/escrever em QUALQUER lugar da máquina ($HOME);
  · **context7** — docs atualizadas de bibliotecas quando você programar ferramentas;
  · **memory** — grafo de conhecimento estruturado (complementa o ./MEMORY.md);
  · **time** — fuso/datas (janelas COPOM/FOMC, agendamentos);
  · **git** — versione as ferramentas que você cria (o workspace é um repo git).
- Acesso TOTAL à máquina: rode QUALQUER comando (Bash), navegue o sistema, leia e
  CRIE ARQUIVOS onde precisar, escreva scripts e CRIE SUAS PRÓPRIAS FERRAMENTAS em
  ./tools/ e reutilize nos próximos ciclos. Crie um venv local e instale libs
  (pip/uvx/npm) se precisar. Tudo é permitido em prol do MELHOR investimento.

## Instale e configure as ferramentas/MCPs que quiser (auto-provisionamento)
- Precisa de uma lib? Instale via Bash (pip/uvx/npm/npx) e use já neste ciclo.
- Precisa de um MCP NOVO de forma permanente? Adicione-o ao arquivo
  **./.mcp.agent.json** (mapa `mcpServers`). Ele é SEU: nunca é sobrescrito e é
  mesclado ao baseline automaticamente — o servidor carrega no PRÓXIMO ciclo
  (você tem prioridade se repetir um nome do baseline). Ex.:
  `{{"mcpServers": {{"nome": {{"command": "npx", "args": ["-y", "pacote-mcp"]}}}}}}`.
- MCPs carregam no INÍCIO do processo; um MCP recém-adicionado ao .mcp.agent.json
  vale no PRÓXIMO ciclo. Para uso IMEDIATO neste ciclo, chame a ferramenta/CLI
  diretamente via Bash (ou escreva um wrapper em ./tools/).
- Se um MCP exigir chave de API, guarde a chave fora do git e referencie via env
  no .mcp.agent.json. NUNCA exponha segredos no MEMORY.md nem em commits.

## Sua memória persistente (você a gerencia)
- ./MEMORY.md é SUA memória entre ciclos. LEIA-a no início de TODO ciclo.
- Ao FINAL de todo ciclo, ATUALIZE ./MEMORY.md: teses vigentes, tickers e
  CoinGecko-ids corretos, o que recomendou e por quê, o que funcionou/falhou,
  watchlist e erros a evitar. Use ./memory/ para notas longas por tema.

## Trava de venda — {min_holding_days} dias POR LOTE (só AÇÕES e CRYPTO)
- A trava de {min_holding_days} dias vale APENAS para AÇÕES e CRYPTO, por LOTE
  de compra (não por ticker): cada compra matura {min_holding_days} dias a
  partir da SUA data. Ex.: 10 ações de hoje liberam antes de 15 do mesmo ticker
  compradas semana que vem.
- **CDB / Renda Fixa = LIQUIDEZ DIÁRIA**: pode ser vendido a QUALQUER momento,
  sem trava. É o DRY POWDER (caixa estratégico) da carteira.
- Portanto: (a) ações/crypto só com convicção de segurar ≥{min_holding_days}
  dias; (b) na revisão semanal, se surgir uma OPORTUNIDADE de mercado relevante
  (ação B3 ou crypto), pode recomendar VENDER CDB e comprar o ativo — o CDB
  existe pra isso; (c) ao revisar, trate cada lote de ação/crypto separadamente
  (travado vs liberado); o CDB está sempre disponível.

## Mandato de alocação (PRIORIDADE MÁXIMA — três classes APENAS)
- **Renda Fixa = 100% CDB** (preferir CDB ≥100% do CDI; prazo/liquidez conforme
  objetivo). NÃO recomende Tesouro Direto, LCI/LCA, debêntures nem fundos de RF.
- **Ações = SOMENTE ações listadas na B3** (ON/PN/UNIT). NÃO recomende FIIs,
  ETFs, BDRs nem qualquer ativo internacional.
- **Crypto = mandato AGRESSIVO ("sonhar alto")**: busque alto upside (majors,
  L1/L2, narrativas emergentes, small/mid caps cripto, DeFi), com gestão de
  risco e respeitando a trava por lote. Exposição USD só via stablecoins (USDC).
- Esse mandato sobrepõe qualquer escopo mais amplo que apareça nos prompts.

## Padrão de equipe (time completo GS / J.P. Morgan)
- Convoque SEMPRE o time inteiro, por nome e função, e faça-os debater:
  Economista-chefe (macro BR + global), Estrategista de Alocação, Analistas de
  Equity Research setoriais da B3, Especialista de Crypto/DeFi on-chain, Head de
  Renda Fixa (CDB/curva DI), Quant (fatores/risco), CRO (VaR/CVaR/stress),
  Forensic/CFE (qualidade contábil), Behavioral, Tax, e o CIO que decide.
- Debate real: tese, contra-tese (devil's advocate), evidência numérica e fontes
  verificadas AO VIVO. Conclua com convicção (tier) e assimetria risco/retorno.
- Nível de output equivalente a um Investment Committee memo de banco tier-1.

## Saída
- Sempre em português, acionável: "onde investir e quanto".
- NÃO cite plataforma/corretora/exchange — o cliente decide onde executar.
- Termine com a folha de ordens consolidada (ticker, classe, R$, %, alvo, racional).
"""

_SEED_MEMORY = """\
# Memória do Agente de Investimentos

Este arquivo é gerenciado por você (Claude) entre ciclos. Atualize-o ao fim de cada
ciclo. Estrutura sugerida:

## Carteira / decisões por ciclo
(ainda vazio — primeiro ciclo)

## Teses macro vigentes
(preencher)

## Tickers e CoinGecko-ids confirmados
(preencher conforme validar)

## Erros a evitar / lições
(preencher)

## Watchlist próximo ciclo
(preencher)
"""

_SEED_AGENT_MCP = """\
{
  "_comment": "MCPs que VOCE (agente) adiciona aqui sao mesclados ao baseline a cada ciclo e carregam no PROXIMO ciclo. Voce tem prioridade em conflito de nome. Ex.: adicione em mcpServers: \\"coingecko\\": {\\"command\\": \\"npx\\", \\"args\\": [\\"-y\\", \\"coingecko-mcp\\"]}",
  "mcpServers": {}
}
"""

_SYNTHESIS_PROMPT = """\
Com base em TODA a análise do comitê acima (todas as reuniões), produza o \
FECHAMENTO EXECUTIVO final para o cliente. Responda em português, de forma \
direta e enxuta, contendo APENAS:

1. **Folha de ordens consolidada** — tabela markdown com as ordens de compra \
deste aporte: Ativo (ticker) | Classe | R$ a investir | % do aporte | \
Preço-alvo de entrada | Racional em 1 linha.
2. **Resumo por classe** — quanto (R$ e %) vai para Renda Fixa (CDB), Ações \
(B3) e Crypto, e o caixa remanescente se houver.
3. **Total alocado** vs. valor do aporte (devem bater).

MANDATO (obrigatório): Renda Fixa = 100% CDB; Ações = só equities da B3 (sem \
FII/ETF/BDR); Crypto = agressivo. NÃO mencione plataforma/corretora/exchange. \
NÃO repita a análise — só o resultado acionável: onde investir e quanto.

ANTES de escrever a folha de ordens, ATUALIZE o arquivo ./MEMORY.md deste \
diretório (crie se não existir) com as teses, tickers/CG-ids e decisões deste \
ciclo, e a watchlist do próximo. Depois entregue a folha de ordens como resposta."""


class AnalysisError(RuntimeError):
    """A Claude CLI step failed or returned an error result."""


class SessionNotFoundError(AnalysisError):
    """The Claude session to ``--resume`` no longer exists; restart fresh."""


_MCP_FILENAME = ".mcp.json"  # effective config Claude loads (regenerated each run)
_AGENT_MCP_FILENAME = ".mcp.agent.json"  # agent-owned; merged in and NEVER overwritten


def _baseline_mcp_servers() -> dict[str, Any]:
    """Curated, research-grade MCP servers always available to the analyst.

    Intentionally excludes the user's personal Gmail/Calendar/Drive MCPs (the
    agent runs autonomously and must not act in those on its own); paired with
    ``--strict-mcp-config`` so ONLY the effective set loads. The agent can add
    ANY extra server itself via ``.mcp.agent.json`` (see ``_effective_mcp_config``).
    """
    home = str(Path.home())
    return {
        # Deep, structured reasoning for institutional-grade analysis.
        "sequential-thinking": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
        },
        # Navigate the whole machine + create/read files anywhere under $HOME.
        "filesystem": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", home],
        },
        # Robust web page → markdown fetch (filings, data pages).
        "fetch": {"command": "uvx", "args": ["mcp-server-fetch"]},
        # Live library docs when the agent writes its own tools.
        "context7": {"command": "npx", "args": ["-y", "@upstash/context7-mcp@latest"]},
        # Full browser for JS-heavy research sites (dashboards, on-chain, RI).
        "playwright": {"command": "npx", "args": ["@playwright/mcp@latest"]},
        # Structured knowledge graph, complementary to the file-based MEMORY.md.
        "memory": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-memory"],
            "env": {"MEMORY_FILE_PATH": str(WORKSPACE / "memory" / "graph.json")},
        },
        # Timezone/date math (COPOM/FOMC windows, usage-limit "resets at").
        "time": {"command": "uvx", "args": ["mcp-server-time"]},
        # Version-control the tools the agent builds in ./tools/.
        "git": {"command": "uvx", "args": ["mcp-server-git", "--repository", str(WORKSPACE)]},
    }


def _load_agent_mcp_servers(workspace: Path) -> dict[str, Any]:
    """Servers the agent added itself, persisted in ``.mcp.agent.json``."""
    path = workspace / _AGENT_MCP_FILENAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("agent_mcp_config_unreadable", path=str(path), error=str(exc))
        return {}
    servers = data.get("mcpServers", {}) if isinstance(data, dict) else {}
    return servers if isinstance(servers, dict) else {}


def _effective_mcp_config(workspace: Path) -> dict[str, Any]:
    """Baseline ∪ agent-added servers (the agent wins on key conflicts).

    This is what lets the agent provision ANY MCP it wants and have it stick:
    it edits ``.mcp.agent.json`` and the server loads on the next cycle.
    """
    servers = _baseline_mcp_servers()
    servers.update(_load_agent_mcp_servers(workspace))
    return {"mcpServers": servers}


def _ensure_workspace(min_holding_days: int) -> Path:
    """Create the agent workspace, refresh standing orders + MCP config, seed memory.

    The effective ``.mcp.json`` is regenerated each run (so curated baseline
    updates propagate) but MERGED with the agent-owned ``.mcp.agent.json``, which
    is seeded once and never overwritten — so MCP servers the agent installs for
    itself survive across cycles.
    """
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    (WORKSPACE / "tools").mkdir(exist_ok=True)
    (WORKSPACE / "memory").mkdir(exist_ok=True)
    (WORKSPACE / "CLAUDE.md").write_text(
        _STANDING_ORDERS.format(min_holding_days=min_holding_days), encoding="utf-8"
    )
    # Agent-owned MCP file: seed once, then it's the agent's to extend.
    agent_mcp = WORKSPACE / _AGENT_MCP_FILENAME
    if not agent_mcp.exists():
        agent_mcp.write_text(_SEED_AGENT_MCP, encoding="utf-8")
    # Effective config Claude loads = curated baseline ∪ whatever the agent added.
    (WORKSPACE / _MCP_FILENAME).write_text(
        json.dumps(_effective_mcp_config(WORKSPACE), indent=2), encoding="utf-8"
    )
    memory = WORKSPACE / "MEMORY.md"
    if not memory.exists():
        memory.write_text(_SEED_MEMORY, encoding="utf-8")
    _ensure_git_repo(WORKSPACE)
    return WORKSPACE


def _ensure_git_repo(workspace: Path) -> None:
    """Best-effort: make the workspace a git repo so the agent can version tools."""
    if (workspace / ".git").exists():
        return
    try:
        subprocess.run(
            ["git", "init", "-q"], cwd=str(workspace), capture_output=True, timeout=30, check=False
        )
        # Local identity so the agent's commits don't fail (never references Claude).
        for key, val in (("user.name", "Investment Agent"), ("user.email", "agent@localhost")):
            subprocess.run(
                ["git", "config", key, val],
                cwd=str(workspace),
                capture_output=True,
                timeout=30,
                check=False,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("workspace_git_init_failed", error=str(exc))


def _build_preamble(*, amount_brl: float, when: str, min_holding_days: int) -> str:
    """Short context block prepended to the first meeting."""
    return (
        "[CONTEXTO DO CICLO — leia antes de tudo]\n"
        f"- Aporte deste ciclo: R$ {amount_brl:,.2f}\n"
        f"- Data: {when}\n"
        "- MANDATO: Renda Fixa = 100% CDB; Ações = só equities da B3 (sem "
        "FII/ETF/BDR); Crypto = agressivo (alto upside, com risco controlado).\n"
        f"- Trava POR LOTE só de AÇÕES e CRYPTO: cada compra vende após "
        f"{min_holding_days} dias da sua data. CDB/Renda Fixa tem liquidez "
        "diária (dry powder) — vende quando quiser.\n"
        "- LEIA seu ./MEMORY.md (memória dos ciclos anteriores) antes de decidir; "
        "ATUALIZE-o ao final.\n"
        "- Carta branca: pesquise qualquer fonte (WebSearch/WebFetch), rode "
        "qualquer Bash, crie ferramentas em ./tools/.\n\n"
        "A seguir, a Reunião nº 1:\n"
        "----------------------------------------------------------------------\n"
    )


def _latest_weekly_context(session: Session, *, max_chars: int = 6000) -> str:
    """Latest weekly review as a consult block to prepend to a contribution run."""
    report = session.exec(
        select(Report)
        .where(Report.kind == ReportKind.WEEKLY)
        .order_by(Report.created_at.desc())
        .limit(1)
    ).first()
    if report is None or not report.content:
        return ""
    body = report.content[:max_chars]
    return (
        "[CONSULTA — última revisão semanal do comitê em "
        f"{report.created_at.date().isoformat()}]\n"
        f"{body}\n"
        "----------------------------------------------------------------------\n\n"
    )


def _claude_bin() -> str:
    """Resolve the `claude` executable, even when PATH is minimal.

    The backend may be launched from a desktop shortcut whose PATH lacks
    ``~/.local/bin``, so fall back to the common install location.
    """
    found = shutil.which("claude")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "claude"
    if fallback.exists():
        return str(fallback)
    raise AnalysisError(
        "Executável 'claude' não encontrado no PATH. Instale o Claude Code CLI "
        "ou ajuste o PATH do processo do backend."
    )


class RetryableError(AnalysisError):
    """A step failed transiently; retrying (after a wait) may succeed."""


class LimitError(RetryableError):
    """A step hit a rate/usage/token limit; resume automatically once it lifts."""


@dataclass
class StepResult:
    label: str
    result: str
    cost_usd: float
    duration_s: float
    session_id: str = ""
    num_turns: int | None = None


@dataclass
class RunSummary:
    run_id: str
    session_id: str = ""
    steps: list[StepResult] = field(default_factory=list)
    final_summary: str = ""

    @property
    def total_cost_usd(self) -> float:
        return round(sum(s.cost_usd for s in self.steps), 4)

    @property
    def total_duration_s(self) -> float:
        return round(sum(s.duration_s for s in self.steps), 1)


# An event callback receives (event_name, payload) for live progress display.
EventCallback = Callable[[str, dict[str, Any]], None]

# Backoff (seconds) for resuming after a rate/usage limit. Escalates toward an
# hour so the run survives the typical multi-hour usage-window reset.
_LIMIT_BACKOFF = [60, 300, 900, 1800, 3600, 3600, 3600]
# Quick retries for plain transient blips (network, empty/garbled output).
_TRANSIENT_BACKOFF = [20, 60, 120]

# Patterns that mean "wait and resume" vs. "give up" (the prompt itself is bad).
_LIMIT_PATTERNS = (
    "rate limit",
    "rate_limit",
    "ratelimit",
    "overloaded",
    "usage limit",
    "limit reached",
    "too many requests",
    "429",
    "529",
    "over capacity",
    "capacity",
    "quota",
    "exhausted",
    "try again later",
    "temporarily unavailable",
    "service unavailable",
    "5-hour",
    "resets at",
    "resets",
    "session limit",
    "hit your",
    "usage limit reached",
    "limit will reset",
)
_HARD_PATTERNS = (
    "prompt is too long",
    "context length",
    "context_length",
    "maximum context",
    "too long",
    "invalid api key",
    "authentication",
)
# A resume target that no longer exists → fall back to a fresh run, don't retry.
_SESSION_GONE_PATTERNS = (
    "no conversation found",
    "session not found",
    "no session found",
    "could not find session",
    "couldn't find session",
    "no such session",
)

# Indirection so tests can run without real sleeping.
_sleep = time.sleep


def _emit(on_event: EventCallback | None, name: str, **payload: Any) -> None:
    if on_event is not None:
        on_event(name, payload)


def _run_claude_step(
    prompt: str,
    *,
    resume_session_id: str | None,
    model: str,
    effort: str,
    timeout: int,
    cwd: Path,
) -> StepResult:
    """Invoke `claude -p` once (stdin prompt) and return its result.

    A fresh step (``resume_session_id=None``) starts a new session and the
    returned ``session_id`` is captured so later steps can ``--resume`` it.
    Classifies failures into LimitError / RetryableError / AnalysisError.
    """
    cmd = [
        _claude_bin(),
        "-p",
        "--output-format",
        "json",
        "--dangerously-skip-permissions",
        "--model",
        model,
        "--effort",
        effort,
        # Full machine access: read/write/navigate anywhere under $HOME.
        "--add-dir",
        str(Path.home()),
    ]
    # Curated MCP servers (research + filesystem + browser), strict so only ours.
    mcp_path = cwd / _MCP_FILENAME
    if mcp_path.exists():
        cmd += ["--mcp-config", str(mcp_path), "--strict-mcp-config"]
    if resume_session_id:
        cmd += ["--resume", resume_session_id]

    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd),
        )
    except subprocess.TimeoutExpired as exc:
        # A timeout is treated as transient — the window may have been slow.
        raise RetryableError(f"Claude step timed out after {timeout}s") from exc

    duration = time.monotonic() - started
    data: dict[str, Any] = {}
    try:
        data = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        data = {}

    blob = f"{proc.stderr}\n{data.get('result', '')}\n{data.get('subtype', '')}".lower()

    def _is(patterns: tuple[str, ...]) -> bool:
        return any(p in blob for p in patterns)

    failed = proc.returncode != 0 or data.get("is_error") or not data

    if failed:
        detail = (proc.stderr.strip() or str(data.get("result", "")) or "sem detalhe")[:500]
        if _is(_SESSION_GONE_PATTERNS):
            raise SessionNotFoundError(f"Sessão de resume não encontrada: {detail}")
        if _is(_HARD_PATTERNS):
            raise AnalysisError(f"Erro não-recuperável do Claude: {detail}")
        if _is(_LIMIT_PATTERNS):
            raise LimitError(f"Limite de uso/taxa do Claude: {detail}")
        # Unknown failure shape → treat as transient (a few quick retries).
        raise RetryableError(f"Falha transitória do Claude (rc={proc.returncode}): {detail}")

    result = (data.get("result") or "").strip()
    if not result:
        raise RetryableError("Claude retornou resultado vazio")

    return StepResult(
        label="",
        result=result,
        cost_usd=float(data.get("total_cost_usd") or 0.0),
        duration_s=round(duration, 1),
        session_id=str(data.get("session_id") or ""),
        num_turns=data.get("num_turns"),
    )


def _seconds_until_reset(message: str, *, cap: int = 6 * 3600) -> int | None:
    """Parse a usage-limit reset time (e.g. 'resets 8:20pm') → seconds to wait.

    Lets the agent wait exactly until the window reopens instead of guessing,
    which is the right behavior for Claude session limits. Returns None if no
    reset time is present. Assumes the machine's local timezone.
    """
    m = re.search(
        r"reset[s]?(?:\s+at)?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", message, re.IGNORECASE
    )
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ampm = (m.group(3) or "").lower()
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # Session limits reset within hours (same day, future). If the parsed time
    # already passed, the window has reopened — fall back to short backoff.
    if target <= now:
        return None
    return min(int((target - now).total_seconds()) + 60, cap)  # +60s buffer


def _run_step_resilient(
    prompt: str,
    *,
    resume_session_id: str | None,
    model: str,
    effort: str,
    timeout: int,
    cwd: Path,
    on_event: EventCallback | None,
    step: int,
    total: int,
    title: str,
) -> StepResult:
    """Run one step, auto-resuming on limit/transient errors.

    Rate/usage limits wait until the parsed reset time (or escalating backoff);
    transient blips get a few quick retries.
    """
    attempt = 0
    while True:
        try:
            return _run_claude_step(
                prompt,
                resume_session_id=resume_session_id,
                model=model,
                effort=effort,
                timeout=timeout,
                cwd=cwd,
            )
        except RetryableError as exc:
            is_limit = isinstance(exc, LimitError)
            schedule = _LIMIT_BACKOFF if is_limit else _TRANSIENT_BACKOFF
            if attempt >= len(schedule):
                raise
            # For usage limits, wait until the announced reset; else backoff.
            reset_wait = _seconds_until_reset(str(exc)) if is_limit else None
            wait = reset_wait if reset_wait is not None else schedule[attempt]
            attempt += 1
            _emit(
                on_event,
                "step_retry",
                step=step,
                total=total,
                title=title,
                attempt=attempt,
                wait_s=wait,
                kind="limit" if is_limit else "transient",
                error=str(exc),
            )
            logger.warning(
                "step_retry",
                title=title,
                attempt=attempt,
                wait_s=wait,
                kind="limit" if is_limit else "transient",
                error=str(exc),
            )
            _sleep(wait)


def run_chain(
    steps: list[tuple[str, str]],
    *,
    run_id: str,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    step_timeout: int = DEFAULT_STEP_TIMEOUT,
    min_holding_days: int | None = None,
    on_event: EventCallback | None = None,
    persist: Callable[[int, str, StepResult], None] | None = None,
    resume_session_id: str | None = None,
    on_session_id: Callable[[str], None] | None = None,
) -> RunSummary:
    """Run an ordered list of (title, prompt) steps in one chained Claude session.

    The first step starts a fresh session; its captured id is resumed by every
    later step (context carries across the whole chain). Each step auto-resumes
    on rate/usage limits. ``persist(index, title, result)`` is called as each
    step finishes so progress is durable and auditable. Generic over N steps —
    used by both the monthly contribution run and the weekly/maturity reviews.
    """
    min_holding_days = (
        min_holding_days if min_holding_days is not None else settings.min_holding_days
    )
    workspace = _ensure_workspace(min_holding_days)
    summary = RunSummary(run_id=run_id)
    summary.session_id = resume_session_id or ""
    total = len(steps)

    for index, (title, prompt) in enumerate(steps):
        _emit(on_event, "step_start", step=index + 1, total=total, title=title)
        result = _run_step_resilient(
            prompt,
            resume_session_id=summary.session_id or None,
            model=model,
            effort=effort,
            timeout=step_timeout,
            cwd=workspace,
            on_event=on_event,
            step=index + 1,
            total=total,
            title=title,
        )
        result.label = title
        if not summary.session_id:
            summary.session_id = result.session_id
            if not summary.session_id:
                raise AnalysisError("Claude não retornou session_id na 1ª etapa")
            if on_session_id is not None:
                on_session_id(summary.session_id)
        summary.steps.append(result)
        if persist is not None:
            persist(index, title, result)
        _emit(
            on_event,
            "step_done",
            step=index + 1,
            total=total,
            title=title,
            cost_usd=result.cost_usd,
            duration_s=result.duration_s,
            result=result.result,
        )

    summary.final_summary = summary.steps[-1].result if summary.steps else ""
    return summary


def run_analysis(
    session: Session,
    contribution_id: UUID,
    *,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    step_timeout: int = DEFAULT_STEP_TIMEOUT,
    min_holding_days: int | None = None,
    notify: bool = True,
    on_event: EventCallback | None = None,
) -> RunSummary:
    """Run every prompt of a contribution in order, then synthesize the result.

    Runs headless in the persistent agent workspace (standing orders + memory
    auto-loaded), persists each prompt response as it completes, stores the
    consolidated summary and pushes it to Telegram. Raises ``AnalysisError`` on
    failure (and marks the contribution back to READY so it can be retried).
    """
    min_holding_days = (
        min_holding_days if min_holding_days is not None else settings.min_holding_days
    )

    contribution = session.get(Contribution, contribution_id)
    if contribution is None:
        raise AnalysisError(f"Contribution {contribution_id} not found")

    prompts = list(
        session.exec(
            select(ContributionPrompt)
            .where(ContributionPrompt.contribution_id == contribution_id)
            .order_by(ContributionPrompt.prompt_order)
        ).all()
    )
    if not prompts:
        raise AnalysisError("Contribution has no prompts to run")

    preamble = _build_preamble(
        amount_brl=float(contribution.amount_brl),
        when=contribution.created_at.date().isoformat(),
        min_holding_days=min_holding_days,
    )
    # Optional: surface the latest weekly review so the committee can consult it.
    review_ctx = _latest_weekly_context(session)

    all_steps: list[tuple[str, str]] = []
    for index, prompt in enumerate(prompts):
        head = (preamble + review_ctx) if index == 0 else ""
        all_steps.append((prompt.title, head + prompt.content))
    all_steps.append(("Fechamento executivo", _SYNTHESIS_PROMPT))

    # Resume point: prompts fill in order, so the completed ones are a prefix.
    done_prompts = 0
    for prompt in prompts:
        if prompt.response:
            done_prompts += 1
        else:
            break
    # Nothing left to do — every meeting and the closing summary are persisted.
    if done_prompts == len(prompts) and contribution.final_summary:
        _emit(
            on_event,
            "run_done",
            contribution_id=str(contribution_id),
            total_cost_usd=0.0,
            total_duration_s=0.0,
            final_summary=contribution.final_summary,
        )
        return RunSummary(
            run_id=str(contribution_id),
            session_id=contribution.claude_session_id or "",
            final_summary=contribution.final_summary,
        )

    resume_index = min(done_prompts, len(prompts))
    saved_session = contribution.claude_session_id
    # True resume needs Claude's chained session; without it, restart fresh.
    if not (resume_index > 0 and saved_session):
        resume_index, saved_session = 0, None

    contribution.status = ContributionStatus.IN_PROGRESS
    session.add(contribution)
    session.commit()

    _emit(
        on_event,
        "run_start",
        contribution_id=str(contribution_id),
        total_steps=len(all_steps) - resume_index,
        model=model,
        effort=effort,
    )
    if resume_index > 0:
        _emit(
            on_event,
            "run_resume",
            contribution_id=str(contribution_id),
            from_step=resume_index + 1,
            total=len(all_steps),
            done=resume_index,
        )

    def _execute(from_index: int, sess: str | None) -> RunSummary:
        steps = all_steps[from_index:]

        def _persist(index: int, title: str, step: StepResult) -> None:
            abs_index = from_index + index
            if abs_index < len(prompts):
                prompts[abs_index].response = step.result
                prompts[abs_index].responded_at = datetime.now(UTC)
                session.add(prompts[abs_index])
                session.commit()

        def _save_session(sid: str) -> None:
            contribution.claude_session_id = sid
            session.add(contribution)
            session.commit()

        return run_chain(
            steps,
            run_id=str(contribution_id),
            model=model,
            effort=effort,
            step_timeout=step_timeout,
            min_holding_days=min_holding_days,
            on_event=on_event,
            persist=_persist,
            resume_session_id=sess,
            on_session_id=_save_session,
        )

    try:
        try:
            summary = _execute(resume_index, saved_session)
        except SessionNotFoundError as exc:
            logger.warning(
                "resume_session_gone_restarting_fresh",
                contribution_id=str(contribution_id),
                error=str(exc),
            )
            contribution.claude_session_id = None
            session.add(contribution)
            session.commit()
            _emit(on_event, "run_resume_failed", contribution_id=str(contribution_id))
            summary = _execute(0, None)

        contribution.final_summary = summary.final_summary
        contribution.status = ContributionStatus.COMPLETED
        contribution.completed_at = datetime.now(UTC)
        session.add(contribution)
        session.commit()

        if notify and telegram_service.is_enabled():
            header = (
                f"📊 Recomendação do aporte de R$ {float(contribution.amount_brl):,.2f} "
                f"({contribution.created_at.date().isoformat()})\n"
                "Registre no app o que você comprar.\n\n"
            )
            telegram_service.notify(header + summary.final_summary)

        _emit(
            on_event,
            "run_done",
            contribution_id=str(contribution_id),
            total_cost_usd=summary.total_cost_usd,
            total_duration_s=summary.total_duration_s,
            final_summary=summary.final_summary,
        )
        logger.info(
            "analysis_completed",
            contribution_id=str(contribution_id),
            steps=len(summary.steps),
            cost_usd=summary.total_cost_usd,
        )
        return summary

    except Exception as exc:
        # Leave finished prompt responses in place but mark the run retryable.
        contribution.status = ContributionStatus.READY
        contribution.notes = f"[run failed @ {datetime.now(UTC).isoformat()}] {exc}"
        session.add(contribution)
        session.commit()
        _emit(on_event, "run_error", contribution_id=str(contribution_id), error=str(exc))
        logger.error("analysis_failed", contribution_id=str(contribution_id), error=str(exc))
        if isinstance(exc, AnalysisError):
            raise
        raise AnalysisError(str(exc)) from exc
