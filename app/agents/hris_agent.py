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
)
from app.llm.llm_client import client, settings
from typing import AsyncGenerator


# ── 1. Definisi Tools untuk LLM ──────────────────────────────────

HRIS_TOOLS = [
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
    }
]


# ── 2. System Prompt ─────────────────────────────────────────────

SYSTEM_PROMPT = """Anda adalah AI Assistant cerdas bernama "HARIS" untuk PT BCS Logistics.
Tugas Anda adalah membantu tim HR mencari dan menganalisis data karyawan & absensi, serta memberikan edukasi terkait ketenagakerjaan.

## Aturan Penting:
1. Anda DILENGKAPI dengan fungsi/tools (Function Calling). JIKA user meminta data, ANDA WAJIB memanggil tools tersebut. JANGAN PERNAH MENJAWAB TANPA MEMANGGIL TOOL JIKA DATA DIBUTUHKAN.
2. JANGAN PERNAH mengarang angka, nama, atau hasil analisis.
3. Jawab dalam Bahasa Indonesia yang profesional dan ramah. Gunakan emoji.
4. Anda bisa melakukan analisis, merangkum, dan membandingkan data yang dikembalikan oleh tool.
5. 🛡️ PEMBATASAN TOPIK: Anda HANYA diizinkan menjawab pertanyaan seputar HRIS, data karyawan, absensi, perusahaan PT BCS Logistics, dan Undang-Undang Ketenagakerjaan (hukum tenaga kerja, hak pekerja, dsb). JIKA user bertanya di luar topik tersebut (misal: olahraga, politik, resep masakan), TOLAK DENGAN SOPAN. Contoh penolakan: "Maaf, saya adalah asisten HARIS. Saya hanya diprogram untuk membantu urusan HRIS dan Ketenagakerjaan."
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
        else:
            return f"Error: Tool '{func_name}' tidak ditemukan."
    except Exception as e:
        return f"INFO DATABASE: Terjadi kesalahan saat mengambil data: {str(e)}"


async def process_chat(messages: list[dict], db: AsyncSession) -> AsyncGenerator[str, None]:
    """
    1. Kirim prompt + tools ke LLM
    2. Jika LLM memanggil tool, eksekusi tool, dan kembalikan hasilnya ke LLM
    3. Stream jawaban final ke user
    """
    
    now_str = datetime.now().strftime("%d %B %Y (%H:%M)")
    dynamic_system_prompt = SYSTEM_PROMPT + f"\n[INFO SISTEM: Waktu dunia nyata saat ini adalah {now_str}. Jangan pernah berasumsi bahwa saat ini tahun 2024. Gunakan tahun ini (2026 atau seterusnya) sebagai acuan dasar.]\n"

    # 1. Siapkan history percakapan
    conversation = [{"role": "system", "content": dynamic_system_prompt}] + messages
    
    # 2. Panggil LLM
    try:
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=conversation,
            tools=HRIS_TOOLS,
            tool_choice="auto",
            temperature=0.1, # Rendah agar tool calling konsisten
        )
        response_message = response.choices[0].message
    except Exception as e:
        # Jika Groq API throw 400 Tool Use Failed
        error_msg = str(e)
        import re
        failed_tool = re.search(r"failed_generation':\s*'([^']+)'", error_msg)
        if failed_tool:
            func_str = failed_tool.group(1)
            # Fallback jika model gagal pakai format Groq yang benar, paksa ambil data total hari ini
            tool_result = await execute_tool(type('obj', (object,), {'function': type('obj2', (object,), {'name': 'get_attendance_today', 'arguments': '{}'})})(), db)
            yield f"⚠️ (Menggunakan Fallback Engine karena AI salah ketik format)\n\n{tool_result}"
            return
        else:
            yield f"⚠️ AI gagal memproses data: {error_msg}"
            return

    # 3. Apakah LLM memutuskan untuk memanggil tool? (Cek native tool_calls atau format Groq yang bocor)
    has_tool_call = False
    
    if response_message.tool_calls:
        has_tool_call = True
        conversation.append(response_message)
        
        for tool_call in response_message.tool_calls:
            print(f"[HARIS] LLM memanggil tool (Native): {tool_call.function.name} dengan args: {tool_call.function.arguments}")
            tool_result = await execute_tool(tool_call, db)
            
            conversation.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call.function.name,
                "content": str(tool_result),
            })
            
    elif response_message.content and "<function=" in response_message.content:
        # Penanganan khusus jika Groq membocorkan tag <function=...>
        has_tool_call = True
        content = response_message.content
        conversation.append({"role": "assistant", "content": content})
        
        # Ekstrak menggunakan Regex
        matches = re.finditer(r"<function=([^>]+)>(.*?)</function>", content)
        for match in matches:
            func_name = match.group(1).strip()
            args_str = match.group(2).strip()
            print(f"[HARIS] LLM memanggil tool (Groq Parser): {func_name} dengan args: {args_str}")
            
            # Buat mock tool_call object agar bisa diproses execute_tool
            class MockFunction:
                name = func_name
                arguments = args_str if args_str.startswith("{") else f'{{"name": "{args_str}"}}'
            class MockToolCall:
                id = f"call_{func_name}"
                function = MockFunction()
                
            tool_result = await execute_tool(MockToolCall(), db)
            
            conversation.append({
                "role": "user",
                "content": f"[System: Hasil dari {func_name}]:\n{tool_result}",
            })

    if has_tool_call:
        # 4. Stream jawaban final setelah mendapat data
        stream = await client.chat.completions.create(
            model=settings.llm_model,
            messages=conversation,
            temperature=0.7,
            stream=True,
        )
        
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
            
