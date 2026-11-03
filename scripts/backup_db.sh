#!/usr/bin/env bash
# Daily SQLite backup with rotation. Uses SQLite's online backup API through
# the project's own Python (safe under WAL, consistent while the API writes).
# No sqlite3-CLI dependency and no `cp` fallback: a plain copy of a WAL
# database misses every commit not yet checkpointed into the main file.
# Keeps the last 14 daily backups.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PROJECT_ROOT}/.venv/bin/python"
DB="${PROJECT_ROOT}/storage/portfolio.db"
BACKUP_DIR="${PROJECT_ROOT}/storage/backups"
KEEP=14

[ -f "$DB" ] || { echo "sem banco em $DB — nada a fazer"; exit 0; }
mkdir -p "$BACKUP_DIR"

STAMP="$(date +%Y%m%d)"
TARGET="${BACKUP_DIR}/portfolio_${STAMP}.db"

"$PY" -c 'import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
dst.close(); src.close()' "$DB" "$TARGET"
gzip -f "$TARGET"

# Rotate: keep the newest $KEEP backups.
ls -1t "${BACKUP_DIR}"/portfolio_*.db.gz 2>/dev/null | tail -n "+$((KEEP + 1))" | xargs -r rm -f

echo "backup ok: ${TARGET}.gz"
