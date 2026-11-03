#!/usr/bin/env bash
# Usage: backup.sh <dir>. Leaves in <dir> everything that exists only on the Pi:
# a consistent DB copy, the agents' memory and tools, the Web Push key, the
# job state files and the .env. pi-ops calls it and ships <dir> off the SD card.
set -euo pipefail

OUT="${1:?uso: backup.sh <dir>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
mkdir -p "$OUT"

# Online backup API, never cp: the DB runs in WAL (A42).
"${ROOT}/.venv/bin/python" -c 'import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
dst.close(); src.close()' "${ROOT}/storage/portfolio.db" "${OUT}/portfolio.db"
gzip -f "${OUT}/portfolio.db"

# Memory of the consultant and the committee, the agent's tools and the VAPID
# key (a new key orphans every subscribed phone). Left out on purpose: run
# outputs and transcripts (regenerable logs), receipt photos (already
# transcribed into the ledger; personal data in one more place) and venvs.
cd "${ROOT}/storage"
shopt -s nullglob
state=(agent_workspace chat_workspace webpush ./*_state.json)
# Exit 1 from GNU tar = a file changed while read (an agent writing its
# memory): the archive is still usable, so only 2+ fails the backup.
tar czf "${OUT}/storage-state.tgz" --ignore-failed-read \
  --exclude 'agent_workspace/out' --exclude 'chat_workspace/inbox' --exclude '.venv' \
  "${state[@]}" || [ $? -eq 1 ]

cp "${ROOT}/.env" "${OUT}/env"
chmod 600 "${OUT}/portfolio.db.gz" "${OUT}/storage-state.tgz" "${OUT}/env"
echo "backup: ok em ${OUT}"
