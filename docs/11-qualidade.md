# 11 · Qualidade, testes e convenções

## O comando único

```bash
make check      # = lint + test + build. É exatamente o que a CI roda.
```

Desdobrado:

```bash
.venv/bin/ruff check app/ scripts/ tests/
.venv/bin/ruff format --check app/ scripts/ tests/
.venv/bin/python -m pytest
cd frontend && pnpm run lint && pnpm run type-check && pnpm run build
```

Auto-correção: `make format` (`ruff format` + `ruff check --fix`).

## CI (`.github/workflows/ci.yml`)

Roda em push para `main` e em todo PR. Dois jobs paralelos:

| Job | Passos |
|---|---|
| `backend` | Python 3.12 → `pip install -r requirements.txt` → `ruff check` → `ruff format --check` → `pytest` |
| `frontend` | pnpm 11 + Node 22 → `pnpm install --frozen-lockfile` → `lint` → `type-check` → `build` |

## Testes

Um arquivo `tests/test_<módulo>.py` por serviço ou router, mais `conftest.py`.
Config em `pyproject.toml`: `asyncio_mode = "auto"`, `pythonpath = ["."]`. O
número muda a cada PR, então não fica escrito aqui; para contar:

```bash
.venv/bin/python -m pytest --collect-only -q 2>/dev/null | tail -1
```

### Fixtures (`conftest.py`)

| Fixture | O que dá |
|---|---|
| `session` | SQLite em memória **com `PRAGMA foreign_keys=ON`** — espelha produção. Sem isso, um bug de ordenação de delete passou despercebido uma vez |
| `stock_locked` | lote de PETR4 de 5 dias atrás (dentro da trava de 30d) |
| `stock_unlocked` | lote de VALE3 de 45 dias atrás (liberado) |
| `crypto_locked` | lote de BTC de 5 dias atrás (dentro da trava de 7d) |
| `crypto_unlocked` | lote de ETH de 20 dias: livre como cripto, travado se fosse ação |
| `cdb` | lote de CDB (nunca trava) |
| `isolated_runner_dirs` | redireciona **todo** efeito de filesystem do `analysis_runner` para `tmp_path` e neutraliza `_sleep` (testes não dormem de verdade) |

### Como testar código que chama Claude

Nunca chame o subprocess de verdade. Faça monkeypatch de
`analysis_runner._run_claude_step` e devolva um `StepResult` montado à mão. Para
testar o encadeamento, use `isolated_runner_dirs` para que workspace, locks e
transcripts caiam em `tmp_path`.

## Convenções de código

### Python

- **Type hints em toda assinatura.**
- Pydantic nas fronteiras (request/response).
- `async def` em todo route handler.
- f-strings.
- Docstring só em API pública, não em helper interno.
- Imports agrupados: stdlib → terceiros → local, com linha em branco.
- **Imports absolutos** (`from app.services import ...`).
- `snake_case`; `PascalCase` para classe; arquivo em `snake_case`.
- Ruff: `line-length = 100`, regras `E,F,I,N,W,UP,B`, ignorando `E501`
  (formatter cuida) e `B008` (`Depends()` no default é o padrão do FastAPI).

### TypeScript

- **strict**, sem `any`, sem `@ts-ignore`.
- **Named exports** — default só onde o Next exige (page, layout).
- `const`/`let`, nunca `var`.
- Arrow function para componente e callback; `function` para top-level.
- `async`/`await`, nunca `.then()` cru.
- Destructure props e imports. Early return em vez de aninhar.
- `camelCase` / `PascalCase` / `UPPER_SNAKE_CASE`; arquivo em `kebab-case`.
- Path alias `@/`.

### Comentários

Comentários **em inglês**, mesmo com a UI e a documentação em pt-BR. O padrão do
repositório é comentário que explica **por quê**, não o quê — quase todo
comentário existente registra uma decisão ou uma armadilha ("4391 é o CDI mensal
e injetava 0,75 errado"). Mantenha esse nível; não polua com o óbvio.

## Git

- Commits em **inglês**, **Conventional Commits**: `feat:`, `fix:`, `chore:`,
  `refactor:`, `docs:`, `style:`, `perf:`, `test:`.
- **Atômicos** — uma mudança lógica por commit.
- ⚠️ **NUNCA mencione Claude** em mensagem de commit, no código ou como
  co-author. Sem exceção.
- Nunca comite `.env`, `storage/`, `node_modules/`, `.venv/`.
- Branch principal: `main`.

## Segurança

- Zero secret hardcoded. Tudo em `.env` via `Settings`.
- Valide toda entrada na fronteira (Pydantic no FastAPI, tipos no front).
- ORM parametrizado (SQLModel/SQLAlchemy) — sem SQL string montada à mão.
- React escapa sozinho; não use `dangerouslySetInnerHTML`.
- Sem dado sensível em URL ou log.
- **Não** reintroduza Supabase Auth/RLS: o app é single-user atrás de VPN.
  A seção de autenticação de `.claude/rules/security.md` é herança de um
  template e não se aplica a este projeto.

## Skills e agentes do projeto (`.claude/`)

| Item | O que é |
|---|---|
| `rules/code-style.md`, `rules/frontend-design.md`, `rules/security.md` | regras carregadas automaticamente |
| `skills/review` | code review criteriosa da codebase |
| `skills/push` | pipeline completo + commit + push |
| `agents/code-reviewer.md` | reviewer crítico que consulta a memória do projeto antes de revisar |
| `settings.json` | hooks: formatação automática em Write/Edit + reviewer crítico no `Stop`. Todos apontam para a memória em `-01-investimentos-financas-app` (corrigido em 2026-08-05) |

Ver `13-estado-atual.md` para o resto do drift conhecido.
