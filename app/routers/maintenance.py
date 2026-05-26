"""
Predictive Maintenance Router
─────────────────────────────────────────────────────────────────
Menganalisis jadwal pemeliharaan dan riwayat perjalanan armada
untuk memprediksi potensi kerusakan dan memberikan peringatan.
"""

from fastapi import APIRouter
from pydantic import BaseModel
import json
from datetime import datetime

from app.llm.llm_client import client, settings

router = APIRouter()

class FleetUnit(BaseModel):
    nopol: str
    type: str
    next_maintenance_date: str
    days_until_maintenance: int
    trips_last_30_days: int

class MaintenanceRequest(BaseModel):
    units: list[FleetUnit]

class MaintenanceAlert(BaseModel):
    nopol: str
    urgency: str # "CRITICAL", "WARNING", or "NORMAL"
    reason: str

class MaintenanceResponse(BaseModel):
    alerts: list[MaintenanceAlert]
    summary: str

@router.post("/predict-maintenance", response_model=MaintenanceResponse)
async def predict_maintenance(request: MaintenanceRequest):
    if not request.units:
        return MaintenanceResponse(alerts=[], summary="Tidak ada data unit yang dikirim.")
        
    current_date_str = datetime.now().strftime("%Y-%m-%d")
    units_text = "\n".join([
        f"- Nopol: {u.nopol}, Tipe: {u.type}, Hari menuju jadwal servis: {u.days_until_maintenance} hari, Trip 30 hari terakhir: {u.trips_last_30_days} trip"
        for u in request.units
    ])
    
    prompt = f"""
Anda adalah AI FARIDA, pakar Predictive Maintenance armada logistik.
Hari ini adalah {current_date_str}.

Berikut adalah data beberapa truk beserta kondisi operasionalnya:
{units_text}

Tugas Anda:
1. Analisis setiap truk.
2. Jika hari menuju servis <= 7 hari ATAU jumlah trip >= 15 dalam 30 hari, berikan status "CRITICAL".
3. Jika hari menuju servis <= 14 hari ATAU jumlah trip >= 10, berikan status "WARNING".
4. Jika tidak memenuhi kondisi di atas, abaikan (tidak perlu masuk alert).
5. Berikan alasan teknis dalam Bahasa Indonesia (maksimal 2 kalimat) mengapa truk tersebut butuh perhatian (misal: "Kampas rem berpotensi tipis karena beban 15 trip berturut-turut").
6. Buat sebuah summary/ringkasan singkat mengenai kondisi kesehatan keseluruhan armada yang Anda analisis.

PENTING:
Balas HANYA dengan format JSON valid berikut (jangan ada teks/markdown di luar JSON):
{{
    "alerts": [
        {{
            "nopol": "NOPOL",
            "urgency": "CRITICAL atau WARNING",
            "reason": "Alasan..."
        }}
    ],
    "summary": "Ringkasan singkat keseluruhan armada."
}}
"""

    try:
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=2048,
        )
        
        content = response.choices[0].message.content.strip()
        
        # Clean <think> tags if model is deepseek/qwen
        if "<think>" in content:
            parts = content.split("</think>")
            if len(parts) > 1:
                content = parts[-1].strip()
                
        # Clean markdown
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
            
        result = json.loads(content.strip())
        
        alerts = []
        for alert in result.get("alerts", []):
            alerts.append(MaintenanceAlert(
                nopol=alert.get("nopol", ""),
                urgency=alert.get("urgency", "WARNING"),
                reason=alert.get("reason", "Tidak ada alasan spesifik")
            ))
            
        return MaintenanceResponse(
            alerts=alerts,
            summary=result.get("summary", "Analisis pemeliharaan selesai.")
        )
    except Exception as e:
        print(f"LLM Maintenance Analysis failed: {e}")
        return MaintenanceResponse(
            alerts=[],
            summary=f"Gagal memproses analisis pemeliharaan: {str(e)}"
        )
