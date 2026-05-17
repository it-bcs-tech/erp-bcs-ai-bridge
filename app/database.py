"""
Database Connection — Async PostgreSQL
─────────────────────────────────────────
Menggunakan SQLAlchemy async engine + asyncpg driver
untuk query langsung ke PostgreSQL tanpa melalui Laravel.
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.config import get_settings

settings = get_settings()

# Buat async engine — pool_size disesuaikan agar tidak membebani DB
engine = create_async_engine(
    settings.database_url,
    echo=settings.ai_bridge_debug,  # Log SQL queries saat debug
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,  # Auto-reconnect jika koneksi putus
    isolation_level="AUTOCOMMIT", # Mencegah data tersendat (stale read) tanpa perlu restart Docker
)

# Session factory untuk dependency injection di FastAPI
async_session = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """FastAPI dependency — memberikan session DB per-request."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
