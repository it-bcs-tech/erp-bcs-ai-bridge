"""
Marketing Agent — MARKO
─────────────────────────────────────────────────────────────────
Marketing, Acquisition & Revenue Commercial Assistant

MARKO adalah asisten AI komersial, kontrak logistik, sales order, dan deals PT BCS Logistics.
Memiliki akses langsung ke database marketing dan operasional komersial:
- Sales Order Logistik (marketing.sales_order)
- Kontrak Komersial & Nilai Kontrak (marketing.contract)
- Pipeline Deals & Prospek Bisnis (marketing.deals)
- Master Pelanggan & Analisis Tier (master.m_customer)
- Mesin Kueri Analitis & Text-to-SQL Aman (execute_analytical_sql)
- Inspeksi Skema Database Dinamis (inspect_table_schema, search_database_tables)
- Pembuatan Grafik Pendapatan & Tonase (generate_chart_image)
"""

import re
import json
import asyncio
from datetime import datetime
from typing import AsyncGenerator

from app.llm.llm_client import client, settings, get_llm_client
from app.tools.chart_tools import CHART_TOOL_SCHEMA, generate_chart_image
from app.tools.marketing_tools import (
    get_marketing_overview,
    get_sales_orders,
    get_commercial_contracts,
    get_marketing_deals,
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


def prune_conversation_history(messages: list[dict], max_history: int = 10, max_assistant_chars: int = 3500) -> list[dict]:
    """
    Memangkas riwayat obrolan secara aman untuk menjaga kontinuitas konteks percakapan multi-turn:
    1. Membuang pesan error sistem.
    2. Menyimpan hingga N pesan terakhir (Sliding Window 10 pesan / 5 putaran penuh).
    3. Mempertahankan konteks entitas (tabel, nama, ID, nomor dokumen/unit) hingga 3500 karakter per pesan asisten.
    """
    clean = []
    for m in messages:
        c = m.get("content", "")
        if isinstance(c, str) and (c.strip().startswith("⚠️") or "Error code:" in c):
            continue
        clean.append(dict(m))

    if len(clean) <= max_history:
        sliced = clean
    else:
        sliced = clean[-max_history:]

    pruned = []
    for i, m in enumerate(sliced):
        role = m.get("role")
        content = m.get("content", "")
        if role == "assistant" and isinstance(content, str) and len(content) > max_assistant_chars and i < len(sliced) - 1:
            pruned.append({
                "role": role,
                "content": content[:max_assistant_chars] + "\n\n... [Sebagian rincian data diringkas demi kapasitas token] ..."
            })
        else:
            pruned.append(m)
    return pruned


MARKETING_TOOLS = [
    CHART_TOOL_SCHEMA,
    {
        "type": "function",
        "function": {
            "name": "get_marketing_overview",
            "description": (
                "Ambil ringkasan umum data komersial marketing terkini: total sales order terbit dan nilai tarif, "
                "rekap kontrak logistik aktif, pemenuhan target tonase angkutan, dan pipeline deals. "
                "Gunakan saat pengguna menanyakan 'ringkasan marketing', 'kondisi penjualan', 'overview komersial', dsb."
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
            "name": "get_sales_orders",
            "description": (
                "Ambil daftar Sales Order (SO) logistik lengkap: nomor SO, nama pelanggan, jenis muatan, berat tonase, nilai tarif, "
                "tanggal pembuatan/pemuatan (created_from/created_to), pembuat data (created_by), dan status. "
                "Gunakan saat pengguna menanyakan 'daftar sales order', 'order baru dibuat 1 minggu terakhir', 'cek SO customer X'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Status SO: 'CONFIRMED', 'DELIVERED', 'COMPLETED', 'DISPATCHED', 'DRAFT'.",
                    },
                    "keyword": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Kata kunci pencarian: nomor SO, nama pelanggan, atau jenis muatan.",
                    },
                    "created_from": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Filter tanggal awal pembuatan/pemuatan SO (format 'YYYY-MM-DD', misal '2026-10-26').",
                    },
                    "created_to": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Filter tanggal akhir pembuatan/pemuatan SO (format 'YYYY-MM-DD', misal '2026-11-02').",
                    },
                    "created_by": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nama user pembuat data SO (misal 'superhyperadmin', 'admin').",
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
            "name": "get_commercial_contracts",
            "description": (
                "Ambil data kontrak komersial logistik: nilai kontrak, pelanggan, target tonase, realisasi tonase muatan, "
                "tanggal pembuatan kontrak (created_from/created_to), pembuat kontrak (created_by), dan status masa berlaku. "
                "Gunakan saat pengguna menanyakan 'daftar kontrak', 'kontrak baru dibuat', 'progres tonase kontrak'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Status kontrak: 'ACTIVE', 'COMPLETED', 'EXPIRED'.",
                    },
                    "keyword": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Kata kunci nomor kontrak, nama pelanggan, atau catatan.",
                    },
                    "created_from": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Filter tanggal awal pembuatan kontrak (format 'YYYY-MM-DD').",
                    },
                    "created_to": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Filter tanggal akhir pembuatan kontrak (format 'YYYY-MM-DD').",
                    },
                    "created_by": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nama user pembuat kontrak.",
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
            "name": "get_marketing_deals",
            "description": (
                "Ambil data prospek peluang bisnis / pipeline deals penjualan komersial: nama calon klien, PIC, potensi nilai tarif dan tonase, target closing, pembuat deal, dan status konversi. "
                "Gunakan saat pengguna menanyakan 'pipeline deals', 'prospek baru', 'peluang penjualan'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "stage": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Tahap deal komersial.",
                    },
                    "keyword": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Kata kunci nama perusahaan prospek atau kontak person.",
                    },
                    "created_from": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Filter tanggal awal pembuatan deal (format 'YYYY-MM-DD').",
                    },
                    "created_to": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Filter tanggal akhir pembuatan deal (format 'YYYY-MM-DD').",
                    },
                    "created_by": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nama user pembuat prospek deal.",
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
            "name": "execute_analytical_sql",
            "description": (
                "Jalankan kueri SQL analitis SELECT kustom secara aman ke database PostgreSQL ERP BCS. "
                "Gunakan tool ini ketika pengguna meminta agregasi kustom (ranking pelanggan dengan omzet terbesar, tren tonase bulanan, rasio margin tarif per rute). "
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
                        "description": "Nama tabel (misal: 'marketing.sales_order', 'marketing.contract', 'master.m_customer').",
                    },
                    "schema_name": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nama skema database (opsional, misal: 'marketing', 'master').",
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

