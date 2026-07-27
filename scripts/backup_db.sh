#!/usr/bin/env bash
# Daily SQLite backup with rotation. Uses sqlite3 .backup (safe under WAL,
# consistent even while the API/bot are writing); falls back to cp.
# Keeps the last 14 daily backups.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="${PROJECT_ROOT}/storage/portfolio.db"
BACKUP_DIR="${PROJECT_ROOT}/storage/backups"
KEEP=14

[ -f "$DB" ] || { echo "sem banco em $DB — nada a fazer"; exit 0; }
mkdir -p "$BACKUP_DIR"

STAMP="$(date +%Y%m%d)"
TARGET="${BACKUP_DIR}/portfolio_${STAMP}.db"

if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$DB" ".backup '${TARGET}'"
else
  cp "$DB" "$TARGET"
fi
gzip -f "$TARGET"

# Rotate: keep the newest $KEEP backups.
ls -1t "${BACKUP_DIR}"/portfolio_*.db.gz 2>/dev/null | tail -n "+$((KEEP + 1))" | xargs -r rm -f

echo "backup ok: ${TARGET}.gz"
