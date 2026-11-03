# 05 · Fluxos ponta a ponta

Cada seção segue um caminho completo pelo sistema. Use como mapa quando algo
"não funcionou" e você precisa saber onde olhar.

---

## Fluxo 1 — Aporte (o principal)

**Gatilhos:** `POST /api/contributions?run=true` · aba **Aportar** em
`/investimentos` · `scripts/run_analysis.py --amount 5000` · **o próprio consultor** ("quero
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
   └─ inbox + push: strip_machine_block(final_summary)  — cliente vê só a estrutura

4. Falha
   ├─ status volta para ready (retentável)
   ├─ causa APENDADA em notes
   ├─ run_attempts += 1  → aos 5, avisa no app e para de tentar
   └─ resume_pending.py retoma no próximo pass da madrugada (00:00–02:45)
```

**Onde ver progresso:** `GET /api/contributions/{id}` (o front faz polling em
`/aporte/[id]` e mostra etapa por etapa) ou `storage/analysis_runs/transcripts/`.

**Tempo e custo típicos:** 20–60 min, opus/max, ~110k chars de prompt no total.

### As 5 reuniões

| # | Reunião | O que produz |
|---|---|---|
| 1 | **Macro · Alocação Tática** (12 personas, 11 rounds) | `final_tactical_brl` (cdb/acoes_b3/crypto), `juros_e_cdb`, `setores_b3`, `digital_assets`. Curva DI como sinal de CDI; Black-Litterman + Risk Parity + HRP; pre-mortem |
| 2 | **Universo, Filtros e Seleção** (12 personas + 2 vetos) | `selecao_acoes_b3` (até 5), `selecao_crypto` (até 4), `shortlist_cdb` (valor + credit do emissor), `sanidade_selecao`. **Não** escreve memo final |
| 3 | **Due Diligence de Ações B3** | `shortlist_acoes_b3`: memo completo por ação — valuation triangulada (múltiplos, Reverse DCF, DCF 3-estágios, CCA; Precedent/LBO/SOTP cortados no D37), forense (Piotroski/Altman/Beneish/Sloan), capital allocation, técnica de entrada, factor, bull/base/bear. Sem pair trades (D44) |
| 4 | **Due Diligence de Crypto** | `shortlist_crypto`: tese, tokenomics/unlocks, on-chain (MVRV-Z/NUPL/SOPR/…), derivativos, dev activity, bull/base/bear. **BTC+ETH ≥ 50%** |
| 5 | **Investment Committee Final** (12 personas, 12 rounds) | risk overlay (vol, drawdown, beta, VaR/CVaR 95; sem EVT/CDaR desde o D44), stress em 8 cenários (incl. evento de crédito bancário), sentimento, confirma CDB, tax, compliance, cross-check do CIO, **folha de ordens** |

Schema JSON `version=5.0`, `escopo=BR_3_classes_cdb_acoesB3_crypto`. As reuniões
3 e 4 podem usar subagentes (Task) por ticker, gravando memos em `./dd/`
(best-effort). A pesquisa foi splitada em 2026-05-24 (era uma reunião única) para
cada nome receber um turno dedicado — resolvia um gargalo de output.

**A folha de ordens não tem coluna de plataforma.** O cliente decide onde executar.

---

## Fluxo 2 — Executar uma ordem

```
UI:  OrdersPanel na Visão geral (ou na página do aporte, /aporte/[id])
     → lista pendentes, "executei" com quantidade e preço
API: POST /api/orders/{id}/execute {quantity, price}
     → order_service.execute_order()

execute_order()
 ├─ portfolio_service.create_asset()   → cria o Asset (lote) + Trade(buy)
 ├─ copia thesis / target_price / stop_price da Order para o Asset
 └─ Order.status = executed + quantity/price/asset_id/executed_at
```

A partir daqui o lote entra na trava da sua classe (ação 30d, cripto 7d),
aparece na revisão semanal com a
tese registrada, e o `check_alerts.py` passa a vigiar alvo/stop.

---

## Fluxo 3 — Revisão semanal (a cada 7 dias)

`scripts/weekly_review.py` (timer diário 02:10, auto-gated a 7 dias; `--force`
ignora o gate).

```
1. refresh de preços (marcação a mercado)
2. market_data_service.build_full_context()
3. review_service.run_weekly_review()
   └─ run_chain com 1 etapa (D46), que devolve as duas partes separadas
      por `_REPORT_MARKER`:
      a) memo: macro + desempenho por LOTE (tese intacta/enfraquecida/
         quebrada) + recomendação por lote liberado + ROTAÇÃO DE DRY POWDER
      b) relatório executivo (o texto do aviso)
