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

    # Portfolio targets (used to compute deviation, in fraction of 1.0)
    target_fixed_income: float = 0.35
    target_stocks: float = 0.40
    target_crypto: float = 0.25

    # Investment agent (autonomous Claude runs). Contributions are ad-hoc (no
    # fixed cadence); min_holding_days is the per-lot sell lock for stocks/crypto.
    min_holding_days: int = 30
    agent_model: str = "opus"
    agent_effort: str = "max"
    # Per-step subprocess ceiling (seconds) for the headless Claude CLI.
    agent_step_timeout: int = 2400
    # Max consecutive failed automatic runs before auto-resume gives up on a
    # contribution (prevents an endless paid retry loop on permanent failures).
    max_run_attempts: int = 5

    # CDB accrual assumption: % of CDI the paper pays (mandate: CDB >= 100%).
    # Used to mark fixed-income lots to market from the BCB daily CDI series.
    cdb_pct_cdi: float = 100.0

    # TTL (seconds) for the cached macro/market context (/api/macro).
    market_cache_ttl: int = 120

    # Telegram bot (notifications + two-way control)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

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
