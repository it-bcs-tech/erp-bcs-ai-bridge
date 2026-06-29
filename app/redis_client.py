import os
import redis.asyncio as redis
import logging

# Konfigurasi URL Redis (Default mengarah ke container docker internal)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# Inisialisasi client
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

logger = logging.getLogger(__name__)

async def get_cache(key: str) -> str | None:
    """Mengambil data dari Redis berdasarkan kunci. Aman dari exception."""
    try:
        return await redis_client.get(key)
    except Exception as e:
        logger.warning(f"[Redis] Gagal mengambil cache untuk {key}: {e}")
        return None

async def set_cache(key: str, value: str, ttl_seconds: int = 1800):
    """Menyimpan data ke Redis dengan waktu kedaluwarsa (TTL). Aman dari exception."""
    try:
        await redis_client.setex(key, ttl_seconds, value)
    except Exception as e:
        logger.warning(f"[Redis] Gagal menyimpan cache untuk {key}: {e}")
