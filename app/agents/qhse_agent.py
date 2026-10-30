"""
QHSE Agent — QISHA
─────────────────────────────────────────────────────────────────
QHSE Intelligence & Safety Hazard Assistant

QISHA adalah asisten AI keselamatan kerja (K3), kesehatan kerja, mutu, dan kepatuhan lingkungan PT BCS Logistics.
Memiliki akses langsung ke database QHSE:
- Insiden & Investigasi Kecelakaan Kerja (qhse.incidents)
- Safety Briefing & Tool Box Meeting (qhse.safety_briefings)
- Distribusi Alat Pelindung Diri / APD (qhse.apd_distributions)
- Temuan K3 Proaktif / Near-Miss (qhse.proactive_reports)
- Keluhan Mutu Pelanggan (qhse.customer_complaints)
- Mesin Kueri Analitis & Text-to-SQL Aman (execute_analytical_sql)
- Inspeksi Skema Database Dinamis (inspect_table_schema, search_database_tables)
- Pembuatan Grafik & Diagram Safety (generate_chart_image)
"""

import re
import json
import asyncio
from datetime import datetime
from typing import AsyncGenerator

from app.llm.llm_client import client, settings
from app.tools.chart_tools import CHART_TOOL_SCHEMA, generate_chart_image
from app.tools.qhse_tools import (
    get_qhse_overview,
    get_incident_records,
    get_proactive_safety_reports,
    get_customer_complaints,
)
from app.tools.analytical_query_tools import (
    execute_analytical_sql,
    inspect_table_schema,
    search_database_tables,
    ERP_CORE_SCHEMA_MAP,
)

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


