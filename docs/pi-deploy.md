# Pi deploy — investimentos (Assay)

Plano da reorganização do Pi (`~/<docs-do-pi>/reorganizacao.md`), já com
as respostas do Pedro (P1–P6) e os achados do `/review-all`. Fonte: backup de
19/10 (`pi-backup-20261019-033233.tar.gz`) + este repo. Nada foi executado no
Pi: ele está offline desde ~20/10.

## 1. O que roda hoje no Pi (retrato de 19/10)

**Pasta:** `~/investimentos_manual` (fora do Docker). Deploy por
`rsync` do desktop, que exclui `.git` — então o `.git` que ainda exista no
Pi é o de agosto (`feat/state-of-art-overhaul`) e **não diz qual código roda**.

**Código no Pi ≠ HEAD local.** Mesmo branch (`feat/consultor-upgrade`), mas o
Pi está atrás. Prova pelo schema do dump de 19/10 03:00 (lido só o schema):
tem `contribution_prompt.context_tokens` (commit `fbc175b`, 18/09) e **não tem**
`report.actions`, coluna que o backend cria no boot desde `c975bf9` (19/10
02:03). Então os 10 commits de `c975bf9` a `46fc73c` (relatórios como
documento, D45, D46, revisão semanal+maturidade numa etapa) **nunca rodaram no
Pi**; os 7 de 19/10 01:42–02:00 são incertos. O último push (`af5a9a3`, 18/09)
é o candidato mais provável; 17 commits locais nunca foram publicados.

**Units = repo, byte a byte.** Gerei as units com `scripts/install_systemd.sh`
(`FRONTEND_PORT=3001`, `HOME=~`) num diretório temporário e
comparei com as 25 `investimentos-*` do backup: **zero diferença**.

| Unit | Tipo | Estado em 19/10 | Detalhe |
|------|------|-----------------|---------|
| `investimentos-backend` | serviço | enabled | `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000` |
| `investimentos-frontend` | serviço | enabled | `next start --hostname 127.0.0.1 --port 3001` (sem pnpm) |
| `investimentos-bot` | serviço | **escrita, disabled** (D30) | `scripts/telegram_bot.py` |
| `-scheduled` | timer | enabled | 01:00 · `run_scheduled.py` (gasta Claude) |
| `-cadence` | timer | enabled | 01:45 · `check_cadence.py` (gasta Claude) |
| `-weekly` | timer | enabled | 02:10 · `weekly_review.py` (gasta Claude, gate 7 d) |
| `-backup` | timer | enabled | 03:00 · `backup_db.sh` |
| `-resume` | timer | enabled | a cada 15 min · `resume_pending.py` |
| `-prices` | timer | enabled | 00/06/12/18:15 · `refresh_prices.py` |
| `-insights` | timer | enabled | 09:07 · `daily_insights.py` |
| `-alerts` | timer | enabled | 11/15/19:05 · `check_alerts.py` |
| `-monthly` | timer | enabled | dias 1–2, 10:00 · `monthly_report.py` |
| `-snapshot` | timer | enabled | 18:45 · `daily_snapshot.py` |
| `-digest` | timer | enabled | dom 20:07 · `weekly_digest.py` |

São **11 timers**, não 13: os "13" do briefing = 11 timers + backend +
frontend (as 13 units habilitadas). Todos `Persistent=true`,
`RandomizedDelaySec=60`, `PATH` com `~/.local/node/bin` e `~/.local/bin`
(`claude`, `uvx`, Node de tarball).

**Rede:** `tailscale serve` `https://<host-do-pi>.<tailnet>.ts.net/` →
`127.0.0.1:3001` (raiz do tailnet). O Next reescreve `/api/*` para
`127.0.0.1:8000` (`BACKEND_ORIGIN`, assado no build). Nenhuma porta fora do
loopback. Sem container, sem crontab próprio (o crontab do Pi só tem o fit).

