"""
Tool Router — Keyword-Based Intent Detection
─────────────────────────────────────────────
Menentukan alat mana yang relevan berdasarkan kata kunci di pesan pengguna.
TANPA memanggil LLM — instan, deterministik, dan hemat token 100%.

Strategi:
1. Jika pesan = sapaan/basa-basi → 0 alat (hemat token maksimal)
2. Jika kata kunci cocok → hanya alat yang relevan
3. Jika tidak ada yang cocok TAPI bukan sapaan → SEMUA alat (aman, biar LLM yang putuskan)
"""

import re

# ── Pola Sapaan / Basa-basi (tidak butuh alat apa pun) ──────────
GREETING_PATTERNS = re.compile(
    r"^(halo|hai|hi|hello|hey|selamat\s*(pagi|siang|sore|malam)|"
    r"apa\s*kabar|terima\s*kasih|makasih|thanks|ok|oke|baik|"
    r"siapa\s*(kamu|anda|namamu)|perkenalkan|kenalkan)[\s\?\!\.\,]*$",
    re.IGNORECASE,
)

# ── Peta Kata Kunci per Nama Tool ────────────────────────────────
# Kunci = nama fungsi tool, Nilai = daftar kata kunci (lowercase)
TOOL_KEYWORDS = {
    # ─── HRIS Tools ───
    "search_employee_by_name": [
        "cari", "nama", "karyawan", "pegawai", "siapa", "data karyawan",
        "profil", "nik", "nip", "payroll",
    ],
    "get_employee_count": [
        "jumlah", "berapa", "total", "hitung", "banyak", "karyawan", "pegawai",
        "headcount",
    ],
    "get_employees_by_department": [
        "departemen", "department", "bagian", "unit kerja",
    ],
    "get_employees_by_division": [
        "divisi", "division",
    ],
    "get_employees_by_status": [
        "status karyawan", "aktif", "resign", "pensiun", "kontrak",
    ],
    "get_employees_by_location": [
        "lokasi", "cabang", "kantor", "penempatan", "location",
    ],
    "get_employee_list": [
        "daftar karyawan", "list karyawan", "semua karyawan", "seluruh karyawan",
    ],
    "get_attendance_today": [
        "absen", "presensi", "kehadiran", "hadir", "hari ini", "masuk",
        "attendance",
    ],
    "get_absent_today": [
        "tidak hadir", "absen", "izin", "sakit", "bolos", "mangkir", "alfa",
    ],
    "get_attendance_monthly": [
        "presensi bulan", "kehadiran bulan", "rekap presensi", "rekap kehadiran",
        "bulan", "bulanan", "monthly",
    ],
    "get_leave_today": [
        "cuti", "leave", "libur",
    ],
    "get_present_today": [
        "hadir", "masuk", "present",
    ],
    "get_absent_monthly": [
        "rekap", "kumulatif", "bulanan", "tidak hadir bulan", "cuti bulan",
        "sakit bulan", "izin bulan",
    ],

    # ─── FMS Tools ───
    "get_all_fleet_status": [
        "armada", "fleet", "unit", "semua unit", "seluruh unit", "kendaraan",
        "truk", "mobil", "nopol",
    ],
    "get_unit_detail": [
        "nopol", "nomor polisi", "plat", "detail unit", "b ", "d ",
    ],
    "get_slow_or_stuck_units": [
        "macet", "lambat", "stuck", "terjebak", "hambatan", "mandek",
    ],
    "get_units_by_status": [
        "moving", "parkir", "idle", "berhenti", "jalan", "bergerak", "standby",
        "loading", "bongkar",
    ],
    "get_fleet_summary_for_monitoring": [
        "laporan", "ringkasan", "summary", "monitoring", "kondisi armada",
        "status armada", "rangkuman",
    ],
    "get_driver_trip_stats": [
        "trip", "perjalanan", "driver", "pengemudi", "sopir", "supir",
        "kinerja driver", "peringkat", "leaderboard", "bandingkan",
    ],
    "get_unit_trip_stats": [
        "trip unit", "perjalanan unit", "kinerja unit", "trip truk",
        "trip armada", "peringkat unit", "leaderboard unit", "jumlah unit yang melakukan trip",
        "trip bulan", "trip hari ini", "trip minggu", "trip tahun",
    ],

    # ─── Shared Tools ───
    "generate_chart_image": [
        "grafik", "chart", "diagram", "visualisasi", "bagan", "pie", "bar",
        "line", "plot", "gambar grafik",
    ],
}


async def get_relevant_tools(user_message: str, available_tools: list) -> list:
    """
    Menentukan alat yang relevan berdasarkan kata kunci di pesan pengguna.
    Tidak memanggil LLM — instan dan deterministik.

    Returns:
        list: Daftar schema tool yang relevan (bisa kosong jika sapaan)
    """
    if not available_tools:
        return []

    msg_lower = user_message.strip().lower()

    # ── Langkah 1: Deteksi sapaan/basa-basi ──
    if GREETING_PATTERNS.match(msg_lower):
        return []

    # ── Langkah 2: Cocokkan kata kunci dengan tool yang tersedia ──
    available_names = {t["function"]["name"] for t in available_tools}
    matched_names = set()

    for tool_name, keywords in TOOL_KEYWORDS.items():
        if tool_name not in available_names:
            continue
        for kw in keywords:
            if kw in msg_lower:
                matched_names.add(tool_name)
                break

    # ── Langkah 3: Jika ada kata kunci grafik, pastikan tool chart juga masuk ──
    chart_keywords = ["grafik", "chart", "diagram", "visualisasi", "bagan", "pie", "bar", "line"]
    if any(kw in msg_lower for kw in chart_keywords):
        if "generate_chart_image" in available_names:
            matched_names.add("generate_chart_image")

    # ── Langkah 4: Jika ada tool cocok → kembalikan hanya yang cocok ──
    if matched_names:
        selected = [t for t in available_tools if t["function"]["name"] in matched_names]
        return selected

    # ── Langkah 5: Jika tidak ada yang cocok DAN bukan sapaan → SEMUA alat (fallback aman) ──
    # Lebih baik mengirim semua alat daripada melewatkan tool call yang dibutuhkan
    return available_tools
