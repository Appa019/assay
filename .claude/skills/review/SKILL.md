---
name: review
description: Code review profissional e criteriosa da codebase inteira
allowed-tools: Read, Grep, Glob, Bash(git diff:*), Bash(git log:*), Bash(git status), Bash(ruff:*), Bash(pnpm run lint), Bash(pnpm run type-check)
---
## Changed Files
!`git diff --name-only HEAD~1 2>/dev/null || git diff --name-only --cached`

## Detailed Changes
!`git diff HEAD~1 2>/dev/null || git diff --cached`

Perform a thorough code review:

1. **Read project memory first** — check `~/.claude/projects/-home-<usuario>-codigos-python-investimentos-manual/memory/project_errors.md` for known issues to watch for
2. **Security**: secrets exposure, injection vulnerabilities, input validation
3. **Performance**: N+1 queries, unnecessary re-renders, missing indexes
4. **Type safety**: any types, missing null checks, unsafe casts
5. **Error handling**: unhandled promises, missing try/catch at boundaries
6. **Test coverage**: untested paths, missing edge cases
7. **Patterns**: check against `project_patterns.md` for consistency
8. **Style**: naming quality, code duplication, unnecessary complexity

Organize findings by severity: CRITICAL > WARNING > SUGGESTION.
Be specific and actionable — include file paths and line numbers.
