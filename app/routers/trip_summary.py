from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import json
import re
from app.llm.llm_client import client, settings

router = APIRouter()

class TripSummaryRequest(BaseModel):
    trip_id: str
    unit: str
    driver: str
    origin: str
    destination: str
    start_time: str
    end_time: str
    distance: int

@router.post("/trip-summary")
async def generate_trip_summary(request: TripSummaryRequest):
    prompt = f"""
Anda adalah AI Data Analyst Logistik untuk PT BCS Logistics.
Tugas Anda adalah membuat simulasi riwayat perjalanan (journey summary) untuk trip berikut:

- Trip ID: {request.trip_id}
- Kendaraan: {request.unit}
- Pengemudi: {request.driver}
- Origin: {request.origin}
- Destinasi: {request.destination}
- Waktu Berangkat: {request.start_time}
- Waktu Tiba: {request.end_time}
- Jarak: {request.distance} km

Karena log GPS detik-demi-detik tidak tersedia, buatkan *estimasi logis dan realistis* untuk merangkum fase-fase berikut secara berurutan:
1. Perjalanan dari Pool ke Origin.
2. Lama waktu muat barang (Loading) di Origin.
3. Perjalanan dari Origin ke Destinasi (termasuk perkiraan waktu istirahat).
4. Lama waktu bongkar barang (Unloading) di Destinasi.
5. Perjalanan kembali ke Pool.

PENTING: Output Anda HARUS berupa JSON murni (tanpa format markdown, tanpa ```json ... ```, tanpa kalimat pengantar).
Struktur JSON yang WAJIB digunakan:
{{
    "narrative": "Ringkasan cerita singkat (maksimal 2 paragraf) mengenai efisiensi perjalanan ini. Apakah on-time, apakah ada potensi delay, bagaimana kinerja driver.",
    "timeline": [
        {{ "phase": "Menuju Origin", "duration": "45m", "description": "Bergerak dari Pool menuju titik muat di {request.origin}." }},
        {{ "phase": "Loading", "duration": "1j 30m", "description": "Proses muat barang (loading) berjalan lancar." }},
        {{ "phase": "Perjalanan ke Destinasi", "duration": "5j 15m", "description": "Perjalanan menuju {request.destination} menempuh jarak {request.distance}km." }},
        {{ "phase": "Unloading", "duration": "2j 0m", "description": "Proses bongkar muatan di tujuan." }},
        {{ "phase": "Kembali ke Pool", "duration": "4j 30m", "description": "Unit kembali ke pool tanpa muatan (balikan kosong)." }}
    ]
}}
"""
    
    try:
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "system", "content": "You output strictly valid JSON."}, {"role": "user", "content": prompt}],
            temperature=0.6,
        )
        content = response.choices[0].message.content
        
        # Bersihkan <think> tags jika menggunakan deepseek
        clean_content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        
        # Pastikan format JSON terekstrak walau ada markdown
        if "```json" in clean_content:
            clean_content = clean_content.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_content:
            clean_content = clean_content.split("```")[1].split("```")[0].strip()

        return json.loads(clean_content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
