#!/usr/bin/env bash
# Deploy on the Pi. The guardian runs it through `~/pi-ops/bin/deploy investimentos <sha>`,
# never by hand, so it runs in its own unit and one deploy at a time.
#   deploy.sh [sha]   fast-forward to sha (default origin/main), refresh units, test and
#                     build beside the live app, swap the build, restart, check
# Any failure puts the previous commit back: code, units, packages and build, restarted.
# Exit 75 from check.sh = a committee run is live: nothing restarts, the guardian retries.
set -euo pipefail
cd "$(dirname "$0")/../.."
export PATH="$HOME/.local/node/bin:$HOME/.local/bin:$PATH"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
# the backend reads its keys from .env; never go live without it
[ -f .env ] || { echo "erro: .env ausente em $PWD" >&2; exit 1; }

git fetch -q origin main
target="${1:-origin/main}"
# only the commit the guardian reviewed: one pushed after the review waits for the next deploy
git merge-base --is-ancestor "$target" origin/main ||
  { echo "erro: $target não está na origin/main" >&2; exit 1; }
before="$(git rev-parse HEAD)"
git merge -q --ff-only "$target"
after="$(git rev-parse HEAD)"
swapped=0

back_to_before() { # code, units and packages of the previous commit; no restart
  # a tracked file dirtied by the check (e.g. a lockfile) would make reset --keep refuse
  git checkout -q -- . &&
    git reset -q --keep "$before" ||
    echo "erro: não consegui voltar o git para ${before:0:7}" >&2
  # check.sh installs the new revision's packages into the live .venv and node_modules;
  # without this the previous code would restart on the new ones
  if ! git diff --quiet "$before" "$after" -- requirements.txt frontend/pnpm-lock.yaml; then
    .venv/bin/python -m pip install -q -r requirements.txt &&
      (cd frontend && pnpm install --frozen-lockfile) ||
      echo "erro: pacotes de ${before:0:7} não voltaram" >&2
  fi
  deploy/pi/install.sh || echo "erro: install.sh de ${before:0:7} falhou" >&2
}

fail() { # best effort, never stops half way: the previous commit rebuilt and running
  trap - TERM INT
  set +e
  back_to_before
  # check.sh builds into .next-build; the live .next only changes at the swap
  rm -rf frontend/.next-build
  if [ "$swapped" = 1 ] && [ -d frontend/.next-old ]; then
    rm -rf frontend/.next && mv frontend/.next-old frontend/.next
  fi
  systemctl --user restart investimentos-backend investimentos-frontend ||
    echo "erro: os serviços não reiniciaram em ${before:0:7}" >&2
  echo "erro: $1 em ${after:0:7}; voltou ${before:0:7}" >&2
  exit 1
}
trap 'fail "deploy interrompido"' TERM INT

deploy/pi/install.sh || fail "install.sh falhou"
set +e
deploy/pi/check.sh
rc=$?
set -e
if [ "$rc" = 75 ]; then
  # a committee run holds the global lock: restarting would kill it
  trap - TERM INT
  back_to_before
  rm -rf frontend/.next-build
  echo "agora não (check.sh saiu com 75: comitê rodando); nada reiniciou" >&2
  exit 75
elif [ "$rc" != 0 ]; then
  fail "check.sh saiu com $rc"
fi

rm -rf frontend/.next-old
if [ -d frontend/.next ]; then mv frontend/.next frontend/.next-old; fi
mv frontend/.next-build frontend/.next
swapped=1
systemctl --user restart investimentos-backend investimentos-frontend || fail "o restart falhou"
set +e
deploy/pi/health.sh # waits ~30 s for uvicorn and next by itself
rc=$?
set -e
# 2 = up but needs attention (a failed job, no claude CLI): a rollback fixes neither
if [ "$rc" != 0 ] && [ "$rc" != 2 ]; then
  fail "o app não ficou saudável (health.sh saiu com $rc)"
fi
trap - TERM INT
rm -rf frontend/.next-old
echo "ok: ${before:0:7} -> ${after:0:7}"
