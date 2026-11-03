# 09 · Operação e deploy

> ## ⚠️ Leia isto antes de qualquer coisa
> **O Raspberry Pi 4 é a única máquina de produção.** Desde 2026-07-28 o app
> roda exclusivamente nele (`pi`, `~/investimentos_manual`),
> sob systemd, 24/7. **O desktop é só onde se ESCREVE código.**

## Topologia

| Item | Valor |
|---|---|
| Host | `raspberrypi` · `<lan-ip>` · usuário `<usuario>` |
| Acesso remoto | `https://<host-do-pi>.<tailnet>.ts.net` — **VPN Tailscale privada**, nada exposto na internet. Só aparelhos logados na conta do Pedro enxergam |
| Backend | uvicorn em `127.0.0.1:8000` |
| Frontend | Next em `127.0.0.1:3001` (a 3000 é do painel de casa) |
| Publicação | `tailscale serve` (é o único que escuta fora do loopback) |
| Bônus no mesmo Pi | Home Assistant em `:8443`, painel de casa em `:3000` |

**Bind SEMPRE em `127.0.0.1`.** A LAN é compartilhada com o prédio inteiro;
`0.0.0.0` entrega as finanças do cliente aos vizinhos.

Detalhes de rede, SSH, firewall e túnel: **`acesso-remoto-pi.md`**.

## Comandos no Pi

```bash
ssh pi
export XDG_RUNTIME_DIR=/run/user/$(id -u)     # necessário via ssh não-interativo

systemctl --user status  investimentos-backend investimentos-frontend
systemctl --user restart investimentos-backend investimentos-frontend
systemctl --user list-timers 'investimentos-*'
journalctl --user -u investimentos-backend -f
sudo tailscale serve status                   # o que está publicado na VPN
```

## Deploy (desktop → Pi)

**Hoje: `rsync` (até a migração). Depois: `deploy/pi/deploy.sh`** — ver
[`pi-deploy.md`](pi-deploy.md) e [`deploy/pi/README.md`](../deploy/pi/README.md).
Enquanto a migração não acontece:

```bash
# --delete: o que saiu do repo tem que sair do Pi. Rode antes com -n -v.
rsync -a --delete --exclude '.venv' --exclude 'node_modules' --exclude '.next' \
  --exclude '__pycache__' --exclude '*.pyc' --exclude 'storage' \
  --exclude '.env' --exclude '.env.local' --exclude 'frontend/.env.local' \
  --exclude '.git' \
  ./ pi:~/investimentos_manual/

# no Pi:
cd ~/investimentos_manual/frontend && pnpm install && pnpm build
systemctl --user restart investimentos-backend investimentos-frontend
```

**O `.env` e o banco do Pi são a fonte da verdade e NÃO são sobrescritos.**

⚠️ `BACKEND_ORIGIN` precisa estar setado **na hora do `pnpm build`** — o rewrite
de `/api/*` é assado no build, não lido no start.

## systemd (preferido)

```bash
bash scripts/install_systemd.sh                         # instalar/atualizar (frontend na 3001)
bash scripts/install_systemd.sh --uninstall             # remover
```

Instala 2 serviços (`Restart=always`) + 11 timers. Os timers usam
`Persistent=true` (máquina desligada na hora agendada **recupera a janela no
boot**), menos `scheduled`, `cadence` e `weekly`, que são `Persistent=false`:
recuperar no boot rodaria o comitê no meio do dia. Uma unit de bot deixada por
instalação antiga é desligada e apagada. `loginctl enable-linger` mantém tudo
vivo após logout.

O `PATH` das units inclui `~/.local/node/bin` e `~/.local/bin` porque no Pi o
Node veio de tarball (fora do apt) e o `claude`/`uvx` moram em `~/.local/bin`.

O frontend roda `node_modules/.bin/next start` **direto**, sem `pnpm start`: o
pnpm é outro processo Node que fica residente só para gerar o filho, e num Pi de
4 GB esse wrapper custava ~110 MB à toa.

### Os 11 timers

Os três primeiros gastam Claude e ficam na madrugada (nada começa depois das
03:00, para não drenar a janela de uso que o consultor divide com eles).

| Unit | Quando | Script |
|---|---|---|
| `-scheduled` | 01:00 diário | `run_scheduled.py` |
| `-cadence` | 01:45 diário | `check_cadence.py` |
| `-weekly` | 02:10 diário (auto-gated a 7d) | `weekly_review.py` |
| `-backup` | 03:00 diário | `backup_db.sh` |
| `-resume` | a cada 15 min | `resume_pending.py` |
| `-prices` | a cada 6h (:15) | `refresh_prices.py` |
| `-insights` | 09:07 diário | `daily_insights.py` |
| `-alerts` | 11/15/19:05 | `check_alerts.py` |
| `-monthly` | dias 1–2, 10:00 | `monthly_report.py` |
| `-snapshot` | 18:45 diário | `daily_snapshot.py` |
| `-digest` | domingo 20:07 | `weekly_digest.py` |

## Desenvolvimento no desktop

```bash
./install.sh                       # setup inicial (venv, deps, atalho)
./start.sh                         # backend + frontend locais (START_RELOAD=1 p/ reload)
make dev                           # idem
make backend / make frontend       # separados
make check                         # o que a CI roda
```

