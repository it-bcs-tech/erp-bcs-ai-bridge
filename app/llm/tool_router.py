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
    "get_employee_attendance_logs": [
        "telat", "terlambat", "late", "keterlambatan", "jam masuk", "jam datang",
        "clock in", "clock-in", "log presensi", "riwayat presensi", "riwayat kehadiran",
        "absen sebulan", "kehadiran sebulan", "log kehadiran", "disiplin", "kedisiplinan",
        "history", "riwayat", "history absensi", "riwayat absensi", "history presensi",
        "history kehadiran", "log absensi", "log absen", "riwayat absen",
    ],
    "get_employee_full_profile": [
        "profil lengkap", "detail karyawan", "masa kerja", "lama kerja", "join date",
        "tanggal masuk", "sisa cuti", "saldo cuti", "kuota cuti", "atasan", "biodata",
        "kontrak berakhir", "habis kontrak", "detail profil", "data lengkap",
    ],
    "get_people_analytics": [
        "ulang tahun", "ultah", "birthday", "anniversary", "masa bakti", "kontrak habis",
        "habis kontrak", "perpanjangan kontrak", "expiring", "analytics", "monitoring kontrak",
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
    Menentukan alat yang relevan berdasarkan pesan pengguna.
    - Sapaan / basa-basi murni -> 0 alat (hemat token maksimal, respons instan).
    - Pertanyaan substantif / operasional -> kembalikan seluruh tools yang tersedia
      agar LLM memiliki kapabilitas pemanggilan tool secara lengkap (Zero Error 400).

    Returns:
        list: Daftar schema tool yang relevan (bisa kosong jika sapaan)
    """
    if not available_tools:
        return []

    msg_lower = user_message.strip().lower()

    # ── Langkah 1: Deteksi sapaan / basa-basi murni ──
    if GREETING_PATTERNS.match(msg_lower):
        return []

    # ── Langkah 2: Sediakan seluruh tools untuk pertanyaan operasional ──
    # Menghindari kegagalan validasi tool call (Error 400) pada pertanyaan multi-kategori
    return available_tools


