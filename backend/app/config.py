from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration. Every field can be overridden by an env var of the same name."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Infrastructure
    database_url: str = "postgresql://nimbus:nimbus@localhost:5433/nimbus"
    test_database_url: str = "postgresql://nimbus:nimbus@localhost:5433/nimbus_test"
    frontend_origin: str = "http://localhost:3000"

    # Providers
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    langsmith_api_key: str | None = None

    # Models
    agent_model: str = "gpt-4.1-mini"
    small_model: str = "gpt-4.1-mini"
    fallback_model: str = "claude-haiku-5-5"
    realtime_model: str = "gpt-realtime"
    realtime_voice: str = "marin"
    transcription_model: str = "gpt-4o-mini-transcribe"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    # Retrieval and guardrails
    rag_t_low: float = 0.44
    rag_t_high: float = 0.52
    rag_top_k: int = 5

    # Resilience
    llm_timeout_s: float = 20.0
    llm_max_retries: int = 2
    llm_backoff_base_s: float = 0.5
    agent_max_iterations: int = 6

    # Cost and abuse protection
    daily_budget_usd: float = 5.0
    chat_rate_per_min: int = 20
    voice_calls_per_hour: int = 5
    voice_max_seconds: int = 600
    voice_idle_seconds: int = 60
    voice_history_turns: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