Comandos manuais úteis:

```bash
.venv/bin/python scripts/run_analysis.py --amount 5000        # aporte + análise no terminal
.venv/bin/python scripts/run_analysis.py --contribution-id <uuid>   # re-rodar/retomar
.venv/bin/python scripts/run_analysis.py --amount 100 --model haiku --effort low   # teste barato
.venv/bin/python scripts/weekly_review.py --force
.venv/bin/python scripts/refresh_prices.py
.venv/bin/python scripts/daily_snapshot.py
.venv/bin/python scripts/resume_pending.py [--watch [s]]
bash scripts/backup_db.sh
```

## Backup

`backup_db.sh` usa a API de backup online do SQLite pelo Python do `.venv`
(consistente sob WAL, mesmo com API e timers escrevendo). Sem fallback para `cp`:
copiar um banco em WAL perde tudo que ainda não passou do `-wal` para o arquivo
principal. Mantém **14** backups diários em `storage/backups/`.

Para restaurar: pare os serviços, copie o backup por cima de
`storage/portfolio.db` (apague `-wal` e `-shm`), suba de novo.

---

## Runbook — o que fazer quando…

### "O aporte não terminou / travou"

1. `GET /api/contributions/{id}` — quantos prompts têm `response`?
2. `storage/analysis_runs/transcripts/<run_id>_stepNN_*.stdout.json` — o que a
   CLI devolveu de verdade (é o flight recorder).
3. `Contribution.notes` — a causa da falha foi apendada lá.
4. `Contribution.run_attempts` — se chegou a 5, o auto-resume desistiu; corrija
   a causa e re-dispare à mão.
5. `ls storage/analysis_runs/*.lock` — há um lock vivo? `_lock_is_active` valida
   pid + starttime. Um lock de processo morto é ignorado automaticamente.
6. Retomar: `.venv/bin/python scripts/run_analysis.py --contribution-id <uuid>`.

### "P&L está zerado / preço não atualiza"

`current_price` nasce igual a `avg_price`. Rode
`.venv/bin/python scripts/refresh_prices.py` ou `POST /api/portfolio/refresh` e
veja o retorno (é best-effort — conta quantos deram certo). Ticker de ação
precisa resolver no Yahoo (`.SA`); cripto precisa de CoinGecko-id válido.

### "database is locked"

Não deveria acontecer (WAL + `busy_timeout=5000`). Se acontecer, procure um
processo segurando transação longa. Nunca escreva no `.db` por fora — o
consultor tem ordem explícita de só **ler** o SQLite direto.

### "O frontend não acha a API"

`BACKEND_ORIGIN` não estava setado no build. Rebuilde. Confirme com
`curl -s localhost:3001/api/health`.

### "MCP do Playwright quebrou no Pi"

Chrome não tem ARM64. `_playwright_mcp_args()` já cai para o Chromium do
sistema — confirme que `chromium` ou `chromium-browser` existe no PATH.

### "RAM acabou"

O Pi tem 3,7 GB, com Home Assistant + 5 containers usando ~1,7 GB. Um run do
comitê com todos os MCPs mediu **pico de 1,1 GB**. Cabe, sem folga larga. Se
apertar: reduza MCPs no baseline ou evite rodar comitê e revisão juntos (o lock
global já impede isso).

### "Preciso ver o que o agente está fazendo agora"

```bash
journalctl --user -u investimentos-backend -f          # eventos do runner
ls -lt storage/analysis_runs/transcripts/ | head       # última invocação
cat storage/agent_workspace/MEMORY.md                  # o que o agente sabe
```

## Armadilhas específicas do Pi (já corrigidas — não regrida)

| Armadilha | Correção que já existe |
|---|---|
| Chrome não tem build ARM64 | `_playwright_mcp_args()` cai para Chromium do sistema |
| Porta 3000 é do painel de casa | frontend na 3001 (`FRONTEND_PORT=3001`) |
| Firewall `panel_guard` filtra 443/3000/3443/8123 por MAC; tráfego de VPN não tem cabeçalho ethernet | regra `iifname "tailscale0" accept` na chain `input` (vive em `~/<repo-automacao>/infra/panel-guard.nft`) |
| `rewrites` do Next é assado no build | setar `BACKEND_ORIGIN` antes do `pnpm build` |
| `pnpm start` desperdiça ~110 MB | unit chama `node_modules/.bin/next` direto |
| NTFS não preserva bit `+x` | `install.sh` recusa rodar em fuseblk/ntfs |
| RAM escassa | um run pesado por vez (lock global) |

## Pré-requisitos de runtime

- Python 3.11+ (o Pi roda 3.13.5; todas as deps têm wheel ARM64, zero compilação)
- Node 20.9+ com pnpm (o Pi roda Node 22 de tarball em `~/.local/node`)
- `claude` (Claude Code CLI) no PATH — `analysis_runner._claude_bin()` também
  procura em `~/.local/bin/claude`
- `uv`/`uvx` em `~/.local/bin` — 4 MCPs dependem dele
- Internet (BCB, Yahoo Finance, CoinGecko)
- Filesystem **ext4**
