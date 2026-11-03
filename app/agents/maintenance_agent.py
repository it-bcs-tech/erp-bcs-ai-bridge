"""
Maintenance Agent — MARIS
─────────────────────────────────────────────────────────────────
Maintenance & Auto Repair Intelligence System

MARIS adalah asisten AI teknis bengkel & perawatan armada PT BCS Logistics.
Memiliki akses langsung ke database perawatan dan workshop:
- Surat Perintah Kerja / Work Orders (fleet.work_orders)
- Pemeriksaan Pra-Jalan / P2H (fleet.vehicle_inspections)
- Manajemen & Ketebalan Ban Armada (fleet.tires)
- Pengeluaran Suku Cadang & Material Bengkel (fleet.maintenance_dn_header/detail)
- Riwayat Perbaikan & Servis Unit (master.m_unit)
- Mesin Kueri Analitis & Text-to-SQL Aman (execute_analytical_sql)
- Inspeksi Skema Database Dinamis (inspect_table_schema, search_database_tables)
- Pembuatan Grafik & Visualisasi Kerusakan (generate_chart_image)
"""

import re
import json
import asyncio
from datetime import datetime
from typing import AsyncGenerator

from app.llm.llm_client import client, settings
from app.tools.chart_tools import CHART_TOOL_SCHEMA, generate_chart_image
from app.tools.maintenance_tools import (
    get_maintenance_overview,
    get_work_orders,
    get_unit_maintenance_history,
    get_tire_inventory_and_condition,
    get_spareparts_and_dn_usage,
)
from app.tools.analytical_query_tools import (
    execute_analytical_sql,
    inspect_table_schema,
    search_database_tables,
    ERP_CORE_SCHEMA_MAP,
)

# ── Fallback candidate models ─────────────────────────────────────────
CANDIDATE_MODELS = [
    settings.llm_model,
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]
CANDIDATE_MODELS = list(dict.fromkeys([m for m in CANDIDATE_MODELS if m]))


def prune_conversation_history(messages: list[dict], max_history: int = 6) -> list[dict]:
    """Memangkas riwayat obrolan agar tidak memicu TPM/TPD rate limit."""
    if len(messages) <= max_history:
        return messages

    pruned = messages[-max_history:]
    for msg in pruned[:-1]:
        if msg.get("role") == "assistant" and len(msg.get("content", "")) > 500:
            msg["content"] = msg["content"][:300] + "... [ringkasan sebelumnya]"
    return pruned


# ── Definisi Tools untuk LLM ─────────────────────────────────────────

