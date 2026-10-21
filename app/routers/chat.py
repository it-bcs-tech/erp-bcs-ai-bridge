"""
Chat Router — /chat endpoint
─────────────────────────────────────────
Endpoint utama untuk menerima pesan dari SvelteKit frontend
dan mengembalikan streaming response dari AI.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json
import hashlib
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, async_session
from app.agents.hris_agent import process_hris_chat
from app.redis_client import get_cache, set_cache

router = APIRouter()


# ── Request / Response Models ────────────────────────────────

class ChatMessage(BaseModel):
    role: str       # "user" | "assistant" | "system"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


# ── Endpoints ────────────────────────────────────────────────

@router.post("/chat")
async def chat(request: ChatRequest):
    """
    Menerima conversation history dari frontend,
    menganalisis intent, query database, dan stream respons AI.
    """
    # Convert Pydantic models ke dict untuk agent
    messages_dict = [msg.model_dump() for msg in request.messages]

    # Generate Hash Key unik dari pesan chat (Cache Key)
    cache_key = "hris_chat:" + hashlib.md5(json.dumps(messages_dict, sort_keys=True).encode()).hexdigest()

    async def generate():
        try:
            # Cek Cache dulu
            cached_response = await get_cache(cache_key)
            if cached_response:
                yield cached_response
                return

            full_response = ""
            async with async_session() as db:
                async for chunk in process_hris_chat(messages_dict, db):
                    full_response += chunk
                    yield chunk
                
            # Simpan ke cache jika tidak kosong dan bukan pesan error (TTL = 30 menit / 1800 detik)
            if full_response.strip() and not full_response.strip().startswith("⚠️") and "Error code:" not in full_response:
                await set_cache(cache_key, full_response, ttl_seconds=1800)
        except Exception as e:
            print(f"[HARIS Stream Error] {e}")
            yield f"\n⚠️ [Terjadi kesalahan sistem: {str(e)}]"

    return StreamingResponse(
        generate(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )



@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Health check — memastikan service dan database terhubung."""
    try:
        from sqlalchemy import text
        result = await db.execute(text("SELECT 1"))
        db_status = "connected" if result else "error"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return {
        "status": "ok",
        "service": "ai-bridge",
        "database": db_status,
    }
