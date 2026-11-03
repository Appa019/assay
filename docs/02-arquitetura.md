# 02 · Arquitetura

## Visão de 10.000 pés

Dois processos longos + onze timers, todos falando com **um** arquivo SQLite.

| Processo | O que é | Porta | Unit systemd |
|---|---|---|---|
| Backend | FastAPI/uvicorn | `127.0.0.1:8000` | `investimentos-backend` |
| Frontend | Next.js production server | `127.0.0.1:3001` (Pi) / 3000 (desktop) | `investimentos-frontend` |
| 11 timers | agendados · maturidade · semanal · resume · preços · snapshot · alertas · mensal · insights · digest · backup (horários em `09-operacao.md`) | — | `investimentos-<nome>.timer` |

O navegador **só fala com o Next**. `next.config.ts` reescreve `/api/*` para o
backend, então não há CORS nem segunda porta exposta. ⚠️ **O rewrite é assado no
`pnpm build`**, não lido no start: `BACKEND_ORIGIN` precisa estar setado na hora
do build.

## Mapa do repositório

```
/
├── app/                      BACKEND (FastAPI)
│   ├── main.py               monta os routers, CORS, lifespan → init_db() + worker do chat
│   ├── config.py             Settings (pydantic-settings) — TODA config vive aqui
│   ├── core/database.py      engine SQLite + PRAGMAs WAL + micro-migrações
│   ├── models/               tabelas SQLModel
│   ├── schemas/              Pydantic de fronteira (request/response)
│   ├── routers/              routers HTTP — finos, sem regra de negócio
│   ├── services/             TODA a regra de negócio mora aqui
│   └── agents_prompts/       5 templates Jinja2 (as 5 reuniões)
│
├── frontend/                 FRONTEND (Next.js 16 App Router)
│   ├── next.config.ts        rewrite /api/* → backend (BUILD TIME)
│   └── src/
│       ├── app/(dashboard)/  rotas (páginas)
│       ├── components/       componentes compartilhados
│       ├── hooks/            hooks de fetch
│       └── lib/              api.ts (cliente tipado) · nav.ts (fonte única de navegação) · format.ts
│
├── scripts/                  jobs dos timers, instalador systemd, ícone
├── tests/                    suíte pytest (+ conftest)
├── storage/                  DADOS EM RUNTIME — gitignored (ver §storage)
├── docs/                     esta documentação
├── CLAUDE.md PRODUCT.md DESIGN.md README.md
├── Makefile                  make check / dev / analyze / weekly / prices …
└── .github/workflows/ci.yml  backend (ruff+pytest) · frontend (lint+types+build)
```

## As camadas do backend (respeite a direção)

```
HTTP  →  routers/      valida entrada, traduz exceção em status code. NADA MAIS.
         services/     regra de negócio, orquestração, chamadas externas
         models/       SQLModel (tabelas) — sem lógica
         core/         engine, sessão, PRAGMAs
```

**Regra:** router nunca importa outro router; service pode importar service;
model não importa nada de service. Se você está escrevendo um `if` de negócio
dentro de um router, ele está no lugar errado.

Tradução de exceção usada em todo lugar:

| Exceção do service | Status HTTP |
|---|---|
| `LookupError` | 404 |
| `ValueError` / `SellLockedError` / lock ativo | 409 |
| `ClassificationError` | 422 |
| `ChatUnavailableError` | 400 (ou 413 no upload) |

## Serviços, um por um

| Serviço | Responsabilidade |
|---|---|
| `analysis_runner.py` | **O motor.** Subprocess do `claude`, sessão encadeada, retry/resume, locks, workspace, MCPs. Todo o resto de IA depende dele. |
| `chat_service.py` | Consultor: turno de chat, workspace próprio, sessão persistente, transcrição compartilhada, anexos |
| `market_data_service.py` | BCB (Selic/IPCA/CDI/USD) + Yahoo (Ibov, fundamentos) + CoinGecko (preços, dominância) + Fear&Greed. Best-effort: nunca levanta exceção, devolve `warnings` |
| `portfolio_service.py` | Carteira: CRUD de lote, **venda com trava por classe (30d ação · 7d cripto)**, alocação, snapshot diário |
| `order_service.py` | Parseia o bloco ```json {"orders"} do fechamento → linhas `Order`; executar ordem cria o lote herdando tese/alvo/stop |
| `prompt_generator.py` | Renderiza os 5 templates Jinja2 com contexto de datas dinâmico |
| `tax_service.py` | IR simplificado: isenções 20k/35k, compensação de prejuízo, DARF mínima |
| `price_refresh_service.py` | Marcação a mercado de TODO lote (Yahoo · CoinGecko · CDI acumulado) |
| `cashflow_service.py` | Ledger pessoal: lançamento, resumo mensal, histórico, deduplicação |
| `forecast_service.py` | Fluxo de caixa previsto: lançamentos + recorrências não cumpridas, mês a mês |
| `recurrence_service.py` | Compromissos mensais (CRUD) e as ocorrências de cada mês |
| `benchmark_service.py` | TWR da carteira vs CDI/IBOV/BTC, rebased 100 |
| `classifier_service.py` | "gastei 42,90 no mercado" → rascunho estruturado (haiku, sem MCP) |
| `model_router.py` | Regra (sem chamar modelo) que escolhe fast/lookup/deep para cada turno de chat |
| `contribution_service.py` | Cria o aporte + captura snapshot + renderiza os 5 prompts |
| `notification_service.py` | Detecta lote que cruzou a trava da classe (estado idempotente em JSON) |
| `review_service.py` | Revisão semanal e de maturidade — usa `run_chain` do motor |
| `notification_center.py` | Porta única de aviso: grava no inbox do app e dispara Web Push |
| `webpush_service.py` | Web Push: chaves VAPID em `storage/webpush/`, inscrições e envio cifrado |
| `card_service.py` | Cartões de crédito e faturas (calculadas a cada leitura, nunca gravadas) |
| `order_sizing.py` | Ordem em R$ → ticker + quantidade + preço da boleta (lote de 100 + fracionário) |
| `insight_service.py` | Insights diários do ledger pessoal, por regra, sem LLM |

## Regra de dependência do motor de IA

Tudo que fala com Claude passa por `analysis_runner._run_claude_step()`:

```
analysis_runner._run_claude_step()     ← única porta para o subprocess `claude`
   ├── analysis_runner.run_chain()     ← N etapas na MESMA sessão
   │      ├── run_analysis()           (aporte: 5 reuniões + fechamento)
   │      └── review_service           (semanal: 2 etapas · maturidade: 2 etapas)
   ├── chat_service._run_turn_once()   (1 turno, workspace do consultor)
   └── classifier_service.classify()   (1 turno, haiku, workspace vazio)
