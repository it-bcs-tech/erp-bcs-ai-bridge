"""
DMS Agent — DIMAS
─────────────────────────────────────────────────────────────────
Document Intelligence & Management Archival System

DIMAS adalah asisten AI resmi khusus modul Document Management System (DMS) di PT BCS Logistics.
Memiliki akses langsung ke database arsip dan legalitas:
- Dokumen Legalitas & Arsip (dms.documents)
- Peringatan Jatuh Tempo / Expiry Alert (STNK, KIR, BPKB, SIM, Izin B3, Sertifikat)
- Lokasi Fisik Penyimpanan Berkas (dms.m_filing_location)
- Kueri Analitis & Text-to-SQL Dinamis Aman (execute_analytical_sql)
- Inspeksi Skema Database (inspect_table_schema, search_database_tables)
- Pembuatan Grafik & Visualisasi Statistik (generate_chart_image)
"""

import re
import json
from datetime import datetime
from typing import AsyncGenerator

from app.llm.llm_client import client, settings
from app.tools.chart_tools import CHART_TOOL_SCHEMA, generate_chart_image
from app.tools.dms_tools import (
    get_dms_summary_stats,
    search_documents,
    get_expiring_documents,
    get_document_detail,
)
from app.tools.analytical_query_tools import (
    execute_analytical_sql,
    inspect_table_schema,
    search_database_tables,
    ERP_CORE_SCHEMA_MAP,
)

