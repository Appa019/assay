# 13 · Estado atual

> **Fotografia de 2026-11-03.** Este é o documento que envelhece —
> atualize-o quando mudar algo estrutural. Os outros 11 descrevem como o
> sistema funciona; este descreve como ele está **agora**.

## 2026-11-03 — revisão final antes de religar o Pi

Contrato `deploy/pi/` conferido item a item contra o pi-ops: scripts
executáveis, `health.sh` com 0/1/2, `backup.sh` só leitura e sem `.env`,
restauração testada seguindo o README (dump idêntico, 500 linhas gravadas sob
escrita viva), guarda do HD simulada com e sem o ponto de montagem. Correções
que mudam comportamento (detalhe em A46–A55 e D48):

- **Ledger**: venda pelo app pede preço e quantidade executados; excluir lote
  só nas primeiras 24 h; edição não mexe mais em quantidade/preço médio.
- **Retomadas**: esperar o lock global ou o limite não conta tentativa
  (`RunBusyError`); mensagem do consultor esperando o limite sobrevive a
  restart.
- **Segurança**: POST marcado como de outro site leva 403.
- **Front no iPhone**: diálogos centrados, cabeçalho do consultor livre dos
  botões flutuantes, excluir com dois toques, link para Ajustes no sino,
  cores de status com contraste 4,5:1, movimento reduzido respeitado.
- **Config**: `CHAT_MODEL`/`CHAT_EFFORT` saíram (sem uso); `.env.example`
  cobre toda variável lida por `Settings`.

Em aberto, esperando decisão do Pedro:
1. `investimentos-resume` roda a cada 15 min o dia todo; uma análise
   interrompida pode ser retomada de tarde, contra a regra da madrugada.
   Restringir a janela atrasa o aporte em até um dia.
2. IR de cripto: `tax_service` compensa prejuízo de cripto com ganho futuro,
   como faz com ações. Pela regra da Receita até nossa última verificação,
   cripto é ganho de capital por alienação, sem compensação. Confirmar com o
   contador antes de mudar.
3. Código legado (`_LEGACY_CHAT_MEMORY_SEEDS`, `PromptKey.RESEARCH`,
   `ChatChannel.TELEGRAM`, `CashflowSource.BOT`): sai depois de uma contagem
   no banco do Pi confirmar que nenhuma linha usa.

## 2026-11-02 — bot removido, contrato de deploy e limpeza do repo

- **Bot do Telegram removido do código** (D47, `0dd0f09`): `telegram_bot.py`,
  `telegram_setup.py`, o espelho do `notification_center` e
  `chat_service.converse()`. Avisos vão para o inbox do app + Web Push; o chat
  entra só por `enqueue()`, pelo `/consultor`. `ChatChannel.TELEGRAM` e
  `CashflowSource.BOT` ficam só para ler linhas antigas.
- **Deploy do Pi com contrato**: `deploy/pi/` (install, deploy, check, health,
  backup) para o guardião do Pi. O plano de migração, com dados no HD e
  riscos, está em [`pi-deploy.md`](pi-deploy.md). Até a migração, o deploy
  segue por `rsync` (`09-operacao.md`).
- **Fontes self-hosted** com `next/font/local` (`47cd298`): o build não
  depende mais do Google Fonts.
- **`sqlmodel` limitado a `<0.0.45`** (A45): a 0.0.45 recusa datetime sem
  fuso.
- **Limpeza do repo**: código morto removido (funções, helpers de API e
  exports que ninguém chamava, dependência `zod`, sobras do create-next-app) e
  `scripts/install_cron.sh` apagado. O systemd é o único instalador.

## 2026-10-19 — comitê revisado e telas do comitê (D44, D45)

Prompts do comitê sem cálculo degenerado (otimizador com CDB de vol zero,
filtros de EBITDA em banco, opções numa folha long-only), semanal medida em
dias de calendário (rodava a cada 8), relatórios com bloco de ações
(`Report.actions`, coluna nova migrada no boot) e o front mostrando agendado,
ordens primeiro e falhas em português. Semanal e maturidade em uma etapa só
(D46). Pendências, em ordem de valor: (1) rodar as etapas do aporte num
processo só (`--input-format stream-json`), porque cada `--resume` reescreve o
cache depois do primeiro resultado grande; (2) a rotação semanal ainda não
vira `Order` (precisa modelar venda + compra); (3) medir o primeiro aporte.

