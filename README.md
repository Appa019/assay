# Investimentos Manual

Gestão de aportes **ad-hoc (sem ciclo fixo)** com **comitê multipersona de IA
padrão Goldman Sachs GIR + Morgan Stanley GIC + Bridgewater + AQR**. A cada
aporte gera prompts extensos (~110k chars · ~28k tokens) e roda o comitê no
Claude Code (Opus · max reasoning).

**Modo automático (padrão):** você informa o aporte quando quiser — um agente
autônomo roda todas as reuniões encadeadas no `claude` headless (carta branca de
pesquisa, cria ferramentas, gerencia a própria memória) e te entrega **onde
investir e quanto**. A recomendação chega no **Telegram**. A carteira é revisada
**toda semana** (macro + posições + rotação de CDB para oportunidades); quando um
lote de ação/crypto completa **30 dias** (trava de venda), o comitê reavalia
manter/vender. CDB tem liquidez diária. Você só registra o que comprou.

**Modo manual (fallback):** o app gera os 3 prompts para você colar à mão.

**Stack 100% local:** FastAPI + SQLite + Next.js + Telegram Bot API.
Sem auth, sem nuvem.

## Mandato de ativos

Três classes, **apenas** — o comitê não recomenda nada fora disso:
- ✅ **Renda Fixa = 100% CDB** (preferência por CDB ≥100% do CDI). Liquidez
  diária: é o *dry powder* que a revisão semanal pode girar para oportunidades.
- ✅ **Ações = só equities listadas na B3** (large/mid/small).
- ✅ **Crypto = agressivo** (BTC/ETH core + alts L1/L2, DeFi, AI, RWA — alto
  upside com risco controlado).

**Fora do mandato**:
- ❌ Tesouro Direto, LCI/LCA, debêntures, CRI/CRA, fundos de renda fixa
- ❌ FIIs, ETFs, BDRs
- ❌ Ações, REITs ou stocks internacionais

> O mandato é **nativo** dos 3 prompts do comitê — todo o universo analisado é
> CDB · Ações B3 · Crypto, sem nenhuma análise de classes fora do escopo — e
> está também nas ordens permanentes do agente.

## Quick start

```bash
./install.sh    # primeira vez (cria venv, instala deps, atalho Desktop)
./start.sh      # rodar (backend + frontend + abre browser)
```

Ou clique no atalho **Investimentos Manual** no Desktop.

## Modo automático + Telegram (recomendado)

Configuração única do Telegram:

```bash
# 1. defina TELEGRAM_BOT_TOKEN no .env (pegue no @BotFather)
# 2. mande /start ao seu bot e capture o chat_id:
.venv/bin/python scripts/telegram_setup.py
# 3. (opcional) maturidade dos lotes + revisão semanal via cron diário:
scripts/install_cron.sh
```

Uso diário — pelo **terminal**:

```bash
.venv/bin/python scripts/run_analysis.py --amount 5000
```

…ou pelo **dashboard** (`/aporte` → "Adicionar aporte e rodar análise",
acompanha etapa por etapa)…

…ou pelo **Telegram** (com `./start.sh` rodando, o bot sobe junto):

```
/aporte 5000        → roda o comitê e devolve a folha de ordens aqui
/comprei PETR4 acoes 100 38,50   → registra a compra (cada compra = um lote)
/carteira           → posições + o que já pode ser vendido (por lote)
/vender PETR4       → vende o lote mais antigo já liberado (≥30 dias)
/revisao            → revisão semanal do comitê agora
/relatorios         → últimos relatórios (semanais + maturidade)
/status   ·   /ajuda
```

### Mandato e ciclos
- **Alocação**: Renda Fixa = 100% CDB · Ações = só equities da B3 · Crypto = agressivo.
- **Trava de 30 dias por lote**: cada compra matura na sua própria data.
- **Revisão semanal** (macro + desempenho + maturidade) chega no Telegram, fica
  salva em `/relatorios` e é consultada nos aportes.