CANDIDATE_MODELS = [
    settings.llm_model,
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
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


# ── Definisi Tools untuk LLM ───────────────────────────────────────

DMS_TOOLS = [
    CHART_TOOL_SCHEMA,
    {
        "type": "function",
        "function": {
            "name": "get_dms_summary_stats",
            "description": (
                "Ambil ringkasan statistik arsip & dokumen perusahaan: total dokumen, jumlah aktif, expired, "
                "serta jumlah dokumen yang mendekati jatuh tempo (30/60/90 hari). "
                "Gunakan saat pengguna menanyakan 'berapa dokumen tersimpan', 'statistik arsip', 'ringkasan dokumen', atau kondisi umum arsip."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": (
                "Cari dokumen arsip berdasarkan nomor dokumen, nopol kendaraan, nama driver, judul dokumen, tipe dokumen (KIR/STNK/SIM), "
                "tanggal input/pembuatan/pembaruan (created_from/created_to meliputi created_at, updated_at, dan issue_date), "
                "atau nama user pembuat/pengupdate dokumen (created_by yang dicek ke created_by dan audit logs dms.document_audit_logs). "
                "Gunakan jika pengguna menanyakan dokumen spesifik, dokumen baru diinput/dibuat/diperpanjang, atau dokumen berdasarkan pembuat/pengupdate."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Kata kunci pencarian (misal: 'A9255R', 'SIM B2', 'KIR', nama driver, judul, atau nomor dokumen).",
                    },
                    "entity_type": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Filter entitas: 'FLEET', 'DRIVER', 'CUSTOMER', 'CORPORATE', 'VENDOR', 'LAND'.",
                    },
                    "doc_type": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Tipe dokumen spesifik (misal: 'Uji Berkala / KIR', 'STNK', 'SIM A Pengemudi').",
                    },
                    "status": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Status dokumen: 'ACTIVE', 'EXPIRED', 'PENDING'.",
                    },
                    "created_from": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Filter tanggal awal input/perpanjangan/pembuatan (format 'YYYY-MM-DD', misal: '2026-10-26'). Mencakup created_at, updated_at, dan issue_date.",
                    },
                    "created_to": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Filter tanggal akhir input/perpanjangan/pembuatan (format 'YYYY-MM-DD', misal: '2026-11-02'). Mencakup created_at, updated_at, dan issue_date.",
                    },
                    "created_by": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nama atau username pembuat atau pengupdate dokumen (misal: 'Joni Sutopo', 'superhyperadmin', admin). Mencakup audit logs.",
                    },
                    "sort_by": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "'newest' (terbaru dibuat), 'expiry_soon' (segera expired), atau 'title'.",
                    },
                    "limit": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Batas jumlah data (default 15).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_expiring_documents",
            "description": (
                "Dapatkan daftar dokumen yang akan segera kedaluwarsa / jatuh tempo dalam kurun waktu tertentu (default 30 hari ke depan). "
                "Sangat penting untuk audit kepatuhan, perpanjangan KIR, STNK, SIM B2 driver, dan izin operasional armada."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days_ahead": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Jangka waktu hari ke depan untuk monitoring (default 30, misal: 14, 30, 60).",
                    },
                    "entity_type": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Filter tipe entitas: 'FLEET', 'DRIVER', 'CORPORATE', dll.",
                    },
                    "limit": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Batas data (default: 15).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_document_detail",
            "description": (
                "Lihat informasi lengkap satu dokumen spesifik: tanggal dibuat, pembuat berkas, nomor, masa berlaku, "
                "metadata JSON, riwayat versi, serta lokasi fisik penyimpanan (lemari/rak arsip)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_number_or_title": {
                        "type": "string",
                        "description": "Nomor dokumen atau judul lengkap dokumen.",
                    },
                },
                "required": ["doc_number_or_title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_analytical_sql",
            "description": (
                "Jalankan kueri SQL analitis SELECT kustom secara aman ke database PostgreSQL DMS/ERP BCS. "
                "Gunakan tool ini ketika pengguna meminta agregasi kustom, pengelompokan tanggal pembuatan (created_at), "
                "filter pembuat dokumen (created_by), atau pencarian arsip kompleks yang memerlukan JOIN atau GROUP BY."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql_query": {
                        "type": "string",
                        "description": "Kueri SELECT SQL aman (contoh: 'SELECT doc_number, title, created_at, created_by FROM dms.documents WHERE created_at >= CURRENT_DATE - INTERVAL \'7 days\' ORDER BY created_at DESC LIMIT 15').",
                    },
                    "purpose": {
                        "type": "string",
                        "description": "Tujuan analisis ad-hoc kueri ini.",
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
            "description": "Periksa kolom dan tipe data tabel database PostgreSQL ERP BCS sebelum menjalankan SQL analitis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "schema_name": {"type": "string", "description": "Nama schema (misal: 'dms', 'master')"},
                    "table_name": {"type": "string", "description": "Nama tabel (misal: 'documents', 'm_doc_type')"},
                },
                "required": ["schema_name", "table_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_database_tables",
            "description": "Cari nama tabel di database PostgreSQL yang cocok dengan kata kunci tertentu.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Kata kunci pencarian nama tabel (misal: 'document', 'arsip')"},
                },
                "required": ["keyword"],
            },
        },
    },
]

