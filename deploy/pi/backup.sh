#!/usr/bin/env bash
# Usage: backup.sh <dir>. Leaves in <dir> everything that exists only on the Pi:
# a consistent DB copy, the agents' memory and tools, the Web Push key and the
# job state files. Writes nothing outside <dir>. The .env is not copied: pi-ops
# collects every secret itself (segredos/ in the snapshot).
set -euo pipefail

OUT="${1:?uso: backup.sh <dir>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DB="${ROOT}/storage/portfolio.db"
# Without the disk there is no database, and connecting would create an empty one.
[ -f "$DB" ] || { echo "backup: $DB ausente (o HD está montado?)" >&2; exit 1; }
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)" # the tar below runs from storage/

# Online backup API, never cp: the DB runs in WAL (A42). The source opens read-only.
"${ROOT}/.venv/bin/python" -c 'import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
dst.close(); src.close()' "$DB" "${OUT}/portfolio.db"
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

chmod 600 "${OUT}/portfolio.db.gz" "${OUT}/storage-state.tgz"
echo "backup: ok em ${OUT}"
