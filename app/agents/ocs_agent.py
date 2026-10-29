"""
OCS Agent — ORIS
─────────────────────────────────────────────────────────────────
Operations Resource Intelligence System

ORIS adalah asisten AI operasional logistik & dispatch untuk PT BCS Logistics.
Memiliki akses langsung ke database operasional:
- Target Rencana Harian (operations.contract_daily_plan)
- Target Bulanan Kontrak (operations.contract_monthly_targets)
- Penugasan Trip & Dispatch (fleet.trip)
- Bukti Serah Terima / POD (operations.proof_of_delivery)
- Master Pelanggan (master.m_customer)
- Kesiapan & Perawatan Unit Bengkel (fleet.work_orders, master.m_unit)
- Mesin Kueri Analitis & Text-to-SQL Aman (execute_analytical_sql)
- Inspeksi Skema Database Dinamis (inspect_table_schema, search_database_tables)
- Pembuatan Grafik & Diagram Visual (generate_chart_image)
"""

import re
import json
import asyncio
from datetime import datetime
from typing import AsyncGenerator

from app.llm.llm_client import client, settings
from app.tools.chart_tools import CHART_TOOL_SCHEMA, generate_chart_image
from app.tools.ocs_tools import (
    get_daily_operational_plan,
    get_active_trips_and_dispatch,
    get_proof_of_delivery_status,
    get_monthly_contract_targets,
    get_customer_and_partner_info,
    get_fleet_maintenance_and_readiness,
    check_unit_dispatch_eligibility,
)
from app.tools.analytical_query_tools import (
    execute_analytical_sql,
    inspect_table_schema,
    search_database_tables,
    ERP_CORE_SCHEMA_MAP,
)

# ── Fallback candidate models jika model utama limit/429/413 ─────────
CANDIDATE_MODELS = [
    settings.llm_model,
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]
# Hapus duplikat sambil mempertahankan urutan
CANDIDATE_MODELS = list(dict.fromkeys([m for m in CANDIDATE_MODELS if m]))


def prune_conversation_history(messages: list[dict], max_history: int = 6) -> list[dict]:
    """
    Memangkas riwayat obrolan agar tidak memicu TPM/TPD rate limit.
    Menyimpan pesan-pesan terakhir dan memadatkan respons asisten lama.
    """
    if len(messages) <= max_history:
        return messages

    pruned = messages[-max_history:]
    for msg in pruned[:-1]:
        if msg.get("role") == "assistant" and len(msg.get("content", "")) > 500:
            msg["content"] = msg["content"][:300] + "... [ringkasan sebelumnya]"
    return pruned


# ── Definisi Tools untuk LLM ───────────────────────────────────────

