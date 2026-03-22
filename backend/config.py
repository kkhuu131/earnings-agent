"""Centralised application settings loaded from environment variables.

All configuration is read from the environment (or a .env file at the repo root).
Never hardcode values — import ``settings`` instead.

Usage:
    from backend.config import settings

    print(settings.llm_provider)
    print(settings.database_url)
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",         # silently ignore unknown env vars
    )

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    database_url: str = "postgresql+asyncpg://localhost/earnings_agent"

    # ------------------------------------------------------------------
    # LLM configuration
    # ------------------------------------------------------------------
    llm_provider: str = "anthropic"          # anthropic | openai | google | ollama
    quick_model: str = "claude-haiku-4-5-20251001"   # cheap, fast tasks
    deep_model: str = "claude-sonnet-4-6"            # reasoning-heavy tasks
    temperature: float = 0.7
    max_debate_rounds: int = 2

    # ------------------------------------------------------------------
    # LLM API keys  (only the active provider needs a real value)
    # ------------------------------------------------------------------
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""

    # ------------------------------------------------------------------
    # Transcript data sources
    # ------------------------------------------------------------------
    fmp_api_key: str = ""   # Financial Modeling Prep — primary transcript source

    # ------------------------------------------------------------------
    # Supabase
    # ------------------------------------------------------------------
    supabase_url: str = ""
    supabase_publishable_key: str = ""   # formerly anon key — safe for frontend
    supabase_secret_key: str = ""        # formerly service_role — backend only


# Module-level singleton — import this everywhere
settings = Settings()
