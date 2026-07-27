# Investimentos Manual — daily-driver commands
PY := .venv/bin/python
RUFF := .venv/bin/ruff

.PHONY: dev backend frontend bot lint format test check build crons systemd analyze weekly prices snapshot backup

dev:            ## backend + frontend + bot (daily use)
	./start.sh

backend:        ## backend only, with reload (development)
	.venv/bin/uvicorn app.main:app --reload

frontend:       ## frontend only (development)
	cd frontend && pnpm dev

bot:            ## Telegram bot in the foreground
	$(PY) scripts/telegram_bot.py

lint:           ## Python + frontend linters
	$(RUFF) check app/ scripts/ tests/
	$(RUFF) format --check app/ scripts/ tests/
	cd frontend && pnpm run lint && pnpm run type-check

format:         ## auto-format Python
	$(RUFF) format app/ scripts/ tests/
	$(RUFF) check --fix app/ scripts/ tests/

test:           ## backend test suite
	$(PY) -m pytest

build:          ## production build of the frontend
	cd frontend && pnpm run build

check: lint test build  ## everything CI runs

crons:          ## install cron schedule (legacy; prefer systemd)
	bash scripts/install_cron.sh

systemd:        ## install systemd user units + persistent timers
	bash scripts/install_systemd.sh

analyze:        ## run a full contribution analysis (make analyze AMOUNT=5000)
	$(PY) scripts/run_analysis.py --amount $(AMOUNT)

weekly:         ## force the weekly committee review now
	$(PY) scripts/weekly_review.py --force

prices:         ## mark every lot to market now
	$(PY) scripts/refresh_prices.py

snapshot:       ## record today's equity-curve datapoint
	$(PY) scripts/daily_snapshot.py

backup:         ## back up the SQLite database now
	bash scripts/backup_db.sh
