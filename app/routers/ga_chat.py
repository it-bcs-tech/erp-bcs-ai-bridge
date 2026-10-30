from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any
import json
import hashlib

from app.agents.ga_agent import process_ga_chat
from app.redis_client import get_cache, set_cache

router = APIRouter()

class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]]

@router.post("/chat")
async def chat_endpoint(request: ChatRequest):
    cache_key = "ga_chat:" + hashlib.md5(json.dumps(request.messages, sort_keys=True).encode()).hexdigest()

    async def generate():
        cached_response = await get_cache(cache_key)
        if cached_response:
            yield cached_response
            return

        full_response = ""
        async for chunk in process_ga_chat(request.messages):
            full_response += chunk
            yield chunk

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
