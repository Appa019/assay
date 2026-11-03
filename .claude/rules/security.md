## Security Rules

### Secrets
- NEVER hardcode API keys, passwords, tokens, or credentials
- ALL secrets in `.env` — read through `app.config.Settings` (Python), never `os.getenv()` scattered in code
- `.env.example` with empty values only — never real credentials
- Before committing: verify no secrets in staged files

### Input Validation
- Validate ALL user input at system boundaries (API endpoints, form submissions)
- Use Pydantic models for request validation in FastAPI
- Use native TS types for frontend form validation
- Sanitize data before database queries — use parameterized queries (SQLAlchemy ORM)

### Access
- Single user, no auth layer: the app is reachable only through the private
  Tailscale network (`tailscale serve`)
- Services bind to 127.0.0.1, never 0.0.0.0 — the LAN is shared with the building
- Never add an endpoint that is meant to be public

### OWASP Top 10
- No SQL injection (use ORM, parameterized queries)
- No XSS (React auto-escapes, avoid dangerouslySetInnerHTML)
- CORS restricted to localhost in development
- No sensitive data in URL parameters or logs