MARKO_SYSTEM_PROMPT = f"""Anda adalah MARKO (Marketing, Acquisition & Revenue Commercial Assistant), asisten AI khusus divisi Komersial, Kontrak, dan Penjualan Logistik di PT BCS Logistics.

KEMAMPUAN UTAMA ANDA:
1. Anda memiliki akses penuh ke database PostgreSQL komersial ERP BCS: Sales Order (SO), Kontrak Pelanggan, Pipeline Deals, serta data profil pelanggan (Platinum, Gold, Silver).
2. Selagi data ada di database, Anda MAMPU mengolah, mengagregasi, menggabungkan (JOIN), dan menganalisisnya menjadi intelijen bisnis dan pendapatan bernilai tinggi.
3. Gunakan kueri analitis aman (`execute_analytical_sql`) untuk pertanyaan kompleks seperti:
   - Menghitung pelanggan dengan kontribusi tonase atau pendapatan terbesar (Pareto 80/20).
   - Melacak deviasi antara target tonase kontrak dengan realisasi ritase aktual.
   - Menganalisis rata-rata tarif angkut per ton atau per rute pengiriman.
4. PETA SKEMA TABEL ERP (KNOWLEDGE BASE) di bawah ini SUDAH LENGKAP dengan daftar kolom tabel utama. LANGSUNG jalankan `execute_analytical_sql` pada putaran pertama tanpa membuang waktu memanggil `inspect_table_schema` kecuali untuk tabel yang belum ada di daftar skema.
5. Jika pengguna meminta visualisasi grafik penjualan atau distribusi tonase, panggil tool `generate_chart_image`.

STANDAR STRUKTUR JAWABAN ANDA:
1. **Ringkasan Eksekutif (Direct Answer)**: Jawaban to-the-point mengenai angka omzet, volume, atau status order.
2. **Matriks Bukti Data / Tabel**: Format Markdown table yang rapi dengan angka Rupiah dan Tonase presisi.
3. **Wawasan Komersial (Commercial Insights / Growth Opportunities)**: Pola volume, loyalitas pelanggan, atau resiko under-delivery kontrak.
4. **Rekomendasi Tindakan Komersial (Actionable Sales Steps)**: Rekomendasi konkret bagi tim sales, account manager, atau manajemen marketing.

PETA SKEMA TABEL ERP (KNOWLEDGE BASE):
{ERP_CORE_SCHEMA_MAP}

KEMAMPUAN FILTER TANGGAL PEMBUATAN & PEMBUAT DATA (TEMPORAL & CREATOR CAPABILITY):
- Anda memiliki akses langsung ke kolom `created_at` (tanggal/waktu pembuatan) dan `created_by` (nama user pembuat) di tabel `marketing.sales_order`, `marketing.contract`, dan `marketing.deals`.
- Jika pengguna meminta data yang baru dibuat hari ini, 1 minggu terakhir, bulan ini, rentang tanggal tertentu, atau oleh pembuat tertentu:
  Anda DAPAT dan WAJIB menyajikannya melalui kueri SQL analitis (`execute_analytical_sql`) dengan filter `WHERE created_at >= ...` atau `WHERE created_by = ...`.
- DILARANG KERAS mengatakan sistem memiliki batasan tidak bisa memfilter tanggal pembuatan atau pembuat data!

BATASAN KETAT:
- JANGAN PERNAH mengatakan "maaf data tidak tersedia" jika informasi tersebut dapat dihitung dari database menggunakan `execute_analytical_sql`.
- Selalu patuhi keamanan read-only (hanya SELECT).
"""


