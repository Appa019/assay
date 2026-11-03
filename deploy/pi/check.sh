#!/usr/bin/env bash
# Quality gate before a deploy: dependencies, what CI runs (ruff, pytest, eslint,
# tsc), then a production build into frontend/.next-build, so the live .next is
# untouched. Runs on the Pi or a laptop. Exit 75 = a committee run is live, retry
# later; any other non-zero = this revision must not go live.
set -euo pipefail
cd "$(dirname "$0")/../.."
export PATH="$HOME/.local/node/bin:$HOME/.local/bin:$PATH"
PY=.venv/bin/python

[ -x "$PY" ] || python3 -m venv .venv
"$PY" -m pip install -q -r requirements.txt

# The build takes hundreds of MB and the deploy restarts the backend; neither
# may overlap a committee run (1.1 GB peak, holds the global lock throughout).
if "$PY" -c 'import sys
from app.services import analysis_runner as a
sys.exit(0 if a._lock_is_active(a._RUN_LOCK_DIR / a._GLOBAL_LOCK_NAME) else 1)'; then
  echo "check: análise do comitê rodando; tente de novo quando ela terminar" >&2
  exit 75
fi

"$PY" -m ruff check app scripts tests
"$PY" -m ruff format --check app scripts tests
"$PY" -m pytest -q -p no:cacheprovider

cd frontend
pnpm install --frozen-lockfile
pnpm run lint
pnpm run type-check
rm -rf .next-build && mkdir .next-build
# reusing the build cache cuts the Pi build time
if [ -d .next/cache ]; then cp -a .next/cache .next-build/; fi
# BACKEND_ORIGIN is baked into the /api rewrite at build time (next.config.ts)
NEXT_DIST_DIR=.next-build BACKEND_ORIGIN=http://127.0.0.1:8000 pnpm run build
echo "check: ok"
