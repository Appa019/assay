# Investimentos Manual

Gestão de aportes (AD-HOC, sem ciclo fixo) com comitê multipersona de IA padrão
**Goldman Sachs GIR + Morgan Stanley GIC + Bridgewater + AQR**. A cada aporte o
backend gera prompts extensos (~110k chars total) rodados no Claude Code (alias
`opus` → Opus mais recente, hoje Opus 5 + max reasoning +
dangerously-skip-permissions). 100% local. A carteira é
revisada toda semana; aporte novo só quando o cliente quiser.

Há dois modos de execução:
- **Automático (padrão)**: o orquestrador (`app/services/analysis_runner.py`)
  abre o `claude` headless e roda as reuniões em ordem numa **única sessão
  encadeada** (cada reunião herda o contexto da anterior), salva cada resposta
  e produz um fechamento "onde investir e quanto". Dispare via CLI
  (`scripts/run_analysis.py`), via `POST /api/contributions?run=true`, ou via
  `POST /api/contributions/{id}/run`. O front faz polling e mostra etapa por etapa.
- **Manual**: `POST /api/contributions` (sem `run`) só gera os prompts para
  colar à mão; o front mantém esse fluxo como fallback.

O agente roda autônomo: workspace persistente próprio
(`storage/agent_workspace/` com CLAUDE.md de ordens permanentes + MEMORY.md
que ele mesmo gerencia entre ciclos), carta branca (web + Bash + criar
ferramentas via `--dangerously-skip-permissions`), effort sempre `max`, e
respeita a trava de venda de `MIN_HOLDING_DAYS` (30) dias (só ações/crypto). Ao
concluir, manda a recomendação no **Telegram**; quando um lote de ação/crypto
completa 30 dias, um cron roda a análise de maturidade. Aporte é ad-hoc.

### Ciclos e mandato (2026-05)
- **Aporte (ad-hoc)**: 5 etapas encadeadas + fechamento → folha de ordens.
- **Revisão semanal (7d)**: comitê analisa macro + desempenho das posições +
  maturidade → `Report(weekly)` salvo + Telegram; injetado como consulta nos
  aportes (`analysis_runner._latest_weekly_context`).
- **Maturidade (por LOTE, só AÇÕES e CRYPTO)**: a trava de 30d é por compra
  (cada `Asset` é um lote com seu `entry_date`). **CDB/Renda Fixa = liquidez
  diária, SEM trava** (dry powder) — excluído de `pending_maturities`, vendável
  a qualquer hora no `/vender`. Ao um lote de ação/crypto cruzar 30d,
  `check_cadence` roda análise de maturidade → `Report(maturity)` + Telegram.
- **Rotação de dry powder**: a revisão semanal pode recomendar VENDER CDB e
  COMPRAR uma ação/crypto se achar oportunidade relevante (a nova compra entra
  na trava de 30d).
- **Mandato de alocação**: Renda Fixa = **100% CDB**; Ações = **só equities da
  B3** (sem FII/ETF/BDR); Crypto = **agressivo** (alto upside, com risco). Está
  nas ordens permanentes, no preâmbulo, na síntese e nos cabeçalhos dos templates.
- **Auto-resume (no processo)**: se uma etapa falha por limite de uso/taxa,
  `run_chain` espera (até a hora do reset, backoff até ~1h) e retoma a MESMA
  etapa via `--resume` automaticamente.
- **Resume entre reinícios de processo**: o `session_id` do Claude é persistido
  em `Contribution.claude_session_id` e cada resposta é salva ao concluir. Se o
  processo morrer (créditos/queda), re-rodar `run_analysis` (CLI
  `--contribution-id <uuid>`) RETOMA da 1ª etapa não concluída na MESMA sessão
  encadeada — não refaz as reuniões já feitas. Se a sessão expirou
  (`SessionNotFoundError`), recomeça do zero sozinho. Migração da coluna em
  `core/database._ensure_sqlite_columns`.
- **Retomada AUTOMÁTICA (sem você re-rodar)**: `scripts/resume_pending.py` acha
  análises automáticas incompletas (`claude_session_id` set + `final_summary`
  null) e as retoma; roda no cron a cada 15 min (`install_cron.sh`) ou em loop
  (`--watch [s]`). Assim, se o limite/créditos acabarem e o processo morrer, o
  sistema conclui sozinho quando o limite voltar. Um **lock PID por aporte**
  (`analysis_runner._acquire_run_lock`, arquivos em `storage/analysis_runs/`)
  impede rodar em dobro com um run vivo (CLI/API/bot). Avisa no Telegram ao retomar.
