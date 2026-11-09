"""Application settings loaded from environment variables."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized application configuration.

    Environment variables take precedence over these defaults. A local .env file
    is supported for development and must never be committed.
    """

    app_name: str = "Minimal Agent Runtime"
    app_env: str = "dev"
    api_prefix: str = "/api/v1"

    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"

    max_agent_steps: int = Field(default=8, ge=1, le=50)
    max_context_messages: int = Field(default=20, ge=2, le=500)
    database_path: str = "./data/agent.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
