"""
HRIS Agent (Tool-Calling Architecture)
─────────────────────────────────────────
Agent cerdas yang menggunakan Ollama Function Calling.
LLM akan membaca pesan, menentukan tools mana yang perlu dipanggil,
menjalankan tools tersebut, dan merangkum hasilnya.
"""

from sqlalchemy.ext.asyncio import AsyncSession
import asyncio
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
    get_employee_full_profile,
    get_people_analytics,
)
from app.tools.presensi import (
    get_attendance_today,
    get_absent_today,
    get_attendance_monthly,
    get_leave_today,
    get_present_today,
    get_absent_monthly,
    get_employee_attendance_logs,
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
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Opsional. Filter berdasarkan lokasi atau cabang kerja."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_present_today",
            "description": "Dapatkan daftar nama karyawan yang HADIR (sudah absen/clock-in) hari ini beserta jam masuknya.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Opsional. Filter berdasarkan lokasi atau cabang kerja."
                    }
                }
            }
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
                    "reason": {
                        "anyOf": [
                            {"type": "string", "enum": ["izin", "sakit", "alpha", "cuti", "mangkir"]},
                            {"type": "null"}
                        ],
                        "description": "Opsional. Filter alasan ketidakhadiran."
                    },
                    "location": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Opsional. Filter berdasarkan lokasi."
                    }
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
                    "month": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Opsional. Angka bulan (1-12) atau null untuk bulan berjalan."
                    },
                    "year": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Opsional. Angka tahun (contoh: 2026) atau null untuk tahun berjalan."
                    },
                    "employee_id": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Opsional. Payroll ID atau NIK karyawan."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_employee_count",
            "description": "Dapatkan total jumlah seluruh karyawan berdasarkan status dan jenis kelamin.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_employees_by_department",
            "description": "Cari daftar karyawan berdasarkan nama departemen, ATAU dapatkan ringkasan jumlah karyawan di SEMUA departemen (jika parameter department dikosongkan/null).",
            "parameters": {
                "type": "object",
                "properties": {
                    "department": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Opsional. Nama departemen. Kosongkan atau null untuk mendapatkan peringkat jumlah karyawan semua departemen."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_employees_by_division",
            "description": "Cari daftar karyawan berdasarkan nama divisi, ATAU ringkasan seluruh divisi.",
            "parameters": {
                "type": "object",
                "properties": {
                    "division": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Opsional. Nama divisi atau null."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_employees_by_status",
            "description": "Ambil daftar karyawan berdasarkan status kepegawaian (PERMANENT, CONTRACT, MITRA KERJA, dll).",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Opsional. Status kepegawaian (contoh: 'CONTRACT', 'PERMANENT') atau null."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_employees_by_location",
            "description": "Ambil daftar karyawan berdasarkan lokasi kantor atau penempatan kerja.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Opsional. Nama lokasi/cabang kerja (contoh: 'Cilegon', 'Head Office') atau null."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_employee_list",
            "description": "Dapatkan daftar seluruh karyawan aktif dengan batas limit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Opsional. Batas jumlah karyawan yang ditampilkan (default: 15)."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_leave_today",
            "description": "Dapatkan daftar nama karyawan yang sedang cuti hari ini.",
            "parameters": {"type": "object", "properties": {}}
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
                    "month": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Opsional. Angka bulan (1-12) atau null untuk bulan berjalan."
                    },
                    "year": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Opsional. Angka tahun (contoh: 2026) atau null untuk tahun berjalan."
                    },
                    "reason": {
                        "anyOf": [
                            {"type": "string", "enum": ["izin", "sakit", "cuti", "semua"]},
                            {"type": "null"}
                        ],
                        "description": "Opsional. Filter alasan ketidakhadiran kumulatif."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_employee_attendance_logs",
            "description": (
                "Ambil log presensi detail & status kedisiplinan (keterlambatan / telat masuk / jam datang) seorang karyawan "
                "pada bulan dan tahun tertentu. Gunakan jika user menanyakan keterlambatan (misal: 'apakah ada telat masuk?', "
                "'berapa kali terlambat?', 'jam masuk'), atau riwayat presensi individual karyawan."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name_or_id": {
                        "type": "string",
                        "description": "Nama karyawan atau Payroll ID / NIK yang dicari (contoh: 'Adi Fuadil Hidayah', '2504.4238')."
                    },
                    "month": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Opsional. Angka bulan (1-12) atau null jika ingin melihat riwayat bulan berjalan/umum."
                    },
                    "year": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Opsional. Angka tahun (contoh: 2026) atau null jika ingin melihat riwayat tahun berjalan."
                    },
                    "only_late": {
                        "anyOf": [{"type": "boolean"}, {"type": "null"}],
                        "description": "Opsional. Set True jika hanya ingin melihat daftar hari ketika karyawan datang terlambat saja."
                    }
                },
                "required": ["name_or_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_employee_full_profile",
            "description": (
                "Dapatkan profil lengkap karyawan: status kerja, jabatan, divisi, departemen, lokasi kerja, tanggal bergabung, "
                "masa kerja (tenure), masa berlaku kontrak, sisa saldo kuota cuti tahunan, dan kontak. "
                "PERINGATAN: Tidak menyertakan nominal gaji/finansial demi kepatuhan privasi."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name_or_id": {
                        "type": "string",
                        "description": "Nama karyawan atau Payroll ID / NIK karyawan."
                    }
                },
                "required": ["name_or_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_people_analytics",
            "description": (
                "Lakukan analisis SDM dan monitoring: deteksi karyawan yang kontrak kerjanya akan habis dalam 30-60 hari, "
                "rekap karyawan yang berulang tahun bulan ini, atau peringatan masa kerja / work anniversary bulan ini."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["contracts_expiring", "birthdays", "anniversaries"],
                        "description": "Kategori analitik: 'contracts_expiring' (kontrak habis), 'birthdays' (ulang tahun bulan ini), 'anniversaries' (work anniversary)."
                    },
                    "days": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Opsional untuk 'contracts_expiring'. Rentang hari ke depan (contoh: 30 atau 60 hari)."
                    },
                    "month": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Opsional untuk 'birthdays' & 'anniversaries'. Angka bulan (1-12)."
                    }
                },
                "required": ["category"]
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