DIMAS_SYSTEM_PROMPT = f"""Anda adalah DIMAS (Document Intelligence & Management Archival System), asisten AI resmi khusus modul Document Management System (DMS) di PT BCS Logistics.

KEMAMPUAN UTAMA & AKSES DATA ANDA:
1. Anda memiliki akses langsung ke database arsip dan legalitas PT BCS Logistics:
   - Dokumen legalitas armada (STNK, KIR, BPKB, Izin Trayek, B3), lisensi pengemudi (SIM A/B1/B2, sertifikat), kontrak, sertifikat, dan perizinan.
   - Peringatan dini masa kedaluwarsa berkas (Expiry Alerts).
   - Lokasi fisik penyimpanan berkas asli di lemari/rak/box arsip.
2. LOGIKA BISNIS INPUT & PERPANJANGAN DOKUMEN (CRITICAL DOMAIN LOGIC):
   - Penginputan dan pembaruan dokumen berkala (seperti Uji Berkala / KIR, STNK, SIM Driver, Lisensi B3) dilakukan user/staf melalui pendaftaran baru ATAU perpanjangan (renewal).
   - Pada perpanjangan dokumen berkala, baris dokumen yang ada di `dms.documents` diperbarui pada kolom `issue_date` (tanggal terbit perpanjangan), `expiry_date` (jatuh tempo baru), dan `updated_at`. Riwayat siapa yang menginput/memperbarui tercatat di `dms.document_audit_logs` (kolom `user_name`, action 'UPDATE' / 'CREATE'). Kolom `created_at` adalah tanggal registrasi awal sistem (bisa bertahun-tahun lalu).
   - Jika pengguna menanyakan dokumen yang "baru dibuat", "baru diinput", "1 minggu terakhir", "hari ini / bulan ini", atau "dibuat/diinput oleh user X":
     * WAJIB memanggil tool `search_documents` dengan parameter `keyword` (cth: 'KIR'), `created_from` (cth: '2026-10-26'), atau `created_by` (cth: 'Joni Sutopo'). Tool `search_documents` sudah otomatis mencakup `created_at`, `updated_at`, `issue_date`, dan `document_audit_logs`.
     * Jika Anda menggunakan `execute_analytical_sql`, WAJIB menggunakan filter:
       `(d.created_at >= CURRENT_DATE - INTERVAL '7 days' OR d.updated_at >= CURRENT_DATE - INTERVAL '7 days' OR d.issue_date >= CURRENT_DATE - INTERVAL '7 days')`
       serta mengambil nama pengupdate/pembuat terkini:
       `COALESCE((SELECT al.user_name FROM dms.document_audit_logs al WHERE al.document_id = d.id AND al.action IN ('CREATE', 'UPDATE') ORDER BY al.created_at DESC LIMIT 1), d.created_by, 'System') AS pembuat_pengupdate`
       dan diurutkan `ORDER BY COALESCE(d.updated_at, d.issue_date::timestamp, d.created_at) DESC`.
     * DILARANG KERAS hanya menyaring `created_at` tanpa `updated_at` dan `issue_date`, karena itu akan membuat Anda melewatkan dokumen perpanjangan KIR/STNK yang baru saja diinput user!
     * DILARANG KERAS mengatakan "sistem memiliki batasan tidak bisa memfilter tanggal pembuatan atau pembuat dokumen". Anda MEMILIKI AKSES PENUH ke data tersebut!
3. Jika Anda sudah mendapatkan data dari tool spesifik (`search_documents`, `get_expiring_documents`, atau `execute_analytical_sql`), SEGERA sajikan jawaban final. JANGAN memanggil tool inspeksi skema berulang-ulang tanpa tujuan.
4. Jika pengguna meminta grafik visualisasi dokumen, panggil tool `generate_chart_image`.
5. STRATEGI RESPON HASIL PENCARIAN DOKUMEN:
   - Sajikan tabel yang jelas berisi: No Dokumen, Judul/Jenis Dokumen, Tanggal Terbit/Update, Pembuat/Pengupdate (user), Masa Berlaku / Status.
   - Jika dalam rentang waktu yang diminta benar-benar tidak ada entri baru, sajikan dokumen yang paling baru diupdate/terbit di sistem lengkap dengan informasi tanggal dan pengupdatenya.
   - JANGAN PERNAH menyajikan respon kosong jika di database ada data dokumen.

PETA SKEMA TABEL ERP (KNOWLEDGE BASE):
{ERP_CORE_SCHEMA_MAP}

STANDAR STRUKTUR JAWABAN ANDA:
1. **Ringkasan Langsung (Direct Answer)**: Jawaban lugas atas kebutuhan pengguna.
2. **Tabel Bukti Dokumen (Markdown Table)**: Tampilkan No Dokumen, Judul/Jenis, Tanggal Dibuat, Pembuat Berkas, Masa Berlaku, dan Status.
3. **Rekomendasi Tindakan Arsip**: Langkah tindak lanjut bagi petugas dokumen atau user.
"""