- **MCPs + acesso total + auto-provisionamento**: cada run usa
  `--mcp-config storage/agent_workspace/.mcp.json` + `--strict-mcp-config` e
  `--add-dir $HOME` + `--dangerously-skip-permissions` → navega a máquina toda,
  cria arquivos e usa browser real. O `.mcp.json` efetivo é gerado a cada run
  como **baseline curado ∪ `.mcp.agent.json`** — este último é do AGENTE (ele
  adiciona QUALQUER MCP novo, nunca é sobrescrito, carrega no próximo ciclo).
  Baseline em 3 tiers: **(1) runtime (8)** sequential-thinking, filesystem,
  fetch, context7, playwright, memory, time, git; **(2) dados financeiros
  sem-chave (4, sempre on)** coingecko, yahoo-finance (B3 `.SA`), defillama, exa;
  **(3) premium key-gated (5, ligam só se a chave existir no `.env`)** glassnode,
  coinglass, messari, firecrawl, tavily — definidos em `_KEY_GATED_MCP_SERVERS`,
  a chave chega ao run via `_agent_subprocess_env()` (injeta as env vars do
  `.env`, que o pydantic não exporta) e o `.mcp.json` usa `${VAR}` (sem segredo
  em disco). Strict EXCLUI Gmail/Calendar/Drive de propósito (autônomo).
  Builders em `analysis_runner._baseline_mcp_servers()` + `_effective_mcp_config()`;
  o workspace é repo git (versiona as ferramentas em `tools/`).
- **Time GS/J.P. Morgan**: ordens permanentes + prompts convocam uma mesa completa
  (economista-chefe, alocação, equity B3, crypto, RF, quant, CRO, forensic, CIO).
- **Bot exclusivo**: `telegram_bot.py` só responde ao `TELEGRAM_CHAT_ID`; qualquer
  outro chat é ignorado e logado.

**Stack:** Python FastAPI + SQLModel/SQLite (backend) · Next.js 16 +
TypeScript + Tailwind v4 (frontend) · pnpm (JS) · pip + venv (Python) ·
Telegram Bot API (notificações + controle). Sem Supabase, sem auth, sem nuvem,
sem Playwright.

### Dados & confiabilidade (2026-07)
- **Marcação a mercado**: `price_refresh_service` atualiza `current_price` de
  TODO lote (ações via Yahoo, crypto via CoinGecko, CDB por CDI acumulado —
  série 12 BCB × `CDB_PCT_CDI`). Roda por cron/systemd, `POST /api/portfolio/
  refresh`, `/atualizar` no bot e antes das revisões.
- **Ledger `Trade`**: toda compra/venda vira linha imutável com P&L realizado
  (`GET /api/portfolio/trades`); a venda continua removendo o `Asset`, mas o
  histórico é permanente (base de track record e IR).
- **Trava de 30d é enforced no service** (`portfolio_service.sell_asset` →
  `SellLockedError` → API 409). O bot pede confirmação em 2 passos no /vender.
- **Snapshot diário** (`portfolio_snapshot`, upsert) → curva de patrimônio em
  `GET /api/portfolio/history` (cron `daily_snapshot.py`).
- **SQLite em WAL** + busy_timeout (API + bot + crons concorrentes) e backup
  diário com rotação (`backup_db.sh`).
- **Locks**: por aporte E global (1 execução pesada de Claude por vez, entre
  processos), criação atômica + identidade de PID via /proc (sem reclaim por
  idade). `IN_PROGRESS` órfão não trava mais o re-run (409 só com lock vivo).
- **Retry**: contadores independentes p/ limite × transiente; reset pós-meia-
  noite tratado; `run_attempts` limita retomadas (`MAX_RUN_ATTEMPTS`, aviso ao
  desistir); `resume_pending` roda fail-fast (re-tenta no próximo pass).
- **Transcripts**: stdout/stderr brutos de cada invocação do CLI em
  `storage/analysis_runs/transcripts/` (flight recorder); custo/duração/turnos
  por etapa persistidos em `ContributionPrompt`.
