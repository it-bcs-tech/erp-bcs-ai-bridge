"""
Chat Router — /chat endpoint
─────────────────────────────────────────
Endpoint utama untuk menerima pesan dari SvelteKit frontend
dan mengembalikan streaming response dari AI.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.agents.hris_agent import process_chat

router = APIRouter()


# ── Request / Response Models ────────────────────────────────

class ChatMessage(BaseModel):
    role: str       # "user" | "assistant" | "system"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


# ── Endpoints ────────────────────────────────────────────────

@router.post("/chat")
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Menerima conversation history dari frontend,
    menganalisis intent, query database, dan stream respons AI.
    
    Request body:
        {
            "messages": [
                {"role": "user", "content": "Berapa jumlah karyawan?"},
                ...
            ]
        }
    
    Response:
        text/plain stream — setiap chunk berisi teks dari AI
    """
    # Convert Pydantic models ke dict untuk agent
    messages_dict = [msg.model_dump() for msg in request.messages]

    async def generate():
        async for chunk in process_chat(messages_dict, db):
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
