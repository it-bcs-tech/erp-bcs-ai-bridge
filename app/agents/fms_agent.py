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
    get_driver_trip_stats,
    get_unit_trip_stats,
)
from app.tools.chart_tools import CHART_TOOL_SCHEMA, generate_chart_image


# ── 1. Definisi Tools untuk LLM ──────────────────────────────────

FMS_TOOLS = [
    CHART_TOOL_SCHEMA,
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
            "name": "get_unit_trip_stats",
            "description": "Ambil rekap total trip selesai & aktif untuk suatu unit armada (nomor polisi/nopol) secara harian, mingguan, bulanan, dan tahunan. Kosongkan parameter nopol untuk mendapatkan peringkat/leaderboard trip top 20 unit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "nopol": {
                        "type": "string",
                        "description": "Nomor polisi unit armada. Biarkan string kosong untuk melihat keseluruhan unit."
                    }
                },
                "required": []
            }
        }
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
    {
        "type": "function",
        "function": {
            "name": "get_driver_trip_stats",
            "description": (
                "Hasilkan statistik riwayat penyelesaian trip (perjalanan) seorang driver. "
                "Memberikan data jumlah trip yang diselesaikan secara harian, mingguan, bulanan, dan tahunan. "
                "JIKA Anda ingin melakukan perbandingan ('compare') atau melihat papan peringkat ('leaderboard') "
                "seluruh pengemudi, kosongkan parameter driver_name. "
                "Gunakan untuk pertanyaan: 'berapa trip driver Budi?', 'bandingkan kinerja driver', 'siapa driver terbaik'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "driver_name": {
                        "type": "string",
                        "description": "Nama pengemudi (driver) yang dicari. Kosongkan (string kosong) jika ingin membandingkan seluruh driver.",
                    }
                }
            },
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
1. Anda DILENGKAPI dengan tools GPS real-time. WAJIB panggil tools jika data dibutuhkan secara sistemik. JANGAN PERNAH mengetikkan niat Anda seperti "Menggunakan Function: X" atau mencetak JSON ke dalam teks balasan!
2. JANGAN PERNAH mengarang data palsu. NAMUN, JANGAN PERNAH MENOLAK menampilkan daftar unit hanya karena nama driver kosong/strip (-).
3. Data GPS diperbarui setiap 30 detik — selalu informasikan ini kepada user jika relevan.
4. Jawab dalam Bahasa Indonesia yang profesional, singkat, dan to-the-point. Gunakan emoji.
5. 🛡️ PEMBATASAN TOPIK: Anda HANYA menjawab pertanyaan seputar armada, GPS, monitoring unit, logistik, dan pengiriman BCS. JIKA ditanya di luar topik, tolak dengan sopan.
6. Untuk deteksi kemacetan: kecepatan < 5 km/h saat status Moving = MACET. 5–20 km/h = LALU LINTAS PADAT.
7. 📊 VISUALISASI GRAFIK: Jika pengguna meminta grafik atau visualisasi, panggil tool `generate_chart_image`. DILARANG KERAS mencetak markdown gambar/URL secara manual.
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
        elif func_name == "get_driver_trip_stats":
            return await get_driver_trip_stats(driver_name=args.get("driver_name"))
        elif func_name == "get_unit_trip_stats":
            return await get_unit_trip_stats(nopol=args.get("nopol", ""))
        elif func_name == "generate_chart_image":
            return await generate_chart_image(**args)
        else:
            return f"Error: Tool '{func_name}' tidak dikenali oleh FARIDA."
    except Exception as e:
        return f"ERROR saat mengambil data: {str(e)}"


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

