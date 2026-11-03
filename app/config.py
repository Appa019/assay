from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Storage
    sqlite_path: str = "storage/portfolio.db"

    # Service URLs
    frontend_url: str = "http://localhost:3000"
    backend_url: str = "http://localhost:8000"

    # External APIs
    coingecko_api_url: str = "https://api.coingecko.com/api/v3"
    coingecko_api_key: str = ""

    # Optional premium data-provider keys for the autonomous analyst's MCPs.
    # All blank by default: the matching MCP server is only wired up when its
    # key is present, so the agent boots fine with none of them set. Keys live
    # in .env (never committed) and are injected into the headless run's env.
    glassnode_api_key: str = ""  # on-chain metrics (MVRV/NUPL/SOPR/...)
    coinglass_api_key: str = ""  # derivatives (funding/OI/liquidations)
    messari_api_key: str = ""  # crypto research/fundamentals
    firecrawl_api_key: str = ""  # structured scraping of JS-heavy sources
    tavily_api_key: str = ""  # citation-grade web research

    # Long-lived CLI auth for headless machines (`claude setup-token`). When
    # set, every headless `claude` run authenticates with this token instead
    # of ~/.claude/.credentials.json — which on the Pi went stale because two
    # machines rotated the same refresh token (A39). Blank on the desktop.
    claude_code_oauth_token: str = ""

    # Portfolio targets (used to compute deviation, in fraction of 1.0).
    # 2026-09-05: fixed income goes 35 -> 50, taking 15 points off the risk side.
    # The cut lands on crypto (25 -> 15) rather than equities (40 -> 35) because
    # crypto drives the risk: at 15% of capital and ~60% vol it still carries
    # more than half the portfolio's gross volatility, while B3 quality equities
    # are the core sleeve of the mandate.
    target_fixed_income: float = 0.50
    target_stocks: float = 0.35
    target_crypto: float = 0.15

    # Investment agent (autonomous Claude runs). Contributions are ad-hoc (no
    # fixed cadence); the sell lock is PER LOT and PER CLASS.
    # Stocks: 30 days is a compliance requirement on the client's side (he works
    # at a brokerage, and the rule covers securities), so it is not negotiable.
    # Crypto: 7 days — no legal hold applies, crypto breaks faster and harder
    # (exploit, depeg, dead token), and this is the sleeve the client runs to
    # make money, so the friction is deliberately minimal. CDB/fixed income
    # never locks (daily liquidity).
    min_holding_days: int = 30
    min_holding_days_crypto: int = 7
    agent_model: str = "opus"
    agent_effort: str = "max"
    # Per-step subprocess ceiling (seconds) for the headless Claude CLI.
    agent_step_timeout: int = 2400
    # Max consecutive failed automatic runs before auto-resume gives up on a
    # contribution (prevents an endless paid retry loop on permanent failures).
    max_run_attempts: int = 5

    # Telegram consultant chat (free-text conversation over the bot). Opus by
    # default for advice quality; set CHAT_MODEL=sonnet for snappier replies.
    chat_model: str = "opus"
    chat_effort: str = "medium"
    # Per-turn subprocess ceiling (seconds) — one chat answer, not a committee run.
    chat_turn_timeout: int = 900
    # Rotate the chained chat session after this many turns; MEMORY.md carries
    # the durable context across rotations so old turns can be dropped.
    chat_max_turns: int = 40
    # ...or as soon as the conversation itself gets this big (tokens read on a
    # single model call, as reported by the CLI). Measured on the real chat:
    # by turn 14 the session was already at ~200k tokens of context, and a
    # chained session re-reads ALL of it on every iteration of every later
    # turn — one "ok, obrigado" cost US$ 2.36 that way. The turn counter never
    # saw it coming, which is why the ceiling is in tokens.
    chat_max_context_tokens: int = 120_000

    # Attachments (receipt photos, statements, invoices) are transcribed in a
    # THROWAWAY session and only the text joins the chained conversation. Read
    # inline, a photo's base64 stays in the session forever and is re-sent on
    # every later turn: 8 photos were 99% of the chat history's payload.
    # Vision quality matters here (these are numbers being copied), so this is
    # the middle model rather than the cheapest one.
    chat_vision_model: str = "sonnet"
    chat_vision_effort: str = "low"
    chat_vision_timeout: int = 300

    # Free-text expense/income classifier. Deliberately a small, fast model with
    # no MCPs: this runs while the user waits with a thumb on the screen, so
    # seconds matter far more than depth.
    classifier_model: str = "haiku"
    classifier_effort: str = "low"
    classifier_timeout: int = 90

    # Model router: three tiers, decided by rules (no triage model call).
    # Booking a spend runs fast; a FACTUAL lookup of data the app already owns
    # (balance, price, pending orders) runs on the middle tier; everything that
    # needs judgment is deep. When in doubt, deep.
    # CHAT_ROUTER_ENABLED=false pins every turn to the deep tier.
    chat_router_enabled: bool = True
    chat_fast_model: str = "haiku"
    chat_fast_effort: str = "low"
    # Middle tier: reading a number out of the local API or a live quote is
    # retrieval, not advice — opus/high there was measured at ~US$ 1.67/turn.
    chat_lookup_model: str = "sonnet"
    chat_lookup_effort: str = "low"
    chat_deep_model: str = "opus"
    # medium, not high: the thinking blocks of every past turn stay in the
    # chained session and are re-read on each iteration (392k chars of them in
    # the measured session). This is the one knob here that trades depth for
    # cost — CHAT_DEEP_EFFORT=high in .env puts it back.
    chat_deep_effort: str = "medium"
    # Small model for auxiliary steps (the chat's rotation summary).
    chat_router_model: str = "haiku"
    chat_router_effort: str = "low"
    chat_router_timeout: int = 60

    # Contributions run at night by default. The committee is the heaviest job
    # here (~90 min) and the plan's usage limit is a rolling window shared with
    # the consultant chat, so running it on demand at 14h ate the window the
    # client wanted for the rest of the day. Asking for an aporte now schedules
    # it for the next night slot; POST ...?run=true&now=true forces immediate.
    contribution_night_run: bool = True
    contribution_night_hour: int = 1

    # Macro delta mode: when a weekly review this fresh (in days) exists, the
    # contribution's meeting #1 reads it and prices only the DELTA instead of
    # re-running the full 11-round macro from scratch. The weekly already did
    # that research days ago, on the same committee, for a fraction of the cost.
    # MACRO_DELTA_ENABLED=false always renders the full template.
    macro_delta_enabled: bool = True
    macro_delta_max_age_days: int = 7

    # CDB accrual assumption: % of CDI the paper pays (mandate: CDB >= 100%).
    # Used to mark fixed-income lots to market from the BCB daily CDI series.
    cdb_pct_cdi: float = 100.0

    # TTL (seconds) for the cached macro/market context (/api/macro).
    market_cache_ttl: int = 120

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @field_validator("target_fixed_income", "target_stocks", "target_crypto")
    @classmethod
    def _validate_target_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Target deve estar em [0, 1], recebido {v}")
        return v

    @model_validator(mode="after")
    def _validate_targets_sum(self) -> "Settings":
        total = self.target_fixed_income + self.target_stocks + self.target_crypto
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"Targets devem somar 1.0 (±0.01); somam {total:.4f} "
                f"(FI={self.target_fixed_income} + Ações={self.target_stocks} "
                f"+ Crypto={self.target_crypto})"
            )
        return self


settings = Settings()
