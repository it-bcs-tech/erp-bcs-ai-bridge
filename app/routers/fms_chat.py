"""
FMS Chat Router — /fms/chat endpoint
─────────────────────────────────────────────────────────────────
Router khusus untuk FARIDA (FMS Agent). Terpisah sepenuhnya dari
router HRIS (/chat). Database session diteruskan untuk konsistensi
arsitektur, meskipun FMS tools saat ini mengakses go-map via HTTP.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.agents.fms_agent import process_fms_chat

router = APIRouter()


# ── Request Models ────────────────────────────────────────────────

class FMSChatMessage(BaseModel):
    role: str       # "user" | "assistant" | "system"
    content: str


class FMSChatRequest(BaseModel):
    messages: list[FMSChatMessage]


# ── Endpoints ─────────────────────────────────────────────────────

@router.post("/chat")
async def fms_chat(
    request: FMSChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Chat dengan FARIDA — AI Monitor Armada FMS.

    Menerima conversation history dari frontend SvelteKit,
    FARIDA akan menganalisis kondisi armada secara real-time dan
    memberikan streaming response.

    Request body:
        {
            "messages": [
                {"role": "user", "content": "Ada berapa unit yang sedang bergerak?"},
                ...
            ]
        }

    Response:
        text/plain stream — setiap chunk berisi teks dari FARIDA
    """
    messages_dict = [msg.model_dump() for msg in request.messages]

    async def generate():
        async for chunk in process_fms_chat(messages_dict):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/health")
async def fms_health(db: AsyncSession = Depends(get_db)):
    """Health check khusus FMS — cek database dan go-map backend."""
    import httpx

    # Cek database
    try:
        from sqlalchemy import text
        result = await db.execute(text("SELECT 1"))
        db_status = "connected" if result else "error"
    except Exception as e:
        db_status = f"error: {str(e)}"

    # Cek go-map backend
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://localhost:8081/api/fms/live-map")
            go_map_status = f"connected ({resp.json().get('total', '?')} units)"
    except Exception as e:
        go_map_status = f"error: {str(e)}"

    return {
        "status": "ok",
        "service": "ai-bridge/fms",
        "agent": "FARIDA",
        "database": db_status,
        "go_map_backend": go_map_status,
    }
