#!/usr/bin/env bash
# Install cron jobs for the autonomous agent:
#   - check_cadence.py   : per-lot maturity reviews (daily)
#   - weekly_review.py   : weekly committee review (daily, self-gated to 7 days)
#   - resume_pending.py  : resume interrupted analyses (every 15 min)
# Idempotent: re-running replaces the previous entries. Remove with --uninstall.
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

mkdir -p "${PROJECT_ROOT}/storage/logs"

CADENCE="0 ${HOUR} * * * cd '${PROJECT_ROOT}' && '${PY}' scripts/check_cadence.py >> '${PROJECT_ROOT}/storage/logs/cadence.log' 2>&1 # ${MARKER}"
WEEKLY="30 ${HOUR} * * * cd '${PROJECT_ROOT}' && '${PY}' scripts/weekly_review.py >> '${PROJECT_ROOT}/storage/logs/weekly.log' 2>&1 # ${MARKER}"
RESUME="*/15 * * * * cd '${PROJECT_ROOT}' && '${PY}' scripts/resume_pending.py >> '${PROJECT_ROOT}/storage/logs/resume.log' 2>&1 # ${MARKER}"

# Drop any previous entries, then append the fresh ones.
( crontab -l 2>/dev/null | grep -v "$MARKER" || true; echo "$CADENCE"; echo "$WEEKLY"; echo "$RESUME" ) | crontab -

echo "Crons instalados:"
echo "  · check_cadence.py   → maturidade dos lotes (diário ~${HOUR}h)"
echo "  · weekly_review.py   → revisão semanal (diário, dispara a cada 7 dias)"
echo "  · resume_pending.py  → retoma análises interrompidas (a cada 15 min)"
echo "Ver: crontab -l   ·   Remover: scripts/install_cron.sh --uninstall"
