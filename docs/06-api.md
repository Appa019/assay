# 06 · Referência da API

Base: `http://127.0.0.1:8000` (o navegador nunca fala direto — o Next reescreve
`/api/*`). Docs interativos do FastAPI em `/docs`.

**Sem autenticação.** É single-user atrás de VPN. Não adicione auth.

---

## Portfolio — `/api/portfolio`

| Método | Rota | O que faz |
|---|---|---|
| `GET` | `` | Resumo: `total_value`, `allocation` (valores + %), `target_allocation`, `deviation`, `assets[]` |
| `GET` | `/assets` | Todos os lotes |
| `POST` | `/assets` | Cria lote → também grava `Trade(buy)`. Body: `ticker`, `asset_class`, `quantity>0`, `avg_price>0`, `current_price?`, `entry_date?`, `name?` |
| `PATCH` | `/assets/{id}` | Atualiza `name`, `quantity`, `avg_price`, `current_price`, `thesis`, `target_price`, `stop_price` |
| `POST` | `/assets/{id}/sell` | Vende o lote. Body OPCIONAL `{"price", "quantity"}`: `price` = preço REAL de execução (sem ele usa a marcação); `quantity` = venda PARCIAL (o resto do lote mantém `entry_date`/PM). **409** dentro da trava de 30d · **422** quantidade > lote |
| `DELETE` | `/assets/{id}` | Remove sem gravar venda (correção de cadastro) |
| `POST` | `/refresh` | Marca tudo a mercado. Best-effort, devolve contagens |
| `GET` | `/history?days=365` | Snapshots diários, cronológicos (curva de patrimônio) |
| `GET` | `/benchmark?days=365` | TWR da carteira vs CDI/IBOV/BTC, rebased 100 |
| `GET` | `/trades?limit=200` | Ledger imutável, mais recentes primeiro |

---

## Aportes — `/api/contributions`

| Método | Rota | O que faz |
|---|---|---|
| `GET` | `` | Lista com `prompts_total` / `prompts_answered` (progresso) |
| `POST` | `?run=true` | Cria o aporte + renderiza os 5 prompts. Com `run=true`, dispara a análise em `BackgroundTasks` e **volta na hora**. Body: `amount_brl>0`, `notes?` |
| `POST` | `/{id}/run` | Dispara a análise de um aporte existente. **409** só se um processo VIVO segura o lock (um `in_progress` órfão continua re-rodável) |
| `GET` | `/{id}` | Aporte completo + os 5 prompts com resposta/custo/duração. **É o endpoint de polling** |
| `POST` | `/{id}/prompts/{prompt_key}/response` | Salva resposta manual (fluxo de colar à mão) |
| `POST` | `/{id}/finalize` | Marca `completed` e grava `final_summary` (fluxo manual) |
| `DELETE` | `/{id}` | Apaga aporte + prompts + ordens (filhos primeiro, com `flush` — FK está ON) |

`prompt_key` ∈ `macro` · `selection` · `equity_diligence` · `crypto_diligence` ·
`decision` (`research` é legado).

---

## Ordens — `/api/orders`

| Método | Rota | O que faz |
|---|---|---|
| `GET` | `?status=pending` | Folha de ordens. `status` ∈ `pending`/`executed`/`skipped` |
| `POST` | `/{id}/execute` | Body `{quantity>0, price>0}`. Cria o lote herdando tese/alvo/stop. 404 / 409 se já resolvida |
| `POST` | `/{id}/skip` | Body `{reason?}`. Marca pulada |

---

## Cashflow (finanças pessoais) — `/api/cashflow`

| Método | Rota | O que faz |
|---|---|---|
| `POST` | `` | Registra gasto/ganho. Body: `kind` (`expense`\|`income`), `amount_brl>0`, `category` (min., default `outros`), `description?`, `occurred_on?` (default hoje), `source` (`chat`\|`bot`\|`api`). **Idêntico em 120s → devolve o existente** |
| `POST` | `/classify` | Texto livre → **rascunho** `CashflowCreate`. **Não grava.** 422 se não achou valor |
| `GET` | `?month=YYYY-MM&kind=&limit=100` | Lançamentos. `month` malformado → 422 |
| `GET` | `/summary?month=YYYY-MM` | `income_brl`, `expense_brl`, `net_brl`, `entries`, `by_category[]` |
| `GET` | `/history?months=6` | Totais por mês, **mais antigo primeiro** (a tendência) |
| `DELETE` | `/{id}` | Apaga um lançamento |

---

## Chat do consultor — `/api/chat`

| Método | Rota | O que faz |
|---|---|---|
| `GET` | `?limit=60` | `{busy, messages[]}` — histórico em ordem de leitura, com `channel`, `status`, `model`, `tier` |
| `POST` | `` | **202.** Enfileira o turno e volta na hora. **409** se ocupado. Body: `{text}` (1–8000 chars) |
| `POST` | `/upload` | multipart `file` + `caption`. Salva no inbox e enfileira o turno. **413** acima de 20 MB |
| `POST` | `/reset` | **204.** Descarta a sessão do Claude. Transcrição e MEMORY.md ficam. 409 no meio de um turno |

Polling do cliente: 2,5s ocupado / 12s ocioso.

---

## Relatórios — `/api/reports`

| Método | Rota | O que faz |
|---|---|---|
| `GET` | `?kind=&limit=50` | Lista. `kind` ∈ `weekly`\|`maturity`\|`monthly` |
| `GET` | `/{id}` | Relatório completo, com `steps[]` (cada etapa encadeada) |

---

## Outros

| Método | Rota | O que faz |
|---|---|---|
| `GET` | `/api/macro` | Snapshot macro (Selic, IPCA 12m, CDI, USD/BRL, Ibov, dominância BTC, Fear&Greed, `warnings[]`). Cache de `MARKET_CACHE_TTL` (120s) |
| `GET` | `/api/cadence` | Informativo: data do último aporte, dias desde então, total. **Não** existe ciclo fixo |
| `GET` | `/api/tax/{ano}` | IR simplificado: DARF mensal por classe + posições em 31/12. 422 fora de 2020..ano atual |
| `GET` | `/api/health` | `{status, version}` |

---

## Convenções

- **Datas:** `date` em ISO (`YYYY-MM-DD`); `datetime` em UTC **naive** no banco.
  O frontend parseia como UTC de propósito (`lib/format.ts::parseLocalDate`) —
  sem isso um aporte da noite aparecia com a data errada.
- **Dinheiro:** `Decimal` no backend (`decimal_places=2`, ou 8 para
  quantidade/preço); serializado como `float` nos schemas `*Read`.
- **Erros:** `{"detail": "mensagem em pt-BR"}`. A mensagem é mostrada ao usuário.
- **Novo endpoint:** router fino → service com a regra → schema Pydantic para
  entrada e saída → teste. Nunca coloque regra de negócio no router.