**Dados (tudo sob `storage/`, caminhos relativos ao projeto no código):**

| O quê | Perder dói? |
|-------|-------------|
| `portfolio.db` (+WAL) — carteira, ledgers, chat, ordens | **sim** |
| `chat_workspace/MEMORY.md` + `CLAUDE.md` + `session.json` + `inbox/` (fotos de recibo) | **sim** (memória do cliente) |
| `agent_workspace/` — repo git: `MEMORY.md`, `tools/`, `.mcp.agent.json`, `out/`, `notes/` | **sim** (memória do comitê) |
| `webpush/` — chave VAPID | **sim**: chave nova invalida todo aparelho inscrito |
| `*_state.json` (alerts, insights, notifications, weekly_review, bot, display) | médio (avisos repetidos) |
| `analysis_runs/` (locks + `transcripts/`) | baixo (flight recorder) |
| `aux_workspace/`, `classifier_workspace/` | nenhum (recriados) |
| `backups/` — 14 dumps diários | é o próprio backup |

`.env` (18 variáveis; nomes batem com `.env.example`, as faltantes têm default)
e o token do `claude` (`CLAUDE_CODE_OAUTH_TOKEN` no `.env`) também são estado.
O `fit-meal-worker` hoje **copia** esse token do nosso `.env` na instalação.

**Token compartilhado (combinado com `pi-fit`):** o token passa a morar em
`~/.config/claude-code/oauth.env` (chmod 600, gerido pelo `pi-ops`, no backup
de segredos) e entra por `EnvironmentFile=-` em todas as units (feito no
`install_systemd.sh`; o `-` deixa a unit subir sem o arquivo). Variável de
ambiente vence o `.env` no pydantic, então o `oauth.env` ganha; mesmo assim a
linha **sai** do nosso `.env` na migração, para não haver duas cópias.

**Furo de backup hoje:** o `pi-backup` de 19/10 leva só
`dumps/portfolio_20261019.db.gz` + o `.env`. **Memória do consultor, memória e
ferramentas do comitê e a chave VAPID não saem do Pi.** Se o SD morrer, o
cliente perde as duas memórias e precisa reinscrever o push em todo aparelho.

## 2. Como fica (decisões do Pedro aplicadas)

| Pergunta | Resposta | Onde está |
|---|---|---|
| P1 pasta | `~/apps/investimentos` | — |
| P2 bot do Telegram | sai: o app cobre todos os comandos (D47) | `install_systemd.sh` não escreve mais a unit e remove a antiga |
| P3 timers que gastam Claude | `Persistent=false` em `scheduled`, `cadence`, `weekly` | `install_systemd.sh` |
| P4 memória | `MemoryHigh=384M` no frontend (medido ~180 MB de RSS servindo todas as abas) | `install_systemd.sh` |
| P5 fotos de recibo no backup | não ajudam a memória do Claude (ver seção 6); ficam fora | `deploy/pi/backup.sh` |
| P6 deploy | por git, pelo `pi-guardiao`, no contrato da garrafeira | `deploy/pi/` |

```
~/apps/investimentos/            git clone do repo privado
├── app/ frontend/ scripts/ tests/ ...
├── .env  .venv/  frontend/node_modules/  frontend/.next/      (fora do git)
├── storage -> <HD>/investimentos   link simbólico para o HD (seção 3)
└── deploy/pi/
    ├── deploy.sh    pull --ff-only → install → check → troca o build → health; volta sozinho
    ├── install.sh   idempotente; units via scripts/install_systemd.sh
    ├── check.sh     ruff, pytest, eslint, tsc e build em frontend/.next-build
    ├── health.sh    saída 0 = backend, frontend, 11 timers e CLI claude ok
    ├── backup.sh    DIR: banco + memórias + chave VAPID + estado + .env
    └── README.md    portas, contratos, rollback
```

