# 13 · Estado atual

> **Fotografia de 2026-08-06.** Este é o documento que envelhece — atualize-o
> quando mudar algo estrutural. Os outros 12 descrevem como o sistema funciona;
> este descreve como ele está **agora**.

## Onde o repositório está

| Item | Valor |
|---|---|
| Branch | `feat/state-of-art-overhaul` (a de trabalho; `main` é a principal) |
| Versão backend | `0.4.0` (`app/main.py`, `pyproject.toml`) |
| Versão frontend | `0.3.0` (`frontend/package.json`) — desalinhada, cosmético |
| Testes | **113 passando** (eram 68 antes do overhaul de 2026-08-06) |
| Tamanho | ~10.700 linhas de Python · ~8.400 de TS/CSS |

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
| 6 | Bancos SEM dados de carteira (desktop e Pi zerados de lotes/trades) | o sistema roda "vazio"; posições reais precisam ser registradas (ou o histórico de maio/julho do desktop migrado deliberadamente) |

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

---

## Como manter esta documentação viva

- Mudou **comportamento**? atualize o doc da área (02–11).
- Mudou por um **motivo não óbvio** ou consertou um bug sutil? registre em
  `12-decisoes.md` — é o que evita alguém desfazer a correção depois.
- Mudou o **estado do repositório** (branch, versão, dívida, drift)? atualize
  **este** arquivo.
- `CLAUDE.md` continua sendo o contrato sempre carregado. Mantenha-o curto e
  operacional; o detalhe mora aqui.