4. Report(kind=weekly) salvo + inbox + push
```

O resultado é injetado como bloco de consulta no **próximo aporte**
(`_latest_weekly_context`).

**Rotação de dry powder:** a revisão pode recomendar "VENDER R$ X de CDB →
COMPRAR <ativo>" quando houver assimetria clara. Se não houver, ela precisa
dizer "manter CDB, sem rotação esta semana".

---

## Fluxo 4 — Maturidade de lote (30d ação · 7d cripto)

`scripts/check_cadence.py` (timer diário 01:45, idempotente; cede a vez à
semanal se ela vence em ≤ 2 dias, D37).

```
notification_service.pending_maturities()
  ├─ ignora fixed_income (liquidez diária, nunca "destrava")
  ├─ lotes com (hoje - entry_date) >= holding_lock_days(classe)
  └─ menos os já tratados (storage/notifications_state.json)

se houver → review_service.run_maturity_review()
             → Report(kind=maturity) + inbox + push
             → mark_maturities(keys)   [SÓ depois do sucesso]
```

As chaves só são marcadas **após** a ação dar certo, então uma falha é
retentada no dia seguinte.

Não existe lembrete de aporte: **aporte é ad-hoc**. O toque recorrente é a
revisão semanal.

---

## Fluxo 5 — Registrar um gasto (a ação mais frequente)

Três caminhos, todos terminando no mesmo `cashflow_service.add_entry`:

| Caminho | Como |
|---|---|
| **Chat** (normal) | "gastei 42 no mercado" → consultor chama `POST /api/cashflow` com `source=chat` e confirma em 1 linha |
| **Foto** | manda o cupom no chat → cai em `chat_workspace/inbox/` → um leitor descartável transcreve o arquivo (D42) → o consultor registra a partir da transcrição |
| **API/UI** | `POST /api/cashflow` direto, `source=api` |

Proteção: lançamento idêntico dentro de 120s é colapsado em um só.

**Leitura:** `/extrato` no site (mês a mês, por categoria, com exclusão inline)
· `GET /api/cashflow/summary?month=`. Linhas antigas com `source=bot` vieram do
bot removido em D47.

---

## Fluxo 6 — Conversar com o consultor

**Uma conversa só, uma porta:** a página `/consultor`.

```
Site: POST /api/chat
        │
        ▼
 chat_service.enqueue()
  ├─ ChatMessage(user)
  └─ ChatMessage(assistant,
        status=QUEUED, prompt=…)  ← a FILA é esta linha
                   │
                   ▼
      worker único (_queue_loop, thread do backend)
        ├─ _claim_next_job(): mais ANTIGO primeiro, FIFO estrito
        ├─ status → RUNNING
        ├─ run_chat_turn()
        │    ├─ model_router.route(text) → tier/modelo (antes do lock)
        │    ├─ adquire _chat_turn.lock (serializa entre processos)
        │    ├─ _expand_attachments(): anexo → transcrição (sessão descartável)
        │    ├─ resume session.json (rotaciona em 120k tokens ou 40 turnos)
        │    └─ _run_claude_step() no chat_workspace
        └─ settle: content + status(done|failed) + model + tier + push
