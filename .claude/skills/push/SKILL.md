---
name: push
description: Full quality pipeline then commit and push to remote
disable-model-invocation: true
allowed-tools: Bash(make:*), Bash(git:*)
---
Run the full quality pipeline, commit, and push. Abort on any failure:

1. **Format**: `make format`
2. **Check**: `make check` (ruff, pytest, frontend lint + type-check + build) — abort on any failure
3. **Stage**: `git add` only changed files (never `git add -A`)
4. **Commit**: Conventional Commits format in English. NEVER mention Claude anywhere.
5. **Push**: `git push -u origin $(git branch --show-current)`

If any step fails, report the error clearly and stop. Do not skip steps.
