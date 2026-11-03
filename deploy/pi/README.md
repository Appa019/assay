# deploy/pi — investimentos (Assay)

Contrato com o Pi. Mesmos nomes e papéis dos outros apps, para o `pi-guardiao`.

| | |
|---|---|
| Pasta no Pi | `~/apps/investimentos` (git clone do repo privado) |
| Backend | uvicorn em `127.0.0.1:8000`, só interno |
| Frontend | Next em `127.0.0.1:3001` (a 3000 é do site da casa) |
| Tailnet | `https://<host-do-pi>.<tailnet>.ts.net/` → `127.0.0.1:3001` (raiz, `:443`) |
| Units | `investimentos-backend`, `investimentos-frontend` + 11 timers (`systemctl --user list-timers 'investimentos-*'`) |
| Dados | `storage/` e `.env`, fora do git |

## Scripts

- `deploy.sh`: `git pull --ff-only` → `install.sh` → `check.sh` → troca o build
  e reinicia backend + frontend → `health.sh`. Se `install`/`check` falhar, o
  código volta ao commit anterior (o backend e os timers rodam o Python direto do
  checkout). Se o `health` falhar, voltam código e build. Saída 75 = comitê
  rodando, tente depois.
- `install.sh`: idempotente. Gera e habilita as units via
  `scripts/install_systemd.sh` (fonte única dos horários). Recusa uma pasta sem
  `storage/portfolio.db`; primeira instalação: `--first-install`.
- `check.sh`: deps, ruff, pytest, eslint, tsc e build em `frontend/.next-build`
  (o `.next` no ar não é tocado). Recusa (75) com análise do comitê rodando.
- `health.sh`: saída 0 = backend e frontend respondem, os dois serviços ativos,
  11 timers carregados e o CLI `claude` no PATH. Job agendado em falha só gera
  aviso: cada job já avisa no app, e a falha pode ser anterior ao deploy.
- `backup.sh DIR`: banco (API de backup online, nunca `cp`, A42), memórias do
  consultor e do comitê, ferramentas do agente, chave VAPID do push, arquivos de
  estado dos jobs e `.env`. Fica de fora: saídas e transcripts de runs, fotos de
  recibo e venvs.

## Rollback

`deploy.sh` volta sozinho. À mão: `git reset --keep <sha anterior>`, depois
`deploy/pi/check.sh` e `mv frontend/.next-build frontend/.next` (ou o
`frontend/.next-old` que ainda existir), e `systemctl --user restart
investimentos-backend investimentos-frontend`. Dados: parar os serviços, pôr
`storage/backups/portfolio_<dia>.db.gz` descomprimido no lugar de
`storage/portfolio.db`, apagar `-wal`/`-shm` e subir.

## Antes de qualquer deploy

- Nenhum aporte rodando (o `check.sh` confere o lock global) e fora da janela
  01:00–03:15, quando rodam os jobs que gastam Claude.
- Um restart do backend no meio de um turno do consultor não perde a mensagem:
  `reconcile_orphan_turns` devolve o turno à fila no boot.