OCS_TOOLS = [
    CHART_TOOL_SCHEMA,
    {
        "type": "function",
        "function": {
            "name": "get_daily_operational_plan",
            "description": (
                "Ambil rencana harian operasional logistik: target ritase, target tonase, dan kebutuhan unit per kontrak/pelanggan. "
                "Gunakan saat pengguna menanyakan 'rencana harian', 'daily plan hari ini', 'target pengiriman', atau mencari rencana kontrak tertentu."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_date": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Tanggal rencana format 'YYYY-MM-DD'. Kosongkan untuk rencana terdekat/terbaru.",
                    },
                    "contract_id": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "ID kontrak spesifik jika ada.",
                    },
                    "limit": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Batas jumlah data (default 10).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_active_trips_and_dispatch",
            "description": (
                "Ambil status perjalanan trip/surat tugas armada: unit nopol, supir, tujuan, muatan, dan status perjalanan "
                "(Scheduled, En Route, Arrived, Delivered, Completed). "
                "Gunakan saat pengguna menanyakan 'truk yang sedang jalan', 'status trip', 'siapa driver pengiriman', atau 'jadwal kirim hari ini'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Status trip: 'AKTIF', 'SCHEDULED', 'EN_ROUTE', 'ARRIVED', 'DELIVERED', 'COMPLETED'.",
                    },
                    "driver_nama": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nama driver untuk filter.",
                    },
                    "unit_id": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nomor plat/nopol unit jika mencari trip armada tertentu.",
                    },
                    "limit": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Batas jumlah data (default 10, max 25).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_proof_of_delivery_status",
            "description": (
                "Ambil bukti serah terima (Proof of Delivery / POD) barang: status penerimaan, penerima barang, catatan kendala muatan di tujuan. "
                "Gunakan saat pengguna menanyakan 'status POD', 'apakah muatan sudah sampai/diterima', 'cek surat jalan yang belum upload POD'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pod_number": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nomor POD jika spesifik.",
                    },
                    "status": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Status POD: 'RECEIVED', 'PENDING', 'REJECTED'.",
                    },
                    "limit": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Batas data (default 10).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_monthly_contract_targets",
            "description": (
                "Ambil target bulanan kontrak logistik: target tonase bulanan, target ritase, dan unit armada yang dibutuhkan per kontrak. "
                "Gunakan saat pengguna menanyakan 'target bulanan', 'pencapaian kontrak bulan ini', atau analisis beban kerja per pelanggan."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "period_year": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Tahun target (misal: 2026).",
                    },
                    "period_month": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Bulan target (1-12).",
                    },
                    "contract_id": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "ID kontrak spesifik.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_and_partner_info",
            "description": (
                "Ambil daftar dan rincian pelanggan/mitra logistik: nama customer, tier pelanggan (Platinum/Gold/Silver/Standard), kontak, dan status aktif. "
                "Gunakan saat pengguna menanyakan 'daftar customer', 'pelanggan Platinum', 'siapa saja rekanan logistik'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nama customer yang dicari.",
                    },
                    "customer_type": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Tier customer: 'PLATINUM', 'GOLD', 'SILVER', 'STANDARD'.",
                    },
                    "limit": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Batas data (default 10).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fleet_maintenance_and_readiness",
            "description": (
                "Ambil data status kesiapan armada operasional dan kondisi perawatan bengkel: "
                "unit mana saja yang siap jalan (Available), unit yang sedang tertahan di bengkel (Open/In Progress Maintenance/Work Orders), "
                "serta unit dengan kendala teknis. Gunakan saat pengguna menanyakan 'berapa truk siap jalan', 'unit yang sedang rusak/diservis', atau 'kesiapan armada hari ini'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status_filter": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Filter status: 'BENGKEL' (hanya yang sedang diservis), 'SIAP' (siap jalan/bebas servis), atau 'ALL'.",
                    },
                    "limit": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Batas data yang ditampilkan (default 10).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_unit_dispatch_eligibility",
            "description": (
                "Periksa apakah satu unit spesifik (berdasarkan plat nomor/nopol) layak dan siap untuk di-dispatch operasional hari ini. "
                "Memeriksa apakah unit terdaftar aktif dan apakah sedang ada Work Order (SPK) perbaikan aktif di bengkel. "
                "Gunakan saat pengguna menanyakan 'apakah unit A 9357 TY bisa jalan?', 'cek mobil B 9012 ABC siap kirim atau tidak'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nopol": {
                        "type": "string",
                        "description": "Nomor polisi unit yang dicek, contoh: 'A 9357 TY' atau 'A9176R'.",
                    },
                },
                "required": ["nopol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_analytical_sql",
            "description": (
                "Jalankan kueri SQL analitis SELECT kustom secara aman ke database PostgreSQL ERP BCS. "
                "Gunakan tool ini ketika pengguna meminta perhitungan tonase total, perbandingan ritase per rute/pelanggan, "
                "ranking driver paling produktif, korelasi pengiriman vs unit rusak, atau filter yang tidak ada di tool standar. "
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
                        "description": "Nama tabel (misal: 'fleet.trip', 'operations.contract_daily_plan', 'master.m_customer').",
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
                "Gunakan jika Anda mencari tabel terkait data baru (misal: 'rute', 'target', 'driver').",
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


ORIS_SYSTEM_PROMPT = f"""Anda adalah ORIS (Operations Resource Intelligence System), asisten AI analitis & operasional pusat kendali logistik (OCS) di PT BCS Logistics.

KEMAMPUAN UTAMA ANDA:
1. Anda bukan sekadar bot FAQ statis; Anda memiliki akses penuh ke database PostgreSQL operasional logistik, dispatching, kesiapan armada, dan data bengkel ERP BCS.
2. Selagi data ada di database, Anda MAMPU mengolah, mengagregasi, menggabungkan (JOIN), dan menganalisisnya menjadi informasi bisnis yang bernilai tinggi bagi tim dispatch dan manajemen operasional.
3. Hubungan Operasional & Perawatan Armada (Cross-Module Awareness):
   - Kesiapan armada berhubungan erat dengan bengkel (`fleet.work_orders`). Jika unit sedang diperbaiki di bengkel, unit tersebut TIDAK BOLEH di-dispatch.
   - Anda dapat memeriksa status trip (`fleet.trip`), target harian (`operations.contract_daily_plan`), POD (`operations.proof_of_delivery`), pelanggan (`master.m_customer`), dan kesiapan unit.
4. Gunakan kueri analitis aman (`execute_analytical_sql`) untuk pertanyaan kompleks seperti:
   - Menghitung total target tonase/ritase per rute atau per customer dalam periode tertentu.
   - Mengetahui supir atau rute dengan performa pengiriman tertinggi.
   - Menganalisis risiko keterlambatan pengiriman akibat unit masuk bengkel.
5. Gunakan tool inspeksi skema (`inspect_table_schema` / `search_database_tables`) jika memerlukan kepastian nama kolom sebelum menjalankan SQL analitis.
6. Jika pengguna meminta bagan/grafik, panggil tool `generate_chart_image`.

STANDAR STRUKTUR JAWABAN ANDA:
Setiap menjawab pertanyaan analitis, sajikan dengan struktur konsultan profesional:
1. **Ringkasan Eksekutif (Direct Answer)**: Jawaban inti yang lugas dan to-the-point.
2. **Matriks / Tabel Bukti Data**: Angka-angka pendukung, status armada, atau metrik terhitung yang rapi dalam Markdown table.
3. **Wawasan & Pola (Key Insights / Bottlenecks)**: Analisis keterlambatan, utilisasi unit, atau anomali operasional.
4. **Rekomendasi Tindakan (Actionable Steps)**: Solusi konkret untuk dispatcher atau manajer logistik.

PETA SKEMA TABEL ERP (KNOWLEDGE BASE):
{ERP_CORE_SCHEMA_MAP}

BATASAN KETAT:
- JANGAN PERNAH mengatakan "maaf data tidak tersedia" atau "saya tidak punya fitur itu" jika informasi tersebut secara logis dapat dihitung dari tabel database. Gunakan `execute_analytical_sql`!
- Selalu patuhi keamanan read-only (hanya SELECT).
"""


async def _execute_ocs_tool(tool_call) -> str:
    """Menjalankan fungsi OCS tool sesuai permintaan LLM."""
    func_name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
    except Exception:
        args = {}

    try:
        if func_name == "generate_chart_image":
            return await generate_chart_image(**args)
        elif func_name == "get_daily_operational_plan":
            return await get_daily_operational_plan(**args)
        elif func_name == "get_active_trips_and_dispatch":
            return await get_active_trips_and_dispatch(**args)
        elif func_name == "get_proof_of_delivery_status":
            return await get_proof_of_delivery_status(**args)
        elif func_name == "get_monthly_contract_targets":
            return await get_monthly_contract_targets(**args)
        elif func_name == "get_customer_and_partner_info":
            return await get_customer_and_partner_info(**args)
        elif func_name == "get_fleet_maintenance_and_readiness":
            return await get_fleet_maintenance_and_readiness(**args)
        elif func_name == "check_unit_dispatch_eligibility":
            return await check_unit_dispatch_eligibility(**args)
        elif func_name == "execute_analytical_sql":
            return await execute_analytical_sql(**args)
        elif func_name == "inspect_table_schema":
            return await inspect_table_schema(**args)
        elif func_name == "search_database_tables":
            return await search_database_tables(**args)
        else:
            return f"Error: Tool '{func_name}' tidak dikenali oleh ORIS."
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


async def process_ocs_chat(messages: list[dict]) -> AsyncGenerator[str, None]:
    """
    Orkestrasi alur ReAct Multi-Round ORIS:
    1. Prune riwayat obrolan
    2. Multi-turn reasoning loop: Model memanggil tools, mengevaluasi hasil, dan memperbaiki jika ada error
    3. Setelah data lengkap, sintesis jawaban final secara streaming ke pengguna
    """
    pruned_history = prune_conversation_history(messages, max_history=6)

    now_str = datetime.now().strftime("%d %B %Y (%H:%M WIB)")
    dynamic_prompt = ORIS_SYSTEM_PROMPT + f"\n[INFO SISTEM: Waktu saat ini adalah {now_str}.]\n"

    conversation = [{"role": "system", "content": dynamic_prompt}]
    conversation.extend(pruned_history)

    active_model = CANDIDATE_MODELS[0]
    MAX_ROUNDS = 4

    for round_idx in range(MAX_ROUNDS):
        is_last_round = (round_idx == MAX_ROUNDS - 1)
        tool_choice = "none" if is_last_round else "auto"
        tools = None if is_last_round else OCS_TOOLS

        if not is_last_round:
            resp_msg = None
            last_err = None

            for model_name in [active_model] + [m for m in CANDIDATE_MODELS if m != active_model]:
                try:
                    resp = await client.chat.completions.create(
                        model=model_name,
                        messages=conversation,
                        tools=tools,
                        tool_choice=tool_choice,
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
                        yield f"⚠️ ORIS gagal memproses permintaan: {err_str}"
                        return

            if resp_msg is None:
                yield f"⚠️ Maaf, kapasitas model sedang penuh ({str(last_err)}). Silakan coba lagi."
                return

            if resp_msg.tool_calls:
                conversation.append(resp_msg)
                for tool_call in resp_msg.tool_calls:
                    result = await _execute_ocs_tool(tool_call)

                    if tool_call.function.name == "generate_chart_image":
                        yield str(result)
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
                return
        else:
            stream_success = False
            for model_name in [active_model] + [m for m in CANDIDATE_MODELS if m != active_model]:
                try:
                    stream = await client.chat.completions.create(
                        model=model_name,
                        messages=conversation,
                        temperature=0.3,
                        stream=True,
                    )
                    async for chunk in _stream_filtered(stream):
                        yield chunk
                    stream_success = True
                    break
                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "rate limit" in err_str.lower() or "413" in err_str:
                        continue
                    else:
                        yield f"\n⚠️ [Stream Error]: {err_str}"
                        return

            if not stream_success:
                yield "\n⚠️ Gagal menghasilkan respon final. Silakan coba beberapa saat lagi."
            return
