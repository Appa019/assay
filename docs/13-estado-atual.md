# 13 · Estado atual

> **Fotografia de 2026-08-05.** Este é o documento que envelhece — atualize-o
> quando mudar algo estrutural. Os outros 12 descrevem como o sistema funciona;
> este descreve como ele está **agora**.

## Onde o repositório está

| Item | Valor |
|---|---|
| Branch | `feat/state-of-art-overhaul` (a de trabalho; `main` é a principal) |
| Último commit | `2389cc7 perf(deploy): run next directly instead of through pnpm` |
| Versão backend | `0.4.0` (`app/main.py`, `pyproject.toml`) |
| Versão frontend | `0.3.0` (`frontend/package.json`) — desalinhada, cosmético |
| Testes | **68 passando** |
| Tamanho | ~10.100 linhas de Python · ~8.500 de TS/CSS |

## Trabalho não commitado (rebrand "Mesa" → "Assay")

Em andamento, coerente, pronto para commit:

```
 M CLAUDE.md                        wordmark + hostname Tailscale novo + nota do ícone
 M frontend/src/app/layout.tsx      title "Assay", themeColor #f6f7f9
 M frontend/src/components/sidebar.tsx        wordmark
 M .../investimentos/page.tsx       masthead "Assay · investimentos"
 M frontend/public/manifest.webmanifest       nome + 4 ícones
 M frontend/src/app/icon.svg, apple-icon.png, favicon.ico
 M frontend/public/icon.svg
 M requirements.txt                 + pillow (build-time, só para o gerador de ícone)
?? scripts/build_icon.py            gerador do ícone (fonte única)
?? frontend/public/icon-{192,512,maskable-512}.png
?? docs/                            esta documentação
 M .claude/settings.json            caminho de memória do hook Stop corrigido
 M .claude/agents/code-reviewer.md  idem
 M .claude/skills/review/SKILL.md   idem
 M app/services/chat_service.py     FIX: is_busy() valida liveness do lock
 M tests/test_chat_service.py       teste de regressão do lock órfão
```

**Caminhos de memória corrigidos (2026-08-05):** três arquivos de `.claude/`
apontavam para diretórios de projeto que não existem mais — o hook `Stop` para
`-home-<usuario>-investimentos-manual` e os outros dois para
`-home-<usuario>-codigos-python-investimentos-manual`. O correto é
`-home-<usuario>-01-investimentos-financas-app`. Enquanto estavam errados, o
code reviewer automático falhava no passo de memória em toda execução.

**Bug corrigido (2026-08-05): lock de chat órfão travava o site.**
`chat_service.is_busy()` testava só a existência do arquivo de lock. Um kill duro
no meio de um turno — **um deploy reiniciando o backend basta** — deixa o lock
para trás, e a partir daí `POST /api/chat`, `/upload` e `/reset` devolviam 409
indefinidamente, com a UI presa em "pensando". O Telegram continuava normal,
porque o runner recupera lock morto ao adquirir. Agora `is_busy()` usa
`_lock_is_active` (pid + starttime), como `is_run_active`. Detalhe em
`12-decisoes.md` (A25).

O hostname Tailscale mudou de `tail1d0148` para **`<tailnet>`** — a URL atual é
`https://<host-do-pi>.<tailnet>.ts.net`.

## Divergências conhecidas na documentação antiga

Encontradas ao escrever estes docs. **A verdade é o código.**

| Onde | Diz | Realidade |
|---|---|---|
| `CLAUDE.md` | "**TRÊS abas**, só" | são **quatro** (`lib/nav.ts`): Visão geral · Consultor · Extrato · Investimentos |
| `CLAUDE.md` | "`/financas` ainda existe como rota" | **não existe mais**. Foi substituída por `/extrato` (commit `f6a6e8d`) |
| `CLAUDE.md` | "Fraunces só em títulos, Manrope no resto" | são **Bricolage Grotesque** + **Plus Jakarta Sans** (commit `5e0ab81`). `DESIGN.md` está certo |
| `README.md` (raiz) | não menciona consultor, cashflow nem extrato | é anterior a toda a camada de finanças pessoais. Serve como apresentação do repo, não como referência |
| `acesso-remoto-pi.md` §7 | "Tailscale ainda não configurado — decisão futura" | **está configurado e é o meio de acesso oficial**. O resto do arquivo (SSH, firewall, túnel) continua válido |
| `.claude/skills/deploy/SKILL.md` | deploy para Vercel | o alvo é o **Pi**. Skill obsoleta |
| `frontend/src/lib/api.ts` | `ReportKind = "weekly" \| "maturity"` | o backend também emite `"monthly"` |

