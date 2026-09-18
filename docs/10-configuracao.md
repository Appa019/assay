# 10 · Configuração

Toda configuração vive em **uma** classe: `app/config.py::Settings`
(pydantic-settings, lê `.env` na raiz, `extra="ignore"`). **Nada de `os.getenv`
espalhado pelo código.**

O `.env.example` tem a lista com comentários e **valores vazios**. O `.env` real
nunca entra no git.

> ⚠️ Pydantic lê o `.env` mas **não exporta para `os.environ`**. Por isso
> `analysis_runner._agent_subprocess_env()` injeta manualmente as chaves premium
> no ambiente do subprocess — sem isso os MCPs key-gated (que expandem `${VAR}`)
> não veriam nada.

---

## Armazenamento e serviços

| Variável | Default | O que faz |
|---|---|---|
| `SQLITE_PATH` | `storage/portfolio.db` | Caminho do banco. Relativo é resolvido contra a **raiz do projeto**, não o cwd (uvicorn pode subir de qualquer lugar) |
| `FRONTEND_URL` | `http://localhost:3000` | Entra na lista de origens do CORS |
| `BACKEND_URL` | `http://localhost:8000` | **Injetado nas ordens permanentes do consultor** — é a URL que ele usa no `curl` para registrar gasto, ler carteira e disparar aporte. Se estiver errada, o consultor não consegue escrever no ledger |

## Dados de mercado

| Variável | Default | O que faz |
|---|---|---|
| `COINGECKO_API_URL` | `https://api.coingecko.com/api/v3` | Endpoint público |
| `COINGECKO_API_KEY` | *(vazio)* | Opcional; sem chave usa o tier gratuito |
| `MARKET_CACHE_TTL` | `120` | TTL (s) do contexto macro cacheado em `/api/macro` |
| `CDB_PCT_CDI` | `100.0` | % do CDI que o papel paga. Usado para marcar renda fixa a mercado pelo CDI diário acumulado |

## Alvos de alocação

| Variável | Default |
|---|---|
| `TARGET_FIXED_INCOME` | `0.35` |
| `TARGET_STOCKS` | `0.40` |
| `TARGET_CRYPTO` | `0.25` |

Cada um precisa estar em [0, 1] e os três **precisam somar 1.0 ± 0.01** —
validadores em `Settings` derrubam o boot com mensagem explícita se não somarem.

## Agente do comitê

| Variável | Default | O que faz |
|---|---|---|
| `MIN_HOLDING_DAYS` | `30` | Trava de venda **por lote** das AÇÕES (compliance do cliente). Interpolada nas ordens permanentes e no preâmbulo |
| `MIN_HOLDING_DAYS_CRYPTO` | `7` | Trava de venda **por lote** da CRIPTO (D36). CDB nunca trava |
| `AGENT_MODEL` | `opus` | Modelo do comitê |
| `AGENT_EFFORT` | `max` | **Sempre `max` no fluxo automático** |
| `AGENT_STEP_TIMEOUT` | `2400` | Teto (s) por etapa do subprocess. Opus/max com pesquisa ao vivo é lento — dê folga |
| `MAX_RUN_ATTEMPTS` | `5` | Falhas automáticas consecutivas antes do auto-resume desistir (e avisar no Telegram). Impede loop pago infinito |

## Consultor (chat)

| Variável | Default | O que faz |
|---|---|---|
| `CHAT_MODEL` | `opus` | Usado quando o roteador está **desligado** |
| `CHAT_EFFORT` | `medium` | idem |
| `CHAT_TURN_TIMEOUT` | `900` | Teto (s) de **um** turno de chat |
| `CHAT_MAX_TURNS` | `40` | Rotaciona a sessão encadeada depois de N turnos. O `MEMORY.md` carrega o contexto durável através da rotação |
| `CHAT_MAX_CONTEXT_TOKENS` | `120000` | Rotaciona quando UMA chamada do modelo lê esse tanto de contexto. É o teto que pega na prática — o de turnos nunca chegou a valer (D42) |
| `CHAT_VISION_MODEL` / `_EFFORT` / `_TIMEOUT` | `sonnet` / `low` / `300` | Leitor de anexo: transcreve foto/PDF numa sessão descartável, antes do turno do consultor (D42) |

## Roteador de modelo

