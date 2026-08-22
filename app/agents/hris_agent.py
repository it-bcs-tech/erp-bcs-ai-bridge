"""
HRIS Agent (Tool-Calling Architecture)
─────────────────────────────────────────
Agent cerdas yang menggunakan Ollama Function Calling.
LLM akan membaca pesan, menentukan tools mana yang perlu dipanggil,
menjalankan tools tersebut, dan merangkum hasilnya.
"""

from sqlalchemy.ext.asyncio import AsyncSession
import json
import re
from datetime import datetime
from app.tools.employees import (
    get_employee_count,
    search_employee_by_name,
    get_employees_by_department,
    get_employees_by_division,
    get_employees_by_status,
    get_employees_by_location,
    get_employee_list,
)
from app.tools.presensi import (
    get_attendance_today,
    get_absent_today,
    get_attendance_monthly,
    get_leave_today,
    get_present_today,
    get_absent_monthly,
)
from app.llm.llm_client import client, settings
from app.tools.chart_tools import CHART_TOOL_SCHEMA, generate_chart_image
from app.llm.tool_router import get_relevant_tools
from typing import AsyncGenerator


# ── 1. Definisi Tools untuk LLM ──────────────────────────────────

HRIS_TOOLS = [
    CHART_TOOL_SCHEMA,
    {
        "type": "function",
        "function": {
            "name": "search_employee_by_name",
            "description": "Cari data spesifik seorang karyawan berdasarkan nama. Gunakan ini jika user menanyakan tentang seseorang tertentu (misal: Asep, Budi).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nama karyawan yang dicari"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_attendance_today",
            "description": "Ambil rekap total kehadiran (hadir, absen, izin, sakit) untuk hari ini.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_present_today",
            "description": "Dapatkan daftar nama karyawan yang HADIR (sudah absen/clock-in) hari ini beserta jam masuknya.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_absent_today",
            "description": "Dapatkan daftar nama karyawan yang absen, izin, sakit, atau cuti hari ini.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "enum": ["izin", "sakit", "alpha", "cuti", "mangkir"], "description": "Filter alasan ketidakhadiran."},
                    "location": {"type": "string", "description": "Opsional. Filter berdasarkan lokasi."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_attendance_monthly",
            "description": "Ambil rekap total kehadiran bulan ini, TERMASUK DAFTAR NAMA KARYAWAN beserta peringkat dan jumlah kehadirannya.",
            "parameters": {
                "type": "object",
                "properties": {
                    "month": {"type": "integer", "description": "Angka bulan (1-12)."},
                    "year": {"type": "integer", "description": "Angka tahun (contoh: 2026)."},
                    "employee_id": {"type": "string", "description": "Opsional. Payroll ID atau NIK karyawan."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_employee_count",
            "description": "Dapatkan total jumlah seluruh karyawan.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_employees_by_department",
            "description": "Cari daftar karyawan berdasarkan nama departemen, ATAU dapatkan ringkasan jumlah karyawan di SEMUA departemen (jika parameter department dikosongkan).",
            "parameters": {
                "type": "object",
                "properties": {
                    "department": {"type": "string", "description": "Nama departemen. Kosongkan untuk mendapatkan peringkat jumlah karyawan semua departemen."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_absent_monthly",
            "description": "Ambil rekap kumulatif daftar karyawan yang tidak hadir (cuti, sakit, izin) pada bulan tertentu beserta detail berapa kali pengajuannya.",
            "parameters": {
                "type": "object",
                "properties": {
                    "month": {"type": "integer", "description": "Angka bulan (1-12)."},
                    "year": {"type": "integer", "description": "Angka tahun (contoh: 2026)."},
                    "reason": {"type": "string", "enum": ["izin", "sakit", "cuti", "semua"], "description": "Filter alasan ketidakhadiran kumulatif."}
                }
            }
        }
    }
]


# ── 2. System Prompt ─────────────────────────────────────────────

SYSTEM_PROMPT = """Anda adalah AI Assistant cerdas bernama "HARIS" untuk PT BCS Logistics.
Tugas Anda adalah membantu tim HR mencari dan menganalisis data karyawan & absensi, serta memberikan edukasi terkait ketenagakerjaan.

## Aturan Penting:
1. Anda DILENGKAPI dengan fungsi/tools (Function Calling). JIKA user meminta data, ANDA WAJIB memanggil tools tersebut secara sistemik. JANGAN PERNAH mengetikkan niat Anda seperti "Menggunakan Function: X" atau mencetak parameter JSON mentah ke dalam teks balasan! Cukup panggil alatnya di latar belakang!
2. JANGAN PERNAH mengarang angka, nama, atau hasil analisis.
3. Jawab dalam Bahasa Indonesia yang profesional dan ramah. Gunakan emoji.
4. Anda bisa melakukan analisis, merangkum, dan membandingkan data yang dikembalikan oleh tool.
5. 🛡️ PEMBATASAN TOPIK SANGAT KETAT: Anda HANYA diizinkan menjawab pertanyaan seputar HRIS, data karyawan, absensi, perusahaan PT BCS Logistics, dan Undang-Undang Ketenagakerjaan. JIKA pengguna bertanya di luar topik tersebut, tolak dengan sopan.
6. 📊 VISUALISASI GRAFIK: Jika pengguna meminta grafik, panggil tool `generate_chart_image`. DILARANG KERAS mencetak markdown gambar/URL secara manual.
"""


# ── 3. Proses Chat & Eksekusi Tool ────────────────────────────────

async def execute_tool(tool_call, db: AsyncSession) -> str:
    """Menjalankan fungsi Python sesuai permintaan LLM."""
    func_name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments)
    except:
        args = {}

    try:
        if func_name == "search_employee_by_name":
            return await search_employee_by_name(db, name=args.get("name"))
        elif func_name == "get_attendance_today":
            return await get_attendance_today(db, location=args.get("location"))
        elif func_name == "get_absent_today":
            return await get_absent_today(db, reason=args.get("reason"), location=args.get("location"))
        elif func_name == "generate_chart_image":
            return await generate_chart_image(**args)
        elif func_name == "get_attendance_monthly":
            return await get_attendance_monthly(db, month=args.get("month"), year=args.get("year"), employee_id=args.get("employee_id"))
        elif func_name == "get_employee_count":
            return await get_employee_count(db)
        elif func_name == "get_employees_by_department":
            return await get_employees_by_department(db, department=args.get("department"))
        elif func_name == "get_leave_today":
            return await get_leave_today(db)
        elif func_name == "get_present_today":
            return await get_present_today(db, location=args.get("location"))
        elif func_name == "get_absent_monthly":
            return await get_absent_monthly(db, month=args.get("month"), year=args.get("year"), reason=args.get("reason"))
        else:
            return f"Error: Tool '{func_name}' tidak ditemukan."
    except Exception as e:
        return f"INFO DATABASE: Terjadi kesalahan saat mengambil data: {str(e)}"


async def process_hris_chat(messages: list[dict], db: AsyncSession) -> AsyncGenerator[str, None]:
    now_str = datetime.now().strftime("%d %B %Y (%H:%M WIB)")
    dynamic_prompt = (
        SYSTEM_PROMPT
        + f"\n[INFO SISTEM: Waktu sekarang adalah {now_str}.]\n"
    )

    conversation = [{"role": "system", "content": dynamic_prompt}] + messages

    # ── Langkah 0: Pemilihan Alat Dinamis (Intent Routing) ──
    # Ambil pesan terakhir dari user
    last_user_msg = ""
    for m in reversed(messages):
        if m["role"] == "user":
            last_user_msg = m["content"]
            break
            
    active_tools = await get_relevant_tools(last_user_msg, HRIS_TOOLS)
    if active_tools:
        print(f"[HARIS Router] Mengaktifkan alat: {[t['function']['name'] for t in active_tools]}")
    else:
        print("[HARIS Router] Pertanyaan umum terdeteksi. Tidak ada alat yang diaktifkan (Hemat Token).")

    # ── Langkah 1: Loop Pemanggilan LLM (Maksimal 3 Putaran Tool) ─────────
    max_tool_turns = 3
    turn = 0
    has_tool_call = False
    response_message = None

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
            yield f"⚠️ HARIS gagal memproses permintaan: {error_msg}"
            return

        current_turn_has_tool = False

        if response_message.tool_calls:
            current_turn_has_tool = True
            has_tool_call = True
            conversation.append(response_message)
            
            for tool_call in response_message.tool_calls:
                print(f"[HARIS] LLM memanggil tool (Putaran {turn}): {tool_call.function.name} dengan args: {tool_call.function.arguments}")
                result = await execute_tool(tool_call, db)
                
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
                
        elif response_message.content and ("<function=" in response_message.content or "<tool_call>" in response_message.content or '{"name":' in response_message.content):
            current_turn_has_tool = True
            has_tool_call = True
            content = response_message.content
            conversation.append({"role": "assistant", "content": content})

            # Coba tangkap JSON mentah
            raw_json_match = re.search(r'\{\s*"name"\s*:\s*"([^"]+)"\s*,\s*"arguments"\s*:\s*(\{.*?\})\s*\}', content, re.DOTALL)
            
            if raw_json_match:
                func_name = raw_json_match.group(1).strip()
                args_str = raw_json_match.group(2).strip()
                print(f"[HARIS] Groq JSON parser (Putaran {turn}): {func_name} | args: {args_str}")
            else:
                match = re.search(r"<function=([^>]+)>(.*?)</function>", content)
                if match:
                    func_name = match.group(1).strip()
                    args_str = match.group(2).strip()
                    print(f"[HARIS] Groq function parser (Putaran {turn}): {func_name} | args: {args_str}")
                else:
                    func_name = None
                    args_str = "{}"
            
            if func_name:
                class _MockFn:
                    name = func_name
                    arguments = args_str if args_str.startswith("{") else f'{{"name": "{args_str}"}}'
                class _MockCall:
                    id = f"call_{func_name}"
                    function = _MockFn()

                result = await execute_tool(_MockCall(), db)
                
                if func_name == "generate_chart_image":
                    yield str(result) + "\n\n"
                    tool_content = "GRAFIK BERHASIL DITAMPILKAN SECARA OTOMATIS OLEH SISTEM. Tolong berikan analisis singkat dari grafik ini tanpa membuat link url apa pun lagi."
                else:
                    tool_content = str(result)
                    
                conversation.append({
                    "role": "user",
                    "content": f"[System: Hasil dari {func_name}]:\n{tool_content}",
                })

        if not current_turn_has_tool:
            break

    # ── Langkah 2: Stream jawaban final ke frontend ────────────────
    if has_tool_call:
        try:
            stream_kwargs = {
                "model": settings.llm_model,
                "messages": conversation,
                "temperature": 0.7,
                "stream": True,
            }
            if active_tools:
                stream_kwargs["tools"] = active_tools
                stream_kwargs["tool_choice"] = "auto"

            stream = await client.chat.completions.create(**stream_kwargs)
        except Exception as e:
            yield f"\n⚠️ [Stream Error]: {str(e)}"
            return
        # State machine untuk menyembunyikan tag <think>...</think>
        buffer = ""
        is_thinking = False
        
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                token = chunk.choices[0].delta.content
                if not is_thinking:
                    buffer += token
                    if "<think>" in buffer:
                        is_thinking = True
                        clean_text = buffer.split("<think>")[0]
                        if clean_text:
                            yield clean_text
                        buffer = ""
                    elif len(buffer) > 8:
                        yield buffer
                        buffer = ""
                else:
                    buffer += token
                    if "</think>" in buffer:
                        is_thinking = False
                        clean_text = buffer.split("</think>")[1].lstrip('\n')
                        if clean_text:
                            yield clean_text
                        buffer = ""
                        
        if buffer and not is_thinking:
            yield buffer

    else:
        # Jika tidak memanggil tool, filter think tag dari pesan statis (Non-stream fallback)
        if response_message.content:
            content = response_message.content
            import re
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            yield content
            
