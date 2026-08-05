# Documentação do Assay

> **Você (Claude) está começando uma sessão nova.** Leia este arquivo inteiro.
> Ele te dá o modelo mental completo em ~5 minutos e diz exatamente qual dos
> outros documentos abrir para a tarefa que o Pedro pedir.
> Não precisa ler os 13 arquivos de uma vez — leia este + o que a tarefa exigir.

---

## 1. O que é isto, em quatro frases

**Assay** é o cockpit financeiro privado de UMA pessoa (Pedro). Ele junta duas
metades do mesmo dinheiro: **finanças pessoais** (gastos e ganhos do dia a dia)
e **investimentos** (carteira + comitê de IA que decide onde aportar).

Roda **100% local** num Raspberry Pi 4, acessível só por VPN Tailscale. Não tem
login, não tem nuvem, não tem segundo usuário — e nunca vai ter.

O diferencial: um **agente autônomo Claude Code headless** que roda um comitê
multipersona de investimentos (5 reuniões encadeadas, nível Goldman Sachs /
J.P. Morgan) e devolve uma folha de ordens. Além dele, um **consultor
financeiro em chat** (mesma conversa no Telegram e no site) que registra gastos,
responde sobre mercado e dispara aportes.

Stack: **FastAPI + SQLModel/SQLite** (backend) · **Next.js 16 + TypeScript +
Tailwind v4** (frontend) · **Telegram Bot API** · **Claude Code CLI** como motor
de IA (subprocess headless, não é chamada de API).

---

## 2. Modelo mental em um diagrama

```
                      ┌──────────────────────────────────────────┐
   iPhone (Tailscale) │  Next.js :3001   ── /api/* reescrito ──▶  │
   ─────────────────▶ │  4 abas: Visão geral · Consultor ·        │
                      │          Extrato · Investimentos         │
                      └──────────────────────────────────────────┘
                                        │
   Telegram bot ───────────────────────▶│◀── crons/timers (8 jobs)
   (mesma conversa do /consultor)       │
                                        ▼
                      ┌──────────────────────────────────────────┐
                      │        FastAPI  127.0.0.1:8000           │
                      │  routers → services → SQLModel → SQLite  │
                      └──────────────────────────────────────────┘
                                        │
                    ┌───────────────────┴────────────────────┐
                    ▼                                        ▼
        ┌───────────────────────┐              ┌──────────────────────────┐
        │  DADOS DE MERCADO     │              │  MOTOR DE IA             │
        │  BCB · Yahoo · CoinGecko             │  subprocess `claude -p`  │
        │  (grátis, sem chave)  │              │  em workspaces isolados  │
        └───────────────────────┘              └──────────────────────────┘
                                                  │        │        │
                                       agent_workspace  chat_ws  router/classifier_ws
                                       (comitê, opus)  (consultor) (haiku, rápido)
```

**A regra que explica quase tudo:** o sistema não chama a API da Anthropic. Ele
abre o binário `claude` como subprocess (`claude -p --output-format json
--dangerously-skip-permissions`), captura o `session_id` do JSON de saída e usa
`--resume <id>` nas etapas seguintes. É por isso que existe workspace com
`CLAUDE.md`/`MEMORY.md`/`.mcp.json` em disco: **o agente é um Claude Code de
verdade, com MCPs, Bash e acesso ao sistema de arquivos.**

---

## 3. As cinco verdades invioláveis

Se você quebrar uma destas, quebrou o produto:

| # | Regra | Onde é aplicada |
|---|---|---|
| 1 | **O Pi é produção.** O desktop só escreve código. Nunca rode o bot em duas máquinas (polling duplicado = resposta em dobro). | `docs/09-operacao.md` |
| 2 | **Bind sempre em `127.0.0.1`.** A LAN é compartilhada com o prédio. Quem publica é o `tailscale serve`. | `scripts/install_systemd.sh` |
| 3 | **Trava de venda de 30 dias por LOTE, só ações e crypto.** CDB tem liquidez diária (é o dry powder). | `portfolio_service.sell_asset` |
| 4 | **Mandato de 3 classes:** Renda Fixa = 100% CDB · Ações = só equities B3 (sem FII/ETF/BDR) · Crypto = agressivo. | ordens permanentes + todos os prompts |
| 5 | **Nunca mencione Claude em commit, código ou co-author.** Nunca comite `.env` nem `storage/`. | `.gitignore`, convenção de commits |

