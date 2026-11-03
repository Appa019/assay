#!/usr/bin/env bash
# Stop hook: a turn that leaves uncommitted code must leave it passing `make lint test`.
# Exit 2 hands the failure back to the agent to fix. The production build stays with check.sh
# and CI: it is slow and fails in worktrees whose node_modules is a symlink.
set -uo pipefail
input="$(cat)"
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
# already continuing because of this hook: report once, never loop
if grep -Eq '"stop_hook_active"[[:space:]]*:[[:space:]]*true' <<<"$input"; then exit 0; fi
changed="$(git status --porcelain -- '*.py' '*.ts' '*.tsx' '*.js' '*.mjs' '*.css' 'pyproject.toml' 'requirements*.txt' 'frontend/package.json' 2>/dev/null)"
[ -n "$changed" ] || exit 0
if ! out="$(make lint test 2>&1)"; then
  printf 'make lint test falhou com mudanças não commitadas. Corrija antes de encerrar:\n%s\n' "$(tail -n 40 <<<"$out")" >&2
  exit 2
fi
exit 0