- **Track record**: contexto com vendas realizadas (P&L, hit-rate) é injetado
  na 1ª reunião de todo aporte; teses/alvo/stop por lote (`Asset.thesis`,
  `target_price`, `stop_price`) entram na revisão semanal.
- **Encadeamento por arquivos**: cada reunião salva seu JSON em
  `workspace/out/<contribution_id>/etapa_NN.json` e lê os anteriores se o
  contexto truncar; notas em `./notes/` (não /tmp). Fechamento exige bloco
  ```json {"orders": [...]}``` (máquina-legível p/ track record futuro).
- **Datas dinâmicas nos prompts**: tenores DI, trimestres de earnings e anos de
  preço-alvo vêm de `prompt_generator._date_context` (nada de DI jan/26 morto);
  regra fiscal de dividendos é VERIFICADA ao vivo, PGBL/holding viraram
  observação fora do mandato.
- **Alertas de falha**: todo cron avisa no Telegram quando QUEBRA, não só o
  sucesso. Bot é single-instance (pidfile), sobrevive a qualquer exceção de
  rede, drena o backlog inteiro no boot e registra o menu via setMyCommands.
- **Pareamento seguro**: `telegram_setup.py` exige código de 6 dígitos — o
  primeiro chat aleatório não vira mais dono do bot.
- **systemd (preferido)**: `scripts/install_systemd.sh` instala backend + bot
  (Restart=always) e timers persistentes (recuperam janelas perdidas com a
  máquina desligada). Cron continua disponível via `install_cron.sh` (flock +
  PATH corretos).

### Produto (2026-07, camada sobre o ledger)
- **Ordens estruturadas**: o fechamento emite bloco ```json {"orders": []}```
  que vira linhas `Order` (ingest idempotente pós-run). `/ordens` mostra a
  folha pendente; `/executei <ticker> <qtd> <preço>` confirma a execução e o
  lote criado HERDA tese/alvo/stop do comitê. API: `/api/orders` (+ execute/
  skip). Base do track record recomendação × realidade.
- **Benchmark**: `GET /api/portfolio/benchmark` — TWR da carteira
  (neutralizando fluxos via ledger) vs CDI/IBOV/BTC, rebased 100.
- **Alertas de nível**: `check_alerts.py` (3x/dia) avisa no Telegram quando o
  preço cruza o alvo/stop registrado no lote; um alerta por cruzamento
  (rearma quando volta à banda). Estado em `storage/alerts_state.json`.
- **IR**: `GET /api/tax/{ano}` + `/ir` no bot — apuração SIMPLIFICADA mensal
  (isenções 20k ações / 35k crypto, carryforward de prejuízo, DARF mínima,
  CDB informativo retido na fonte, posição 31/12). Não substitui contador.
- **Relatório mensal**: `monthly_report.py` (dias 1-2) → Report(monthly) +
  Telegram (texto + anexo .md): patrimônio, operações, IR do mês, custo de
  análise. `--force` gera do mês corrente.
- **Consultor em tempo real (chat, 2026-07-28)**: qualquer texto SEM `/` no bot
  é uma conversa com o consultor (`app/services/chat_service.py`) — sessão
  Claude encadeada persistente (`storage/chat_workspace/session.json` sobrevive
  a reinícios; rotaciona após `CHAT_MAX_TURNS` turnos), workspace PRÓPRIO
  (`storage/chat_workspace/`) com CLAUDE.md de ordens do consultor (reescrito a
  cada turno) + MEMORY.md (memória FIXA sobre o cliente, gerida pelo próprio
  agente) + mesmos MCPs financeiros do comitê (baseline ∪ `.mcp.agent.json` do
  chat, `--strict-mcp-config`). Modelo/effort próprios: `CHAT_MODEL` (opus) /
  `CHAT_EFFORT` (high) / `CHAT_TURN_TIMEOUT` (900s). Ele registra gastos/ganhos
  que o cliente contar via `POST /api/cashflow` (source=chat), consulta
  carteira/IR/ordens pela API local e responde tickers com dados ao vivo
  (yahoo-finance/coingecko). Lock de turno próprio (`_chat_turn.lock`) — NÃO usa
  o lock global pesado, então chat funciona mesmo com comitê rodando; fila
  serial no bot com indicador "digitando…". Limite de uso → mensagem amigável
  (fail-fast, sem esperar horas). `/resetchat` descarta a sessão (memória fica).
