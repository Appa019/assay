#!/usr/bin/env bash
# Install systemd USER units for the whole system (preferred over cron):
#   services : backend (uvicorn) + telegram bot — Restart=always
#   timers   : maturidade · revisão semanal · resume (15min) · preços (6h)
#              · snapshot diário · backup diário — all Persistent=true, so a
#              machine that was OFF at the scheduled time catches up on boot
#              (plain cron silently skips missed windows).
# Idempotent. Remove with --uninstall. Requires a systemd user session.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PROJECT_ROOT}/.venv/bin/python"
UNIT_DIR="${HOME}/.config/systemd/user"
PREFIX="investimentos"
# ~/.local/node/bin covers hosts where Node was installed from the tarball
# instead of a package manager (e.g. the Raspberry Pi); harmless when absent.
PATH_LINE="PATH=${HOME}/.local/node/bin:${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

if [[ "${1:-}" == "--uninstall" ]]; then
  systemctl --user disable --now "${PREFIX}-backend.service" "${PREFIX}-bot.service" \
    "${PREFIX}-frontend.service" 2>/dev/null || true
  for t in cadence weekly resume prices snapshot alerts monthly backup; do
    systemctl --user disable --now "${PREFIX}-${t}.timer" 2>/dev/null || true
  done
  rm -f "${UNIT_DIR}/${PREFIX}"-*.service "${UNIT_DIR}/${PREFIX}"-*.timer
  systemctl --user daemon-reload
  echo "Unidades systemd do Investimentos Manual removidas."
  exit 0
fi

if [[ ! -x "$PY" ]]; then
  echo "venv não encontrado em $PY — rode ./install.sh primeiro." >&2
  exit 1
fi
command -v systemctl >/dev/null 2>&1 || { echo "systemctl não encontrado." >&2; exit 1; }

mkdir -p "$UNIT_DIR" "${PROJECT_ROOT}/storage/logs"

long_service() { # long_service <name> <description> <command>
  cat > "${UNIT_DIR}/${PREFIX}-$1.service" <<UNIT
[Unit]
Description=$2

[Service]
WorkingDirectory=${PROJECT_ROOT}
Environment=${PATH_LINE}
Environment=PYTHONUNBUFFERED=1
ExecStart=$3
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
UNIT
}

oneshot_pair() { # oneshot_pair <name> <description> <command> <on_calendar>
  cat > "${UNIT_DIR}/${PREFIX}-$1.service" <<UNIT
[Unit]
Description=$2

[Service]
Type=oneshot
WorkingDirectory=${PROJECT_ROOT}
Environment=${PATH_LINE}
Environment=PYTHONUNBUFFERED=1
ExecStart=$3
UNIT
  cat > "${UNIT_DIR}/${PREFIX}-$1.timer" <<UNIT
[Unit]
Description=Timer: $2

[Timer]
OnCalendar=$4
Persistent=true
RandomizedDelaySec=60

[Install]
WantedBy=timers.target
UNIT
}

long_service backend "Investimentos Manual — backend FastAPI" \
  "${PROJECT_ROOT}/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000"
long_service bot "Investimentos Manual — bot do Telegram" \
  "${PY} ${PROJECT_ROOT}/scripts/telegram_bot.py"
# Serves the production build; bound to loopback so a shared LAN cannot reach it
# (put a TLS front like `tailscale serve` in front for remote access).
long_service frontend "Investimentos Manual — frontend Next.js" \
  "/usr/bin/env sh -c 'cd ${PROJECT_ROOT}/frontend && exec pnpm start --hostname 127.0.0.1 --port ${FRONTEND_PORT}'"

oneshot_pair cadence  "maturidade dos lotes"        "${PY} ${PROJECT_ROOT}/scripts/check_cadence.py"  "*-*-* 09:00"
oneshot_pair weekly   "revisão semanal do comitê"    "${PY} ${PROJECT_ROOT}/scripts/weekly_review.py"  "*-*-* 09:30"
oneshot_pair resume   "retomada de análises"         "${PY} ${PROJECT_ROOT}/scripts/resume_pending.py" "*:0/15"
oneshot_pair prices   "marcação a mercado"           "${PY} ${PROJECT_ROOT}/scripts/refresh_prices.py" "*-*-* 00/6:15"
oneshot_pair snapshot "snapshot diário da carteira"  "${PY} ${PROJECT_ROOT}/scripts/daily_snapshot.py" "*-*-* 18:45"
oneshot_pair alerts   "alertas de alvo/stop"         "${PY} ${PROJECT_ROOT}/scripts/check_alerts.py"   "*-*-* 11,15,19:05"
oneshot_pair monthly  "relatório mensal"             "${PY} ${PROJECT_ROOT}/scripts/monthly_report.py" "*-*-01,02 10:00"
oneshot_pair backup   "backup do SQLite"             "/usr/bin/env bash ${PROJECT_ROOT}/scripts/backup_db.sh" "*-*-* 03:00"

systemctl --user daemon-reload
systemctl --user enable --now "${PREFIX}-backend.service" "${PREFIX}-bot.service" \
  "${PREFIX}-frontend.service"
for t in cadence weekly resume prices snapshot alerts monthly backup; do
  systemctl --user enable --now "${PREFIX}-${t}.timer"
done

# Keep user services running after logout (ignore failure on odd setups).
loginctl enable-linger "$USER" 2>/dev/null || true

echo "Unidades instaladas e ativas. Úteis:"
echo "  systemctl --user status ${PREFIX}-backend ${PREFIX}-bot"
echo "  systemctl --user list-timers '${PREFIX}-*'"
echo "  journalctl --user -u ${PREFIX}-bot -f"
echo "Se usar systemd, remova os crons equivalentes: scripts/install_cron.sh --uninstall"
