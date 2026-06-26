from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any

from app.agents.ocs_agent import process_ocs_chat

router = APIRouter()

class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]]

@router.post("/chat")
async def chat_endpoint(request: ChatRequest):
    return StreamingResponse(
        process_ocs_chat(request.messages),
        media_type="text/plain"
    )
