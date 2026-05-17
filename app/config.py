"""
AI Bridge Configuration
─────────────────────────────────────────
Semua konfigurasi diambil dari environment variables.
Di production: dari docker-compose environment atau .env file.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── Openclaw AI ──────────────────────────────────────────
    openclaw_base_url: str = "http://127.0.0.1:8080/v1"
    openclaw_api_key: str = "openclaw-key"
    openclaw_model: str = "glm-4.7-flash"

    # ── Database ─────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://bcs_admin:sangatrahasia@localhost:5433/mybcs_db"

    # ── Service ──────────────────────────────────────────────
    ai_bridge_host: str = "0.0.0.0"
    ai_bridge_port: int = 8000
    ai_bridge_debug: bool = False

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance — hanya di-load sekali."""
    return Settings()