QHSE_TOOLS = [
    CHART_TOOL_SCHEMA,
    {
        "type": "function",
        "function": {
            "name": "get_qhse_overview",
            "description": (
                "Ambil ringkasan umum data QHSE & K3 terkini: total insiden per tingkat keparahan, "
                "sesi safety briefing/TBM, pembagian APD, temuan K3 proaktif (near-miss), dan keluhan mutu pelanggan. "
                "Gunakan saat pengguna menanyakan 'ringkasan K3', 'status safety hari ini', 'overview QHSE', dsb."
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
            "name": "get_incident_records",
            "description": (
                "Ambil riwayat insiden dan kecelakaan kerja armada atau operasional: jenis kecelakaan, tingkat keparahan, "
                "akar penyebab (root cause), dan tindakan perbaikan (CAPA). "
                "Gunakan saat pengguna menanyakan 'riwayat kecelakaan', 'insiden fatal/high', 'evaluasi insiden bulan ini'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "severity": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Tingkat keparahan: 'HIGH', 'MEDIUM', atau 'LOW'.",
                    },
                    "limit": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Batas data yang ditampilkan (default: 10, max: 25).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_proactive_safety_reports",
            "description": (
                "Ambil data laporan temuan bahaya K3 proaktif (near-miss, kondisi berbahaya, tindakan tidak aman/unsafe act) dan status CAPA. "
                "Gunakan saat pengguna menanyakan 'laporan near miss', 'temuan K3 resiko tinggi', 'bahaya keselamatan lapangan'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "risk_level": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Level resiko: 'HIGH', 'MEDIUM', atau 'LOW'.",
                    },
                    "limit": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Batas data yang ditampilkan (default: 10, max: 25).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_complaints",
            "description": (
                "Ambil data keluhan mutu dari pelanggan logistik: jenis masalah, hasil investigasi, dan tindakan pencegahan. "
                "Gunakan saat pengguna menanyakan 'keluhan customer', 'komplain kualitas muatan', 'masalah pengiriman customer'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Status keluhan: 'OPEN', 'INVESTIGATING', atau 'CLOSED'.",
                    },
                    "limit": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Batas data yang ditampilkan (default: 10, max: 25).",
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
                "Gunakan tool ini ketika pengguna meminta agregasi kustom (analisis tren insiden per rute/supir, proporsi temuan hazard, evaluasi partisipasi safety briefing). "
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
                        "description": "Nama tabel (misal: 'qhse.incidents', 'qhse.apd_distributions', 'qhse.safety_briefings').",
                    },
                    "schema_name": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nama skema database (opsional, misal: 'qhse', 'master').",
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
            "description": "Cari nama tabel di database PostgreSQL yang cocok dengan kata kunci tertentu.",
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

QISHA_SYSTEM_PROMPT = f"""Anda adalah QISHA (QHSE Intelligence & Safety Hazard Assistant), asisten AI keselamatan kerja (K3), kesehatan kerja, mutu, dan kepatuhan lingkungan di PT BCS Logistics.

KEMAMPUAN UTAMA ANDA:
1. Anda memiliki akses penuh ke database PostgreSQL QHSE ERP BCS: laporan kecelakaan/insiden armada, safety briefing (TBM), pembagian APD, laporan temuan K3 proaktif (near-miss/hazard), dan keluhan pelanggan.
2. Selagi data ada di database, Anda MAMPU mengolah, mengagregasi, menggabungkan (JOIN), dan menganalisisnya menjadi laporan keselamatan kerja standar ISO 45001 dan SMK3.
3. Gunakan kueri analitis aman (`execute_analytical_sql`) untuk pertanyaan kompleks seperti:
   - Menghitung rasio insiden armada (Lost Time Injury / Severity Rate).
   - Mengkorelasikan rute trip atau supir dengan riwayat insiden kecelakaan.
   - Melacak kepatuhan distribusi APD dan masa pakai kelayakannya.
   - Menganalisis keluhan mutu pelanggan berulang per jenis muatan/rute.
4. Gunakan tool inspeksi skema (`inspect_table_schema` / `search_database_tables`) jika memerlukan kepastian nama kolom sebelum menjalankan SQL analitis.
5. Jika pengguna meminta visualisasi grafik keselamatan atau tren hazard, panggil tool `generate_chart_image`.

STANDAR STRUKTUR JAWABAN ANDA:
1. **Ringkasan Eksekutif (Direct Answer)**: Jawaban lugas dan langsung to-the-point mengenai status keselamatan.
2. **Matriks Bukti Data / Tabel**: Format Markdown table yang rapi.
3. **Analisis Resiko & Akar Masalah (Risk & Root Cause Insights)**: Analisis potensi bahaya fatal atau kegagalan SOP.
4. **Rekomendasi Tindakan Pencegahan (Actionable Safety Steps)**: Langkah mitigasi konkrit bagi Officer K3, supir, atau manajemen operasional.

PETA SKEMA TABEL ERP (KNOWLEDGE BASE):
{ERP_CORE_SCHEMA_MAP}

BATASAN KETAT:
- JANGAN PERNAH mengatakan "maaf data tidak tersedia" jika informasi tersebut dapat dihitung dari database menggunakan `execute_analytical_sql`.
- Selalu patuhi keamanan read-only (hanya SELECT).
"""


async def _execute_qhse_tool(tool_call) -> str:
    """Menjalankan fungsi QHSE tool sesuai permintaan LLM."""
    func_name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
    except Exception:
        args = {}

    try:
        if func_name == "generate_chart_image":
            return await generate_chart_image(**args)
        elif func_name == "get_qhse_overview":
            return await get_qhse_overview()
        elif func_name == "get_incident_records":
            return await get_incident_records(**args)
        elif func_name == "get_proactive_safety_reports":
            return await get_proactive_safety_reports(**args)
        elif func_name == "get_customer_complaints":
            return await get_customer_complaints(**args)
        elif func_name == "execute_analytical_sql":
            return await execute_analytical_sql(**args)
        elif func_name == "inspect_table_schema":
            return await inspect_table_schema(**args)
        elif func_name == "search_database_tables":
            return await search_database_tables(**args)
        else:
            return f"Error: Tool '{func_name}' tidak dikenali oleh QISHA."
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
                    post = buffer.split("</think>", 1)[1]
                    buffer = ""
                    if post:
                        yield post


async def process_qhse_chat(messages: list[dict]) -> AsyncGenerator[str, None]:
    """
    Orkestrasi alur ReAct Multi-Round QISHA:
    1. Prune riwayat obrolan
    2. Multi-turn reasoning loop untuk mengevaluasi data K3 & Mutu
    3. Sintesis laporan keselamatan kerja secara streaming
    """
    pruned_history = prune_conversation_history(messages, max_history=6)

    now_str = datetime.now().strftime("%d %B %Y (%H:%M WIB)")
    dynamic_prompt = QISHA_SYSTEM_PROMPT + f"\n[INFO SISTEM: Waktu saat ini adalah {now_str}.]\n"

    conversation = [{"role": "system", "content": dynamic_prompt}]
    conversation.extend(pruned_history)

    active_model = CANDIDATE_MODELS[0]
    MAX_ROUNDS = 4

    for round_idx in range(MAX_ROUNDS):
        is_last_round = (round_idx == MAX_ROUNDS - 1)

        if not is_last_round:
            resp_msg = None
            last_err = None

            for model_name in [active_model] + [m for m in CANDIDATE_MODELS if m != active_model]:
                try:
                    resp = await client.chat.completions.create(
                        model=model_name,
                        messages=conversation,
                        tools=QHSE_TOOLS,
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
                        yield f"⚠️ QISHA gagal memproses permintaan: {err_str}"
                        return

            if resp_msg is None:
                yield f"⚠️ Maaf, kapasitas model sedang penuh ({str(last_err)}). Silakan coba lagi."
                return

            if resp_msg.tool_calls:
                conversation.append(resp_msg)
                for tool_call in resp_msg.tool_calls:
                    result = await _execute_qhse_tool(tool_call)

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
                        tools=QHSE_TOOLS,
                        tool_choice="auto",
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