MAINTENANCE_TOOLS = [
    CHART_TOOL_SCHEMA,
    {
        "type": "function",
        "function": {
            "name": "get_maintenance_overview",
            "description": (
                "Ambil ringkasan umum aktivitas bengkel dan perawatan armada terkini: total SPK aktif/dalam proses, "
                "kategori perbaikan, populasi ban armada, dan status inspeksi P2H. "
                "Gunakan saat pengguna menanyakan 'ringkasan bengkel', 'status maintenance hari ini', 'berapa SPK aktif', dsb."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_work_orders",
            "description": (
                "Ambil daftar Surat Perintah Kerja (SPK / Work Orders) bengkel berdasarkan status, nopol unit, atau kategori. "
                "Gunakan saat pengguna menanyakan 'daftar SPK', 'WO yang masih open/proses', 'unit apa saja yang sedang di bengkel', atau mencari SPK unit tertentu."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Status SPK: 'AKTIF', 'OPEN', 'PROSES', 'READY_FOR_REINSPECTION', 'DISPENSATION_ACTIVE', atau 'CLOSED'.",
                    },
                    "unit_id": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nomor polisi atau nomor unit armada (misal: 'A9357TY' atau 'A 9138 R').",
                    },
                    "maint_category": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Kategori servis (misal: 'Regular Repair', 'Corrective Repair (P2H)', 'Periodic Service').",
                    },
                    "keyword": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Kata kunci pencarian nomor SPK, problem, keluhan driver, atau kesimpulan.",
                    },
                    "created_from": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Filter tanggal awal pembuatan/pengerjaan SPK (format 'YYYY-MM-DD', misal '2026-10-26').",
                    },
                    "created_to": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Filter tanggal akhir pembuatan/pengerjaan SPK (format 'YYYY-MM-DD').",
                    },
                    "created_by": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nama user pembuat SPK.",
                    },
                    "limit": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Batas data yang ditampilkan (default: 15, max: 30).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_unit_maintenance_history",
            "description": (
                "Ambil riwayat lengkap perbaikan, servis bengkel, dan riwayat temuan inspeksi untuk satu unit spesifik (nomor polisi). "
                "Gunakan saat pengguna menanyakan 'riwayat servis nopol X', 'apakah truk A9357TY sering rusak', 'histori bengkel mobil A9138R'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nopol": {
                        "type": "string",
                        "description": "Nomor polisi unit (misal: 'A9357TY' atau 'A 9138 R').",
                    },
                },
                "required": ["nopol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_tire_inventory_and_condition",
            "description": (
                "Ambil data populasi dan kondisi ban armada: nomor seri ban, merk ban, ketebalan tapak (tread depth), "
                "serta ban kritis (tapak <= 3.0 mm) yang memerlukan vulkanisir/afkir. "
                "Gunakan saat pengguna menanyakan 'kondisi ban', 'ban botak/kritis', 'stok ban', atau ban merk tertentu."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Status ban: 'MOUNTED', 'SPARE_STOCK', 'RETREADING', 'SCRAP'.",
                    },
                    "brand": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Merk ban (misal: 'Bridgestone', 'Aeolus', 'Gajah Tunggal').",
                    },
                    "only_critical": {
                        "anyOf": [{"type": "boolean"}, {"type": "null"}],
                        "description": "True jika hanya ingin menampilkan ban yang tapaknya menipis/kritis (<= 3.0 mm).",
                    },
                    "limit": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Batas data (default: 10, max: 25).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_spareparts_and_dn_usage",
            "description": (
                "Ambil data pengeluaran suku cadang, material, dan Surat Jalan (Delivery Note) bengkel per SPK atau unit armada. "
                "Gunakan saat pengguna menanyakan 'pemakaian sparepart', 'biaya suku cadang unit X', atau pengeluaran material bengkel."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "wo_no": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nomor Work Order (misal: '01427/WO/WSP/06/2026').",
                    },
                    "target_unit": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nomor polisi unit penerima suku cadang.",
                    },
                    "limit": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Batas data (default: 10, max: 20).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_analytical_sql",
            "description": (
                "Jalankan kueri SQL analitis SELECT kustom secara aman ke database PostgreSQL ERP BCS. "
                "Gunakan tool ini ketika pengguna meminta: "
                "1. Agregasi kustom (SUM biaya sparepart, AVG durasi servis, COUNT kerusakan per kategori). "
                "2. Korelasi cross-module (misal: unit yang sedang servis vs jadwal trip di fleet.trip). "
                "3. Ranking atau tren yang tidak dicakup oleh fungsi standar. "
                "HANYA SELECT / WITH (read-only), dilarang INSERT/UPDATE/DELETE. Selalu gunakan klausa LIMIT <= 50."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql_query": {
                        "type": "string",
                        "description": "Pernyataan SQL SELECT lengkap dan valid.",
                    },
                    "purpose": {
                        "type": "string",
                        "description": "Tujuan analisis singkat dalam bahasa Indonesia.",
                    },
                },
                "required": ["sql_query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_table_schema",
            "description": (
                "Periksa nama kolom, tipe data, dan ambil 2 sampel baris dari tabel database tertentu. "
                "Gunakan jika Anda ragu tentang nama kolom atau struktur tabel sebelum menyusun kueri SQL analitis."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Nama tabel (misal: 'fleet.tires', 'master.m_unit', 'fleet.trip').",
                    },
                    "schema_name": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nama skema database (opsional, misal: 'fleet', 'master', 'operations').",
                    },
                },
                "required": ["table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_database_tables",
            "description": (
                "Cari nama tabel di database PostgreSQL yang cocok dengan kata kunci tertentu. "
                "Gunakan jika Anda mencari tabel terkait data baru (misal: 'vendor', 'invoice', 'toll')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "Kata kunci pencarian nama tabel.",
                    },
                },
                "required": ["keyword"],
            },
        },
    },
]