## Dívidas e pontos frágeis (nenhum urgente)

| # | Item | Impacto |
|---|---|---|
| 1 | `ativos/page.tsx` tem **1423 linhas** | é o maior arquivo do front; candidato natural a quebrar em componentes |
| 2 | `analysis_runner.py` tem **1494 linhas** e mistura motor, locks, workspace, MCPs e o fluxo de aporte | funciona e está bem testado, mas seria mais legível separado em `runner_core` / `workspace` / `mcp_config` / `locks` |
| 3 | `.gitignore` não lista `storage/router_workspace/` nem `storage/classifier_workspace/` | inofensivo hoje (git não versiona diretório vazio), mas qualquer arquivo que caia lá seria rastreado |
| 4 | `frontend/.vercel/` e `frontend/supabase/` | resíduos de arquiteturas abandonadas. Podem ser apagados |
| 5 | Sem teste de frontend | a validação é `lint` + `type-check` + `build`. Nenhum teste de componente |
| 6 | `PromptKey.RESEARCH` | legado de aportes anteriores a 2026-05-24; mantido só para não quebrar registros antigos |
| 7 | `README.md` desatualizado | ver tabela acima |

## Linha do tempo (o que aconteceu, em ordem)

| Quando | Marco |
|---|---|
| 2026-05 | Telegram + scheduler reintroduzidos a pedido do usuário. Ciclos: aporte ad-hoc, revisão semanal, maturidade por lote |
| 2026-05-24 | Pesquisa splitada em 3 reuniões (seleção → DD ações → DD cripto) |
| 2026-07 (início) | Camada de dados: ledger `Trade`, snapshots diários, WAL, marcação a mercado, trava enforçada no service |
| 2026-07 (meio) | Produto: ordens estruturadas, benchmark TWR, alertas de nível, IR, relatório mensal |
| 2026-07-23 | Última verificação registrada do acesso ao Pi |
| 2026-07-27 | Testes + CI + Makefile |
| 2026-07-28 | **Grande virada:** ledger de finanças pessoais, consultor no chat, chat no site, roteador de modelo, classificador, mobile-first, Pi vira produção única |
| 2026-07-29 | Rebrand Mesa → **Assay** + marca gerada por script |
| 2026-08-02 | Última escrita no banco de produção do desktop |
| 2026-08-05 | Esta documentação |

## O que eu faria a seguir (sugestões, não compromissos)

1. Commitar o rebrand Assay (está completo e coerente).
2. Corrigir as divergências do `CLAUDE.md` — feito parcialmente: veja o
   aviso no topo do arquivo apontando para `docs/`.
3. Reescrever o `README.md` para refletir o produto de duas metades, ou reduzi-lo
   a uma capa curta que aponte para `docs/`.
4. Apagar `frontend/.vercel/` e `frontend/supabase/`.
5. Remover ou reescrever `.claude/skills/deploy` (ainda deploya para Vercel).
6. Se `ativos/page.tsx` voltar a ser tocado, quebrar em componentes na mesma
   passada.

---

## Como manter esta documentação viva

- Mudou **comportamento**? atualize o doc da área (02–11).
- Mudou por um **motivo não óbvio** ou consertou um bug sutil? registre em
  `12-decisoes.md` — é o que evita alguém desfazer a correção depois.
- Mudou o **estado do repositório** (branch, versão, dívida, drift)? atualize
  **este** arquivo.
- `CLAUDE.md` continua sendo o contrato sempre carregado. Mantenha-o curto e
  operacional; o detalhe mora aqui.