## 2026-10-19 — vazamentos de token fora do modelo (D43)

Cache do comitê quebrava em todo `--resume` (snapshot de git), CLAUDE.md de dev
ia em toda chamada (15,6k tokens), visão pagava piso de 55k por foto, e o chat
perdia a resposta quando editava a memória depois de escrevê-la. Corrigidos
em `analysis_runner._run_claude_step` + `chat_service`. Rotação do chat
também por pausa > 1h. Falta medir o primeiro aporte depois disso
(`ContributionPrompt.context_tokens`).

## 2026-09-14 — fila do consultor e banco zerado

Quatro colunas novas em `chat_message` (`prompt`, `attempts`, `run_after`,
`retry_kind`, migração automática no boot) + o status `queued`. O chat virou
uma fila durável drenada por um worker único que sobe com o backend: dá para
mandar várias mensagens seguidas (o POST não devolve mais 409) e uma mensagem
barrada pelo limite de uso é retomada sozinha quando o crédito volta,
inclusive atravessando restart do Pi (D41). No front, a caixa de texto esvazia
sempre ao enviar e a mensagem na fila aparece com relógio. Sem variável de
ambiente nova.

**O banco e a memória foram zerados a pedido do cliente** (backup consistente
em `storage/backups/portfolio_pre_wipe_20260914_003614.db`, no Pi). O app
subiu com carteira, ledger, transcrição e `chat_workspace/` vazios — a memória
do consultor sobre o cliente começa do zero, então vale recontar salário,
gastos fixos e cartão.

## 2026-09-13 — fluxo de caixa previsto

Tabela `recurrence` (criada pelo `create_all` no boot, sem migração manual) +
`GET /api/cashflow/forecast` + CRUD em `/api/recurrences`. O `/extrato` ganhou
duas sub-abas na URL (`?aba=mes|fluxo`); `fluxo` mostra 6 meses de entrada ×
saída com barras em escala compartilhada, composição por mês e a fatura como
legenda. Só conta compromisso cadastrado — sem média histórica (D40). Cadastro
exclusivamente pelo consultor, que ganhou ordens e endpoints novos. Sem
variável de ambiente nova. Depois do deploy no Pi: contar ao consultor o
salário e os gastos fixos ("meu salário é 8.000 todo dia 5"), senão a aba abre
no estado vazio.

## 2026-09-12 — cartão de crédito e olhinho

Tabela `credit_card` + 4 colunas em `cashflow_entry` (migração automática no
boot). Cartão padrão para gasto da conta, parcelas expandidas em linhas,
fatura calculada (`/api/cards`), aviso no dia seguinte ao fechamento,
consultor/classificador/roteador com as regras (D39). No front: bloco de
fatura no extrato, cadastro em Ajustes, linha na visão geral e o **olhinho**
que mascara os formatadores de moeda (`lib/privacy.ts`). Sem variável de
ambiente nova. Depois do deploy no Pi: cadastrar o cartão em `/configuracoes`
(ou dizer ao consultor "meu cartão fecha dia X e vence dia Y").

## 2026-09-06 — corte de custo do motor (D37)

Com os números do backup pré-reset na mão (aporte = **US$ 62,99**; consultor =
**US$ 118,79 em 71 turnos**), quatro cortes cirúrgicos, todos com `make check`
verde e nenhum modelo rebaixado nas etapas de julgamento:

1. **Reunião nº 1 em modo delta** quando há revisão semanal ≤7 dias
   (`01_macro_delta.j2`, prompt 75% menor, mesmo contrato JSON).
2. **DD de ações enxuta**: 3 métodos de valuation em vez de 6, consenso com ≥3
   fontes em vez de casa por casa.
3. **Seleção de 4-5 ações** (era 5-8) e 3-4 criptos.
4. **Tier `lookup` (sonnet/low)** no consultor para consulta factual, e
   **maturidade absorvida pela revisão semanal** quando ela vence em ≤2 dias.

Expectativa: aporte ~US$ 63 → ~US$ 35-40. É projeção — a próxima rodada real
confirma.

