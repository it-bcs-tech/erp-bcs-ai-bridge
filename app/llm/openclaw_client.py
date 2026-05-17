"""
Openclaw LLM Client
─────────────────────────────────────────
Wrapper untuk berkomunikasi dengan Openclaw server
menggunakan OpenAI-compatible API (chat/completions).
Mendukung streaming response.
"""

from openai import AsyncOpenAI
from app.config import get_settings

settings = get_settings()

# OpenAI SDK kompatibel dengan Openclaw karena endpoint-nya sama
# yaitu: POST /v1/chat/completions
client = AsyncOpenAI(
    base_url=settings.openclaw_base_url,
    api_key=settings.openclaw_api_key,
)


async def stream_chat_completion(
    messages: list[dict],
    system_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 2048,
):
    """
    Stream chat completion dari Openclaw.
    
    Yields string chunks yang bisa langsung di-stream ke client.
    
    Args:
        messages: List of {role, content} dari conversation history
        system_prompt: System prompt berisi konteks dan instruksi
        temperature: Kreativitas AI (0.0 = deterministik, 1.0 = kreatif)
        max_tokens: Batas panjang respons
    """
    # Sisipkan system prompt di awal conversation
    full_messages = [
        {"role": "system", "content": system_prompt},
        *messages,
    ]

    stream = await client.chat.completions.create(
        model=settings.openclaw_model,
        messages=full_messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )

    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


async def chat_completion(
    messages: list[dict],
    system_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> str:
    """
    Non-streaming chat completion — untuk keperluan internal
    seperti intent detection dimana kita butuh full response sekaligus.
    """
    full_messages = [
        {"role": "system", "content": system_prompt},
        *messages,
    ]

    response = await client.chat.completions.create(
        model=settings.openclaw_model,
        messages=full_messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
    )

    return response.choices[0].message.content or ""
