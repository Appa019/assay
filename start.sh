#!/usr/bin/env bash
# Investimentos Manual — start backend + frontend + open browser

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
LOG_DIR="$PROJECT_DIR/storage/logs"
mkdir -p "$LOG_DIR"

color() { printf "\033[%sm%s\033[0m" "$1" "$2"; }
info() { echo "$(color 36 '[~]') $*"; }
ok()   { echo "$(color 32 '[+]') $*"; }
warn() { echo "$(color 33 '[!]') $*"; }
fail() { echo "$(color 31 '[x]') $*" >&2; exit 1; }

# ── 1. Pré-requisitos ─────────────────────────────────────────────
info "Verificando pré-requisitos"
command -v python3 >/dev/null 2>&1 || fail "python3 não encontrado"
command -v pnpm >/dev/null 2>&1 || fail "pnpm não encontrado (rode ./install.sh)"

# ── 2. Venv Python ───────────────────────────────────────────────
if [ ! -x ".venv/bin/python" ]; then
  info "Criando virtualenv .venv"
  python3 -m venv .venv
fi

if [ ! -f ".venv/.deps_installed" ] || [ requirements.txt -nt ".venv/.deps_installed" ]; then
  info "Instalando dependências Python"
  .venv/bin/pip install --upgrade pip -q
  .venv/bin/pip install -r requirements.txt -q
  touch .venv/.deps_installed
  ok "Dependências Python instaladas"
fi

# ── 3. Frontend deps ─────────────────────────────────────────────
if [ ! -d "frontend/node_modules" ]; then
  info "Instalando dependências do frontend"
  (cd frontend && pnpm install)
fi

# ── 4. Libera portas ─────────────────────────────────────────────
free_port() {
  local port=$1
  local pids
  pids="$(ss -ltnp 2>/dev/null | awk -v p=":$port" 'index($4,p){print $0}' | grep -oP 'pid=\K[0-9]+' | sort -u || true)"
  for pid in $pids; do
    warn "Encerrando processo na porta $port (pid $pid)"
    kill -9 "$pid" 2>/dev/null || true
  done
}
free_port "$BACKEND_PORT"
free_port "$FRONTEND_PORT"

# ── 5. Backend ───────────────────────────────────────────────────
info "Iniciando backend FastAPI na porta $BACKEND_PORT"
.venv/bin/uvicorn app.main:app \
  --host 127.0.0.1 \
  --port "$BACKEND_PORT" \
  --reload \
  > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID" > "$LOG_DIR/backend.pid"

for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
    ok "Backend pronto"
    break
  fi
  sleep 1
  if [ "$i" = "30" ]; then
    fail "Backend não respondeu em 30s. Veja $LOG_DIR/backend.log"
  fi
done

# ── 6. Frontend ──────────────────────────────────────────────────
info "Iniciando frontend Next.js na porta $FRONTEND_PORT"
(cd frontend && pnpm dev --port "$FRONTEND_PORT") \
  > "$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "$FRONTEND_PID" > "$LOG_DIR/frontend.pid"

for i in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:$FRONTEND_PORT" >/dev/null 2>&1; then
    ok "Frontend pronto"
    break
  fi
  sleep 1
  if [ "$i" = "90" ]; then
    warn "Frontend ainda compilando — veja $LOG_DIR/frontend.log"
    break
  fi
done

# ── 6.5 Telegram bot (opcional) ──────────────────────────────────
# Só sobe se TELEGRAM_CHAT_ID estiver preenchido no .env (rode
# scripts/telegram_setup.py uma vez para configurar).
BOT_PID=""
if [ -f .env ] && grep -qE '^TELEGRAM_CHAT_ID=.+' .env; then
  info "Iniciando bot do Telegram"
  .venv/bin/python scripts/telegram_bot.py > "$LOG_DIR/telegram_bot.log" 2>&1 &
  BOT_PID=$!
  echo "$BOT_PID" > "$LOG_DIR/telegram_bot.pid"
  ok "Bot do Telegram rodando"
else
  warn "Telegram não configurado — pulei o bot (rode scripts/telegram_setup.py)"
fi

# ── 7. Browser ───────────────────────────────────────────────────
URL="http://localhost:$FRONTEND_PORT"
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 &
fi

cat <<BANNER

╭───────────────────────────────────────────────╮
│  $(color 36 'INVESTIMENTOS MANUAL · RODANDO')              │
├───────────────────────────────────────────────┤
│  Frontend  → $URL          │
│  Backend   → http://localhost:$BACKEND_PORT/api/health   │
│  Logs      → $LOG_DIR/      │
│                                               │
│  Pressione $(color 31 'Ctrl+C') para encerrar           │
╰───────────────────────────────────────────────╯

BANNER

# ── 8. Cleanup ──────────────────────────────────────────────────
cleanup() {
  echo
  warn "Encerrando..."
  kill "$FRONTEND_PID" 2>/dev/null || true
  kill "$BACKEND_PID" 2>/dev/null || true
  [ -n "$BOT_PID" ] && kill "$BOT_PID" 2>/dev/null || true
  sleep 1
  kill -9 "$FRONTEND_PID" 2>/dev/null || true
  kill -9 "$BACKEND_PID" 2>/dev/null || true
  [ -n "$BOT_PID" ] && kill -9 "$BOT_PID" 2>/dev/null || true
  rm -f "$LOG_DIR/backend.pid" "$LOG_DIR/frontend.pid" "$LOG_DIR/telegram_bot.pid"
  ok "Tudo encerrado."
}
trap cleanup INT TERM EXIT

tail -F "$LOG_DIR/backend.log" "$LOG_DIR/frontend.log"
