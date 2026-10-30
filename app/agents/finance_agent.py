"""
Finance Agent — FINA
─────────────────────────────────────────────────────────────────
Financial Intelligence & Numeric Analytics

FINA adalah asisten AI keuangan, perpajakan, kasir, dan penagihan PT BCS Logistics.
Memiliki akses langsung ke database keuangan dan operasional:
- Faktur & Piutang (finance.invoice)
- Uang Jalan Operasional / UJO Driver (finance.cash_advance)
- Buku Kas Kasir / Kas Kecil (finance.kasir_cash_ledger)
- Surat Jalan Penagihan (finance.dn_header & dn_detail)
- Riwayat Pembayaran (finance.payment)
- Mesin Kueri Analitis & Text-to-SQL Aman (execute_analytical_sql)
- Inspeksi Skema Database Dinamis (inspect_table_schema, search_database_tables)
- Pembuatan Grafik Keuangan & Arus Kas (generate_chart_image)
"""

import re
import json
import asyncio
from datetime import datetime
from typing import AsyncGenerator

from app.llm.llm_client import client, settings
from app.tools.chart_tools import CHART_TOOL_SCHEMA, generate_chart_image
from app.tools.finance_tools import (
    get_finance_overview,
    get_invoices,
    get_cash_advances,
    get_kasir_ledger,
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


FINANCE_TOOLS = [
    CHART_TOOL_SCHEMA,
    {
        "type": "function",
        "function": {
            "name": "get_finance_overview",
            "description": (
                "Ambil ringkasan umum data keuangan dan kasir terkini: total invoice dan nilai piutang berjalan, "
                "total uang jalan (UJO) driver, serta saldo dan mutasi kas kecil kasir. "
                "Gunakan saat pengguna menanyakan 'ringkasan keuangan', 'kondisi piutang saat ini', 'total uang jalan', dsb."
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
            "name": "get_invoices",
            "description": (
                "Ambil daftar faktur penagihan (invoices) ke pelanggan/customer berdasarkan status (PAID, POSTED, DRAFT). "
                "Gunakan saat pengguna menanyakan 'daftar invoice', 'tagihan yang belum lunas', 'cek invoice pelanggan'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Status invoice: 'PAID', 'POSTED', 'DRAFT', atau 'OPEN'.",
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
            "name": "get_cash_advances",
            "description": (
                "Ambil rincian data Uang Jalan Operasional (UJO / Cash Advance) driver per trip armada: "
                "komponen uang makan, tol, biaya ekstra, dan status pencairan. "
                "Gunakan saat pengguna menanyakan 'uang jalan supir', 'status UJO trip X', 'biaya tol/makan supir'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "payment_status": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Status pembayaran UJO: 'PAID', 'PENDING', atau 'UNPAID'.",
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
            "name": "get_kasir_ledger",
            "description": (
                "Ambil mutasi pembukuan kasir (kas kecil / petty cash): kas masuk (IN), kas keluar (OUT), "
                "kategori transaksi, dan pelaksana transaksi. "
                "Gunakan saat pengguna menanyakan 'mutasi kasir hari ini', 'pengeluaran kas kecil', 'saldo kasir'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Arah mutasi: 'IN' (kas masuk) atau 'OUT' (kas keluar).",
                    },
                    "category": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Kategori pengeluaran (misal: 'BBM', 'Konsumsi', 'Tol', 'Operasional').",
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
            "name": "execute_analytical_sql",
            "description": (
                "Jalankan kueri SQL analitis SELECT kustom secara aman ke database PostgreSQL ERP BCS. "
                "Gunakan tool ini ketika pengguna meminta agregasi kustom (SUM piutang per pelanggan, AVG UJO per rute, rasio kas masuk/keluar bulanan). "
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
                        "description": "Nama tabel (misal: 'finance.invoice', 'finance.cash_advance', 'finance.payment').",
                    },
                    "schema_name": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nama skema database (opsional, misal: 'finance', 'master').",
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

FINA_SYSTEM_PROMPT = f"""Anda adalah FINA (Financial Intelligence & Numeric Analytics), asisten AI khusus divisi Keuangan, Akuntansi, Kasir, dan Penagihan (Finance & Kasir) di PT BCS Logistics.

KEMAMPUAN UTAMA ANDA:
1. Anda memiliki akses penuh ke database PostgreSQL keuangan ERP BCS: faktur (invoice), kasir (petty cash), uang jalan driver (cash advance UJO), penagihan (delivery notes), dan pembayaran (payments).
2. Selagi data ada di database, Anda MAMPU mengolah, mengagregasi, menggabungkan (JOIN), dan menganalisisnya menjadi laporan keuangan eksekutif bernilai tinggi.
3. Gunakan kueri analitis aman (`execute_analytical_sql`) untuk pertanyaan kompleks seperti:
   - Menghitung total piutang yang jatuh tempo (aging receivables).
   - Menganalisis rasio biaya UJO makan & tol per rute perjalanan armada.
   - Melacak aliran kas masuk/keluar kasir per kategori transaksi.
   - Mengkorelasikan Surat Jalan (DN) dengan status penerbitan faktur.
4. Gunakan tool inspeksi skema (`inspect_table_schema` / `search_database_tables`) jika memerlukan kepastian nama kolom sebelum menjalankan SQL analitis.
5. Jika pengguna meminta visualisasi grafik keuangan atau proporsi pengeluaran, panggil tool `generate_chart_image`.

STANDAR STRUKTUR JAWABAN ANDA:
1. **Ringkasan Eksekutif (Direct Answer)**: Jawaban to-the-point mengenai angka atau status penagihan.
2. **Matriks Bukti Data / Tabel Keuangan**: Nilai moneter dalam format Rupiah rapi (Rp X,XXX,XXX.XX) dan tabel Markdown.
3. **Wawasan & Anomali (Key Insights / Financial Flags)**: Peringatan piutang macet, pengeluaran tak wajar, atau deviasi UJO.
4. **Rekomendasi Tindakan Keuangan (Actionable Financial Steps)**: Rekomendasi konkret bagi tim finance, kasir, atau penagihan.

PETA SKEMA TABEL ERP (KNOWLEDGE BASE):
{ERP_CORE_SCHEMA_MAP}

BATASAN KETAT:
- JANGAN PERNAH mengatakan "maaf data tidak tersedia" jika informasi tersebut dapat dihitung dari tabel database menggunakan `execute_analytical_sql`.
- Selalu patuhi keamanan read-only (hanya SELECT).
"""


async def _execute_finance_tool(tool_call) -> str:
    """Menjalankan fungsi Finance tool sesuai permintaan LLM."""
    func_name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
    except Exception:
        args = {}

    try:
        if func_name == "generate_chart_image":
            return await generate_chart_image(**args)
        elif func_name == "get_finance_overview":
            return await get_finance_overview()
        elif func_name == "get_invoices":
            return await get_invoices(**args)
        elif func_name == "get_cash_advances":
            return await get_cash_advances(**args)
        elif func_name == "get_kasir_ledger":
            return await get_kasir_ledger(**args)
        elif func_name == "execute_analytical_sql":
            return await execute_analytical_sql(**args)
        elif func_name == "inspect_table_schema":
            return await inspect_table_schema(**args)
        elif func_name == "search_database_tables":
            return await search_database_tables(**args)
        else:
            return f"Error: Tool '{func_name}' tidak dikenali oleh FINA."
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


async def process_finance_chat(messages: list[dict]) -> AsyncGenerator[str, None]:
    """
    Orkestrasi alur ReAct Multi-Round FINA:
    1. Prune riwayat obrolan
    2. Multi-turn reasoning loop untuk mengevaluasi data keuangan
    3. Sintesis laporan finansial secara streaming
    """
    pruned_history = prune_conversation_history(messages, max_history=6)

    now_str = datetime.now().strftime("%d %B %Y (%H:%M WIB)")
    dynamic_prompt = FINA_SYSTEM_PROMPT + f"\n[INFO SISTEM: Waktu saat ini adalah {now_str}.]\n"

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
                        tools=FINANCE_TOOLS,
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
                        yield f"⚠️ FINA gagal memproses permintaan: {err_str}"
                        return

            if resp_msg is None:
                yield f"⚠️ Maaf, kapasitas model sedang penuh ({str(last_err)}). Silakan coba lagi."
                return

            if resp_msg.tool_calls:
                conversation.append(resp_msg)
                for tool_call in resp_msg.tool_calls:
                    result = await _execute_finance_tool(tool_call)

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
                        tools=FINANCE_TOOLS,
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