**O chat continua caro e o motivo NÃO é o roteador** (D37, item 5): o tier
`lookup` foi testado contra as 80 mensagens reais do histórico e não pegou
nenhuma. O custo está no contexto de cada chamada (17,4k chars de ordens + 6
MCPs). Cortar ali tira capacidade do consultor — decisão pendente do cliente.

## 2026-09-06 — trava de venda por classe

A trava de 30 dias passou a valer **só para ações** (é compliance do cliente,
que trabalha no mercado financeiro); **cripto trava 7 dias** e o CDB segue sem
trava (D36). A regra saiu de seis superfícies e virou uma função só,
`portfolio_service.holding_lock_days`; a API passou a entregar
`lock_days_total`/`lock_days_left` por lote e `holding_lock_days` por classe no
resumo da carteira, e o front deixou de ter a constante `MIN_HOLDING_DAYS = 30`.
Nova chave: `MIN_HOLDING_DAYS_CRYPTO=7` (não precisa entrar no `.env` do Pi:
sem a chave vale o default do código, que já é 7).

## 2026-09-05 — recomeço do zero, app como canal único

O banco de produção foi **zerado deliberadamente** a pedido do cliente (backup
íntegro em `~/assay_backup_20260905_pre_reset/`, no Pi e no desktop). Junto
vieram quatro mudanças estruturais:

1. **Motor de IA ressuscitado.** O `claude` no Pi estava bloqueado desde ~28/08
   ("organization has disabled Claude subscription access"): consultor morto,
   revisão semanal falhando todo dia, aporte impossível. Token novo via
   `claude setup-token` no `.env` do Pi + `hasTrustDialogAccepted` marcado (as
   26 entradas de permissão estavam sendo ignoradas em modo headless). A
   classificação do erro foi corrigida em A40.
2. **Telegram aposentado** (D30). Tudo vai para o app: `notification_center`
   escreve no inbox, dispara Web Push e só espelha no Telegram se
   `TELEGRAM_MIRROR_ENABLED=true`. `investimentos-bot.service` parado e
   desabilitado no Pi.
3. **Roteador de 2 tiers determinístico** (D31). Registro de gasto em haiku,
   todo o resto em opus, sem triagem por LLM.
4. **Folha de ordens com ticker/quantidade/preço** (D32), com split de lote
   padrão vs fracionário da B3.
5. **Mandato mais defensivo** (D33): alvo passa de 35/40/25 para
   **RF 50% · Ações 35% · Crypto 15%**, com tolerância de drawdown 25%→20% (D35).
6. **Regra do CDB único imposta no código** (D34), não só no prompt.

Estado do banco depois do reset: **todas as tabelas em 0**. Preservado por
escolha do cliente: `agent_workspace/MEMORY.md` (422 linhas), `tools/` e
`.mcp.agent.json` do comitê. Descartado: memória do consultor, sessões,
workspaces efêmeros, chaves VAPID (é preciso reassinar o push em
`/configuracoes`).

## Onde o repositório está

| Item | Valor |
|---|---|
| Branch | `main` |
| Versão backend | `0.4.0` (`app/main.py`, `pyproject.toml`) |
| Versão frontend | `0.3.0` (`frontend/package.json`) — desalinhada, cosmético |
| Testes | **384 passando** (191 → 193 auth/entitlement → 204 sizing de ordem → 221 roteador + inbox → 227 mandato do CDB → 231 trava por classe → 252 corte de custo → 325 cartão de crédito → 384 fila do consultor + rotação por contexto) |
| Tamanho | ~10.700 linhas de Python · ~8.400 de TS/CSS |

## O que aconteceu na madrugada de 2026-08-06 (upgrade do consultor)

Missão de melhoria do assessor: diagnóstico do código + conversas de produção
do Pi + pesquisa de estado da arte com verificação adversarial. **Achado
central: o consultor nunca tinha sido usado** (0 linhas em `chat_message`,
MEMORY.md intocado) — por isso metade da entrega é ativação, não feature.
Detalhes em docs/12 (D23–D27, A35–A38); o backlog que sobrou está em
"Backlog" abaixo.

