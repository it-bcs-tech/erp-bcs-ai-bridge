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

@router.post("/chat")
async def chat_endpoint(request: ChatRequest):
    # Generate Hash Key unik dari pesan chat (Cache Key)
    cache_key = "dms_chat:" + hashlib.md5(json.dumps(request.messages, sort_keys=True).encode()).hexdigest()

    async def generate():
        # Cek Cache dulu
        cached_response = await get_cache(cache_key)
        if cached_response:
            yield cached_response
            return

        full_response = ""
        async for chunk in process_dms_chat(request.messages):
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
