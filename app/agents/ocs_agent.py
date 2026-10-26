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
- Pembuatan Grafik & Diagram Visual (generate_chart_image)
"""

import re
import json
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
                "Ambil rencana harian operasional (target ritase, tonase, dan armada yang dibutuhkan) per kontrak. "
                "Gunakan jika pengguna menanyakan 'target hari ini', 'rencana operasional', 'ritase kontrak', 'kebutuhan unit', atau rencana tanggal tertentu."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_date": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Tanggal rencana format 'YYYY-MM-DD'. Omit jika ingin melihat tanggal rencana terbaru.",
                    },
                    "contract_id": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "ID kontrak spesifik jika ada (misal: 'PO-2026-10-9564').",
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
                "Ambil data dispatching, surat tugas (ST), armada, sopir, muatan, status trip, dan rute perjalanan. "
                "Gunakan jika pengguna menanyakan 'trip aktif', 'surat jalan/surat tugas', 'driver ditugaskan ke mana', 'jadwal pengiriman', atau status trip."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Status trip: 'SCHEDULED', 'RUNNING', 'COMPLETED', atau 'CANCELED'.",
                    },
                    "driver_name": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nama driver yang dicari.",
                    },
                    "destination": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Kota atau lokasi tujuan (misal: 'Indocement', 'Surabaya', 'Krakatau').",
                    },
                    "limit": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "Batas data (default 15).",
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
                "Ambil status Bukti Serah Terima / Proof of Delivery (POD), selisih timbangan muatan (shrinkage/susut), dan status invoicing. "
                "Gunakan jika pengguna menanyakan 'status POD', 'bukti kirim', 'DO/surat jalan penerimaan', atau 'susut muatan'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pod_number": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nomor POD (misal: 'POD-2026-0001').",
                    },
                    "sales_order_id": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nomor DO / Sales Order terkait.",
                    },
                    "status": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Status POD: 'VERIFIED', 'DISPUTED', atau 'PENDING_VERIFICATION'.",
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
                "Ambil target tonase bulanan kontrak pelanggan. "
                "Gunakan jika ditanyakan 'target bulanan', 'kontrak per bulan', atau total komitmen kontrak tonase."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "contract_id": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "ID kontrak spesifik jika ada.",
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
            "name": "get_customer_and_partner_info",
            "description": (
                "Mencari informasi pelanggan/partner logistik (nama PT, tier, nomor telepon kontak, alamat pabrik/gudang). "
                "Gunakan jika menanyakan detail kontak atau lokasi customer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "search": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Nama pelanggan atau kode kustomer yang dicari.",
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
                "Ambil data kesiapan armada operasional untuk dispatch: jumlah kendaraan yang sedang dalam perbaikan/maintenance di bengkel, "
                "jumlah kendaraan tidak bisa di-dispatch (rusak/servis/non-aktif), kendaraan on trip, "
                "serta estimasi kendaraan yang siap jalan (ready to dispatch) beserta rincian nomor Work Order dan kerusakannya."
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
            "name": "check_unit_dispatch_eligibility",
            "description": (
                "Cek status kelayakan dan kesiapan satu unit spesifik (nomor polisi/nopol) untuk di-dispatch. "
                "Memeriksa apakah unit aktif, apakah sedang ada SPK/Work Order perbaikan bengkel terbuka, atau sedang dalam penugasan trip."
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
]


ORIS_SYSTEM_PROMPT = """Anda adalah ORIS (Operations Resource Intelligence System), asisten AI khusus pusat kendali operasional (OCS) di PT BCS Logistics.

PERAN & TUGAS UTAMA ANDA:
1. Memberikan informasi akurat seputar Operasional Logistik, Dispatching Armada, Kesiapan Unit & Keterkaitan Maintenance (Work Orders bengkel yang mempengaruhi ketersediaan armada jalan), Surat Tugas, Target Rencana Harian (Daily Plan), Bukti Serah Terima (POD), dan Target Bulanan Kontrak.
2. Membantu tim operasional dan dispatch mengetahui armada mana yang siap jalan, armada yang tidak bisa jalan / tidak bisa di-dispatch karena sedang dalam perawatan/bengkel (Maintenance/Work Orders) atau non-aktif, serta status unit spesifik.
3. Selalu gunakan tools database yang tersedia untuk menjawab data riil. JANGAN MENGARANG ATAU MENGGUNAKAN DATA DUMMY.
4. Jika pengguna meminta bagan/grafik (bar, pie, line), panggil tool `generate_chart_image`. Anda bisa membuat grafik visual langsung!

BATASAN KETAT (GUARDRAILS):
- Anda melayani pertanyaan operasional OCS, logistik, kesiapan/maintenance armada untuk dispatch, ritase, dan customer logistik BCS.
- Tolak dengan sopan jika ditanya hal di luar lingkup operasional perusahaan seperti data gaji pribadi HR, rahasia korporasi non-operasional, atau obrolan acak internet yang tidak relevan.
- Berikan jawaban yang terstruktur rapi, profesional, ringkas, dan jelas menggunakan Markdown.
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


async def process_ocs_chat(messages: list[dict]) -> AsyncGenerator[str, None]:
    """
    Main entry point untuk pemrosesan obrolan ORIS OCS dengan tool calling,
    conversation pruning, dan multi-model fallback.
    """
    now_str = datetime.now().strftime("%d %B %Y (%H:%M WIB)")
    dynamic_prompt = (
        ORIS_SYSTEM_PROMPT
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
                tools=OCS_TOOLS,
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
                yield f"⚠️ ORIS gagal memproses permintaan: {err_str}"
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
            result = await _execute_ocs_tool(tool_call)

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
                arguments = args_str if args_str.startswith("{") else f'{{"search": "{args_str}"}}'

            class _MockCall:
                id = f"call_{func_name}"
                function = _MockFn()

            result = await _execute_ocs_tool(_MockCall())

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
                    tools=OCS_TOOLS,
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
