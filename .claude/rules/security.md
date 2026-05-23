## Security Rules

### Secrets
- NEVER hardcode API keys, passwords, tokens, or credentials
- ALL secrets in `.env` — reference via `os.getenv()` (Python) or `process.env` (Node)
- `.env.example` with empty values only — never real credentials
- Before committing: verify no secrets in staged files

### Input Validation
- Validate ALL user input at system boundaries (API endpoints, form submissions)
- Use Pydantic models for request validation in FastAPI
- Use Zod or native TS types for frontend form validation
- Sanitize data before database queries — use parameterized queries (SQLAlchemy ORM)

### Authentication
- Supabase Auth for user authentication
- Row Level Security (RLS) on ALL Supabase tables
- Server-side session validation — never trust client-only auth checks
- Use `@supabase/ssr` for cookie-based session management

### Gmail SMTP
- Use App Password — never the main Google account password
- GMAIL_APP_PASSWORD in `.env` only
- TLS required (port 587, STARTTLS)
- Rate limit email sending to avoid Google blocking

### OWASP Top 10
- No SQL injection (use ORM, parameterized queries)
- No XSS (React auto-escapes, avoid dangerouslySetInnerHTML)
- No CSRF (Supabase handles via tokens)
- CORS restricted to localhost in development
- No sensitive data in URL parameters or logs