- **Chat**: contador de turnos zerado no renascimento de sessão (A35); custo/
  duração persistidos na `ChatMessage` (A36); bolha "Pensando…" órfã
  reconciliada no startup (A37); perfil de MCP enxuto por turno (D23); resumo
  estruturado na rotação (D24); triagem com contexto e fora do lock (A38);
  atalho fast para valores por extenso; ordens permanentes com aritmética via
  ferramenta, gatilhos de escalação, anti-sycophancy e memória
  reconciliar-não-apendar; seed do MEMORY.md com bloco de suitability.
- **Proatividade v1 (D25)**: `insight_service` determinístico + timers
  `investimentos-insights` (09:07) e `investimentos-digest` (dom 20:07).
- **Ativação (D27)**: aviso de chat desconhecido ao dono, onboarding no
  primeiro boot, fila do bot sem descarte em busy.
- **Custo (D26)**: revisão semanal não roda com carteira+ledger vazios.

## O que aconteceu em 2026-08-06 (overhaul pós-revisão extensiva)

Uma revisão extensiva (5 revisores + verificação manual + smoke de runtime)
levantou 3 críticos, 12 warnings e 10 propostas de motor. Tudo o que era
acionável foi corrigido na mesma data — detalhes em `12-decisoes.md`
(D18–D22, A26–A34). Resumo do que mudou:

- **Ledger**: `execute_order` atômico (commit único); venda aceita **preço real
  e quantidade parcial** (`SellPayload`); ordens do consultor corrigidas.
- **Concorrência**: pidfile do bot no lock com identidade de processo;
  `/classify` fora do event loop; `delete_contribution` protegido (409 com
  ordem executada ou run ativo); aporte que morre pré-1ª-etapa entra no
  auto-resume; `resume_pending` alerta falha de infra.
- **Timezone**: `days_held` do IR, `_ibov_closes`, preâmbulo/notify do runner e
  displays do bot/monthly agora convertem UTC→local antes de extrair data.
- **Cashflow**: vocabulário canônico único de categorias
  (`CANONICAL_CATEGORIES`) + fold de acentos/aliases no service;
  `month_history` em 1 GROUP BY.
- **Benchmark**: CDI tolera linha malformada; BTC via `market_chart/range`
  (UTC); todas as séries rebased no 1º dia comum (`base_date` no payload).
- **Motor de IA**: validador determinístico pós-run com 1 turno corretivo +
  alerta de folha; ordens pendentes injetadas no contexto do aporte; rotação do
  chat semeada com a transcrição; DDs com 2× timeout; **MCPs pinados**
  (versão/sha — supply chain); templates sem contradições (N≥6,
  Options_Overlays fora) + nota anti-fossilização de tickers; tiers do roteador
  reportados no relatório mensal.
- **Frontend**: race do `useCashflow` eliminada; `ReportKind` ganhou
  `"monthly"` (label/ícone "Mensal"); payload tipado no cadastro de ativo;
  `formatAmount` substitui o `.replace("R$")` frágil; gráfico morto removido.
- **Tooling**: `python -m uvicorn` em start.sh/Makefile/systemd (rename-proof —
  a renomeação do projeto tinha quebrado os shebangs do venv no desktop);
  gitignore cobre router/classifier workspaces; resíduos `frontend/.vercel` e
  `frontend/supabase` apagados; permissões supabase/vercel removidas de
  `.claude/settings.json`.

## Divergências conhecidas na documentação antiga

| Onde | Diz | Realidade |
|---|---|---|
| `README.md` (raiz) | não menciona consultor, cashflow nem extrato | é anterior à camada de finanças pessoais. Serve como capa do repo, não referência |
| `.claude/skills/deploy/SKILL.md` | deploy para Vercel | o alvo é o **Pi**. Skill obsoleta |

## Dívidas e pontos frágeis (nenhum urgente)

| # | Item | Impacto |
|---|---|---|
| 1 | `ativos/page.tsx` tem ~1430 linhas | maior arquivo do front; quebrar em componentes quando voltar a ser tocado |
| 2 | `analysis_runner.py` ~1700 linhas (motor + locks + workspace + MCPs + validador) | funciona e está testado; separável em módulos numa refatoração futura |
| 3 | Sem teste de frontend | validação é lint + type-check + build |
| 4 | `PromptKey.RESEARCH` | legado de aportes pré-2026-05-24 |
| 5 | `README.md` desatualizado | ver tabela acima |
| 6 | Banco zerado por decisão do cliente (2026-09-05) | esperado, não é dívida. Backup íntegro pré-reset em `~/assay_backup_20260905_pre_reset/` |
| 7 | `delete_asset` apaga lote sem `Trade` nem trava de 30d (A41) | buraco silencioso no track record; sem risco agora (banco vazio), corrigir antes de acumular histórico |