---

## 4. Mapa dos documentos

| Documento | Leia quando… |
|---|---|
| **[01-produto.md](01-produto.md)** | precisar entender *por que* o produto é assim, para quem, e o que ele deliberadamente NÃO faz |
| **[02-arquitetura.md](02-arquitetura.md)** | for mexer em qualquer coisa — é o mapa do repositório, camada por camada, arquivo por arquivo |
| **[03-dominio.md](03-dominio.md)** | for mexer em dados: 9 tabelas, regras de negócio, P&L, ledgers, IR |
| **[04-motor-ia.md](04-motor-ia.md)** | for mexer no `analysis_runner`, chat, roteador de modelo, MCPs, locks ou resiliência |
| **[05-fluxos.md](05-fluxos.md)** | quiser ver um fluxo ponta a ponta (aporte, revisão semanal, registrar gasto, executar ordem…) |
| **[06-api.md](06-api.md)** | for consumir ou alterar um endpoint HTTP |
| **[07-frontend.md](07-frontend.md)** | for mexer em qualquer `.tsx` — rotas, design system, regras de iOS |
| **[08-telegram.md](08-telegram.md)** | for mexer no bot: 16 comandos, chat, anexos |
| **[09-operacao.md](09-operacao.md)** | for fazer deploy, debugar produção, mexer em systemd/cron/backup |
| **[10-configuracao.md](10-configuracao.md)** | precisar saber o que cada variável do `.env` faz |
| **[11-qualidade.md](11-qualidade.md)** | for commitar: testes, CI, lint, convenções de código |
| **[12-decisoes.md](12-decisoes.md)** | pensar "por que diabos isso é assim?" — é o registro de decisões e armadilhas |
| **[13-estado-atual.md](13-estado-atual.md)** | quiser saber o que está em andamento agora, o que está desatualizado e as dívidas conhecidas |

Documentos que **já existiam** e continuam valendo (não os duplique):

- **`CLAUDE.md`** (raiz) — contrato sempre carregado. Regras operacionais.
- **`PRODUCT.md`** (raiz, em inglês) — registro de produto, usuário, anti-referências.
- **`DESIGN.md`** (raiz, em inglês) — sistema visual: cor, tipo, motion, mobile.
- **`acesso-remoto-pi.md`** (raiz) — SSH, firewall, portas e rede do Pi.
- **`README.md`** (raiz) — apresentação pública do repositório. ⚠️ parcialmente
  desatualizado (é anterior às finanças pessoais); veja `13-estado-atual.md`.

---

## 5. Atalho por tarefa

| O Pedro pediu… | Vá direto para |
|---|---|
| "muda a cor / layout / fonte" | `07-frontend.md` + `DESIGN.md` |
| "o comitê travou / não terminou o aporte" | `04-motor-ia.md` §resiliência + `09-operacao.md` §runbook |
| "adiciona um campo no ativo" | `03-dominio.md` §migrações (SQLite não tem Alembic aqui) |
| "adiciona um comando no bot" | `08-telegram.md` |
| "adiciona um endpoint" | `06-api.md` + `02-arquitetura.md` §camadas |
| "o consultor está caro / lento" | `04-motor-ia.md` §roteador de modelo |
| "deploy para o Pi" | `09-operacao.md` §deploy |
| "por que o preço está zerado?" | `03-dominio.md` §marcação a mercado |
| "quero um relatório novo" | `05-fluxos.md` §revisão semanal (é o molde) |

---

## 6. Antes de commitar (checklist curto)

```bash
make check      # ruff + pytest + lint/type-check/build do frontend — é o que a CI roda
```

- Commits em inglês, Conventional Commits, **atômicos**.
- **Zero menção a Claude** em mensagem, código ou co-author.
- Nada de secrets. `.env` nunca entra.
- Backend: `.venv/bin/python -m pytest` (68 testes, todos passando em 2026-08-05).
- Frontend: `cd frontend && pnpm lint && pnpm type-check && pnpm build`.

Detalhes em `11-qualidade.md`.