```

Se você precisar de um novo uso de IA, **reutilize `_run_claude_step` ou
`run_chain`** — não escreva outro `subprocess.Popen`.

## Frontend: rotas e navegação

`src/lib/nav.ts` é a **fonte única** de navegação. Mexa lá, nunca nos
componentes — `<Sidebar>` (≥md) e `<MobileNav>` (<md) leem dele.

| Rota | Papel |
|---|---|
| `/` | **Visão geral** — patrimônio + saldo do mês + alocação vs mandato + benchmark + ordens pendentes + macro. A única tela que mostra as duas metades do dinheiro juntas |
| `/consultor` | **Chat** com o consultor. Aceita até 3 fotos/arquivos por mensagem |
| `/extrato` | **Extrato** somente-leitura do ledger pessoal (mês a mês, por categoria) |
| `/investimentos` | Casca com sub-abas na URL (`?aba=carteira\|aportar\|analises\|ir`) |
| `/ativos`, `/aporte`, `/relatorios`, `/ir` | Rotas antigas, vivas para deep link. Exportam o componente **por nome** (`AtivosView`, `AporteView`, `RelatoriosView`, `IrView`) além do default — é assim que `/investimentos` as hospeda |
| `/aporte/[id]` | Acompanhamento de um aporte, etapa por etapa (polling) |
| `/configuracoes` | Diagnóstico: pinga `/api/health` |

## storage/ — o que é cada pasta

Tudo aqui é **gitignored** e o do Pi é a fonte da verdade. O deploy nunca toca
`storage/` (hoje é `rsync` com exclude; depois da migração, `deploy/pi/deploy.sh`).

| Caminho | Conteúdo |
|---|---|
| `portfolio.db` (+ `-wal`, `-shm`) | O banco. SQLite em modo WAL |
| `backups/` | 14 backups diários rotacionados (`backup_db.sh`) |
| `agent_workspace/` | Workspace do **comitê**: `CLAUDE.md` (reescrito a cada run), `MEMORY.md` (do agente), `.mcp.json` (gerado), `.mcp.agent.json` (do agente, nunca sobrescrito), `tools/`, `notes/`, `out/<contribution_id>/etapa_NN.json`, repo git |
| `chat_workspace/` | Workspace do **consultor**: `CLAUDE.md`, `MEMORY.md` (memória fixa sobre o cliente), `session.json` (sessão + contagem de turnos), `inbox/` (fotos e arquivos recebidos) |
| `classifier_workspace/` | Diretório **vazio de propósito** — sem `.mcp.json` é o que mantém o classificador rápido |
| `analysis_runs/` | Locks PID (`<uuid>.lock`, `_global_run.lock`, `_chat_turn.lock`) + `transcripts/` (stdout/stderr bruto de cada invocação — o flight recorder) |
| `logs/` | Logs do `start.sh` e dos jobs |
| `notifications_state.json` | Lotes cuja maturidade já foi tratada (idempotência) |
| `alerts_state.json` | Estado dos alertas de alvo/stop (rearma ao voltar à banda) |

## Onde a config vive

**Uma única classe:** `app/config.py::Settings` (pydantic-settings, lê `.env`).
Nada de `os.getenv` espalhado. Ver `10-configuracao.md` para a lista completa.

Pegadinha: pydantic lê o `.env` mas **não exporta para `os.environ`**. Por isso
`analysis_runner._agent_subprocess_env()` injeta manualmente as chaves premium
no ambiente do subprocess — sem isso os MCPs key-gated (que expandem `${VAR}`)
não veriam nada.
