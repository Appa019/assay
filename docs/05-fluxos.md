# 05 · Fluxos ponta a ponta

Cada seção segue um caminho completo pelo sistema. Use como mapa quando algo
"não funcionou" e você precisa saber onde olhar.

---

## Fluxo 1 — Aporte (o principal)

**Gatilhos:** `POST /api/contributions?run=true` · `/aporte <valor>` no bot ·
`scripts/run_analysis.py --amount 5000` · **o próprio consultor** ("quero
investir 5000" → ele confirma o valor e chama a API).

```
1. contribution_service.create_contribution_with_prompts()
   ├─ portfolio_service.get_portfolio_summary()     posições e alocação
   ├─ portfolio_service.build_portfolio_snapshot()  detalhe por lote (com tese)
   ├─ market_data_service.build_full_context()      BCB + Yahoo + CoinGecko + F&G
   └─ prompt_generator.render_all_prompts()         5 templates Jinja2
   → Contribution(status=ready) + 5 ContributionPrompt

2. analysis_runner.run_analysis()  [BackgroundTasks / CLI]
   ├─ adquire lock do aporte (409 se já tem run vivo)
   ├─ monta os steps: preâmbulo + revisão semanal + track record  ⟶ etapa 1
   │                  as 4 reuniões seguintes                     ⟶ etapas 2-5
   │                  _SYNTHESIS_PROMPT                           ⟶ etapa 6
   ├─ status = in_progress
   └─ run_chain()  [segura o lock GLOBAL]
        etapa 1 fresh → session_id salvo no banco
        etapas 2-6 --resume
        cada etapa: persiste response + cost + duration + turns

3. Sucesso
   ├─ final_summary salvo, status = completed, run_attempts = 0
   ├─ order_service.ingest_contribution_orders()   (fora do try de falha)
   └─ Telegram: strip_machine_block(final_summary)  — cliente vê só a estrutura

4. Falha
   ├─ status volta para ready (retentável)
   ├─ causa APENDADA em notes
   ├─ run_attempts += 1  → aos 5, avisa no Telegram e para de tentar
   └─ resume_pending.py retoma no próximo pass de 15 min
```

**Onde ver progresso:** `GET /api/contributions/{id}` (o front faz polling em
`/aporte/[id]` e mostra etapa por etapa) ou `storage/analysis_runs/transcripts/`.

**Tempo e custo típicos:** 20–60 min, opus/max, ~110k chars de prompt no total.

### As 5 reuniões

| # | Reunião | O que produz |
|---|---|---|
| 1 | **Macro · Alocação Tática** (12 personas, 11 rounds) | `final_tactical_brl` (cdb/acoes_b3/crypto), `juros_e_cdb`, `setores_b3`, `digital_assets`. Curva DI como sinal de CDI; Black-Litterman + Risk Parity + HRP; pre-mortem |
| 2 | **Universo, Filtros e Seleção** (12 personas + 2 vetos) | `selecao_acoes_b3` (5–8), `selecao_crypto` (3–5), `shortlist_cdb` (valor + credit do emissor), `sanidade_selecao`. **Não** escreve memo final |
| 3 | **Due Diligence de Ações B3** | `shortlist_acoes_b3`: memo completo por ação — valuation triangulada (DCF 3-estágios, Reverse DCF, CCA, Precedent, LBO, SOTP), forense (Piotroski/Altman/Beneish/Sloan/Dechow), capital allocation, técnica, factor, bull/base/bear + pair trades |
| 4 | **Due Diligence de Crypto** | `shortlist_crypto`: tese, tokenomics/unlocks, on-chain (MVRV-Z/NUPL/SOPR/…), derivativos, dev activity, bull/base/bear. **BTC+ETH ≥ 50%** |
| 5 | **Investment Committee Final** (14 personas, 14 rounds) | risk overlay (VaR/CVaR/EVT/CDaR), stress em 8 cenários (incl. evento de crédito bancário), sentimento, confirma CDB, tax, compliance, cross-check do CIO, **folha de ordens** |

Schema JSON `version=5.0`, `escopo=BR_3_classes_cdb_acoesB3_crypto`. As reuniões
3 e 4 podem usar subagentes (Task) por ticker, gravando memos em `./dd/`
(best-effort). A pesquisa foi splitada em 2026-05-24 (era uma reunião única) para
cada nome receber um turno dedicado — resolvia um gargalo de output.

**A folha de ordens não tem coluna de plataforma.** O cliente decide onde executar.

---

## Fluxo 2 — Executar uma ordem

```
Telegram: /ordens                    → lista pendentes
Telegram: /executei PETR4 100 38.20  → order_service.execute_order()
   ou API: POST /api/orders/{id}/execute {quantity, price}
   ou UI:  OrdersPanel na Visão geral

execute_order()
 ├─ portfolio_service.create_asset()   → cria o Asset (lote) + Trade(buy)
 ├─ copia thesis / target_price / stop_price da Order para o Asset
 └─ Order.status = executed + quantity/price/asset_id/executed_at
```

A partir daqui o lote entra na trava de 30d, aparece na revisão semanal com a
tese registrada, e o `check_alerts.py` passa a vigiar alvo/stop.

---

## Fluxo 3 — Revisão semanal (a cada 7 dias)

`scripts/weekly_review.py` (timer diário 09:30, auto-gated a 7 dias; `--force`
ignora o gate).

```
1. refresh de preços (marcação a mercado)
2. market_data_service.build_full_context()
3. review_service.run_weekly_review()
   └─ run_chain com 2 etapas:
      a) análise: macro + desempenho por LOTE (tese intacta/enfraquecida/
         quebrada) + recomendação por lote liberado + ROTAÇÃO DE DRY POWDER
      b) relatório executivo para o Telegram
4. Report(kind=weekly) salvo + Telegram
```

O resultado é injetado como bloco de consulta no **próximo aporte**
(`_latest_weekly_context`).

**Rotação de dry powder:** a revisão pode recomendar "VENDER R$ X de CDB →
COMPRAR <ativo>" quando houver assimetria clara. Se não houver, ela precisa
dizer "manter CDB, sem rotação esta semana".

---

## Fluxo 4 — Maturidade de lote (30 dias)

`scripts/check_cadence.py` (timer diário 09:00, idempotente).

```
notification_service.pending_maturities()
  ├─ ignora fixed_income (liquidez diária, nunca "destrava")
  ├─ lotes com (hoje - entry_date) >= 30 dias
  └─ menos os já tratados (storage/notifications_state.json)

se houver → review_service.run_maturity_review()
             → Report(kind=maturity) + Telegram
             → mark_maturities(keys)   [SÓ depois do sucesso]
```

As chaves só são marcadas **após** a ação dar certo, então uma falha é
retentada no dia seguinte.

Não existe lembrete de aporte: **aporte é ad-hoc**. O toque recorrente é a
revisão semanal.

---

## Fluxo 5 — Registrar um gasto (a ação mais frequente)

Quatro caminhos, todos terminando no mesmo `cashflow_service.add_entry`:

| Caminho | Como |
|---|---|
| **Chat** (normal) | "gastei 42 no mercado" → consultor chama `POST /api/cashflow` com `source=chat` e confirma em 1 linha |
| **Bot** | `/gasto 42 compras #mercado` → `source=bot` |
| **Foto** | manda o cupom no chat → cai em `chat_workspace/inbox/` → consultor lê pela visão, extrai valor/data/estabelecimento e registra |
| **API/UI** | `POST /api/cashflow` direto, `source=api` |

Proteção: lançamento idêntico dentro de 120s é colapsado em um só.

**Leitura:** `/extrato` no site (mês a mês, por categoria, com exclusão inline)
· `/financas [AAAA-MM]` no bot · `GET /api/cashflow/summary?month=`.

---

## Fluxo 6 — Conversar com o consultor

**Uma conversa só, duas portas.**

```
Telegram: texto sem "/"          Site: POST /api/chat
        │                               │
        └──────────┬────────────────────┘
                   ▼
      chat_service.converse(text, channel)
        ├─ grava ChatMessage(user)
        ├─ grava ChatMessage(assistant, status=running)   ← bolha pendente
        ├─ run_chat_turn()
        │    ├─ adquire _chat_turn.lock (fila serial)
        │    ├─ model_router.route(text) → tier/modelo
        │    ├─ resume session.json (rotaciona em 40 turnos)
        │    └─ _run_claude_step() no chat_workspace
        └─ settle: content + status(done|failed) + model + tier
```

O site faz polling: **2,5s ocupado, 12s ocioso** — a resposta pode chegar do
Telegram. O bot mostra "digitando…" enquanto roda (o indicador expira em ~5s,
então há um loop que renova).

`/resetchat` (bot) e `POST /api/chat/reset` descartam a sessão do Claude. A
transcrição e o `MEMORY.md` **ficam**.

---

## Fluxo 7 — Vender uma posição

```
/vender PETR4  (bot, 2 passos com confirmação)
   ou POST /api/portfolio/assets/{id}/sell

portfolio_service.sell_asset()
 ├─ sell_lock_days_left() > 0 ?  → SellLockedError → 409
 ├─ preço = current_price ?? avg_price
 ├─ grava Trade(sell) com realized_pnl_brl / _pct / lot_entry_date
 └─ DELETA o Asset          ← o histórico vive no Trade, não no Asset
```

O consultor **nunca vende sozinho.** Ele recomenda a cascata de liquidez (caixa
→ CDB → lote livre, contando a isenção de IR) e registra só depois que o cliente
confirmar que executou na corretora.

---

## Fluxo 8 — Jobs agendados (o que roda sozinho)

| Horário | Job | Custa Claude? |
|---|---|---|
| 09:00 diário | `check_cadence.py` — maturidade de lotes | sim, se houver lote maduro |
| 09:30 diário | `weekly_review.py` — auto-gated a 7 dias | sim, quando dispara |
| a cada 15 min | `resume_pending.py` — retoma análises interrompidas | sim, quando há o que retomar |
| a cada 6h (:15) | `refresh_prices.py` — marcação a mercado | **não** |
| 18:45 diário | `daily_snapshot.py` — ponto da curva de patrimônio | **não** |
| 11/15/19:05 | `check_alerts.py` — alvo/stop cruzados | **não** |
| dias 1–2, 10:00 | `monthly_report.py` — relatório mensal | **não** |
| 03:00 diário | `backup_db.sh` — backup rotacionado (14 dias) | **não** |

Todo cron avisa no Telegram quando **quebra**, não só quando dá certo.
Timers systemd usam `Persistent=true`: máquina desligada na hora agendada
recupera a janela no boot (cron simples pula em silêncio).

---

## Fluxo 9 — Alertas de preço

`check_alerts.py` (3× ao dia, sem Claude): atualiza preços e compara cada lote
com `target_price`/`stop_price`. **Um alerta por cruzamento** — o estado
(`storage/alerts_state.json`) rearma quando o preço volta à banda, então um
nível cruzado de novo mais tarde alerta de novo, sem spam a cada run.