- **Maturidade**: quando um lote completa 30 dias, o comitê analisa manter/vender.
- **Auto-resume**: se bater limite de uso, o agente espera o reset e retoma
  sozinho. E se o processo cair no meio (créditos/queda), ao re-rodar o mesmo
  aporte (`run_analysis.py --contribution-id <uuid>`) ele **retoma de onde
  parou** — não refaz as reuniões já concluídas.

> ⚠️ Cada run é Opus/max em ~110k chars × N reuniões — custa alguns dólares e
> leva dezenas de minutos. Teste barato: `--model haiku --effort low`.

## Fluxo manual (fallback)

1. Abrir `/ativos` e cadastrar/atualizar a carteira com preços atuais.
2. Em outro terminal: `claude --dangerously-skip-permissions`
   (Opus 4.7, max reasoning).
3. Abrir `/aporte`, informar valor — no modo manual o app gera os prompts.
4. Para cada prompt no MESMO chat do Claude: copiar → colar → aguardar →
   colar resposta no app → **Salvar e prosseguir**.
5. Histórico em `/relatorios` mantém prompts + respostas para audit.

## Os 3 prompts

| # | Reunião | Personas | Linhas | Chars |
|---|---|---:|---:|---:|
| 1 | **GIC — Macro + Alocação Tática (CDB·B3·Crypto)** | 12 | ~720 | ~36k |
| 2 | **Equity & Crypto Research + CDB Credit** | 12+2 | ~470 | ~29k |
| 3 | **Investment Committee Final** | 14 | ~530 | ~28k |

**Total**: ~1730 linhas / ~92k chars / ~23k tokens. Os 3 prompts são
nativamente de 3 classes (CDB · Ações B3 · Crypto) — sem análise de FII/
Tesouro/debênture/ETF — e cada um fica folgado em Opus 4.7 (1M context).

Cada prompt instrui o Claude a usar `WebSearch`/`WebFetch`/`Bash` para
validar dados (Glassnode, CryptoQuant, Coinglass, Fundamentus, StatusInvest,
Suno, etc.), e exige **JSON estruturado** ao final com 50+ validações
obrigatórias.

## Frameworks institucionais aplicados (116 conceitos auditados)

- **GS "Top of Mind"** (Round 0 com 5 questões críticas)
- **GS Asset Allocation Framework**
- **MS Capital Market Assumptions** (10y expected returns × vol × Sharpe)
- **MS GIC "On the Markets"** (Overweight/Equal/Underweight)
- **Black-Litterman bayesiano** (equilibrium + views × confidence)
- **Bridgewater All-Weather / Risk-Parity**
- **AQR Multi-Factor** (Value × Momentum × Quality × Low-Vol × Carry)
- **Fama-French 5 + Carhart Momentum**
- **Damodaran ERP + Country Risk Premium Brazil**
- **Fed Model BR-adapted** (Ibov EY vs NTN-B 10y)
- **GMO 7-Year Real Return Forecast**
- **Hierarchical Risk Parity** (López de Prado)
- **Markowitz Mean-Variance + Max Sharpe + Min Variance**
- **Kelly Criterion fracional**

### Forensic Accounting (R2)
Piotroski F-Score · Altman Z-Score · Beneish M-Score · Sloan accruals ·
Dechow F-Score · Capital Allocation Scorecard (Buffett-Munger) ·
Earnings Quality (cash conversion + accruals + SBC + leases IFRS 16 +
pension obligations)

### Valuation triangulada (R2)
3-stage DCF · Reverse DCF · CCA (Comparable Companies) · Precedent
Transactions · LBO Check · SOTP

### Crypto On-Chain Institucional (R1 + R2)
Realized Cap · MVRV-Z · NUPL · SOPR · Puell · Reserve Risk · HODL Waves ·
STH-LTH Cost Basis · CDD · Dormancy · VOCD · RHODL · NVT · NVT Signal ·
Stock-to-Flow · Coinbase Premium · Kimchi Premium · CME Basis · DVOL ·
Funding Rate · Active Developers (Electric Capital)