- **Ledger de finanças pessoais (`CashflowEntry`, 2026-07-28)**: gastos e
  ganhos do dia a dia, separado do ledger `Trade`. API `/api/cashflow` (POST /
  GET com `month=`+`kind=` / DELETE / `GET /summary?month=YYYY-MM` com totais e
  por categoria). Bot: `/gasto <valor> [descrição #categoria]`, `/ganho ...`,
  `/financas [AAAA-MM]`; categorias normalizadas p/ minúsculas; fontes:
  chat | bot | api.

## Commands
- `./start.sh`: Inicia backend + frontend, abre browser (uso diário; sem
  --reload por padrão — `START_RELOAD=1` p/ dev)
- `./install.sh`: Setup inicial (venv, deps, atalho Desktop)
- `make check`: ruff + pytest + lint/type-check/build do frontend (o que a CI roda)
- `.venv/bin/python -m pytest`: suíte de testes do backend (tests/)
- `.venv/bin/python scripts/refresh_prices.py`: marcação a mercado agora
- `.venv/bin/python scripts/daily_snapshot.py`: snapshot da curva de patrimônio
- `bash scripts/backup_db.sh`: backup do SQLite com rotação
- `bash scripts/install_systemd.sh [--uninstall]`: units + timers persistentes
- `.venv/bin/python scripts/run_analysis.py --amount 5000`: cria o aporte e
  roda a análise inteira no terminal, etapa por etapa (opus/max por padrão).
  Flags úteis: `--notes`, `--contribution-id <uuid>` (re-rodar), `-y` (sem
  confirmação), `--no-telegram`, `--model haiku --effort low` (teste barato).
- `.venv/bin/python scripts/telegram_setup.py`: detecta o chat_id (mande /start
  ao bot antes) e grava em `.env`
- `.venv/bin/python scripts/telegram_bot.py`: bot interativo (também sobe no
  start.sh se Telegram configurado)
- `.venv/bin/python scripts/check_cadence.py`: roda análise de maturidade dos
  lotes de ação/crypto que cruzaram 30d (cron diário). Sem nag de aporte (ad-hoc)
- `.venv/bin/python scripts/weekly_review.py [--force]`: revisão semanal do
  comitê (macro + carteira + maturidade); auto-regula a 7 dias
- `.venv/bin/python scripts/resume_pending.py [--watch [s]]`: retoma análises de
  aporte interrompidas (limite/queda), continuando de onde pararam; roda no cron
  a cada 15 min
- `scripts/install_cron.sh [hora]`: instala os crons (maturidade + revisão
  semanal + retomada a cada 15 min; `--uninstall` remove)
- `.venv/bin/uvicorn app.main:app --reload`: backend dev (porta 8000)
- `cd frontend && pnpm dev`: frontend dev (porta 3000)
- `cd frontend && pnpm lint && pnpm type-check && pnpm build`: validação
- `.venv/bin/ruff check app/ && .venv/bin/ruff format app/`: lint Python

## Architecture
- `/app`: FastAPI backend
  - `agents_prompts/`: 5 templates Jinja2 (macro · seleção · DD ações · DD crypto · decisão)
  - `core/database.py`: SQLite + SQLModel
  - `models/`: Asset, Contribution, ContributionPrompt, Report (weekly/
    maturity), Order, Trade, PortfolioSnapshot, CashflowEntry (gastos/ganhos)
  - `routers/`: portfolio, contributions, macro, cadence, reports, orders, tax,
    cashflow
  - `services/`: portfolio_service, market_data_service, prompt_generator,
    contribution_service (cria aporte + renderiza prompts), analysis_runner
    (MOTOR: `run_chain` genérico encadeado + auto-resume por limite + workspace/
    memória; `run_analysis` p/ aporte), review_service (revisão semanal +
    maturidade via run_chain → Report), telegram_service (Bot API),
    notification_service (marcos de 30 dias por lote), chat_service (consultor
    do Telegram: turno de chat = `_run_claude_step` no chat_workspace),
    cashflow_service (ledger pessoal de gastos/ganhos)
- `/scripts/`: run_analysis (aporte→análise), telegram_setup, telegram_bot,
  check_cadence, weekly_review, resume_pending (retoma análises interrompidas),
  install_cron
