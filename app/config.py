"""
AI Bridge Configuration
─────────────────────────────────────────
Semua konfigurasi diambil dari environment variables.
Di production: dari docker-compose env_file atau .env file di server.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── LLM / AI Provider (OpenAI-compatible) ────────────────
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = "your-api-key-here"
    llm_model: str = "qwen/qwen3-32b"

    # ── Database ─────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://bcs_admin:sangatrahasia@localhost:5433/mybcs_db"

    # ── FMS / Go-Map Backend ──────────────────────────────────
    # Di Docker: http://erp_go_map:8081 | Di lokal: http://localhost:8081
    go_map_url: str = "http://erp_go_map:8081/api/fms/live-map"

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
