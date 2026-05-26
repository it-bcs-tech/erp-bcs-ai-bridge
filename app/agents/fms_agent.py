"""
FMS Agent — FARIDA
─────────────────────────────────────────────────────────────────
Fleet AI Realtime Intelligence & Dispatch Assistant

FARIDA adalah asisten AI monitoring armada untuk PT BCS Logistics.
Menggunakan Tool-Calling (function calling) yang identik dengan HARIS (HRIS Agent),
namun HANYA memiliki akses ke data GPS armada — tidak ada akses ke data karyawan/HR.

Tools yang tersedia: fms_tools.py (data dari go-map Golang backend → EasyGo GPS)
"""

import re
import json
from datetime import datetime
from typing import AsyncGenerator

from app.llm.llm_client import client, settings
from app.tools.fms_tools import (
    get_all_fleet_status,
    get_unit_detail,
    get_slow_or_stuck_units,
    get_units_by_status,
    get_fleet_summary_for_monitoring,
)


# ── 1. Definisi Tools untuk LLM ──────────────────────────────────

FMS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_all_fleet_status",
            "description": (
                "Ambil status lengkap SELURUH armada saat ini: nopol, driver, status operasional, "
                "kecepatan, dan lokasi. Gunakan jika user menanyakan 'semua unit', 'berapa armada', "
                "'mana saja yang jalan', atau pertanyaan umum tentang kondisi armada."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_unit_detail",
            "description": (
                "Ambil detail lengkap SATU unit tertentu berdasarkan nomor polisi (nopol). "
                "Gunakan jika user menyebutkan nopol spesifik, misalnya: B 9123 AA, D 7810 BA."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nopol": {
                        "type": "string",
                        "description": "Nomor polisi kendaraan, contoh: 'B 9123 AA' atau 'B9123AA'.",
                    }
                },
                "required": ["nopol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_slow_or_stuck_units",
            "description": (
                "Deteksi unit yang berpotensi terjebak kemacetan atau lalu lintas padat. "
                "Kecepatan < 5 km/h saat Moving = macet. Kecepatan 5–20 km/h = padat. "
                "Gunakan untuk pertanyaan: 'ada macet?', 'unit mana yang lambat?', 'ada hambatan?'."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_units_by_status",
            "description": (
                "Filter dan tampilkan unit berdasarkan status operasional. "
                "Gunakan untuk pertanyaan: 'berapa yang sedang moving?', 'unit mana yang parkir?', "
                "'mana yang idle/loading?', 'mana yang standby di pool?'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["moving", "idle", "parkir"],
                        "description": "Status yang dicari: 'moving' (bergerak), 'idle' (loading/bongkar muat), 'parkir' (standby/pool).",
                    }
                },
                "required": ["status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fleet_summary_for_monitoring",
            "description": (
                "Hasilkan laporan ringkas monitoring armada: total unit, distribusi status, "
                "kecepatan rata-rata, dan alert kemacetan. "
                "Gunakan untuk: 'buat laporan', 'ringkasan armada', 'status terkini semua unit', "
                "atau pertanyaan tentang kondisi keseluruhan operasi."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# ── 2. System Prompt ──────────────────────────────────────────────

FARIDA_SYSTEM_PROMPT = """Anda adalah AI Assistant monitoring armada bernama "FARIDA" \
(Fleet AI Realtime Intelligence & Dispatch Assistant) untuk PT BCS Logistics.

Tugas Anda adalah membantu tim operasional FMS (Fleet Management System) untuk:
- Memantau posisi dan status armada secara real-time
- Mendeteksi kemacetan, keterlambatan, atau anomali perjalanan
- Memberikan laporan ringkas kondisi armada
- Menjawab pertanyaan spesifik tentang unit atau pengemudi

## Aturan Penting:
1. Anda DILENGKAPI dengan tools GPS real-time. WAJIB panggil tools jika data dibutuhkan.
2. JANGAN PERNAH mengarang data, nopol, nama driver, atau koordinat.
3. Data GPS diperbarui setiap 30 detik — selalu informasikan ini kepada user jika relevan.
4. Jawab dalam Bahasa Indonesia yang profesional, singkat, dan to-the-point. Gunakan emoji.
5. 🛡️ PEMBATASAN TOPIK: Anda HANYA menjawab pertanyaan seputar armada, GPS, monitoring unit, \
logistik, dan pengiriman BCS. JIKA ditanya di luar topik, tolak dengan sopan: \
"Maaf, saya FARIDA — asisten monitoring armada. Saya hanya bisa membantu urusan fleet dan GPS."
6. Untuk deteksi kemacetan: kecepatan < 5 km/h saat status Moving = MACET. \
5–20 km/h = LALU LINTAS PADAT. Sampaikan koordinat GPS untuk referensi tim lapangan.
"""


# ── 3. Tool Executor ──────────────────────────────────────────────

async def _execute_fms_tool(tool_call) -> str:
    """Menjalankan fungsi FMS tool sesuai permintaan LLM."""
    func_name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments)
    except Exception:
        args = {}

    try:
        if func_name == "get_all_fleet_status":
            return await get_all_fleet_status()
        elif func_name == "get_unit_detail":
            return await get_unit_detail(nopol=args.get("nopol", ""))
        elif func_name == "get_slow_or_stuck_units":
            return await get_slow_or_stuck_units()
        elif func_name == "get_units_by_status":
            return await get_units_by_status(status=args.get("status", "moving"))
        elif func_name == "get_fleet_summary_for_monitoring":
            return await get_fleet_summary_for_monitoring()
        else:
            return f"Error: Tool '{func_name}' tidak dikenali oleh FARIDA."
    except Exception as e:
        return f"ERROR saat mengambil data GPS: {str(e)}"


# ── 4. Streaming Filter (hapus tag <think>) ───────────────────────

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


# ── 5. Main Process Chat ──────────────────────────────────────────

async def process_fms_chat(
    messages: list[dict],
) -> AsyncGenerator[str, None]:
    """
    Pipeline utama FARIDA:
    1. Kirim conversation + FMS_TOOLS ke LLM
    2. Jika LLM memanggil tool → eksekusi → kembalikan ke LLM
    3. Stream jawaban final ke frontend
    """
    now_str = datetime.now().strftime("%d %B %Y (%H:%M WIB)")
    dynamic_prompt = (
        FARIDA_SYSTEM_PROMPT
        + f"\n[INFO SISTEM: Waktu sekarang adalah {now_str}. "
        "Data GPS diperbarui otomatis setiap 30 detik dari EasyGo GPS.]\n"
    )

    conversation = [{"role": "system", "content": dynamic_prompt}] + messages

    # ── Langkah 1: Panggil LLM (dengan tools) ────────────────
    try:
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=conversation,
            tools=FMS_TOOLS,
            tool_choice="auto",
            temperature=0.1,
        )
        response_message = response.choices[0].message
    except Exception as e:
        error_msg = str(e)
        yield f"⚠️ FARIDA gagal memproses permintaan: {error_msg}"
        return

    has_tool_call = False

    # ── Langkah 2a: Native tool_calls ────────────────────────
    if response_message.tool_calls:
        has_tool_call = True
        conversation.append(response_message)

        for tool_call in response_message.tool_calls:
            print(f"[FARIDA] Tool dipanggil: {tool_call.function.name} | args: {tool_call.function.arguments}")
            result = await _execute_fms_tool(tool_call)
            conversation.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call.function.name,
                "content": str(result),
            })

    # ── Langkah 2b: Groq bocor <function=...> ────────────────
    elif response_message.content and "<function=" in response_message.content:
        has_tool_call = True
        content = response_message.content
        conversation.append({"role": "assistant", "content": content})

        for match in re.finditer(r"<function=([^>]+)>(.*?)</function>", content):
            func_name = match.group(1).strip()
            args_str = match.group(2).strip()
            print(f"[FARIDA] Groq parser: {func_name} | args: {args_str}")

            class _MockFn:
                name = func_name
                arguments = args_str if args_str.startswith("{") else f'{{"nopol": "{args_str}"}}'

            class _MockCall:
                id = f"call_{func_name}"
                function = _MockFn()

            result = await _execute_fms_tool(_MockCall())
            conversation.append({
                "role": "user",
                "content": f"[System: Hasil dari {func_name}]:\n{result}",
            })

    # ── Langkah 3: Stream jawaban final ──────────────────────
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
        # Tidak ada tool call — filter think tag dari respons statis
        if response_message.content:
            clean = re.sub(r"<think>.*?</think>", "", response_message.content, flags=re.DOTALL).strip()
            yield clean