Diferenças em relação ao modelo da garrafeira (avisadas ao coordenador):
- **O código volta também quando `install`/`check` falham**, não só no
  `health`: o backend e os 11 timers rodam o Python direto do checkout, então
  uma revisão reprovada que ficasse no disco rodaria no próximo restart ou timer.
- **`check.sh` sai com 75 se uma análise do comitê estiver rodando** (lock
  global): o build e o restart não podem cruzar o pico de 1,1 GB nem matar um
  aporte disparado pela API.
- **`install.sh` recusa uma pasta sem `storage/portfolio.db`** (primeira vez:
  `--first-install`). Units apontando para a pasta errada sobem o app num banco
  novo e vazio, e o cliente passa a gravar nele.
- O gerador de units continua em `scripts/install_systemd.sh` (o `install.sh`
  só o chama): `CLAUDE.md` e docs apontam para ele, e mudá-lo de lugar fica para
  o commit da migração, junto com a troca de `~/investimentos_manual`.

O build ao lado (`NEXT_DIST_DIR=.next-build`) foi testado aqui: build renomeado
para `.next` serve páginas e assets com 200 (Next 16.1.6). O `next build`
reescreve o `tsconfig.json` para incluir `.next-build/types`; essa versão já
está commitada, senão todo check deixaria o checkout sujo.

## 3. Dados no HD

O código resolve todos os caminhos relativos a `storage/` (banco, workspaces do
comitê e do consultor, chave do push, estado dos jobs). Então **não precisa de
`DATA_DIR` no código**: `storage` vira link simbólico para a pasta do HD, e o
gerador põe em toda unit um `ExecStartPre` que confere o banco
(`<destino real de storage>/portfolio.db`; na primeira instalação, a pasta).
Se o HD não montar (o `pi-ops` monta com `nofail`), o backend e o frontend
tentam de novo a cada 5 s até o HD voltar, e o timer só pula aquela rodada.
Nunca sobem num ponto de montagem vazio do SD, onde o `init_db` criaria um
banco novo. `RequiresMountsFor` foi descartado: no systemd `--user` o gerente
não monta nada, e uma dependência que falhou não é tentada de novo.

O que continua no SD e escreve: `~/.claude/projects/` (sessões do CLI, uma
linha por turno). Se o `pi-ops` quiser tirar isso do cartão, é um link em nível
de máquina, não deste app.

## 4. O que sai

| Item | Onde | Ação |
|------|------|------|
| `investimentos-bot.service` | Pi | o `install.sh` desabilita e apaga (D47) |
| `telegram_bot.py`, `telegram_setup.py`, espelho em `telegram_service`, `docs/08-telegram.md` | repo | **feito** em `0dd0f09` (D47) |
| `scripts/install_cron.sh` | repo | **feito** na limpeza de 2026-11-02: systemd é o caminho, o crontab do Pi não tem nada dele |
| `.git` velho (agosto) | Pi | some com a pasta nova (clone limpo) |
| `storage/router_workspace/` | Pi | apagar: triagem por LLM morreu no D31/D37 |
| `storage/claude_session.json` | Pi, se existir | apagar: resíduo do Playwright antigo |
| `~/assay_backup_20260905_pre_reset/` | Pi | `~/attic/` |
| `.claude/skills/deploy/SKILL.md` (Vercel) | repo | apagar, já marcada obsoleta em `docs/13` |
| `~/investimentos_manual` em `CLAUDE.md`, `docs/09` e auto-memória (o antigo `acesso-remoto-pi.md` saiu do repo) | repo | trocar pelo caminho novo **no mesmo commit da migração** |
| §7 e §11 de `raspberry-pi.md` | docs do Pi | atualizar: bot ativo, branch, 8–10 timers |

## 5. Migração (fase 2, com o Pi online)

**Janela:** fora de 00:45–03:15 e sem aporte rodando.