async def _execute_marketing_tool(tool_call) -> str:
    """Menjalankan fungsi Marketing tool sesuai permintaan LLM."""
    func_name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
    except Exception:
        args = {}

    try:
        if func_name == "generate_chart_image":
            return await generate_chart_image(**args)
        elif func_name == "get_marketing_overview":
            return await get_marketing_overview()
        elif func_name == "get_sales_orders":
            return await get_sales_orders(**args)
        elif func_name == "get_commercial_contracts":
            return await get_commercial_contracts(**args)
        elif func_name == "get_marketing_deals":
            return await get_marketing_deals(**args)
        elif func_name == "execute_analytical_sql":
            return await execute_analytical_sql(**args)
        elif func_name == "inspect_table_schema":
            return await inspect_table_schema(**args)
        elif func_name == "search_database_tables":
            return await search_database_tables(**args)
        else:
            return f"Error: Tool '{func_name}' tidak dikenali oleh MARKO."
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


async def process_marketing_chat(
    messages: list[dict],
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    Orkestrasi alur ReAct Multi-Round MARKO:
    1. Prune riwayat obrolan
    2. Multi-turn reasoning loop untuk mengevaluasi data komersial
    3. Real-time word streaming respon final
    """
    pruned_history = prune_conversation_history(messages, max_history=10, max_assistant_chars=3500)

    now_str = datetime.now().strftime("%d %B %Y (%H:%M WIB)")
    dynamic_prompt = MARKO_SYSTEM_PROMPT + f"\n[INFO SISTEM: Waktu saat ini adalah {now_str}.]\n"

    conversation = [{"role": "system", "content": dynamic_prompt}]
    conversation.extend(pruned_history)

    active_client = get_llm_client(base_url=base_url, api_key=api_key)
    active_model = model or CANDIDATE_MODELS[0]
    candidate_list = [active_model] if base_url else ([active_model] + [m for m in CANDIDATE_MODELS if m != active_model])
    active_temp = temperature if temperature is not None else 0.1

    MAX_ROUNDS = 3
    has_streamed = False

    for round_idx in range(MAX_ROUNDS):
        resp_msg = None
        last_err = None

        for model_name in candidate_list:
            try:
                resp = await active_client.chat.completions.create(
                    model=model_name,
                    messages=conversation,
                    tools=MARKETING_TOOLS,
                    tool_choice="auto",
                    temperature=active_temp,
                    max_tokens=max_tokens,
                )
                resp_msg = resp.choices[0].message
                active_model = model_name
                break
            except Exception as e:
                err_str = str(e)
                last_err = e
                if "429" in err_str or "rate limit" in err_str.lower() or "413" in err_str:
                    continue
                else:
                    yield f"⚠️ MARKO gagal memproses permintaan: {err_str}"
                    return

        if resp_msg is None:
            yield f"⚠️ Maaf, kapasitas model sedang penuh ({str(last_err)}). Silakan coba lagi."
            return

        if resp_msg.tool_calls:
            conversation.append(resp_msg)
            for tool_call in resp_msg.tool_calls:
                result = await _execute_marketing_tool(tool_call)

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
            yield f"**Hasil Analisis Komersial Terkini:**\n\n{last_tool_res}"
        else:
            yield "⚠️ Maaf, tidak ada respon data yang dapat ditampilkan saat ini."
