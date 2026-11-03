# investimentos (Assay) no Raspberry Pi

Contrato do pi-ops (`~/pi-ops/README.md`). Antes de cada deploy, o guardião lê
este arquivo junto com as regras gerais.

| | |
|---|---|
| Código | `~/apps/investimentos` (clone do repo privado) |
| Backend | uvicorn em `127.0.0.1:8000`, só interno |
| Frontend | Next em `127.0.0.1:3001` (a 3000 é do site da casa) |
| Tailnet | `https://<host-do-pi>.<tailnet>.ts.net/` → `127.0.0.1:3001` (`serve.tsv`, `:443`) |
| Dados | `/mnt/hd/investimentos`; `~/apps/investimentos/storage` é um link para lá |
| Segredos | `.env` na pasta do app; o token do `claude` em `~/.config/claude-code/oauth.env` |
| Units | `investimentos-backend`, `investimentos-frontend` + 11 timers (`systemctl --user list-timers 'investimentos-*'`) |

**Trava do HD:** toda unit tem um `ExecStartPre` que confere
`/mnt/hd/investimentos/portfolio.db` (só a pasta, se o banco ainda não existir
na instalação). Sem o HD, backend e frontend tentam de novo a cada 5 s até ele
voltar, e o timer pula aquela rodada. Nada sobe no cartão SD com banco vazio.

## Regras deste app

Recuse o diff que:

- faça qualquer serviço escutar fora de `127.0.0.1` (`--host`, `--hostname`);
- ligue `Persistent=true` nos timers `scheduled`, `cadence` ou `weekly`
  (`scripts/install_systemd.sh`): eles gastam o limite de uso do Claude, que é
  dividido com o chat do cliente, e não podem rodar de dia ao religar o Pi;
- encurte `MIN_HOLDING_DAYS` (30 dias, trava de venda de ações exigida pelo
  compliance do cliente) ou tire a trava de `portfolio_service.sell_asset`;
- tire do `check.sh` a saída 75 com o comitê rodando, ou do `install.sh` a
  recusa a uma pasta sem `storage/portfolio.db`;
- tire a guarda de `tests/conftest.py` (banco temporário, rede bloqueada e
  falha se algo aparecer em `storage/`): o `check.sh` roda a suíte na pasta de
  produção;
- comite `storage/`, `.env` ou o token;
- volte o bot do Telegram (D47).

Antes do deploy: fora da janela 01:00–03:15 (jobs que gastam Claude) e sem
aporte rodando (o `check.sh` confere o lock global e sai 75). Um restart no meio
de um turno do consultor não perde a mensagem: `reconcile_orphan_turns` a
devolve à fila no boot.

## Scripts

- `deploy.sh`: `git pull --ff-only` → `install.sh` → `check.sh` → troca o build
  e reinicia backend e frontend → `health.sh`. Se `install`/`check` falhar, o
  código volta ao commit anterior (o backend e os timers rodam o Python direto
  do checkout), junto com os pacotes do `.venv` e do `node_modules` se mudaram.
  Se o `health` sair 1, voltam também o build. Saída 75 = comitê rodando.
- `install.sh`: idempotente. Gera e habilita as units via
  `scripts/install_systemd.sh` (fonte única dos horários). Recusa uma pasta sem
  `storage/portfolio.db`; primeira instalação: `--first-install`.
- `check.sh`: deps, ruff, pytest, eslint, tsc e build em `frontend/.next-build`
  (o `.next` no ar não é tocado). Não toca `storage/` nem a rede.
- `health.sh`: 0 = backend e frontend respondem, os dois serviços ativos e 11
  timers carregados. 2 = alerta: job agendado em falha ou CLI `claude` fora do
  PATH (o site funciona; rollback não resolveria). 1 = fora do ar.
- `backup.sh DIR`: deixa em `DIR` o `portfolio.db.gz` (API de backup online,
  nunca `cp`, A42) e o `storage-state.tgz` (memórias do consultor e do comitê,
  ferramentas do agente, chave VAPID do push, arquivos de estado dos jobs).
  Fora: `.env` (o pi-backup leva em `segredos/`), saídas e transcripts de
  runs, fotos de recibo e venvs. Sem o banco, falha em vez de criar um vazio.

## Restaurar

A partir de `apps/investimentos/` de um snapshot do pi-backup (`SNAP` abaixo) e
com o código já em `~/apps/investimentos` (`instalar-app investimentos`):

1. Parar tudo:
   `systemctl --user stop 'investimentos-*.timer' investimentos-backend investimentos-frontend`
2. Dados, com o HD montado:
   ```sh
   mkdir -p /mnt/hd/investimentos
   ln -sfn /mnt/hd/investimentos ~/apps/investimentos/storage
   cd /mnt/hd/investimentos
   rm -f portfolio.db-wal portfolio.db-shm
   gunzip -c "$SNAP/portfolio.db.gz" > portfolio.db
   tar xzf "$SNAP/storage-state.tgz"
   ```
3. Segredos: `.env` de `segredos/investimentos/` do snapshot para
   `~/apps/investimentos/.env` (chmod 600); `oauth.env` já é do pi-ops.
4. Conferir o banco: `~/apps/investimentos/.venv/bin/python -c "import sqlite3;
   print(sqlite3.connect('portfolio.db').execute('pragma integrity_check').fetchone()[0])"`
   tem que imprimir `ok`.
5. Subir: `~/apps/investimentos/deploy/pi/install.sh` (religa os serviços e os
   timers) e `deploy/pi/health.sh`.

Depois: o push precisa de reinscrição só se a chave VAPID não veio no
`storage-state.tgz`; o chat abre sessão nova (a memória do cliente volta).

## Rollback de código

`deploy.sh` volta sozinho. À mão: `git reset --keep <sha anterior>`, depois
`deploy/pi/check.sh` e `mv frontend/.next-build frontend/.next`, e
`systemctl --user restart investimentos-backend investimentos-frontend`.
