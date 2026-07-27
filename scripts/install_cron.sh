#!/usr/bin/env bash
# Install cron jobs for the autonomous agent:
#   - check_cadence.py   : per-lot maturity reviews (daily)
#   - weekly_review.py   : weekly committee review (daily, self-gated to 7 days)
#   - resume_pending.py  : resume interrupted analyses (every 15 min)
#   - refresh_prices.py  : mark lots to market (every 6h)
#   - daily_snapshot.py  : equity-curve datapoint (daily, after market close)
#   - backup_db.sh       : SQLite backup with rotation (daily)
#   - log rotation       : trim cron logs monthly
# Idempotent: re-running replaces the previous entries. Remove with --uninstall.
#
# Every entry runs under flock so a slow run never stacks on top of itself,
# and PATH includes ~/.local/bin + node/uv shims so the headless Claude CLI
# and npx/uvx MCP servers work under cron's minimal environment.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PROJECT_ROOT}/.venv/bin/python"
MARKER="investimentos_manual_cron"
HOUR="${1:-9}"

if [[ "${1:-}" == "--uninstall" ]]; then
  crontab -l 2>/dev/null | grep -v "$MARKER" | crontab - || true
  echo "Crons do Investimentos Manual removidos."
  exit 0
fi

if [[ ! -x "$PY" ]]; then
  echo "venv não encontrado em $PY — rode ./install.sh primeiro." >&2
  exit 1
fi

LOGS="${PROJECT_ROOT}/storage/logs"
LOCKS="${PROJECT_ROOT}/storage/cron_locks"
mkdir -p "$LOGS" "$LOCKS"

CRON_PATH="PATH=${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin # ${MARKER}"

entry() { # entry <schedule> <lockname> <command> <logname>
  local sched="$1" lock="$2" cmd="$3" log="$4"
  echo "${sched} cd '${PROJECT_ROOT}' && flock -n '${LOCKS}/${lock}.lock' ${cmd} >> '${LOGS}/${log}.log' 2>&1 # ${MARKER}"
}

CADENCE="$(entry "0 ${HOUR} * * *"   cadence  "'${PY}' scripts/check_cadence.py"   cadence)"
WEEKLY="$(entry  "30 ${HOUR} * * *"  weekly   "'${PY}' scripts/weekly_review.py"   weekly)"
RESUME="$(entry  "*/15 * * * *"      resume   "'${PY}' scripts/resume_pending.py"  resume)"
PRICES="$(entry  "15 */6 * * *"      prices   "'${PY}' scripts/refresh_prices.py"  prices)"
SNAPSHOT="$(entry "45 18 * * *"      snapshot "'${PY}' scripts/daily_snapshot.py"  snapshot)"
ALERTS="$(entry  "5 11,15,19 * * *"  alerts   "'${PY}' scripts/check_alerts.py"    alerts)"
MONTHLY="$(entry "0 10 1,2 * *"      monthly  "'${PY}' scripts/monthly_report.py"  monthly)"
BACKUP="$(entry  "0 3 * * *"         backup   "bash scripts/backup_db.sh"          backup)"
LOGTRIM="0 4 1 * * find '${LOGS}' -name '*.log' -size +5M -exec truncate -s 1M {} \; # ${MARKER}"

# Drop any previous entries, then append the fresh ones.
(
  crontab -l 2>/dev/null | grep -v "$MARKER" || true
  echo "$CRON_PATH"
  echo "$CADENCE"
  echo "$WEEKLY"
  echo "$RESUME"
  echo "$PRICES"
  echo "$SNAPSHOT"
  echo "$ALERTS"
  echo "$MONTHLY"
  echo "$BACKUP"
  echo "$LOGTRIM"
) | crontab -

echo "Crons instalados:"
echo "  · check_cadence.py   → maturidade dos lotes (diário ~${HOUR}h)"
echo "  · weekly_review.py   → revisão semanal (diário, dispara a cada 7 dias)"
echo "  · resume_pending.py  → retoma análises interrompidas (a cada 15 min)"
echo "  · refresh_prices.py  → marcação a mercado (a cada 6h)"
echo "  · daily_snapshot.py  → curva de patrimônio (diário 18h45)"
echo "  · check_alerts.py    → alertas de alvo/stop do comitê (3x ao dia)"
echo "  · monthly_report.py  → relatório mensal consolidado (dias 1-2)"
echo "  · backup_db.sh       → backup do SQLite com rotação (diário 3h)"
echo "  · rotação de logs    → mensal"
echo "Ver: crontab -l   ·   Remover: scripts/install_cron.sh --uninstall"
echo
echo "Dica: para máquinas que ficam desligadas, prefira scripts/install_systemd.sh"
echo "(timers persistentes recuperam janelas perdidas ao ligar)."