async def _execute_dms_tool(tool_call) -> str:
    """Menjalankan fungsi DMS tool sesuai permintaan LLM."""
    func_name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
    except Exception:
        args = {}

    try:
        if func_name == "generate_chart_image":
            return await generate_chart_image(**args)
        elif func_name == "get_dms_summary_stats":
            return await get_dms_summary_stats()
        elif func_name == "search_documents":
            return await search_documents(**args)
        elif func_name == "get_expiring_documents":
            return await get_expiring_documents(**args)
        elif func_name == "get_document_detail":
            return await get_document_detail(**args)
        elif func_name == "execute_analytical_sql":
            return await execute_analytical_sql(**args)
        elif func_name == "inspect_table_schema":
            return await inspect_table_schema(**args)
        elif func_name == "search_database_tables":
            return await search_database_tables(**args)
        else:
            return f"Error: Tool '{func_name}' tidak dikenali oleh DIMAS."
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
                elif len(buffer) > 8:
                    yield buffer
                    buffer = ""
            else:
                buffer += token
                if "</think>" in buffer:
                    is_thinking = False
                    post = buffer.split("</think>", 1)[1].lstrip("\n")
                    buffer = ""
                    if post:
                        yield post

    if buffer and not is_thinking:
        yield buffer


async def process_dms_chat(messages: list[dict]) -> AsyncGenerator[str, None]:
    """
    Main entry point untuk pemrosesan obrolan DIMAS DMS dengan tool calling multi-round
    dan real-time streaming respon akhir.
    """
    now_str = datetime.now().strftime("%d %B %Y (%H:%M WIB)")
    dynamic_prompt = (
        DIMAS_SYSTEM_PROMPT
        + f"\n[INFO SISTEM: Waktu saat ini adalah {now_str}.]\n"
    )

    clean_messages = prune_conversation_history(messages, max_history=6)
    conversation = [{"role": "system", "content": dynamic_prompt}] + clean_messages

    active_model = CANDIDATE_MODELS[0]
    MAX_ROUNDS = 4
    has_streamed = False

    for round_idx in range(MAX_ROUNDS):
        resp_msg = None
        last_error = None

        for model_name in [active_model] + [m for m in CANDIDATE_MODELS if m != active_model]:
            try:
                resp = await client.chat.completions.create(
                    model=model_name,
                    messages=conversation,
                    tools=DMS_TOOLS,
                    tool_choice="auto",
                    temperature=0.1,
                )
                resp_msg = resp.choices[0].message
                active_model = model_name
                break
            except Exception as e:
                err_str = str(e)
                last_error = e
                if "429" in err_str or "rate limit" in err_str.lower() or "413" in err_str:
                    continue
                else:
                    yield f"⚠️ DIMAS gagal memproses permintaan: {err_str}"
                    return

        if resp_msg is None:
            yield f"⚠️ Maaf, kapasitas model sedang penuh ({str(last_error)}). Silakan coba lagi."
            return

        if resp_msg.tool_calls:
            conversation.append(resp_msg)
            for tool_call in resp_msg.tool_calls:
                result = await _execute_dms_tool(tool_call)

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
            # Lanjut ke putaran berikutnya agar LLM mensintesis jawaban dari hasil tool
            continue
        else:
            # LLM selesai memanggil tool dan menghasilkan respon teks final
            if resp_msg.content:
                clean = re.sub(r"<think>.*?</think>", "", resp_msg.content, flags=re.DOTALL).strip()
                words = clean.split(" ")
                for i, w in enumerate(words):
                    yield w + (" " if i < len(words) - 1 else "")
                    if i % 4 == 0:
                        import asyncio
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
            yield f"**Hasil Pencarian Dokumen Arsip Terkini:**\n\n{last_tool_res}"
        else:
            yield "⚠️ Maaf, tidak ada respon data yang dapat ditampilkan saat ini."
