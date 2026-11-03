#!/usr/bin/env bash
# Deploy on the Pi (run by pi-guardiao): pull, refresh units, test and build beside
# the live app, swap the build and restart (a few seconds offline), then health.sh.
# Any failure puts the code, its packages and (after the swap) the build back.
set -euo pipefail
cd "$(dirname "$0")/../.."
export PATH="$HOME/.local/node/bin:$HOME/.local/bin:$PATH"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
# the backend reads its Claude token and keys from .env; never go live without it
if [ ! -f .env ]; then
  echo "erro: .env ausente em $PWD" >&2
  exit 1
fi
before=$(git rev-parse HEAD)
git pull --ff-only
after=$(git rev-parse HEAD)

back_to_before() {
  git reset -q --keep "$before"
  # check.sh installs the new revision's packages into the live .venv and
  # node_modules; without this the old code would restart on the new ones.
  if ! git diff --quiet "$before" "$after" -- requirements.txt frontend/pnpm-lock.yaml; then
    .venv/bin/python -m pip install -q -r requirements.txt
    (cd frontend && pnpm install --frozen-lockfile)
  fi
  deploy/pi/install.sh
}

# The backend and every timer run Python straight from the checkout: a revision
# that fails its gate must not stay checked out, or the next restart runs it.
status=0
deploy/pi/install.sh && deploy/pi/check.sh || status=$?
if [ "$status" -ne 0 ]; then
  echo "erro: install/check falhou em ${after:0:7}; código volta para ${before:0:7}" >&2
  back_to_before
  exit "$status" # 75 = committee running, retry later
fi

rm -rf frontend/.next-old
if [ -d frontend/.next ]; then mv frontend/.next frontend/.next-old; fi
mv frontend/.next-build frontend/.next
systemctl --user restart investimentos-backend investimentos-frontend
health=0
deploy/pi/health.sh || health=$?
# 2 = up but needs attention (a failed job, no claude CLI): a rollback fixes neither
if [ "$health" -ne 0 ] && [ "$health" -ne 2 ]; then
  echo "erro: não ficou saudável em ${after:0:7}; voltando para ${before:0:7}" >&2
  back_to_before
  if [ -d frontend/.next-old ]; then rm -rf frontend/.next && mv frontend/.next-old frontend/.next; fi
  systemctl --user restart investimentos-backend investimentos-frontend
  exit 1
fi
rm -rf frontend/.next-old
echo "ok: ${before:0:7} -> ${after:0:7}"
