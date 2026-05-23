---
name: deploy
description: Deploy application to Vercel production after running full quality pipeline
disable-model-invocation: true
allowed-tools: Bash(pnpm:*), Bash(vercel:*), Bash(git:*), Bash(ruff:*), Bash(pytest:*)
---
Deploy the application to production. Follow these steps strictly — abort on any failure:

1. Run `ruff check .` — abort if Python lint errors
2. Run `pnpm run lint` — abort if ESLint errors
3. Run `pnpm run type-check` — abort if TypeScript errors
4. Run `pytest -x -q` — abort if test failures
5. Run `pnpm run build` — abort on build errors
6. Run `vercel deploy --prod`
7. Verify the deployment URL returns HTTP 200
8. Report: deployment URL, status, and any warnings from steps above