```

**A fila mora no banco**, não na memória — é isso que dá as duas propriedades:

- **Mandar várias mensagens seguidas**: o POST nunca devolve 409; cada
  mensagem entra atrás e é lida na ordem, na mesma sessão encadeada.
- **Voltar sozinho quando o crédito volta**: `LimitError` não mata o turno —
  a linha volta a `QUEUED` com `run_after` na hora do reset (`retry_kind =
  limit`, até 24 tentativas) e o worker a retoma. Sobrevive a restart do
  backend, porque está no SQLite. Erro transitório: 3 tentativas curtas.
  `AuthError` (login expirado) NÃO é retentado — só um humano resolve.
- Um turno morto por reinício volta para a fila (`reconcile_orphan_turns`).
  Toda retomada prefixa `_RESUME_PREFACE` no prompt, mandando o consultor
  conferir o ledger antes de gravar — a tentativa anterior pode ter registrado
  metade do trabalho antes de cair.

FIFO é **estrito**: se a primeira mensagem está esperando o limite, as de trás
esperam junto. Passar na frente reordenaria a conversa e elas bateriam na
mesma janela fechada.

O site faz polling: **2,5s trabalhando, 12s ocioso** (e 12s enquanto a fila
espera crédito); a resposta chega mesmo se a página recarregar, porque o turno
conclui no servidor.

O botão **Nova sessão** no `/consultor` (`POST /api/chat/reset`) descarta a
sessão do Claude. A transcrição e o `MEMORY.md` **ficam**. Com fila pendente o
reset dá 409.

---

## Fluxo 7 — Vender uma posição

```
UI: botão Vender na aba Carteira (diálogo de confirmação; mostra a trava)
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

Os 11 timers de `scripts/install_systemd.sh` (unit `investimentos-<nome>.timer`):

| Horário | Timer · script | Custa Claude? |
|---|---|---|
| 01:00 diário | `scheduled` · `run_scheduled.py` — aportes agendados para a madrugada (D38) | sim, quando há aporte agendado |
| 01:45 diário | `cadence` · `check_cadence.py` — maturidade de lotes | sim, se houver lote maduro |
| 02:10 diário | `weekly` · `weekly_review.py` — auto-gated a 7 dias | sim, quando dispara |
| a cada 15 min, 00:00–02:45 | `resume` · `resume_pending.py` — retoma análises interrompidas | sim, quando há o que retomar |
| a cada 6h (:15) | `prices` · `refresh_prices.py` — marcação a mercado | **não** |
| 18:45 diário | `snapshot` · `daily_snapshot.py` — ponto da curva de patrimônio | **não** |
| 11/15/19:05 | `alerts` · `check_alerts.py` — alvo/stop cruzados | **não** |
| dias 1–2, 10:00 | `monthly` · `monthly_report.py` — relatório mensal | **não** |
| 09:07 diário | `insights` · `daily_insights.py` — insights do ledger pessoal | **não** |
| domingo 20:07 | `digest` · `weekly_digest.py` — digest financeiro semanal | **não** |
| 03:00 diário | `backup` · `backup_db.sh` — backup rotacionado (14 dias) | **não** |

Todo job avisa no app (inbox + push) quando **quebra**, não só quando dá certo.
Os timers usam `Persistent=true` (máquina desligada na hora agendada recupera a
janela no boot), **menos** `scheduled`, `cadence` e `weekly`, que são
`Persistent=false`: recuperar no boot rodaria o comitê no meio do dia, dentro
da janela de uso que o consultor precisa. Noite perdida espera a próxima.

---

## Fluxo 9 — Alertas de preço

`check_alerts.py` (3× ao dia, sem Claude): atualiza preços e compara cada lote
com `target_price`/`stop_price`. **Um alerta por cruzamento** — o estado
(`storage/alerts_state.json`) rearma quando o preço volta à banda, então um
nível cruzado de novo mais tarde alerta de novo, sem spam a cada run.