MARIS_SYSTEM_PROMPT = f"""Anda adalah MARIS (Maintenance & Auto Repair Intelligence System), asisten AI analitis & teknis bengkel perawatan armada PT BCS Logistics.

KEMAMPUAN UTAMA ANDA:
1. Anda bukan sekadar bot FAQ statis; Anda memiliki akses penuh ke database PostgreSQL operasional bengkel dan armada ERP BCS.
2. Selagi data ada di database, Anda MAMPU mengolah, mengagregasi, menggabungkan (JOIN), dan menganalisisnya menjadi informasi bisnis yang bernilai tinggi bagi pengguna.
3. Gunakan kueri analitis aman (`execute_analytical_sql`) untuk pertanyaan kompleks seperti:
   - Menghitung total pengeluaran sparepart per unit armada atau per rentang waktu.
   - Mengidentifikasi unit dengan tingkat kerusakan tertinggi atau keluhan berulang.
   - Menganalisis kondisi ban kritis, merk ban paling awet, atau kebutuhan ban baru.
   - Mengkorelasikan unit bengkel dengan jadwal pengiriman/trip operasional (cross-module awareness).
4. PETA SKEMA TABEL ERP (KNOWLEDGE BASE) di bawah ini SUDAH LENGKAP dengan daftar kolom tabel utama. LANGSUNG jalankan `execute_analytical_sql` pada putaran pertama tanpa membuang waktu memanggil `inspect_table_schema` kecuali untuk tabel yang belum ada di daftar skema.
5. Jika pengguna meminta visualisasi atau grafik perbandingan, panggil tool `generate_chart_image`.

STANDAR STRUKTUR JAWABAN ANDA:
Setiap menjawab pertanyaan analitis, sajikan dengan struktur konsultan profesional:
1. **Ringkasan Eksekutif (Direct Answer)**: Jawaban inti yang lugas dan to-the-point.
2. **Matriks / Tabel Bukti Data**: Angka-angka pendukung, daftar unit, atau metrik terhitung yang rapi dalam Markdown table.
3. **Wawasan & Pola (Key Insights / Red Flags)**: Analisis akar masalah, unit paling rawan, atau anomali yang terdeteksi.
4. **Rekomendasi Tindakan (Actionable Steps)**: Solusi teknis operasional yang perlu dilakukan oleh kepala bengkel atau tim fleet.

PETA SKEMA TABEL ERP (KNOWLEDGE BASE):
{ERP_CORE_SCHEMA_MAP}


## KEMAMPUAN FILTER TANGGAL PEMBUATAN & PEMBUAT DATA (TEMPORAL & CREATOR CAPABILITY):
- Anda memiliki akses langsung ke database PostgreSQL ERP BCS melalui `execute_analytical_sql`.
- Setiap tabel transaksi maupun master memiliki kolom audit `created_at` (waktu data dibuat di sistem) dan `created_by` (user pembuat data), serta tanggal transaksi operasional spesifik.
- Jika pengguna meminta data yang baru dibuat hari ini, 1 minggu terakhir, bulan ini, rentang tanggal tertentu, atau dibuat oleh user/pembuat tertentu:
  Anda DAPAT dan WAJIB menyajikannya menggunakan kueri SQL analitis (`execute_analytical_sql`) dengan filter `WHERE created_at >= ...` atau `WHERE created_by = ...` atau tanggal transaksi terkait.
- DILARANG KERAS mengatakan sistem memiliki batasan tidak bisa memfilter tanggal pembuatan atau pembuat data! Selalu periksa dan gunakan kolom `created_at` dan `created_by`.


BATASAN KETAT:
- JANGAN PERNAH mengatakan "maaf data tidak tersedia" atau "saya tidak punya fitur itu" jika informasi tersebut secara logis dapat dihitung dari tabel database. Gunakan `execute_analytical_sql`!
- Selalu patuhi keamanan read-only (hanya SELECT).
"""


