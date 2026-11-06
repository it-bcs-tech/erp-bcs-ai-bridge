"""
LLM Client — AI Bridge
─────────────────────────────────────────
Wrapper untuk berkomunikasi dengan AI Provider (Groq, OpenAI, atau
provider lain yang kompatibel dengan OpenAI API /v1/chat/completions).
Mendukung streaming response.
"""

from openai import AsyncOpenAI
from app.config import get_settings

settings = get_settings()

# AsyncOpenAI SDK kompatibel dengan semua provider OpenAI-compatible
# seperti Groq, OpenRouter, Together AI, dsb.
client = AsyncOpenAI(
    base_url=settings.llm_base_url,
    api_key=settings.llm_api_key,
)


def get_llm_client(base_url: str | None = None, api_key: str | None = None) -> AsyncOpenAI:
    """
    Mengembalikan client AsyncOpenAI. Jika base_url atau api_key kustom
    diberikan, inisialisasi client baru dengan endpoint dan kredensial tersebut.
    Jika kosong, gunakan singleton client bawaan settings.
    """
    effective_base_url = (base_url.strip() if base_url and base_url.strip() else None) or settings.llm_base_url
    effective_api_key = (api_key.strip() if api_key and api_key.strip() else None) or settings.llm_api_key

    if effective_base_url == settings.llm_base_url and effective_api_key == settings.llm_api_key:
        return client

    return AsyncOpenAI(
        base_url=effective_base_url,
        api_key=effective_api_key,
    )


async def stream_chat_completion(
    messages: list[dict],
    system_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 2048,
):
    """
    Stream chat completion dari AI Provider.
    
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
        model=settings.llm_model,
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
        model=settings.llm_model,
        messages=full_messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
    )

    return response.choices[0].message.content or ""
