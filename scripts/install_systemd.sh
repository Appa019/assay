#!/usr/bin/env bash
# Install systemd USER units for the whole system (preferred over cron):
#   services : backend (uvicorn) + frontend (Next) — Restart=always. No
#              Telegram bot unit: the client only uses the app (D30, D47), and
#              a leftover one from older installs is removed.
#   timers   : aportes agendados · maturidade · revisão semanal · resume
#              (15min) · preços (6h) · snapshot diário · alertas de alvo/stop
#              · relatório mensal · insights diários · digest semanal · backup
#              diário — 11 in all. Persistent=true, so a machine that was OFF
#              at the scheduled time catches up on boot (plain cron silently
#              skips missed windows), except the three that spend Claude
#              usage, which wait for the next night instead (see below).
# Idempotent. Remove with --uninstall. Requires a systemd user session.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PROJECT_ROOT}/.venv/bin/python"
UNIT_DIR="${HOME}/.config/systemd/user"
PREFIX="investimentos"
# ~/.local/node/bin covers hosts where Node was installed from the tarball
# instead of a package manager (e.g. the Raspberry Pi); harmless when absent.
PATH_LINE="PATH=${HOME}/.local/node/bin:${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin"
# 3001: on the Pi (the only production host) 3000 belongs to the house site.
FRONTEND_PORT="${FRONTEND_PORT:-3001}"

if [[ "${1:-}" == "--uninstall" ]]; then
  systemctl --user disable --now "${PREFIX}-backend.service" "${PREFIX}-bot.service" \
    "${PREFIX}-frontend.service" 2>/dev/null || true
  for t in scheduled cadence weekly resume prices snapshot alerts monthly insights digest backup; do
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
# storage/ may be a symlink to the external disk (pi-ops mounts it with nofail).
# Without the disk the app would start on the empty mount point on the SD card
# and init_db would create a fresh database. RequiresMountsFor= does not help in
# a --user unit (the user manager cannot start system mounts, and a failed
# dependency is never retried), so every unit checks for the data itself before
# starting: long services keep retrying until the disk is back, a timer just
# skips that round. Guard on the database when it exists (an empty mount point
# still passes a directory test), else on the folder (first install).
DATA_DIR="$(readlink -f "${PROJECT_ROOT}/storage")"
GUARD_PATH="${DATA_DIR}"
[ -f "${DATA_DIR}/portfolio.db" ] && GUARD_PATH="${DATA_DIR}/portfolio.db"
if [ "${GUARD_PATH}" = "${DATA_DIR}" ]; then
  echo "AVISO: sem portfolio.db, as units conferem só a pasta ${DATA_DIR}." >&2
  echo "       Rode este instalador de novo depois do primeiro boot do backend." >&2
fi
# The Claude token shared with the other Pi apps lives here (pi-ops creates it);
# "-" = optional, so the desktop and an old .env that still carries it keep working.
TOKEN_LINE="EnvironmentFile=-%h/.config/claude-code/oauth.env"
GUARD_LINE="ExecStartPre=/bin/sh -c 'test -e \"${GUARD_PATH}\" || { echo \"${GUARD_PATH} ausente: o HD está montado?\" >&2; exit 1; }'"

long_service() { # long_service <name> <description> <command> [extra [Service] line]
  local extra="${4:+$'\n'$4}"
  cat > "${UNIT_DIR}/${PREFIX}-$1.service" <<UNIT
[Unit]
Description=$2
# Retry forever: the guard below fails until the disk is back.
StartLimitIntervalSec=0

[Service]
WorkingDirectory=${PROJECT_ROOT}
Environment=${PATH_LINE}
Environment=PYTHONUNBUFFERED=1
${TOKEN_LINE}
${GUARD_LINE}
ExecStart=$3${extra}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
UNIT
}

oneshot_pair() { # oneshot_pair <name> <description> <command> <on_calendar> [persistent]
  cat > "${UNIT_DIR}/${PREFIX}-$1.service" <<UNIT
[Unit]
Description=$2

[Service]
Type=oneshot
WorkingDirectory=${PROJECT_ROOT}
Environment=${PATH_LINE}
Environment=PYTHONUNBUFFERED=1
${TOKEN_LINE}
${GUARD_LINE}
ExecStart=$3
UNIT
  cat > "${UNIT_DIR}/${PREFIX}-$1.timer" <<UNIT
[Unit]
Description=Timer: $2

[Timer]
OnCalendar=$4
Persistent=${5:-true}
RandomizedDelaySec=60

[Install]
WantedBy=timers.target
UNIT
}

# python -m survives a project-dir rename; the uvicorn entry-point script
# hardcodes its creation path in the shebang and dies with exit 127 after one.
long_service backend "Investimentos Manual — backend FastAPI" \
  "${PROJECT_ROOT}/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
