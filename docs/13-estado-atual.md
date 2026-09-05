# 13 · Estado atual

> **Fotografia de 2026-09-05.** Este é o documento que envelhece —
> atualize-o quando mudar algo estrutural. Os outros 12 descrevem como o
> sistema funciona; este descreve como ele está **agora**.

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

Estado do banco depois do reset: **todas as tabelas em 0**. Preservado por
escolha do cliente: `agent_workspace/MEMORY.md` (422 linhas), `tools/` e
`.mcp.agent.json` do comitê. Descartado: memória do consultor, sessões,
workspaces efêmeros, chaves VAPID (é preciso reassinar o push em
`/configuracoes`).

## Onde o repositório está

| Item | Valor |
|---|---|
| Branch | `feat/consultor-upgrade` (sobre `feat/state-of-art-overhaul`; `main` é a principal) |
| Versão backend | `0.4.0` (`app/main.py`, `pyproject.toml`) |
| Versão frontend | `0.3.0` (`frontend/package.json`) — desalinhada, cosmético |
| Testes | **221 passando** (191 → 193 auth/entitlement → 204 sizing de ordem → 221 roteador + inbox) |
| Tamanho | ~10.700 linhas de Python · ~8.400 de TS/CSS |

## O que aconteceu na madrugada de 2026-08-06 (upgrade do consultor)

Missão de melhoria do assessor: diagnóstico do código + conversas de produção
do Pi + pesquisa de estado da arte com verificação adversarial. **Achado
central: o consultor nunca tinha sido usado** (0 linhas em `chat_message`,
MEMORY.md intocado) — por isso metade da entrega é ativação, não feature.
Detalhes em `CONSULTOR_UPGRADE_REPORT.md` (raiz) e docs/12 (D23–D27, A35–A38).

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
| `acesso-remoto-pi.md` §7 | "Tailscale ainda não configurado" | está configurado e é o acesso oficial (`https://<host-do-pi>.<tailnet>.ts.net`) |
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
| 8 | Superfícies só-do-bot sem equivalente no app | o bot está desabilitado; se faltar algo (`/atualizar`, `/ir`), promover para a interface |

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
| 2026-09-05 | **Recomeço do zero**: banco zerado, auth restaurada (A40), Telegram aposentado (D30), roteador de 2 tiers (D31), boleta na folha de ordens (D32) |

---

## Como manter esta documentação viva

- Mudou **comportamento**? atualize o doc da área (02–11).
- Mudou por um **motivo não óbvio** ou consertou um bug sutil? registre em
  `12-decisoes.md` — é o que evita alguém desfazer a correção depois.
- Mudou o **estado do repositório** (branch, versão, dívida, drift)? atualize
  **este** arquivo.
- `CLAUDE.md` continua sendo o contrato sempre carregado. Mantenha-o curto e
  operacional; o detalhe mora aqui.
