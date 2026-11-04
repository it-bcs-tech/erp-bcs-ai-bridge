import os
import time
import redis.asyncio as redis
import logging

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
REDIS_ENABLED = os.getenv("REDIS_ENABLED", "true").lower() in ("true", "1", "yes")

logger = logging.getLogger(__name__)

# Inisialisasi client
redis_client = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_ENABLED else None
_last_fail_time = 0.0
_COOLDOWN_SECONDS = 60.0

async def get_cache(key: str) -> str | None:
    """Mengambil data dari Redis berdasarkan kunci. Aman dari exception."""
    global _last_fail_time
    if not REDIS_ENABLED or redis_client is None:
        return None
    if time.time() - _last_fail_time < _COOLDOWN_SECONDS:
        return None
    try:
        return await redis_client.get(key)
    except Exception as e:
        _last_fail_time = time.time()
        logger.warning(f"[Redis] Gagal mengambil cache untuk {key} (cooldown {_COOLDOWN_SECONDS}s diaktifkan): {e}")
        return None

async def set_cache(key: str, value: str, ttl_seconds: int = 1800):
    """Menyimpan data ke Redis dengan waktu kedaluwarsa (TTL). Aman dari exception."""
    global _last_fail_time
    if not REDIS_ENABLED or redis_client is None:
        return
    if time.time() - _last_fail_time < _COOLDOWN_SECONDS:
        return
    try:
        await redis_client.setex(key, ttl_seconds, value)
    except Exception as e:
        _last_fail_time = time.time()
        logger.warning(f"[Redis] Gagal menyimpan cache untuk {key} (cooldown {_COOLDOWN_SECONDS}s diaktifkan): {e}")