## 🔒 KEBIJAKAN PRIVASI & KERAHASIAAN DATA GAJI (STRICT SALARY GUARDRAIL):
- Informasi mengenai gaji pokok, slip gaji, nominal take home pay (THP), tunjangan finansial, bonus, dan pinjaman/kasbon karyawan bersifat SANGAT RAHASIA (CONFIDENTIAL).
- Anda DILARANG KERAS memberikan data nominal uang, slip gaji, atau perkiraan gaji karyawan kepada siapapun.
- Jika pengguna menanyakan perihal gaji, nominal uang, atau slip gaji (misal: "berapa gaji si X?", "minta slip gaji si Y", "berapa take home pay Z?"), Anda WAJIB menolak dengan sopan:
  "Mohon maaf, informasi mengenai nominal gaji, slip gaji, dan kompensasi finansial bersifat rahasia perusahaan dan tidak dapat diakses melalui asisten AI demi menjaga privasi dan kepatuhan kebijakan perusahaan."

## 🎯 PANDUAN PENGGUNAAN TOOLS KHUSUS:
- Jika pengguna menanyakan status kedisiplinan, keterlambatan, jam masuk, atau telat datang seorang karyawan (misal: "apakah ada telat masuk?", "berapa kali terlambat bulan ini?"), WAJIB panggil tool `get_employee_attendance_logs`.
- Jika pengguna meminta profil lengkap, biodata detail, masa kerja (tenure), masa berlaku kontrak, atau sisa saldo cuti seorang karyawan, WAJIB panggil tool `get_employee_full_profile`.
- Jika pengguna menanyakan ulang tahun karyawan, masa bakti (work anniversary), atau kontrak yang akan habis, WAJIB panggil tool `get_people_analytics`.
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
        elif func_name == "get_employee_attendance_logs":
            return await get_employee_attendance_logs(
                db,
                name_or_id=args.get("name_or_id", ""),
                month=args.get("month"),
                year=args.get("year"),
                only_late=args.get("only_late", False),
            )
        elif func_name == "get_employee_full_profile":
            return await get_employee_full_profile(db, name_or_id=args.get("name_or_id", ""))
        elif func_name == "get_people_analytics":
            return await get_people_analytics(
                db,
                category=args.get("category", ""),
                days=args.get("days", 60),
                month=args.get("month"),
            )
        elif func_name == "get_employee_count":
            return await get_employee_count(db)
        elif func_name == "get_employees_by_department":
            return await get_employees_by_department(db, department=args.get("department"))
        elif func_name == "get_employees_by_division":
            return await get_employees_by_division(db, division=args.get("division"))
        elif func_name == "get_employees_by_status":
            return await get_employees_by_status(db, status=args.get("status"))
        elif func_name == "get_employees_by_location":
            return await get_employees_by_location(db, location=args.get("location"))
        elif func_name == "get_employee_list":
            return await get_employee_list(db, limit=args.get("limit") or 20)
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


