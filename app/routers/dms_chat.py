from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any
import json
import hashlib

from app.agents.dms_agent import process_dms_chat
from app.redis_client import get_cache, set_cache

router = APIRouter()

class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]]
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    base_url: str | None = None
    api_key: str | None = None

@router.post("/chat")
async def chat_endpoint(request: ChatRequest):
    # Generate Hash Key unik dari pesan chat (Cache Key)
    req_sig = f"{request.model}_{request.base_url}_{json.dumps(request.messages, sort_keys=True)}"
    cache_key = "dms_chat:" + hashlib.md5(req_sig.encode()).hexdigest()

    async def generate():
        # Cek Cache dulu
        cached_response = await get_cache(cache_key)
        if cached_response:
            yield cached_response
            return

        full_response = ""
        async for chunk in process_dms_chat(
            request.messages,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            base_url=request.base_url,
            api_key=request.api_key,
        ):
            full_response += chunk
            yield chunk

        # Simpan ke cache jika valid dan bukan pesan error (TTL = 30 menit / 1800 detik)
        if (
            full_response.strip()
            and not full_response.startswith("⚠️")
            and not full_response.startswith("❌")
            and "gagal memproses permintaan" not in full_response
        ):
            await set_cache(cache_key, full_response, ttl_seconds=1800)

    return StreamingResponse(
        generate(),
        media_type="text/plain"
    )