- `/storage/agent_workspace/`: workspace persistente do agente (gitignored) —
  CLAUDE.md (ordens permanentes, reescrito a cada run), MEMORY.md (memória do
  agente), tools/ (ferramentas que ele cria)
- `/storage/chat_workspace/`: workspace do consultor do Telegram (gitignored) —
  CLAUDE.md (ordens do consultor), MEMORY.md (memória fixa sobre o cliente),
  session.json (sessão encadeada + contagem de turnos)
- `/frontend/src/app/(dashboard)`: páginas
- `/storage/portfolio.db`: SQLite (auto-criado no boot)
- `/storage/logs/`: logs do start.sh

## Code Standards
- TypeScript strict, sem `any`, sem `@ts-ignore`
- Named exports salvo onde Next.js exige default (pages, layouts)
- const/let only
- Arrow functions para componentes/callbacks
- async/await sempre
- Python: type hints, Pydantic para boundaries, async def

## Perfil do investidor (preferências do cliente — referência local)

> Essas preferências SÃO INFORMAÇÃO LOCAL para você (Claude). Os prompts
> NÃO devem refletir nada disso — o comitê multipersona dentro dos
> prompts é agnóstico de plataforma e foca apenas em decisão de
> investimento (o quê comprar, quanto, quando). Plataforma e exchange
> são decisão do usuário ao executar a folha de ordens.

- **Escopo de ativos (mandato)**: três classes APENAS — Renda Fixa = 100%
  CDB, Ações = só equities da B3, Crypto = agressivo. SEM FII/ETF/BDR,
  Tesouro, LCI/LCA, debêntures, fundos ou internacional direto.
- **Broker B3 preferido**: a corretora do banco para ações e CDB.
- **Crypto**: comitê é agnóstico (escolhe por liquidez/segurança). Usuário
  decide exchange:
  - BTC/ETH/majors: Mercado Bitcoin, Binance BR, Bitso, Coinext
  - Alts de menor liquidez: Binance BR
  - DeFi yield (USDC/USDT/USDe): wallet própria (MetaMask) + Aave / Pendle /
    Spark / Lido / Morpho
- **Exposição USD permitida**: stablecoins (USDC) via crypto. Não há
  stocks USA direto.

## IMPORTANT
- NEVER commit `.env` files ou expor secrets (inclui TELEGRAM_BOT_TOKEN)
- NEVER voltar Supabase / Playwright / Avenue integration — projeto foi
  simplificado intencionalmente. (Telegram + scheduler/cron foram REINTRODUZIDOS
  a pedido do usuário em 2026-05; não são mais proibidos.)
- Dois fluxos: AUTOMÁTICO (analysis_runner orquestra o `claude` CLI headless,
  encadeado, e salva tudo) e MANUAL (backend só gera prompts p/ colar à mão).
  O orquestrador roda no `storage/agent_workspace/` (CLAUDE.md + MEMORY.md
  auto-carregados), via subprocess do `claude` com
  `--dangerously-skip-permissions --effort max --model opus --output-format json`;
  a 1ª etapa roda fresh e o `session_id` é capturado do JSON de saída, as
  etapas seguintes usam `--resume <id>` (e o id é persistido em
  `Contribution.claude_session_id` para retomar entre reinícios de processo)
- effort SEMPRE `max` no fluxo automático; agente tem carta branca e gerencia
  a própria memória em `storage/agent_workspace/MEMORY.md`
- Trava de venda: `MIN_HOLDING_DAYS` (30) dias por LOTE vale só p/ AÇÕES e
  CRYPTO. CDB/Renda Fixa = liquidez diária (vende a qualquer hora). O bot
  bloqueia `/vender` de ação/crypto antes do prazo, mas libera CDB sempre
- Bot do Telegram é PRIVADO: responde só ao `TELEGRAM_CHAT_ID` configurado
- Os prompts são para Claude Code CLI (com WebSearch/WebFetch/Bash) —
  não para claude.ai web
- NUNCA commitar `storage/claude_session.json` (credenciais) — está no
  .gitignore; é resíduo do Playwright antigo, não é usado pelo orquestrador
- **NÃO mencione plataforma específica DENTRO dos prompts** — comitê é
  agnóstico
- Sempre rode `pnpm lint && pnpm type-check && pnpm build` antes de
  commits no frontend
