"""
Smart Dispatch Router
─────────────────────────────────────────────────────────────────
Menganalisis order (muatan, tujuan) dan armada yang tersedia,
lalu memberikan rekomendasi penugasan truk dan sopir terbaik.
"""

from fastapi import APIRouter
from pydantic import BaseModel
import json

from app.llm.llm_client import client, settings

router = APIRouter()

class OrderDetail(BaseModel):
    cargo: str
    weight: float
    origin: str
    destination: str
    loading_date: str

class AvailableUnit(BaseModel):
    nopol: str
    type: str
    driver: str

class SmartDispatchRequest(BaseModel):
    order: OrderDetail
    available_units: list[AvailableUnit]

class SmartDispatchResponse(BaseModel):
    recommended_unit: str
    reason: str

@router.post("/smart-dispatch", response_model=SmartDispatchResponse)
async def analyze_dispatch(request: SmartDispatchRequest):
    if not request.available_units:
        return SmartDispatchResponse(
            recommended_unit="",
            reason="Tidak ada unit yang tersedia di Pool saat ini."
        )
        
    # Format available units for prompt
    units_text = "\n".join([f"- Nopol: {u.nopol}, Tipe: {u.type}, Driver: {u.driver}" for u in request.available_units])
    
    prompt = f"""
Anda adalah AI Dispatcher logistik bernama FARIDA.
Ada sebuah tugas pengiriman baru dengan detail:
- Muatan: {request.order.cargo} ({request.order.weight} ton)
- Rute: {request.order.origin} -> {request.order.destination}
- Tanggal Muat: {request.order.loading_date}

Berikut adalah daftar truk yang saat ini sedang Standby di Pool:
{units_text}

Tugas Anda:
Pilih SATU unit truk dari daftar di atas yang paling cocok untuk mengangkut muatan ini.
Jika kargo berupa batu bara/pasir/tanah, prioritaskan tipe unit DUMP TRUCK.
Jika kargo berupa barang palet/kargo umum, prioritaskan tipe unit WINGBOX atau TRAILER.
Berikan alasan logis mengapa Anda memilih truk dan sopir tersebut.

PENTING:
Balas HANYA dalam format JSON valid tanpa markdown, dengan struktur berikut:
{{
    "recommended_unit": "NOPOL",
    "reason": "Alasan singkat dalam Bahasa Indonesia (maksimal 2 kalimat)"
}}
"""

    try:
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        
        content = response.choices[0].message.content.strip()
        
        # Clean <think> tags if model is deepseek/qwen
        if "<think>" in content:
            parts = content.split("</think>")
            if len(parts) > 1:
                content = parts[-1].strip()
                
        # Clean markdown code blocks if any
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
            
        result = json.loads(content.strip())
        unit = result.get("recommended_unit", "")
        reason = result.get("reason", "Rekomendasi AI (Parsing gagal)")
        
        # Validate that the unit actually exists in the list
        valid_nopols = [u.nopol.replace(" ", "") for u in request.available_units]
        requested_clean = unit.replace(" ", "")
        
        final_unit = ""
        for u in request.available_units:
            if u.nopol.replace(" ", "") == requested_clean:
                final_unit = u.nopol
                break
                
        if not final_unit and request.available_units:
            final_unit = request.available_units[0].nopol
            reason = "Rekomendasi fallback karena AI memilih unit yang salah eja."
            
        return SmartDispatchResponse(
            recommended_unit=final_unit,
            reason=reason
        )
    except Exception as e:
        print(f"LLM Dispatch Analysis failed: {e}")
        return SmartDispatchResponse(
            recommended_unit=request.available_units[0].nopol if request.available_units else "",
            reason=f"Gagal menghubungi AI: {str(e)}"
        )
