## Code Style Rules

### TypeScript / JavaScript
- TypeScript strict mode — no `any`, no `@ts-ignore`
- Named exports only — never `export default`
- `const`/`let` only — never `var`
- Arrow functions for callbacks, `function` declarations for top-level
- `async`/`await` — never raw `.then()` chains
- Destructure props and imports
- Prefer early returns over nested conditionals

### Python
- Type hints on all function signatures
- Pydantic models for request/response schemas
- `async def` for all route handlers
- f-strings for string formatting
- Docstrings only on public API functions (not internal helpers)

### Naming
- TypeScript: camelCase variables, PascalCase components/types, UPPER_SNAKE_CASE constants
- Python: snake_case everywhere, PascalCase for classes
- Files: kebab-case (TS), snake_case (Python)
- Be descriptive — avoid single-letter variables except in lambdas/comprehensions

### Imports
- Group: stdlib → third-party → local (blank line between groups)
- Absolute imports only in Python
- Path aliases (`@/`) in TypeScript