1. **Religar sem o comitê disparar de dia.** O Pi volta com as units velhas
   (`Persistent=true`): `scheduled`, `cadence` e `weekly` disparam no boot (o
   weekly está vencido desde 18/10). Logo após o SSH:
   `systemctl --user stop investimentos-scheduled.timer investimentos-cadence.timer investimentos-weekly.timer`.
2. **Nada em voo:** `ls storage/analysis_runs/*.lock`, `curl -s
   127.0.0.1:8000/api/chat | jq .busy` = `false`, nenhuma mensagem `queued`.
3. **Parar:** `systemctl --user stop 'investimentos-*.timer' investimentos-backend investimentos-frontend`.
4. **Backup:** `cp -a ~/investimentos_manual/storage ~/attic/investimentos-storage-$(date +%F)`
   com tudo parado (banco sem escrita = cópia consistente) e `.env` junto.
5. **Clone:** `git clone <repo> ~/apps/investimentos` no branch combinado.
6. **Dados:** mover `~/investimentos_manual/storage` para o HD
   (`<HD>/investimentos`) e `ln -s <HD>/investimentos ~/apps/investimentos/storage`;
   `mv ~/investimentos_manual/.env ~/apps/investimentos/`. Tirar
   `CLAUDE_CODE_OAUTH_TOKEN` do `.env` quando o `pi-ops` criar
   `~/.config/claude-code/oauth.env` (combinado com `pi-fit`).
7. **Sessões do Claude:** o CLI guarda sessões por caminho real do cwd. Copiar
   `~/.claude/projects/-home-<usuario>-investimentos-manual-storage-<ws>` para o
   nome codificado do caminho novo (o real, no HD) de `agent-workspace` e
   `chat-workspace`. Sem isso o `--resume` dá `SessionNotFoundError`: o chat
   recomeça a sessão (a memória fica, A35) e um aporte pela metade recomeça do zero.
8. **Trust:** marcar `hasTrustDialogAccepted` em `~/.claude.json` para os
   caminhos novos de `agent_workspace`, `chat_workspace`, `aux_workspace` e
   `classifier_workspace`. Foi isso que travou o motor em 05/09 (`docs/13`).
   Venvs que o agente criou em `storage/agent_workspace/tools/` quebram com a
   mudança de caminho: `find storage -name pyvenv.cfg` e recriar.
9. **Subir:** `deploy/pi/install.sh` e depois `deploy/pi/deploy.sh` (primeiro
   build). `tailscale serve` não muda (`/ → 127.0.0.1:3001`).
10. **Backup diário:** o `pi-ops` passa a chamar `deploy/pi/backup.sh <dir>`.

**Verificar:** `deploy/pi/health.sh` = `ok`; a raiz do tailnet abre no iPhone;
"oi" no `/consultor` responde (prova CLI, trust e token); push de teste em
`/configuracoes` chega (prova a chave VAPID); `deploy/pi/backup.sh /tmp/t`.

**Rollback:** parar as units novas, `rm ~/apps/investimentos/storage` (é só o
link), devolver a pasta do HD para `~/investimentos_manual/storage` e o `.env`,
e rodar `bash ~/investimentos_manual/scripts/install_systemd.sh` de lá. As
cópias do passo 7 ficam nos dois nomes, então nenhuma sessão se perde.

## 6. Economia de tokens (P5)

Medido no dump de 19/10 (só agregados): **revisão semanal** n=4, mediana US$ 3,87;
**chat opus** n=26, mediana US$ 0,65, p90 1,65, US$ 22 em setembro; depois do
D42 a mediana do chat caiu de 0,79 para 0,58. **Nenhum aporte** no período, então
o custo por etapa do comitê não tem medição.

Já feito e não reproposto: D42 (rotação por tamanho, anexo vira texto fora da
conversa, consultor em effort medium), D43 (CLAUDE.md de dev fora, snapshot de
git desligado, rotação por pausa), D46 (semanal e maturidade numa etapa).

