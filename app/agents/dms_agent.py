"""
DMS Agent — DIMAS
─────────────────────────────────────────────────────────────────
Document Intelligence & Management Archival System

DIMAS adalah asisten AI khusus modul Document Management System (DMS) PT BCS Logistics.
Memiliki akses langsung ke database arsip dan legalitas:
- Dokumen Legalitas & Arsip (dms.documents)
- Peringatan Jatuh Tempo / Expiry Alert (STNK, KIR, BPKB, SIM, Izin B3, Sertifikat)
- Lokasi Fisik Penyimpanan Berkas (dms.m_filing_location)
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

# ── Fallback candidate models jika model utama limit/429/413 ─────────
CANDIDATE_MODELS = [
    settings.llm_model,
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]
CANDIDATE_MODELS = list(dict.fromkeys([m for m in CANDIDATE_MODELS if m]))


def prune_conversation_history(messages: list[dict], max_history: int = 6) -> list[dict]:
    """
    Memangkas riwayat obrolan agar tidak memicu TPM/TPD rate limit.
    """
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
                "Cari dokumen arsip berdasarkan nomor dokumen, nopol kendaraan, nama driver, judul dokumen, atau tipe entitas. "
                "Gunakan jika pengguna menanyakan dokumen spesifik (contoh: 'dokumen truk A9255R', 'SIM driver Rudi', 'akta notaris', 'kontrak Indocement')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Kata kunci pencarian (misal: 'A9255R', 'SIM B2', 'KIR', nama driver, atau nomor dokumen).",
                    },
                    "entity_type": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Filter entitas: 'FLEET', 'DRIVER', 'CUSTOMER', 'CORPORATE', 'VENDOR', 'LAND'.",
                    },
                    "doc_type": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Tipe dokumen spesifik (misal: 'Uji Berkala / KIR', 'STNK', 'SIM Pengemudi').",
                    },
                    "status": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Status dokumen: 'ACTIVE', 'EXPIRED', 'PENDING'.",
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
                        "description": "Batas data yang ditampilkan (default 15).",
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
                "Ambil rincian lengkap satu dokumen tertentu termasuk tanggal terbit, tanggal jatuh tempo, catatan, dan lokasi penyimpanan fisik rak/lemari."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_number_or_title": {
                        "type": "string",
                        "description": "Nomor dokumen atau judul lengkap dokumen yang dicari.",
                    }
                },
                "required": ["doc_number_or_title"],
            },
        },
    },
]


DIMAS_SYSTEM_PROMPT = """Anda adalah DIMAS (Document Intelligence & Management Archival System), asisten AI resmi khusus modul Document Management System (DMS) di PT BCS Logistics.

PERAN & TUGAS UTAMA ANDA:
1. Membantu pengguna memonitor, mencari, dan mengelola lebih dari 5.800 dokumen legalitas perusahaan, legalitas armada (STNK, KIR, BPKB, Izin B3, IBM), lisensi pengemudi (SIM A/B1/B2, sertifikat B3, SIO), kontrak pelanggan/vendor, serta sertifikat tanah dan akta notaris.
2. Memberikan peringatan dini (Expiry Alert) untuk dokumen yang mendekati tanggal kedaluwarsa agar operasional armada tidak terhenti karena tilang atau izin mati.
3. Menginformasikan lokasi penyimpanan fisik berkas asli (Lemari, Rak, Binder, Box).
4. Jika pengguna meminta grafik rekap dokumen, panggil tool `generate_chart_image`.

BATASAN KETAT (GUARDRAILS):
- Anda HANYA menangani dokumen arsip, legalitas, perizinan, dan masa berlaku berkas di modul DMS.
- Jika ditanya hal di luar DMS seperti nominal gaji karyawan, detail teknis mesin truk yang tidak berhubungan dengan dokumen, atau obrolan acak, tolak dengan sopan dan tegaskan peran Anda sebagai DIMAS.
- Sajikan jawaban secara profesional, terstruktur rapi dengan tabel atau poin Markdown, dan beri sorotan khusus (badge 🔴 🟡 🟢) untuk status kedaluwarsa.
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
                    clean = buffer.split("</think>")[1].lstrip("\n")
                    if clean:
                        yield clean
                    buffer = ""

    if buffer and not is_thinking:
        yield buffer


async def process_dms_chat(messages: list[dict]) -> AsyncGenerator[str, None]:
    """
    Main entry point untuk pemrosesan obrolan DIMAS DMS dengan tool calling,
    conversation pruning, dan multi-model fallback.
    """
    now_str = datetime.now().strftime("%d %B %Y (%H:%M WIB)")
    dynamic_prompt = (
        DIMAS_SYSTEM_PROMPT
        + f"\n[INFO SISTEM: Waktu saat ini adalah {now_str}.]\n"
    )

    clean_messages = prune_conversation_history(messages, max_history=6)
    conversation = [{"role": "system", "content": dynamic_prompt}] + clean_messages

    active_model = settings.llm_model
    response_message = None
    last_error = None

    # Step 1: LLM Call dengan auto fallback jika rate limit
    for model_name in CANDIDATE_MODELS:
        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=conversation,
                tools=DMS_TOOLS,
                tool_choice="auto",
                temperature=0.1,
            )
            response_message = response.choices[0].message
            active_model = model_name
            break
        except Exception as e:
            err_str = str(e)
            last_error = e
            if "429" in err_str or "rate limit" in err_str.lower() or "413" in err_str or "too large" in err_str.lower():
                continue
            else:
                yield f"⚠️ DIMAS gagal memproses permintaan: {err_str}"
                return

    if response_message is None:
        yield f"⚠️ Maaf, seluruh model AI sedang mencapai batas kapasitas limit ({str(last_error)}). Silakan tunggu sebentar."
        return

    has_tool_call = False

    # Step 2: Tangani Tool Calls jika ada
    if response_message.tool_calls:
        has_tool_call = True
        conversation.append(response_message)

        for tool_call in response_message.tool_calls:
            result = await _execute_dms_tool(tool_call)

            if tool_call.function.name == "generate_chart_image":
                yield str(result)
                tool_content = "Berhasil membuat dan menyajikan grafik ke layar."
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
                arguments = args_str if args_str.startswith("{") else f'{{"keyword": "{args_str}"}}'

            class _MockCall:
                id = f"call_{func_name}"
                function = _MockFn()

            result = await _execute_dms_tool(_MockCall())

            if func_name == "generate_chart_image":
                yield str(result)
                tool_content = "Berhasil membuat dan menyajikan grafik ke layar."
            else:
                tool_content = str(result)

            conversation.append({
                "role": "user",
                "content": f"[System: Hasil dari {func_name}]:\n{tool_content}",
            })

    # Step 3: Stream Final Answer
    if has_tool_call:
        stream_success = False
        for model_name in [active_model] + [m for m in CANDIDATE_MODELS if m != active_model]:
            try:
                stream = await client.chat.completions.create(
                    model=model_name,
                    messages=conversation,
                    tools=DMS_TOOLS,
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
            yield "\n⚠️ [Kapasitas Model Penuh]: Gagal menghasilkan respons final. Coba beberapa saat lagi."
    else:
        if response_message.content:
            clean = re.sub(r"<think>.*?</think>", "", response_message.content, flags=re.DOTALL).strip()
            yield clean