def prune_conversation_history(messages: list[dict], max_history: int = 6, max_assistant_chars: int = 600) -> list[dict]:
    """
    Mengoptimalkan riwayat percakapan untuk menghemat token (Token Optimization):
    1. Membuang pesan error sistem (misal: ⚠️ HARIS mengalami antrian...)
    2. Mengambil maksimal N pesan terakhir (Sliding Context Window)
    3. Meringkas respon asisten yang terlalu panjang dari putaran sebelumnya
    """
    clean = []
    for m in messages:
        c = m.get("content", "")
        if isinstance(c, str) and (c.strip().startswith("⚠️") or "Error code:" in c):
            continue
        clean.append(m)

    sliced = clean[-max_history:]
    pruned = []
    for i, m in enumerate(sliced):
        role = m.get("role")
        content = m.get("content", "")
        if role == "assistant" and isinstance(content, str) and len(content) > max_assistant_chars and i < len(sliced) - 1:
            pruned.append({
                "role": role,
                "content": content[:max_assistant_chars] + "\n\n...[Ringkasan data tabel sebelumnya untuk konteks]..."
            })
        else:
            pruned.append(m)
    return pruned


async def process_hris_chat(messages: list[dict], db: AsyncSession) -> AsyncGenerator[str, None]:
    now_str = datetime.now().strftime("%d %B %Y (%H:%M WIB)")
    dynamic_prompt = (
        SYSTEM_PROMPT
        + f"\n[INFO SISTEM: Waktu sekarang adalah {now_str}.]\n"
    )

    optimized_messages = prune_conversation_history(messages, max_history=6, max_assistant_chars=600)
    conversation = [{"role": "system", "content": dynamic_prompt}] + optimized_messages

    # ── Langkah 0: Pemilihan Alat Dinamis (Intent Routing) ──
    # Ambil pesan terakhir dari user
    last_user_msg = ""
    for m in reversed(messages):
        if m["role"] == "user":
            last_user_msg = m["content"]
            break
            
    # Gabungkan 2 pesan user terakhir untuk menangkap konteks multi-turn (misal: 'karyawan tersebut', 'dia')
    recent_user_msgs = [m["content"] for m in messages if m.get("role") == "user"][-2:]
    combined_user_text = " ".join(recent_user_msgs) if recent_user_msgs else last_user_msg
            
    active_tools = await get_relevant_tools(combined_user_text, HRIS_TOOLS)
    if active_tools:
        print(f"[HARIS Router] Mengaktifkan alat: {[t['function']['name'] for t in active_tools]}")
    else:
        print("[HARIS Router] Pertanyaan umum terdeteksi. Tidak ada alat yang diaktifkan (Hemat Token).")

    # ── Langkah 1: Loop Pemanggilan LLM (Maksimal 10 Putaran Tool) ─────────
    max_tool_turns = 10
    turn = 0
    has_tool_call = False
    response_message = None
    final_content = None
    current_model = settings.llm_model

    while turn < max_tool_turns:
        turn += 1
        try:
            if active_tools:
                response = await client.chat.completions.create(
                    model=current_model,
                    messages=conversation,
                    tools=active_tools,
                    tool_choice="auto",
                    temperature=0.1,
                )
            else:
                response = await client.chat.completions.create(
                    model=current_model,
                    messages=conversation,
                    temperature=0.7,
                )
            
            response_message = response.choices[0].message

        except Exception as e:
            error_msg = str(e)

            # Auto-fallback jika model terkena Rate Limit (429) atau Request Too Large (413)
            err_lower = error_msg.lower()
            if "429" in error_msg or "413" in error_msg or "rate_limit" in err_lower or "request too large" in err_lower or "tokens per minute" in err_lower:
                print(f"[HARIS] Limit terdeteksi pada {current_model} ({error_msg[:100]}). Mencoba fallback model...")
                if "413" in error_msg or "request too large" in err_lower or "tokens per minute" in err_lower:
                    conversation = [{"role": "system", "content": dynamic_prompt}, messages[-1]]

                candidate_models = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
                recovered_via_fallback = False
                for fb_m in candidate_models:
                    if fb_m != current_model:
                        try:
                            print(f"[HARIS] Mengalihkan turn {turn} ke model fallback: {fb_m}")
                            if active_tools:
                                response = await client.chat.completions.create(
                                    model=fb_m,
                                    messages=conversation,
                                    tools=active_tools,
                                    tool_choice="auto",
                                    temperature=0.1,
                                )
                            else:
                                response = await client.chat.completions.create(
                                    model=fb_m,
                                    messages=conversation,
                                    temperature=0.7,
                                )
                            response_message = response.choices[0].message
                            current_model = fb_m
                            recovered_via_fallback = True
                            break
                        except Exception as fb_err:
                            print(f"[HARIS] Fallback {fb_m} gagal: {fb_err}")
                if recovered_via_fallback:
                    error_msg = ""
                else:
                    yield f"⚠️ HARIS mengalami antrian kuota provider (Rate Limit): {error_msg}"
                    return

            failed_gen = None
            if hasattr(e, "body") and isinstance(e.body, dict):
                failed_gen = e.body.get("failed_generation")
            elif hasattr(e, "response"):
                try:
                    resp_json = e.response.json()
                    failed_gen = resp_json.get("error", {}).get("failed_generation")
                except Exception:
                    pass

            if failed_gen:
                try:
                    fg_data = json.loads(failed_gen) if isinstance(failed_gen, str) else failed_gen
                    func_name = fg_data.get("name")
                    args_dict = fg_data.get("arguments", {})
                    print(f"[HARIS] Self-healing recovered tool call from failed_generation: {func_name} | args: {args_dict}")

                    class _MockFn:
                        name = func_name
                        arguments = json.dumps(args_dict)

                    class _MockToolCall:
                        id = f"call_rec_{turn}_{func_name}"
                        type = "function"
                        function = _MockFn()

                    class _MockMsg:
                        role = "assistant"
                        content = None
                        tool_calls = [_MockToolCall()]

                    response_message = _MockMsg()
                except Exception as rec_err:
                    print(f"[HARIS] Could not recover from failed_generation: {rec_err}")
                    response_message = None

            if response_message is None:
                if "which was not in request.tools" in error_msg:
                    print(f"[HARIS] Tool call validation error detected. Self-healing retry with all HRIS_TOOLS...")
                    active_tools = HRIS_TOOLS
                    try:
                        response = await client.chat.completions.create(
                            model=current_model,
                            messages=conversation,
                            tools=active_tools,
                            tool_choice="auto",
                            temperature=0.1,
                        )
                        response_message = response.choices[0].message
                    except Exception as inner_e:
                        yield f"⚠️ HARIS gagal memproses permintaan: {str(inner_e)}"
                        return
                else:
                    yield f"⚠️ HARIS gagal memproses permintaan: {error_msg}"
                    return


        current_turn_has_tool = False

        if response_message.tool_calls:
            current_turn_has_tool = True
            has_tool_call = True
            if isinstance(response_message, dict):
                conversation.append(response_message)
            elif hasattr(response_message, "function_call"):
                conversation.append(response_message)
            else:
                conversation.append({
                    "role": "assistant",
                    "content": getattr(response_message, "content", None),
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            }
                        }
                        for tc in (response_message.tool_calls or [])
                    ]
                })
            
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
            if response_message and response_message.content:
                final_content = response_message.content
            break

    # ── Langkah 2: Pastikan jawaban final tersedia ────────────────
    if not final_content:
        if has_tool_call:
            conversation.append({
                "role": "user",
                "content": "Tolong rangkum semua data yang sudah diperoleh di atas ke dalam format yang rapi dan lengkap untuk pengguna.",
            })
            candidate_models = [current_model, "openai/gpt-oss-20b", "qwen/qwen3.8-27b", "openai/gpt-oss-120b"]
            candidate_models = list(dict.fromkeys(candidate_models))
            
            for m_candidate in candidate_models:
                try:
                    synth = await client.chat.completions.create(
                        model=m_candidate,
                        messages=conversation,
                        temperature=0.3,
                    )
                    final_content = synth.choices[0].message.content or ""
                    if final_content:
                        break
                except Exception as e:
                    print(f"[HARIS Synthesis] Model {m_candidate} gagal: {e}")
                    if "429" in str(e) or "rate_limit" in str(e).lower():
                        continue
                    else:
                        yield f"\n⚠️ [Sintesis Error]: {str(e)}"
                        return

            if not final_content:
                final_content = "Maaf, sistem sedang mengalami antrian batas kuota AI provider. Silakan coba sesaat lagi."
        elif response_message and response_message.content:
            final_content = response_message.content
        else:
            final_content = "Maaf, tidak ada informasi yang dapat ditampilkan."

    # ── Langkah 3: Stream teks final ke frontend dengan efek mengetik ────────────────
    clean_content = re.sub(r"<think>.*?</think>", "", final_content, flags=re.DOTALL).strip()
    words = clean_content.split(" ")
    chunk_buffer = []
    for i, word in enumerate(words):
        chunk_buffer.append(word)
        if len(chunk_buffer) >= 3 or i == len(words) - 1:
            chunk_str = " ".join(chunk_buffer) + (" " if i < len(words) - 1 else "")
            yield chunk_str
            chunk_buffer = []
            await asyncio.sleep(0.015)

            