Proposta, em ordem:
1. **Conferir versão e modelo do CLI no Pi** (`claude update`; `claude -p hi
   --output-format json` mostra o modelo). O alias `opus` aponta hoje para o
   Opus 5.5, mais barato que o Opus 5 usado nas contas do D46 (leitura de cache
   0,20 contra 0,50/M; output 20 contra 25/M). Ganho mínimo estimado ~20%: cerca
   de US$ 3/mês na semanal e US$ 3/mês no chat. E fixar
   `CLAUDE_CODE_PROMPT_CACHE_TTL=1h`: fora da cota do plano o CLI cai para TTL de
   5 min, e a rotação por pausa do D43 assume 1h.
2. **Comitê num processo só** (`--input-format stream-json`; `--resume` só como
   reserva), o próximo passo que o D46 já apontou: cada um dos 5 resumes reescreve
   100–250k tokens de cache em vez de ler. Estimativa US$ 4–12 por aporte, ainda
   sem medição. Mexe no motor de retomada; precisa de um aporte real de teste.

Descartados: context editing e memory tool (só na API crua, não no CLI com a
assinatura); auto-compact (o chat já rotaciona com resumo próprio).

Fontes: code.claude.com/docs (cli-reference, model-config, prompt-caching,
env-vars) e platform.claude.com/docs (pricing, context-editing, memory-tool),
lidas em 2026-11-02.

**Fotos de recibo e a memória do Claude:** não ajudam. `_expand_attachments`
troca o anexo pela transcrição, que fica em cache em `inbox/.transcripts/`; o
consultor só reabre o original quando a transcrição vem `[ilegível]`, e as
ordens dele permitem apagar arquivos com mais de 30 dias. O comitê nunca lê o
inbox. O que dura é o lançamento no banco (que tem backup) e o `MEMORY.md`. Foto
no backup serve de comprovante para o cliente, não de memória para o Claude.

## 7. Riscos

1. **Religada:** ver passo 1 da migração. Também roda o relatório mensal de
   outubro e o resume a cada 15 min, que são baratos.
2. **Token do `claude` pode ter sido revogado** nesses dias (aconteceu em
   28/08): o consultor e o comitê morrem calados. Primeiro teste: "oi" no consultor.
3. **Se o Pi não voltar:** restaurar = repo + `.env` e dump de 19/10 do
   desktop. As duas memórias se perdem (o backup antigo não as levava).
4. **Deploy:** o restart do backend corta um turno do chat em andamento; o
   `reconcile_orphan_turns` devolve o turno à fila no boot, então nada se perde.
5. **RAM:** 3,7 GB para casa + fit + garrafeira + nós. O `check.sh` (pytest +
   build) não cruza com o comitê, mas pode cruzar com o build de outro app.
6. **Porta 3000** é do site da casa; nós ficamos na 3001.
7. **Firewall:** o acesso pelo tailnet depende da regra `iifname "tailscale0"
   accept` do `panel-guard`. Se o firewall migrar para o `pi-ops`, essa regra
   vai junto.
8. **Guarda do HD** (`ExecStartPre` que confere o banco) passou no
   `systemd-analyze verify` e num teste com a pasta ausente, mas não no Pi:
   confirmar com o HD desligado que o backend fica tentando e volta sozinho.

## 8. Achados da revisão (corrigidos neste branch)

- **A43:** a suíte de testes abria o banco real; no Pi, o `check.sh` mandaria
  push de teste para o celular do cliente. `conftest.py` isola o banco.
- **A42:** `backup_db.sh` caía para `cp` sem o CLI `sqlite3` e perdia o que
  estava no WAL. Usa a API de backup online pelo Python do `.venv`.
- `install_systemd.sh` voltava o frontend para a porta 3000 (a do site da
  casa) se rodado sem `FRONTEND_PORT`. O padrão agora é 3001.
- `docs/09-operacao.md` descrevia 8 timers em horários antigos e um rsync sem
  `--delete`.