### Risk Quant (R3)
VaR 95%/99% · CVaR (Expected Shortfall) · EVT tail-VaR (Generalized
Pareto) · Marginal VaR · Component VaR · CDaR · Sharpe/Sortino/Calmar ·
Information Ratio · Tracking Error · Time Under Water · HHI · Effective
N positions

### Stress Test 8 Cenários (R3)
Risk-off severo · Inflação acelera · Selic +200 bps · Crise crypto ·
Crash 2020-tipo · China hard landing · Bull dovish (upside) · Stagflação

### Options Strategies (R3)
Covered Call · Protective Put · Collar · Cash-Secured Put · Vertical
Spread · Iron Condor · Calendar Spread · Diagonal Spread (com Greeks)

### Execution (R3)
VWAP · TWAP · POV · Implementation Shortfall · Slippage estimation ·
Lot rounding · Intra-day timing windows

### Behavioral (R3)
9 cognitive biases: anchoring · loss aversion · recency · herding ·
confirmation · overconfidence · disposition effect · sunk cost · endowment.
Sentiment mean reversion: AAII · NAAIM · CNN F&G · Put/Call · IBOV
breadth

### Wealth Planning (R3)
Bucket Strategy (immediate/intermediate/growth) · 4% Rule · Dynamic
withdrawal · Sequence-of-returns risk mitigation · Holding analysis com
breakeven

### Tax Strategy (R3)
CDB IR regressivo (22.5%→15%) · Isenção R$ 20k/mês em ações · Crypto:
isenção até R$ 35k/mês em vendas · Dividendos B3 · JCP vs Dividendo ·
Tax-Loss Harvesting com Wash-Sale 30d · DARF projetado · Reforma 2026
dividendos

## Configuração

Edite `.env` (criado pelo `install.sh` a partir de `.env.example`):

```
SQLITE_PATH=storage/portfolio.db
TARGET_FIXED_INCOME=0.35
TARGET_STOCKS=0.40
TARGET_CRYPTO=0.25
MIN_HOLDING_DAYS=30        # trava de venda por lote (ações/crypto; CDB é líquido)
AGENT_MODEL=opus
AGENT_EFFORT=max
COINGECKO_API_KEY=        # opcional (CoinGecko Pro)
TELEGRAM_BOT_TOKEN=       # @BotFather — NUNCA commitar valor real
TELEGRAM_CHAT_ID=         # preenchido por scripts/telegram_setup.py
```

Reinicie o backend após editar.

## Estrutura

```
app/
  agents_prompts/    # 3 templates Jinja2 (GS/MS-tier · 111k chars total)
  core/database.py   # SQLite + SQLModel
  models/            # Asset, Contribution, ContributionPrompt, Report
  routers/           # portfolio, contributions, macro, cadence, reports
  services/          # analysis_runner   → motor do agente (claude headless)
                     # review_service    → revisão semanal + maturidade
                     # telegram_service  → cliente + formatação Telegram
                     # notification_service, contribution_service
                     # prompt_generator, market_data_service, portfolio_service
scripts/             # run_analysis · weekly_review · check_cadence
                     # telegram_bot · telegram_setup · install_cron
frontend/
  src/app/(dashboard)/
    page.tsx            # dashboard + widget último aporte
    aporte/             # fluxo de aporte (auto-run, etapa por etapa)
    ativos/             # CRUD carteira (lotes)
    relatorios/         # histórico de aportes + relatórios do agente
    configuracoes/      # leitura do .env
```

## Comandos úteis

```bash
# Backend
.venv/bin/uvicorn app.main:app --reload

# Frontend
cd frontend && pnpm dev

# Validações
.venv/bin/ruff check app/ && .venv/bin/ruff format app/
cd frontend && pnpm lint && pnpm type-check && pnpm build

# DB
sqlite3 storage/portfolio.db
```
