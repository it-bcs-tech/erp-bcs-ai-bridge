"""
OCS Agent — ORIS
─────────────────────────────────────────────────────────────────
OCS Resource Intelligence System

ORIS adalah asisten AI untuk modul Operational Center System (OCS) PT BCS Logistics.
Agen ini memiliki batas (guardrails) yang ketat untuk HANYA menjawab pertanyaan
seputar OCS dan tidak akan melenceng ke topik di luar sistem (seperti HR atau internet umum).
"""

import re
import json
from datetime import datetime
from typing import AsyncGenerator

from app.llm.llm_client import client, settings
from app.tools.chart_tools import CHART_TOOL_SCHEMA, generate_chart_image

ORIS_TOOLS = [
    CHART_TOOL_SCHEMA
]

ORIS_SYSTEM_PROMPT = """Anda adalah ORIS (OCS Resource Intelligence System), asisten AI khusus untuk modul Operational Center System (OCS) di PT BCS Logistics.
Tugas Anda HANYA membantu menjawab pertanyaan seputar operasional OCS seperti Dispatch, UJO (Uang Jalan), Assign Driver, Target Harian, dan Master Rute.
Jika pengguna menanyakan hal di luar konteks OCS (seperti HR, informasi karyawan, pelacakan armada secara umum di luar dispatching, atau hal-hal acak dari internet), tolak dengan sopan dan tegaskan identitas Anda bahwa Anda hanya menangani operasional OCS.
Jawab dengan gaya yang profesional, ringkas, dan jelas. Karena saat ini akses database Anda (tools) masih ditahap persiapan integrasi, jika Anda ditanya tentang data transaksi riil, sampaikan dengan sopan bahwa Anda "masih menunggu sinkronisasi database operasional".
📊 VISUALISASI GRAFIK: Jika pengguna meminta grafik, bagan (bar, pie, line), atau diagram visual, panggil tool `generate_chart_image` dengan data yang Anda miliki. Jangan katakan Anda tidak bisa membuat grafik; Anda BISA membuatnya melalui tool tersebut!
"""

async def _execute_ocs_tool(tool_call) -> str:
    """Menjalankan fungsi OCS tool sesuai permintaan LLM."""
    func_name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments)
    except Exception:
        args = {}

    try:
        if func_name == "generate_chart_image":
            return await generate_chart_image(**args)
        else:
            return f"Error: Tool '{func_name}' tidak dikenali oleh ORIS."
    except Exception as e:
        return f"ERROR eksekusi tool: {str(e)}"

async def _stream_filtered(stream) -> AsyncGenerator[str, None]:
    """Stream response dari LLM, menyembunyikan tag <think>...</think>."""
    buffer = ""
    is_thinking = False

    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            token = chunk.choices[0].delta.content
            if not is_thinking:
                buffer += token
                if "<think>" in buffer:
                    is_thinking = True
                    clean = buffer.split("<think>")[0]
                    if clean:
                        yield clean
                    buffer = ""
                elif len(buffer) > 8:
                    yield buffer
                    buffer = ""
            else:
                buffer += token
                if "</think>" in buffer:
                    is_thinking = False
                    clean = buffer.split("</think>")[1].lstrip("\n")
                    if clean:
                        yield clean
                    buffer = ""

    if buffer and not is_thinking:
        yield buffer

async def process_ocs_chat(messages: list[dict]) -> AsyncGenerator[str, None]:
    """
    Pipeline ORIS: Tool-Calling Architecture
    """
    now_str = datetime.now().strftime("%d %B %Y (%H:%M WIB)")
    dynamic_prompt = (
        ORIS_SYSTEM_PROMPT
        + f"\n[INFO SISTEM: Waktu sekarang adalah {now_str}.]\n"
    )

    conversation = [{"role": "system", "content": dynamic_prompt}] + messages

    try:
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=conversation,
            tools=ORIS_TOOLS,
            tool_choice="auto",
            temperature=0.1,
        )
        response_message = response.choices[0].message
    except Exception as e:
        yield f"⚠️ ORIS gagal memproses permintaan: {str(e)}"
        return

    has_tool_call = False

    if response_message.tool_calls:
        has_tool_call = True
        conversation.append(response_message)

        for tool_call in response_message.tool_calls:
            print(f"[ORIS] Tool dipanggil: {tool_call.function.name}")
            result = await _execute_ocs_tool(tool_call)
            
            if tool_call.function.name == "generate_chart_image":
                yield str(result)
                tool_content = "Berhasil membuat dan menampilkan grafik ke pengguna secara langsung."
            else:
                tool_content = str(result)

            conversation.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call.function.name,
                "content": tool_content,
            })
    elif response_message.content and "<function=" in response_message.content:
        has_tool_call = True
        content = response_message.content
        conversation.append({"role": "assistant", "content": content})

        for match in re.finditer(r"<function=([^>]+)>(.*?)</function>", content):
            func_name = match.group(1).strip()
            args_str = match.group(2).strip()
            class _MockFn:
                name = func_name
                arguments = args_str if args_str.startswith("{") else f'{{"chart_config": "{args_str}"}}'
            class _MockCall:
                id = f"call_{func_name}"
                function = _MockFn()
            result = await _execute_ocs_tool(_MockCall())
            
            if func_name == "generate_chart_image":
                yield str(result)
                tool_content = "Berhasil membuat dan menampilkan grafik ke pengguna secara langsung."
            else:
                tool_content = str(result)

            conversation.append({
                "role": "user",
                "content": f"[System: Hasil dari {func_name}]:\n{tool_content}",
            })

    if has_tool_call:
        stream = await client.chat.completions.create(
            model=settings.llm_model,
            messages=conversation,
            temperature=0.7,
            stream=True,
        )
        async for chunk in _stream_filtered(stream):
            yield chunk
    else:
        if response_message.content:
            clean = re.sub(r"<think>.*?</think>", "", response_message.content, flags=re.DOTALL).strip()
            yield clean
