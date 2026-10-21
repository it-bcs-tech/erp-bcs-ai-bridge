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
        "Anda adalah asisten AI Vision OCR cerdas khusus membaca dokumen identitas resmi Republik Indonesia: "
        "Surat Izin Mengemudi (SIM) atau Kartu Tanda Penduduk (e-KTP). "
        "Tugas Anda mendeteksi jenis dokumen yang diunggah dan mengekstrak informasi di dalamnya secara akurat. "
        "Kembalikan HANYA JSON murni tanpa kata pengantar atau markdown."
    )

    user_prompt = (
        "Analisis gambar berikut. Deteksi apakah gambar ini adalah SIM atau KTP (e-KTP), lalu ekstrak datanya ke format JSON persis seperti ini:\n"
        "{\n"
        '  "doc_type": "SIM", // "SIM" atau "KTP"\n'
        '  "sim_type": "SIM B2 UMUM", // Jika SIM, pilih salah satu: "SIM A", "SIM B1", "SIM B1 UMUM", "SIM B2", "SIM B2 UMUM", "SIM C". Jika KTP, isi null.\n'
        '  "sim_number": "123456789012", // Jika SIM nomor SIM; jika KTP isi nomor NIK\n'
        '  "nik": "3671012345670001", // Nomor NIK jika KTP, atau null jika SIM\n'
        '  "driver_name": "NAMA LENGKAP", // Sesuai yang tercetak pada kartu\n'
        '  "expiry_date": "YYYY-MM-DD", // Tanggal masa berlaku format ISO YYYY-MM-DD. Jika KTP Seumur Hidup, isi null.\n'
        '  "birth_place": "KOTA LAHIR",\n'
        '  "birth_date": "YYYY-MM-DD", // Format YYYY-MM-DD\n'
        '  "address": "ALAMAT LENGKAP",\n'
        '  "gender": "L / P",\n'
        '  "blood_type": "A / B / AB / O / -",\n'
        '  "confidence_score": 0.95 // Tingkat keyakinan (0.0 - 1.0)\n'
        "}\n\n"
        "Aturan Penting:\n"
        "1. Format tanggal WAJIB ISO YYYY-MM-DD. Jika tertulis '25-10-2029', ubah menjadi '2029-10-25'.\n"
        "2. Jangan tambahkan markdown triple backtick. Berikan respons HANYA teks JSON valid."
    )

    candidate_models = [
        settings.llm_vision_model,
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "qwen/qwen3.8-27b",
        "meta-llama/llama-4-maverick-17b-128e-instruct",
        "llama-3.2-11b-vision-preview",
        settings.llm_model,
    ]
    # Filter duplikat dan None
    models_to_try = [m for i, m in enumerate(candidate_models) if m and m not in candidate_models[:i]]

    last_error = None
    raw_content = ""

    for model_name in models_to_try:
        try:
            response = await client.chat.completions.create(
                model=model_name,
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
            cleaned_json = raw_content.strip()
            if cleaned_json.startswith("```"):
                cleaned_json = re.sub(r"^```(?:json)?\s*", "", cleaned_json)
                cleaned_json = re.sub(r"\s*```$", "", cleaned_json)

            data = json.loads(cleaned_json)

            # Normalisasi data
            detected_doc = str(data.get("doc_type") or "").upper()
            if "KTP" in detected_doc:
                data["doc_type"] = "KTP"
                if not data.get("sim_type"):
                    data["sim_type"] = "KTP KARYAWAN"
                if not data.get("sim_number") and data.get("nik"):
                    data["sim_number"] = data.get("nik")
            else:
                data["doc_type"] = "SIM"
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
                else:
                    data["sim_type"] = "SIM B2 UMUM"

            return SimScanResponse(
                success=True,
                message=f"Dokumen {data['doc_type']} berhasil dipindai oleh AI Vision ({model_name}).",
                data=data,
            )

        except Exception as e:
            last_error = e
            print(f"[SIM Scanner] Model '{model_name}' gagal: {str(e)}, mencoba model berikutnya...")
            continue

    # Jika semua model vision gagal dicoba
    return SimScanResponse(
        success=False,
        message=f"AI Vision tidak dapat memproses berkas (Error: {str(last_error)}). Silakan periksa atau isi manual.",
        data={
            "doc_type": "SIM",
            "sim_type": "SIM B2 UMUM",
            "sim_number": None,
            "driver_name": None,
            "expiry_date": None,
            "raw_text": raw_content,
        },
    )
