---
name: push
description: Full quality pipeline then commit and push to remote
disable-model-invocation: true
allowed-tools: Bash(pnpm:*), Bash(ruff:*), Bash(pytest:*), Bash(git:*), Bash(npx prettier:*)
---
Run the full quality pipeline, commit, and push. Abort on any failure:

1. **Format**: `ruff format .` and `npx prettier --write "frontend/src/**/*.{ts,tsx,js,jsx,json,css}"`
2. **Lint Python**: `ruff check --fix .` — abort if unfixable errors
3. **Lint JS**: `pnpm run lint` — abort if errors
4. **Type-check**: `pnpm run type-check` — abort if TypeScript errors
5. **Tests**: `pytest -x -q` and `pnpm run test` — abort if failures
6. **Stage**: `git add` only changed files (never `git add -A`)
7. **Commit**: Conventional Commits format in English. NEVER mention Claude anywhere.
8. **Push**: `git push -u origin $(git branch --show-current)`

If any step fails, report the error clearly and stop. Do not skip steps.