| Variável | Default | O que faz |
|---|---|---|
| `CHAT_ROUTER_ENABLED` | `true` | `false` fixa todo turno no tier DEEP (comportamento pré-roteador) |
| `CHAT_ROUTER_MODEL` / `_EFFORT` / `_TIMEOUT` | `haiku` / `low` / `60` | Modelo dos passos auxiliares (resumo de rotação da sessão) |
| `CHAT_FAST_MODEL` / `_EFFORT` | `haiku` / `low` | Saudação e lançamento no ledger |
| `CHAT_LOOKUP_MODEL` / `_EFFORT` | `sonnet` / `low` | Consulta factual: saldo, preço, ordens pendentes, extrato (D37) |
| `CHAT_DEEP_MODEL` / `_EFFORT` | `opus` / `medium` | Decisão de investimento, análise de ativo, macro, risco, tributação — e tudo o que não for provadamente os dois de cima |
| `CONTRIBUTION_NIGHT_RUN` | `true` | `false` faz `run=true` executar na hora, como antes de D38 |
| `CONTRIBUTION_NIGHT_HOUR` | `1` | Hora LOCAL em que os aportes agendados rodam. O timer `investimentos-scheduled` precisa apontar para a mesma hora |
| `MACRO_DELTA_ENABLED` | `true` | `false` faz a Reunião nº 1 rodar sempre o macro completo (11 rodadas) |
| `MACRO_DELTA_MAX_AGE_DAYS` | `7` | Idade máxima da revisão semanal para a Reunião nº 1 rodar em modo delta (D37) |

## Classificador de gasto

| Variável | Default | O que faz |
|---|---|---|
| `CLASSIFIER_MODEL` | `haiku` | Roda enquanto alguém espera com o polegar na tela — segundos importam mais que profundidade |
| `CLASSIFIER_EFFORT` | `low` | idem |
| `CLASSIFIER_TIMEOUT` | `90` | idem |

## Telegram

| Variável | Default | O que faz |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | *(vazio)* | Do @BotFather. **NUNCA comite** |
| `TELEGRAM_CHAT_ID` | *(vazio)* | Preenchido por `scripts/telegram_setup.py` (código de 6 dígitos). O bot só responde a este chat |

`settings.telegram_enabled` é `True` só quando os dois estão preenchidos; sem
isso todas as notificações viram no-op silencioso.

## MCPs premium (todos opcionais)

Cada chave liga **sozinha** o MCP correspondente. Sem chave, o servidor
simplesmente não é configurado — o agente boota normalmente com os 4 keyless.

| Variável | Liga | Para quê | Onde obter |
|---|---|---|---|
| `GLASSNODE_API_KEY` | `glassnode` | on-chain (MVRV-Z, NUPL, SOPR, Puell, Reserve Risk) | studio.glassnode.com |
| `COINGLASS_API_KEY` | `coinglass` | derivativos (funding, OI, CME basis, liquidation heatmap) | coinglass.com/CryptoApi |
| `MESSARI_API_KEY` | `messari` | research/tokenomics/unlocks | messari.io/api |
| `FIRECRAWL_API_KEY` | `firecrawl` | scraping estruturado de sites JS (StatusInvest, TradingView, RI/CVM) | firecrawl.dev |
| `TAVILY_API_KEY` | `tavily` | research web com score de credibilidade | tavily.com |

Definidos em `analysis_runner._KEY_GATED_MCP_SERVERS`. O JSON usa `${VAR}`, então
o segredo **não fica em disco** no `.mcp.json`.

## Variáveis do frontend

| Variável | Onde | O que faz |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `frontend/.env.local` | **Deixe vazio.** Vazio = chamadas relativas + rewrite do Next = sem CORS e sem segunda porta |
| `BACKEND_ORIGIN` | ambiente do **build** | Destino do rewrite `/api/*`. Default `http://127.0.0.1:8000`. ⚠️ Lido no `pnpm build`, **não** no start |
| `FRONTEND_PORT` | ambiente do `install_systemd.sh` | `3001` no Pi (a 3000 é do painel de casa) |

## Regras de segredo

- Nunca hardcode chave, token ou senha. Tudo em `.env`, lido via `Settings`.
- `.env.example` só com valores vazios.
- Antes de commitar, confira que nada de `.env` ou `storage/` entrou.
- `storage/claude_session.json` **nunca** entra no git (resíduo do Playwright
  antigo; não é usado pelo orquestrador).
- O agente tem ordem explícita de nunca gravar segredo no `MEMORY.md` nem em
  commit.