from app.llm.tool_router import get_relevant_tools

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

    # ── Langkah 0: Pemilihan Alat Dinamis (Intent Routing) ──
    last_user_msg = ""
    for m in reversed(messages):
        if m["role"] == "user":
            last_user_msg = m["content"]
            break
            
    active_tools = await get_relevant_tools(last_user_msg, FMS_TOOLS)
    if active_tools:
        print(f"[FARIDA Router] Mengaktifkan alat: {[t['function']['name'] for t in active_tools]}")
    else:
        print("[FARIDA Router] Pertanyaan umum terdeteksi. Tidak ada alat yang diaktifkan (Hemat Token).")

    # ── Langkah 1: Loop Pemanggilan LLM (Maksimal 3 Putaran Tool) ─────────
    max_tool_turns = 3
    turn = 0
    has_tool_call = False

    while turn < max_tool_turns:
        turn += 1
        try:
            if active_tools:
                response = await client.chat.completions.create(
                    model=settings.llm_model,
                    messages=conversation,
                    tools=active_tools,
                    tool_choice="auto",
                    temperature=0.1,
                )
            else:
                response = await client.chat.completions.create(
                    model=settings.llm_model,
                    messages=conversation,
                    temperature=0.7,
                )
            response_message = response.choices[0].message
        except Exception as e:
            error_msg = str(e)
            yield f"⚠️ FARIDA gagal memproses permintaan: {error_msg}"
            return

        current_turn_has_tool = False

        # ── Cek Native Tool Calls ────────────────────────
        if response_message.tool_calls:
            current_turn_has_tool = True
            has_tool_call = True
            conversation.append(response_message)

            for tool_call in response_message.tool_calls:
                print(f"[FARIDA] Tool dipanggil (Putaran {turn}): {tool_call.function.name} | args: {tool_call.function.arguments}")
                result = await _execute_fms_tool(tool_call)
                
                if tool_call.function.name == "generate_chart_image":
                    yield str(result) + "\n\n"
                    tool_content = "GRAFIK BERHASIL DITAMPILKAN SECARA OTOMATIS OLEH SISTEM. Tolong berikan analisis singkat dari grafik ini tanpa membuat link url apa pun lagi."
                else:
                    tool_content = str(result)

                conversation.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "content": tool_content,
                })

        # ── Cek Groq Fallback (<function=...> atau <tool_call>) ────────────────
        elif response_message.content and ("<function=" in response_message.content or "<tool_call>" in response_message.content or '{"name":' in response_message.content):
            current_turn_has_tool = True
            has_tool_call = True
            content = response_message.content
            conversation.append({"role": "assistant", "content": content})

            # Coba tangkap JSON mentah jika menggunakan <tool_call> atau raw JSON
            raw_json_match = re.search(r'\{\s*"name"\s*:\s*"([^"]+)"\s*,\s*"arguments"\s*:\s*(\{.*?\})\s*\}', content, re.DOTALL)
            
            if raw_json_match:
                func_name = raw_json_match.group(1).strip()
                args_str = raw_json_match.group(2).strip()
                print(f"[FARIDA] Groq JSON parser (Putaran {turn}): {func_name} | args: {args_str}")
            else:
                # Fallback ke regex <function=name>args</function>
                match = re.search(r"<function=([^>]+)>(.*?)</function>", content)
                if match:
                    func_name = match.group(1).strip()
                    args_str = match.group(2).strip()
                    print(f"[FARIDA] Groq function parser (Putaran {turn}): {func_name} | args: {args_str}")
                else:
                    func_name = None
                    args_str = "{}"
            
            if func_name:
                class _MockFn:
                    name = func_name
                    arguments = args_str if args_str.startswith("{") else f'{{"nopol": "{args_str}"}}'

                class _MockCall:
                    id = f"call_{func_name}"
                    function = _MockFn()

                result = await _execute_fms_tool(_MockCall())
                print(f"[FARIDA] Hasil eksekusi fallback: {result[:50]}...")
                
                if func_name == "generate_chart_image":
                    yield str(result) + "\n\n"
                    tool_content = "GRAFIK BERHASIL DITAMPILKAN SECARA OTOMATIS OLEH SISTEM. Tolong berikan analisis singkat dari grafik ini tanpa membuat link url apa pun lagi."
                else:
                    tool_content = str(result)

                conversation.append({
                    "role": "user",
                    "content": f"[System: Hasil dari {func_name}]:\n{tool_content}",
                })

        # Jika di putaran ini tidak ada pemanggilan tool lagi, keluar dari loop LLM
        if not current_turn_has_tool:
            # Karena ini bukan tool call, ini bisa jadi jawaban final statis.
            break

    # ── Langkah 2: Stream jawaban final ──────────────────────
    if has_tool_call:
        try:
            stream = await client.chat.completions.create(
                model=settings.llm_model,
                messages=conversation,
                temperature=0.7,
                stream=True,
            )
            async for chunk in _stream_filtered(stream):
                yield chunk
        except Exception as e:
            yield f"\n⚠️ [Stream Error]: {str(e)}"
    else:
        # Tidak ada tool call sama sekali sejak putaran pertama
        if response_message.content:
            clean = re.sub(r"<think>.*?</think>", "", response_message.content, flags=re.DOTALL).strip()
            yield clean