- Sempre rode validação Python antes de commits no backend
- Commits em inglês, Conventional Commits (feat:, fix:, chore:, refactor:)
- NEVER mencionar Claude em commits, código ou co-author tags

## As 5 etapas (3 classes: CDB · Ações B3 · Crypto)

Mandato NATIVO: todo o universo analisado é CDB, Ações B3 e Crypto (fora do
escopo só em linhas de veto). Schema JSON `version=5.0`,
`escopo=BR_3_classes_cdb_acoesB3_crypto`. As etapas rodam encadeadas numa única
sessão; cada uma lê o JSON das anteriores. A pesquisa foi **SPLITADA** (seleção →
DD ações → DD crypto, 2026-05-24) para cada nome receber um turno dedicado de DD
profunda — resolve o gargalo de output da antiga reunião única de research.
Templates em `app/agents_prompts/` (01_macro_strategy, 02_research_selection,
03_equity_diligence, 04_crypto_diligence, 05_decision_orders); mapeados em
`prompt_generator._PROMPT_DEFINITIONS`; `PromptKey` =
macro/selection/equity_diligence/crypto_diligence/decision.

### Reunião nº 1 — Macro · Alocação Tática (GIC)
12 personas. 11 rounds: Top of Mind → macro BR → macro global → juros & CDB
(curva DI como SINAL de CDI; FGC) → setor B3 + style tilts → crypto on-chain →
risk frame + Black-Litterman (3 buckets) → ESG/special sit → tax → behavioral →
decisão tactical (BL+RP+HRP) → pre-mortem. Saída: `final_tactical_brl`
(cdb/acoes_b3/crypto), `juros_e_cdb`, `setores_b3`, `digital_assets`.

### Reunião nº 2 — Universo, Filtros e Seleção (+ CDB final)
12 personas + 2 vetos. Universo → long lists → filtros (quant + forense preview)
→ **SELEÇÃO** (5-8 ações + 3-5 cryptos, com sizing-alvo) → **CDB final** com
credit analysis. Saída: `selecao_acoes_b3`, `selecao_crypto`, `shortlist_cdb`
(valor_brl + credit do emissor), `sanidade_selecao`. NÃO escreve o memo final.

### Reunião nº 3 — Due Diligence de Ações B3
Equity desk. Memo COMPLETO por ação de `selecao_acoes_b3`: thesis + valuation
triangulada (DCF 3-stage/Reverse/CCA/Precedent/LBO/SOTP) + forense (Piotroski/
Altman/Beneish/Sloan/Dechow) + Capital Allocation + técnica + factor + bull/base/
bear. Saída: `shortlist_acoes_b3` (objeto completo por nome) + pair_trades. Pode
usar subagentes (Task) por ticker (memo em ./dd/), best-effort.

### Reunião nº 4 — Due Diligence de Crypto
Crypto desk. Memo COMPLETO por cripto de `selecao_crypto`: tese + tokenomics/
unlocks + on-chain (MVRV-Z/NUPL/SOPR/…) + derivativos (Coinglass) + dev activity
+ bull/base/bear. Saída: `shortlist_crypto`. BTC+ETH ≥ 50%. Subagentes por nome
(best-effort).

### Reunião nº 5 — Investment Committee Final
14 personas. 14 rounds: risk overlay (VaR/CVaR/EVT/CDaR/Component VaR) → stress 8
cenários (incl. **evento de crédito bancário**) → sentiment + IV/RV → confirma
CDB (vindo da R2) → tax → pair trades + options (informativos, não geram ordem)
→ compliance → behavioral →
cross-check CIO → execution → folha de ordens → monitoramento → resumo. Bolso ∈
{cdb, acoes_b3, crypto}.

**Folha de ordens SEM coluna plataforma** — cliente decide onde executar.

## Pré-requisitos de runtime
- Python 3.11+
- Node 20+ com pnpm (install.sh instala via npm se não houver)
- Acesso à internet (BCB, Yahoo Finance, CoinGecko)
- Projeto em filesystem ext4 (NTFS via ntfs-3g não preserva bits +x)

## Memória do projeto
- Memória persistente em `~/.claude/projects/<encoded>/memory/`
- Consulte ao retomar sessão futura para recuperar contexto
- Salve em `feedback_lessons.md` se descobrir erros de ticker / CG id
- Salve em `project_patterns.md` se mudar padrão de prompt que funcionou
