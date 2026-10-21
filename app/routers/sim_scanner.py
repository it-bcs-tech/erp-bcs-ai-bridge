"""
SIM Scanner Router — /ocs/scan-sim
───────────────────────────────────────────────────────────
Menerima upload foto/gambar fisik Surat Izin Mengemudi (SIM),
memprosesnya dengan Vision AI (OpenAI-compatible / Groq Llama Vision),
dan mengembalikan data JSON terstruktur untuk verifikasi operasional.
"""

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
import base64
import json
import re
from typing import Optional

from app.config import get_settings
from app.llm.llm_client import client

router = APIRouter()
settings = get_settings()


class SimScanResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    data: Optional[dict] = None


@router.post("/scan-sim", response_model=SimScanResponse)
async def scan_sim(
    file: Optional[UploadFile] = File(None),
    image_base64: Optional[str] = Form(None),
    mime_type: Optional[str] = Form("image/jpeg"),
):
    """
    Ekstrak data Surat Izin Mengemudi (SIM) dari berkas gambar via Vision AI.
    Bisa menerima file multipart/form-data ATAU base64 string.
    """
    base64_data = ""
    actual_mime = mime_type or "image/jpeg"

    if file:
        content = await file.read()
        base64_data = base64.b64encode(content).decode("utf-8")
        if file.content_type:
            actual_mime = file.content_type
    elif image_base64:
        # Bersihkan data:image/...;base64, prefix jika disertakan
        if "," in image_base64:
            header, base64_data = image_base64.split(",", 1)
            match = re.search(r"data:([^;]+);base64", header)
            if match:
                actual_mime = match.group(1)
        else:
            base64_data = image_base64
    else:
        raise HTTPException(status_code=400, detail="File gambar SIM atau image_base64 wajib diunggah.")

    system_prompt = (
        "Anda adalah asisten AI OCR cerdas khusus membaca dokumen resmi Surat Izin Mengemudi (SIM) Kepolisian Republik Indonesia. "
        "Tugas Anda mengekstrak informasi pada foto fisik SIM dengan akurasi 100% dan mengembalikannya HANYA sebagai JSON murni tanpa pengantar atau markdown."
    )

    user_prompt = (
        "Analisis gambar SIM berikut dan ekstrak data ke dalam format JSON dengan struktur persis seperti ini:\n"
        "{\n"
        '  "sim_type": "SIM B2 UMUM", // Pilih persis salah satu: "SIM A", "SIM B1", "SIM B1 UMUM", "SIM B2", "SIM B2 UMUM", "SIM C"\n'
        '  "sim_number": "123456789012", // Nomor SIM (string angka tanpa spasi)\n'
        '  "driver_name": "NAMA LENGKAP PENGEMUDI", // Huruf kapital sesuai yang tercetak\n'
        '  "expiry_date": "YYYY-MM-DD", // Tanggal masa berlaku (format YYYY-MM-DD)\n'
        '  "birth_place": "KOTA LAHIR",\n'
        '  "birth_date": "YYYY-MM-DD", // Tanggal lahir jika terbaca\n'
        '  "address": "ALAMAT PADA SIM",\n'
        '  "blood_type": "A / B / AB / O / -",\n'
        '  "confidence_score": 0.95 // Tingkat keyakinan bacaan (0.0 - 1.0)\n'
        "}\n\n"
        "Catatan penting:\n"
        "1. Pastikan expiry_date dalam format ISO YYYY-MM-DD. Jika tertulis tanggal seperti '25-10-2029', ubah menjadi '2029-10-25'.\n"
        "2. Jika foto buram atau field tertentu tidak terbaca, isi dengan null.\n"
        "3. Berikan respons HANYA valid JSON."
    )

    try:
        response = await client.chat.completions.create(
            model=settings.llm_vision_model or settings.llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{actual_mime};base64,{base64_data}"
                            },
                        },
                    ],
                },
            ],
            temperature=0.1,
            max_tokens=1000,
        )

        raw_content = response.choices[0].message.content or "{}"
        
        # Bersihkan format markdown jika model menyertakan ```json ... ```
        cleaned_json = raw_content.strip()
        if cleaned_json.startswith("```"):
            cleaned_json = re.sub(r"^```(?:json)?\s*", "", cleaned_json)
            cleaned_json = re.sub(r"\s*```$", "", cleaned_json)

        data = json.loads(cleaned_json)

        # Standardisasi jenis SIM
        raw_type = str(data.get("sim_type") or "").upper()
        if "B2" in raw_type and "UMUM" in raw_type:
            data["sim_type"] = "SIM B2 UMUM"
        elif "B2" in raw_type:
            data["sim_type"] = "SIM B2"
        elif "B1" in raw_type and "UMUM" in raw_type:
            data["sim_type"] = "SIM B1 UMUM"
        elif "B1" in raw_type:
            data["sim_type"] = "SIM B1"
        elif "A" in raw_type:
            data["sim_type"] = "SIM A"
        elif "C" in raw_type:
            data["sim_type"] = "SIM C"

        return SimScanResponse(
            success=True,
            message="Foto SIM berhasil dipindai dan diekstrak oleh AI.",
            data=data,
        )

    except json.JSONDecodeError:
        # Fallback jika model mengembalikan teks non-JSON
        return SimScanResponse(
            success=False,
            message="AI membaca dokumen namun gagal menyusun format data. Silakan tinjau dan masukkan manual.",
            data={
                "sim_type": "SIM B2 UMUM",
                "sim_number": None,
                "driver_name": None,
                "expiry_date": None,
                "raw_text": raw_content,
            },
        )
    except Exception as e:
        return SimScanResponse(
            success=False,
            message=f"Gagal memproses gambar SIM via AI Vision: {str(e)}",
            data=None,
        )
