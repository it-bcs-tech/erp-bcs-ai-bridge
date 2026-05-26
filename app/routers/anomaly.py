"""
FMS Anomaly Analysis Router
─────────────────────────────────────────────────────────────────
Menganalisis deviasi GPS dari go-map menggunakan LLM untuk menentukan
apakah itu shortcut (NOTE) atau anomali fatal (INCIDENT).
"""

from fastapi import APIRouter
from pydantic import BaseModel
import httpx
import json

from app.llm.llm_client import client, settings

router = APIRouter()

class AnomalyAnalysisRequest(BaseModel):
    trip_id: int
    vehicle_plate: str
    current_lat: float
    current_lon: float
    destination_lat: float
    destination_lon: float

class AnomalyAnalysisResponse(BaseModel):
    status: str
    notes: str
    new_distance: float

@router.post("/anomaly-analysis", response_model=AnomalyAnalysisResponse)
async def analyze_anomaly(request: AnomalyAnalysisRequest):
    # 1. Fetch new route from go-map
    go_map_url = f"http://localhost:8081/api/fms/route?startLat={request.current_lat}&startLng={request.current_lon}&endLat={request.destination_lat}&endLng={request.destination_lon}"
    
    new_distance = 0.0
    new_duration = 0.0
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            resp = await http_client.get(go_map_url)
            if resp.status_code == 200:
                data = resp.json()
                new_distance = data.get("distance", 0.0)
                new_duration = data.get("duration", 0.0)
    except Exception as e:
        print(f"Failed to fetch new route from go-map: {e}")
        # Fallback if go-map fails
        return AnomalyAnalysisResponse(
            status="INCIDENT",
            notes="ANOMALI: KELUAR JALUR (Gagal menganalisa rute baru)",
            new_distance=new_distance
        )
        
    # 2. Prepare prompt for LLM
    prompt = f"""
Anda adalah AI Dispatcher logistik bernama FARIDA.
Truk {request.vehicle_plate} keluar dari rute awal sejauh > 500 meter.
Saya baru saja menghitung ulang rute dari posisi truk saat ini ke tujuan akhir.
Jarak rute baru ke tujuan adalah {(new_distance/1000):.1f} km, dengan estimasi waktu {(new_duration/60):.0f} menit.

Tugas Anda:
Nilai apakah ini deviasi yang wajar (mungkin mencari jalan pintas/alternatif) atau deviasi fatal/mencurigakan (nyasar/keluar arah). 
Karena Anda tidak tahu jarak rute aslinya, jika jarak barunya masih masuk akal (tidak 0, dan masuk akal untuk operasional logistik darat), anggap ini jalan alternatif.

PENTING:
Balas HANYA dalam format JSON valid tanpa markdown, dengan struktur berikut:
{{
    "status": "NOTE" atau "INCIDENT",
    "notes": "Penjelasan singkat dalam Bahasa Indonesia (maksimal 2 kalimat)"
}}
Gunakan status "NOTE" jika ini shortcut/wajar, atau "INCIDENT" jika sangat mencurigakan.
    """
    
    try:
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
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
        status = result.get("status", "INCIDENT")
        notes = result.get("notes", "ANOMALI: KELUAR JALUR")
        
        return AnomalyAnalysisResponse(
            status=status,
            notes=notes,
            new_distance=new_distance
        )
    except Exception as e:
        print(f"LLM Analysis failed: {e}")
        return AnomalyAnalysisResponse(
            status="INCIDENT",
            notes="ANOMALI: KELUAR JALUR (Analisis AI Gagal)",
            new_distance=new_distance
        )