## Backlog (não implementado, com o gatilho para fazer)

Herdado do upgrade do consultor (2026-08-06).

| Item | Por que ficou | Gatilho |
|---|---|---|
| Golden set + juiz haiku + `make eval` | não havia conversa real para curar | ~1 mês de uso real |
| Verificador determinístico pós-resposta (lançamento citado × ledger) | valor baixo sem volume de conversas | primeiro mês de uso |
| Busca FTS5 na transcrição (`GET /api/chat/search`) exposta nas ordens | o valor cresce com o histórico | transcrição com alguns meses |
| Fallback de cotação yfinance → brapi → Stooq | protege a marcação a mercado; medir 429 antes | primeiro 429 do Yahoo nos timers |
| Consolidação offline de memória (da transcrição crua) | `MEMORY.md` ainda pequeno | memória > ~8k chars |
| `client_ref` idempotente no `POST /api/cashflow` | a dedup de 120s cobre o caso comum | primeiro gasto duplicado real |
| `tools/fundamentus.py` + `tools/sgs.py` seedados no comitê | ganho do comitê, fora do escopo do consultor | próximo ciclo de aporte |

## Linha do tempo (o que aconteceu, em ordem)

| Quando | Marco |
|---|---|
| 2026-05 | Telegram + scheduler reintroduzidos. Ciclos: aporte ad-hoc, revisão semanal, maturidade por lote |
| 2026-05-24 | Pesquisa splitada em 3 reuniões (seleção → DD ações → DD cripto) |
| 2026-07 | Camada de dados (ledger Trade, snapshots, WAL) → produto (ordens, benchmark, alertas, IR, mensal) |
| 2026-07-28 | **Grande virada:** finanças pessoais, consultor no chat/site, roteador de modelo, mobile-first, Pi vira produção única |
| 2026-07-29 | Rebrand Mesa → **Assay** |
| 2026-08-05 | Documentação `docs/` (13 arquivos) + fix do lock do chat (A25) |
| 2026-08-06 | **Revisão extensiva + overhaul state-of-art** (D18–D22, A26–A34) + deploy no Pi |
| 2026-08-06 (madrugada) | **Upgrade do consultor** (D23–D27, A35–A38): ativação, proatividade v1, MCP enxuto, rotação com resumo + deploy no Pi |
| 2026-08-06 | **Carteiras no ledger** (D28): `wallet` conta/vr/va em todo o cashflow — API, classificador, bot, ordens do consultor, extrato |
| 2026-08-06 (noite) | Consultor fixado em opus/max (.env do Pi); token de auth de 1 ano; reset zera a tela; push nativo do PWA + até 3 fotos por mensagem no site |
| 2026-08-10 | **CDB vira instrumento fixo** (D29): só Bradesco 100% CDI liquidez diária, nos 3 templates que tocam RF + ordens permanentes + revisão semanal + consultor |
| 2026-08-28 | (silencioso) acesso ao Claude Code revogado no Pi — motor de IA para de funcionar sem ninguém perceber |
| 2026-09-05 | **Recomeço do zero**: banco zerado, auth restaurada (A40), Telegram aposentado (D30), roteador de 2 tiers (D31), boleta na folha de ordens (D32), mandato 50/35/15 + DD 20% (D33/D35), CDB único imposto no ingest (D34) |

---

## Como manter esta documentação viva

- Mudou **comportamento**? atualize o doc da área (02–11).
- Mudou por um **motivo não óbvio** ou consertou um bug sutil? registre em
  `12-decisoes.md` — é o que evita alguém desfazer a correção depois.
- Mudou o **estado do repositório** (branch, versão, dívida, drift)? atualize
  **este** arquivo.
- `CLAUDE.md` continua sendo o contrato sempre carregado. Mantenha-o curto e
  operacional; o detalhe mora aqui.