async def _execute_maintenance_tool(tool_call) -> str:
    """Menjalankan fungsi Maintenance tool sesuai permintaan LLM."""
    func_name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
    except Exception:
        args = {}

    try:
        if func_name == "generate_chart_image":
            return await generate_chart_image(**args)
        elif func_name == "get_maintenance_overview":
            return await get_maintenance_overview()
        elif func_name == "get_work_orders":
            return await get_work_orders(**args)
        elif func_name == "get_unit_maintenance_history":
            return await get_unit_maintenance_history(**args)
        elif func_name == "get_tire_inventory_and_condition":
            return await get_tire_inventory_and_condition(**args)
        elif func_name == "get_spareparts_and_dn_usage":
            return await get_spareparts_and_dn_usage(**args)
        elif func_name == "execute_analytical_sql":
            return await execute_analytical_sql(**args)
        elif func_name == "inspect_table_schema":
            return await inspect_table_schema(**args)
        elif func_name == "search_database_tables":
            return await search_database_tables(**args)
        else:
            return f"Error: Tool '{func_name}' tidak dikenali oleh MARIS."
    except Exception as e:
        return f"ERROR eksekusi tool '{func_name}': {str(e)}"


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
                else:
                    yield buffer
                    buffer = ""
            else:
                buffer += token
                if "</think>" in buffer:
                    is_thinking = False
                    buffer = ""


async def process_maintenance_chat(messages: list[dict]) -> AsyncGenerator[str, None]:
    """
    Orkestrasi alur ReAct Multi-Round MARIS:
    1. Prune riwayat obrolan
    2. Multi-turn reasoning loop untuk evaluasi data analitis
    3. Real-time word streaming respon final
    """
    pruned_history = prune_conversation_history(messages, max_history=6)

    now_str = datetime.now().strftime("%d %B %Y (%H:%M WIB)")
    dynamic_prompt = MARIS_SYSTEM_PROMPT + f"\n[INFO SISTEM: Waktu saat ini adalah {now_str}.]\n"

    conversation = [{"role": "system", "content": dynamic_prompt}]
    conversation.extend(pruned_history)

    active_model = CANDIDATE_MODELS[0]
    MAX_ROUNDS = 3
    has_streamed = False

    for round_idx in range(MAX_ROUNDS):
        resp_msg = None
        last_err = None

        for model_name in [active_model] + [m for m in CANDIDATE_MODELS if m != active_model]:
            try:
                resp = await client.chat.completions.create(
                    model=model_name,
                    messages=conversation,
                    tools=MAINTENANCE_TOOLS,
                    tool_choice="auto",
                    temperature=0.1,
                )
                resp_msg = resp.choices[0].message
                active_model = model_name
                break
            except Exception as e:
                err_str = str(e)
                last_err = e
                if "429" in err_str or "rate limit" in err_str.lower() or "413" in err_str or "too large" in err_str.lower():
                    continue
                else:
                    yield f"⚠️ MARIS gagal memproses permintaan: {err_str}"
                    return

        if resp_msg is None:
            yield f"⚠️ Maaf, kapasitas model sedang penuh ({str(last_err)}). Silakan coba lagi."
            return

        if resp_msg.tool_calls:
            conversation.append(resp_msg)
            for tool_call in resp_msg.tool_calls:
                result = await _execute_maintenance_tool(tool_call)

                if tool_call.function.name == "generate_chart_image":
                    yield str(result) + "\n\n"
                    tool_content = "Berhasil membuat dan menyajikan grafik ke layar."
                else:
                    tool_content = str(result)
                    if len(tool_content) > 3500:
                        tool_content = tool_content[:3500] + "\n... [Sebagian data diringkas demi kapasitas token]"

                conversation.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "content": tool_content,
                })
            continue
        else:
            if resp_msg.content:
                clean = re.sub(r"<think>.*?</think>", "", resp_msg.content, flags=re.DOTALL).strip()
                words = clean.split(" ")
                for i, w in enumerate(words):
                    yield w + (" " if i < len(words) - 1 else "")
                    if i % 4 == 0:
                        await asyncio.sleep(0.01)
                has_streamed = True
                return
            else:
                break

    if not has_streamed:
        last_tool_res = ""
        for m in reversed(conversation):
            if m.get("role") == "tool" and m.get("content"):
                last_tool_res = m["content"]
                break
        if last_tool_res:
            yield f"**Hasil Analisis Terkini:**\n\n{last_tool_res}"
        else:
            yield "⚠️ Maaf, tidak ada respon data yang dapat ditampilkan saat ini."
