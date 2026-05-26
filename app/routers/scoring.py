"""
Driver Scoring Router
─────────────────────────────────────────────────────────────────
Mengevaluasi kinerja sopir berdasarkan data perjalanan dan
insiden/anomali yang tercatat di sistem.
"""

from fastapi import APIRouter
from pydantic import BaseModel
import json

from app.llm.llm_client import client, settings

router = APIRouter()

class DriverStat(BaseModel):
    driver_id: str
    name: str
    total_trips_30d: int
    total_incidents_30d: int
    total_notes_30d: int

class ScoringRequest(BaseModel):
    drivers: list[DriverStat]

class DriverScore(BaseModel):
    driver_id: str
    name: str
    score: int # 0 - 100
    review: str

class ScoringResponse(BaseModel):
    leaderboard: list[DriverScore]

@router.post("/driver-scoring", response_model=ScoringResponse)
async def score_drivers(request: ScoringRequest):
    if not request.drivers:
        return ScoringResponse(leaderboard=[])
        
    drivers_text = "\n".join([
        f"- ID: {d.driver_id}, Nama: {d.name}, Total Trip (30 Hari): {d.total_trips_30d}, Insiden Parah: {d.total_incidents_30d}, Catatan Rute: {d.total_notes_30d}"
        for d in request.drivers
    ])
    
    prompt = f"""
Anda adalah AI FARIDA, pakar HRD dan Evaluasi Perilaku Pengemudi untuk perusahaan logistik.

Berikut adalah statistik kinerja beberapa sopir dalam 30 hari terakhir:
{drivers_text}

Tugas Anda:
1. Berikan skor (0-100) untuk masing-masing sopir.
   - Dasar skor adalah 90 untuk sopir dengan trip > 0 tanpa insiden.
   - Kurangi 15 poin untuk setiap "Insiden Parah" (misal: keluar rute fatal).
   - Kurangi 2 poin untuk setiap "Catatan Rute" (misal: mengambil jalan alternatif yang masih wajar).
   - Tambahkan 1 poin untuk setiap "Total Trip" yang berhasil (maksimal skor 100).
   - Jika Total Trip = 0, berikan skor 70 (karena tidak ada produktivitas).
2. Tulis "review" (ulasan singkat) yang mengomentari kinerjanya. Maksimal 1 kalimat dalam Bahasa Indonesia.
   - Contoh pujian: "Kinerja sangat andal dan aman tanpa catatan pelanggaran."
   - Contoh teguran: "Perlu pembinaan karena sering terjadi insiden keluar jalur yang membahayakan operasional."

PENTING:
Balas HANYA dengan format JSON valid berikut:
{{
    "leaderboard": [
        {{
            "driver_id": "ID",
            "name": "NAMA",
            "score": 95,
            "review": "Ulasan singkat..."
        }}
    ]
}}
"""

    try:
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=2048,
        )
        
        content = response.choices[0].message.content.strip()
        
        if "<think>" in content:
            parts = content.split("</think>")
            if len(parts) > 1:
                content = parts[-1].strip()
                
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
            
        result = json.loads(content.strip())
        
        scores = []
        for d in result.get("leaderboard", []):
            # Ensure safe types
            scores.append(DriverScore(
                driver_id=str(d.get("driver_id", "")),
                name=str(d.get("name", "")),
                score=int(d.get("score", 0)),
                review=str(d.get("review", ""))
            ))
            
        # Sort leaderboard descending
        scores.sort(key=lambda x: x.score, reverse=True)
            
        return ScoringResponse(leaderboard=scores)
    except Exception as e:
        print(f"LLM Driver Scoring failed: {e}")
        return ScoringResponse(leaderboard=[])