# Serves the production build; bound to loopback so a shared LAN cannot reach it
# (put a TLS front like `tailscale serve` in front for remote access).
#
# Invokes next directly rather than through `pnpm start`: pnpm is itself a Node
# process that stays resident just to spawn another one, and on a 4 GB Pi that
# wrapper costs ~110 MB for nothing.
#
# MemoryHigh: next-server measured ~180 MB RSS after serving every tab. Past
# twice that the kernel reclaims and throttles it instead of letting it crowd
# the committee (1.1 GB peak) on a 3.7 GB Pi. High, not Max: nothing is killed.
long_service frontend "Investimentos Manual — frontend Next.js" \
  "/usr/bin/env sh -c 'cd ${PROJECT_ROOT}/frontend && exec node_modules/.bin/next start --hostname 127.0.0.1 --port ${FRONTEND_PORT}'" \
  "MemoryHigh=384M"

# The three jobs below are the only scheduled ones that spend Claude usage, and
# the plan's limit is a window (~5h) shared with the consultant chat.
#
# THE RULE: nothing may START later than (client's work start) minus 5 hours.
# He starts at 08:00, so nothing after 03:00 — a job begun at 04:30 leaves its
# window open past 09:30, and he would sit down inside a window the committee
# already drained. Times below leave ~50 min of slack on top of that.
#
# Ordered longest-first: the aporte can run 90 min and holds the global heavy
# lock, so the two short jobs follow it. On a night when all three land (rare —
# the aporte is ad-hoc and the weekly is 7-day gated), the short ones defer to
# the next night, which is harmless and already handled.
#
# Persistent=false on these three ONLY: catching up a missed night at boot
# would start the committee in the middle of the day, which THE RULE forbids.
# A missed night waits for the next one: the scheduled aporte stays scheduled,
# the weekly stays due, a matured lot stays pending.
oneshot_pair scheduled "aportes agendados"          "${PY} ${PROJECT_ROOT}/scripts/run_scheduled.py"  "*-*-* 01:00" false
oneshot_pair cadence  "maturidade dos lotes"        "${PY} ${PROJECT_ROOT}/scripts/check_cadence.py"  "*-*-* 01:45" false
oneshot_pair weekly   "revisão semanal do comitê"    "${PY} ${PROJECT_ROOT}/scripts/weekly_review.py"  "*-*-* 02:10" false
oneshot_pair resume   "retomada de análises"         "${PY} ${PROJECT_ROOT}/scripts/resume_pending.py" "*:0/15"
oneshot_pair prices   "marcação a mercado"           "${PY} ${PROJECT_ROOT}/scripts/refresh_prices.py" "*-*-* 00/6:15"
oneshot_pair snapshot "snapshot diário da carteira"  "${PY} ${PROJECT_ROOT}/scripts/daily_snapshot.py" "*-*-* 18:45"
oneshot_pair alerts   "alertas de alvo/stop"         "${PY} ${PROJECT_ROOT}/scripts/check_alerts.py"   "*-*-* 11,15,19:05"
oneshot_pair monthly  "relatório mensal"             "${PY} ${PROJECT_ROOT}/scripts/monthly_report.py" "*-*-01,02 10:00"
# 09:07 by design: insights must never ping during the night (quiet hours).
oneshot_pair insights "insights do ledger pessoal"   "${PY} ${PROJECT_ROOT}/scripts/daily_insights.py" "*-*-* 09:07"
oneshot_pair digest   "digest financeiro semanal"    "${PY} ${PROJECT_ROOT}/scripts/weekly_digest.py"  "Sun *-*-* 20:07"
oneshot_pair backup   "backup do SQLite"             "/usr/bin/env bash ${PROJECT_ROOT}/scripts/backup_db.sh" "*-*-* 03:00"

# Older installs wrote a (disabled) bot unit; converge to "no bot" (D47).
systemctl --user disable --now "${PREFIX}-bot.service" 2>/dev/null || true
rm -f "${UNIT_DIR}/${PREFIX}-bot.service"

systemctl --user daemon-reload
systemctl --user enable --now "${PREFIX}-backend.service" "${PREFIX}-frontend.service"
# `scheduled` belongs in this loop: since D38 a contribution asked for during
# the day is parked for the 01:00 window, so leaving its timer out meant the
# client could ask for an aporte and nothing would ever run it.
for t in scheduled cadence weekly resume prices snapshot alerts monthly insights digest backup; do
  systemctl --user enable --now "${PREFIX}-${t}.timer"
done

# Keep user services running after logout (ignore failure on odd setups).
loginctl enable-linger "$USER" 2>/dev/null || true

echo "Unidades instaladas e ativas. Úteis:"
echo "  systemctl --user status ${PREFIX}-backend ${PREFIX}-frontend"
echo "  systemctl --user list-timers '${PREFIX}-*'"
echo "  journalctl --user -u ${PREFIX}-backend -f"
