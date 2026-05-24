# Investimentos Manual

Gestão de aportes (AD-HOC, sem ciclo fixo) com comitê multipersona de IA padrão
**Goldman Sachs GIR + Morgan Stanley GIC + Bridgewater + AQR**. A cada aporte o
backend gera prompts extensos (~110k chars total) rodados no Claude Code (Opus
4.7 + max reasoning + dangerously-skip-permissions). 100% local. A carteira é
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
- **Aporte (ad-hoc)**: 3 prompts encadeados + fechamento → folha de ordens.
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
  Baseline (8): sequential-thinking, filesystem, fetch, context7, playwright,
  memory, time, git. Strict EXCLUI Gmail/Calendar/Drive de propósito (autônomo).
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

## Commands
- `./start.sh`: Inicia backend + frontend, abre browser (uso diário)
- `./install.sh`: Setup inicial (venv, deps, atalho Desktop)
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
  - `agents_prompts/`: 3 templates Jinja2 (super prompts GS/MS-tier)
  - `core/database.py`: SQLite + SQLModel
  - `models/`: Asset, Contribution, ContributionPrompt, Report (weekly/maturity)
  - `routers/`: portfolio, contributions, macro, cadence, reports
  - `services/`: portfolio_service, market_data_service, prompt_generator,
    contribution_service (cria aporte + renderiza prompts), analysis_runner
    (MOTOR: `run_chain` genérico encadeado + auto-resume por limite + workspace/
    memória; `run_analysis` p/ aporte), review_service (revisão semanal +
    maturidade via run_chain → Report), telegram_service (Bot API),
    notification_service (marcos de 30 dias por lote)
- `/scripts/`: run_analysis (aporte→análise), telegram_setup, telegram_bot,
  check_cadence, weekly_review, resume_pending (retoma análises interrompidas),
  install_cron
- `/storage/agent_workspace/`: workspace persistente do agente (gitignored) —
  CLAUDE.md (ordens permanentes, reescrito a cada run), MEMORY.md (memória do
  agente), tools/ (ferramentas que ele cria)
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

## Os 3 prompts (3 classes: CDB · Ações B3 · Crypto)

Mandato NATIVO: todo o universo analisado é CDB, Ações B3 e Crypto. Nenhum
prompt analisa/cita Tesouro, LCI/LCA, debênture, CRI/CRA, fundo, FII, ETF
(GOLD11/BOVA11/IVVB11), BDR, ouro, DOL ou internacional (só aparecem em
linhas de veto). Schema JSON `version=5.0`, `escopo=BR_3_classes_cdb_acoesB3_crypto`.
Os campos de R1 (`final_tactical_brl`, `juros_e_cdb`, etc.) são lidos por R2/R3.

### Reunião nº 1 (GIC) — Macro · Alocação Tática
12 personas (Helena macro BR, Marcus global, Bruno alocação, Ricardo setor
B3, Aline crypto, Henrique CDB & rates, Mateus quant, Tiago CRO, Cláudia
tax, Diogo ESG, Felipe special situations, Júlia secretary).

11 rounds: Top of Mind → macro BR → macro global → **juros & estratégia de
CDB** (curva DI como SINAL de CDI; FGC; crédito bancário) → setor B3 + style
tilts → crypto on-chain → risk frame + Black-Litterman (3 buckets) → ESG +
special sit → tax overlay → behavioral → decisão tactical (BL + RP + HRP) →
pre-mortem. Buckets = cdb / acoes_b3 / crypto. Defesa = CDB líquido (dry
powder) + USDC (sem ouro/ETF/DOL).

### Reunião nº 2 (Equity & Crypto Research + CDB Credit)
12 personas + 2 vetos (Lucas head equity, 4 analysts setoriais, Sophia
behavioral/multi-asset, Rafael crypto on-chain, Henrique CDB credit, Anderson
CMT, Vera CFE forensic, Felipe special sit, Júlia quant; vetos Tiago CRO +
Diogo ESG).

6 rounds densos. **Ações B3**: investment thesis + valuation triangulada (DCF
3-stage + Reverse DCF + CCA + Precedent + LBO + SOTP) + forensic (Piotroski/
Altman/Beneish/Sloan/Dechow) + Capital Allocation + Earnings Quality + técnica
institucional + factor exposure + bull/base/bear ≥ 2:1 + conviction. **Crypto**:
on-chain Glassnode-tier + derivatives (Coinglass) + tokenomics/unlocks + dev
activity. **CDB**: credit analysis do banco emissor (Basel III Tier 1, NPL,
ROE, rating), %CDI pós-IR, cobertura FGC R$ 250k.

### Reunião nº 3 (Investment Committee Final)
14 personas (Otávio CIO, Tiago CRO, Mateus quant, Sofia sentiment, Daniel
trader, Henrique CDB, Cláudia tax, Alexandre compliance, Anderson CMT, Felipe
special sit, Vera forensic, Júlia validator, Diogo ESG, Edson wealth).

14 rounds: risk overlay (VaR + CVaR + EVT + CDaR + Marginal/Component VaR; CDB
por risco de crédito/FGC) → stress 8 cenários (incl. **evento de crédito
bancário**) → sentiment + IV/RV → **CDB final** → tax (CDB IR regr + 20k ações
+ 35k crypto + PGBL + holding + harvesting) → pair trades + options → compliance
→ behavioral 9 biases → cross-check CIO → execution → folha de ordens →
monitoramento → resumo executivo. Bolso ∈ {cdb, acoes_b3, crypto}.

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
