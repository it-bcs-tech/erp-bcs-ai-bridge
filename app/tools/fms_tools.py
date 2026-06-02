"""
FMS Tools — Data Armada dari Go-Map Backend
─────────────────────────────────────────────
Tools ini mengambil data GPS real-time dari backend Golang (go-map)
yang sudah di-cache setiap 30 detik dari EasyGo GPS API.

Digunakan oleh fms_agent.py (FARIDA).

Struktur data EasyGo yang relevan:
  - nopol         : Nomor polisi
  - driver_nm     : Nama driver
  - company_nm    : Nama perusahaan
  - car_type      : Tipe kendaraan
  - speed         : Kecepatan saat ini (km/h)
  - lat, lon      : Koordinat GPS terakhir
  - addr          : Alamat lengkap posisi terakhir
  - currentStatusVehicle.ket : Status → 'Driving' | 'Parking' | 'Idle' | None
  - currentGeoAreaStatus.geo_nm : Nama area (pool/lokasi GPS)
"""

import httpx
import os
from datetime import datetime

# ── Konfigurasi Go-Map Backend ────────────────────────────────────
# Di Docker: erp_go_map (nama service) | Di lokal: localhost:8081
# Set GO_MAP_URL di .env untuk override
GO_MAP_URL = os.environ.get("GO_MAP_URL", "http://erp_go_map:8081/api/fms/live-map")
HTTP_TIMEOUT = 10.0  # seconds


# ── Helper: Fetch semua data GPS dari go-map ──────────────────────

async def _fetch_fleet_data() -> tuple[list[dict], str | None]:
    """
    Mengambil seluruh data armada dari Golang go-map backend.
    Returns: (list_of_records, error_message_or_None)
    """
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(GO_MAP_URL)
            resp.raise_for_status()
            data = resp.json()
            records = data.get("records", [])
            if not records:
                return [], "Data GPS kosong — go-map mengembalikan 0 unit."
            return records, None
    except httpx.ConnectError:
        return [], f"Tidak dapat terhubung ke go-map backend ({GO_MAP_URL}). Pastikan server Go berjalan."
    except httpx.TimeoutException:
        return [], f"Timeout saat menghubungi go-map backend. Coba lagi."
    except Exception as e:
        return [], f"Error: {str(e)}"


def _parse_vehicle(v: dict) -> dict:
    """
    Mengkonversi raw EasyGo vehicle dict ke format yang mudah dibaca AI.
    """
    # Status dari field currentStatusVehicle.ket
    csv = v.get("currentStatusVehicle") or {}
    ket = csv.get("ket") or "Unknown"

    if ket == "Driving":
        status = "Moving"
    elif ket == "Idle":
        status = "Idle (Berhenti Mesin Hidup)"
    elif ket == "Parking":
        status = "Parkir"
    else:
        status = "Tidak Diketahui"

    speed = round(v.get("speed", 0) or 0)
    lat = v.get("lat") or 0
    lon = v.get("lon") or 0

    # Lokasi: preferensikan geo_nm, fallback ke addr
    geo = v.get("currentGeoAreaStatus") or {}
    geo_nm = geo.get("geo_nm") or ""
    addr = v.get("addr") or ""
    lokasi = geo_nm if geo_nm else (addr[:60] + "..." if len(addr) > 60 else addr) if addr else "Tidak diketahui"

    return {
        "nopol": (v.get("nopol") or "UNKNOWN").strip(),
        "driver": (v.get("driver_nm") or "-").strip() or "-",
        "perusahaan": (v.get("company_nm") or "-").strip(),
        "tipe": (v.get("car_type") or "-").strip(),
        "status": status,
        "status_raw": ket,
        "kecepatan_kmh": speed,
        "lat": round(float(lat), 5),
        "lng": round(float(lon), 5),
        "lokasi": lokasi,
        "addr": addr[:80] if addr else "-",
    }


# ── Tool Functions ────────────────────────────────────────────────

async def get_all_fleet_status() -> str:
    """
    Mengambil status seluruh armada: nopol, driver, status, kecepatan, lokasi.
    """
    records, err = await _fetch_fleet_data()
    if err:
        return f"❌ Gagal mengambil data GPS: {err}"

    parsed = [_parse_vehicle(v) for v in records]
    # Deduplikasi berdasarkan nopol
    seen = set()
    unique = []
    for u in parsed:
        if u["nopol"] not in seen:
            seen.add(u["nopol"])
            unique.append(u)
    parsed = unique
    moving = [u for u in parsed if u["status_raw"] == "Driving"]
    idle = [u for u in parsed if u["status_raw"] == "Idle"]
    parkir = [u for u in parsed if u["status_raw"] == "Parking"]
    unknown = [u for u in parsed if u["status_raw"] not in ("Driving", "Idle", "Parking")]

    lines = [
        f"📊 RINGKASAN ARMADA — {datetime.now().strftime('%d %B %Y %H:%M')}",
        f"Total Unit  : {len(parsed)} unit",
        f"Moving      : {len(moving)} unit",
        f"Idle        : {len(idle)} unit",
        f"Parkir      : {len(parkir)} unit",
        f"Unknown     : {len(unknown)} unit",
        "",
        "DETAIL UNIT (Moving):",
    ]
    for u in moving[:20]:  # Batasi 20 untuk efisiensi token
        spd = f"{u['kecepatan_kmh']} km/h"
        lines.append(f"  • {u['nopol']} | {u['driver']} | {spd} | {u['lokasi']}")

    if len(moving) > 20:
        lines.append(f"  ... dan {len(moving) - 20} unit Moving lainnya.")

    lines.append("\nDETAIL UNIT (Parkir - sample 10):")
    for u in parkir[:10]:
        lines.append(f"  • {u['nopol']} | {u['driver']} | {u['lokasi']}")

    return "\n".join(lines)


async def get_unit_detail(nopol: str) -> str:
    """
    Mengambil detail lengkap satu unit berdasarkan nomor polisi (nopol).
    """
    records, err = await _fetch_fleet_data()
    if err:
        return f"❌ Gagal mengambil data GPS: {err}"

    nopol_clean = nopol.replace(" ", "").upper()
    match = None
    for v in records:
        v_nopol = (v.get("nopol") or "").replace(" ", "").upper()
        if nopol_clean in v_nopol or v_nopol in nopol_clean:
            match = v
            break

    if not match:
        return f"❌ Unit dengan nopol '{nopol}' tidak ditemukan. Coba cek ulang nomor polisinya."

    u = _parse_vehicle(match)
    spd = f"{u['kecepatan_kmh']} km/h" if u["kecepatan_kmh"] > 0 else "Sedang diam"

    # Info DO jika ada
    do_info = ""
    current_do = match.get("currentDO") or {}
    if current_do and isinstance(current_do, dict):
        do_nm = current_do.get("do_nm") or current_do.get("do_id") or ""
        if do_nm:
            do_info = f"\nDO Aktif      : {do_nm}"

    return (
        f"🚛 DETAIL UNIT: {u['nopol']}\n"
        f"Driver        : {u['driver']}\n"
        f"Perusahaan    : {u['perusahaan']}\n"
        f"Tipe Kendaraan: {u['tipe']}\n"
        f"Status        : {u['status']}\n"
        f"Kecepatan     : {spd}\n"
        f"Lokasi GPS    : {u['lokasi']}\n"
        f"Alamat        : {u['addr']}\n"
        f"Koordinat     : {u['lat']}, {u['lng']}"
        f"{do_info}"
    )


async def get_slow_or_stuck_units() -> str:
    """
    Mendeteksi unit yang berpotensi terjebak kemacetan:
    - Moving + kecepatan < 5 km/h = MACET
    - Moving + kecepatan 5-20 km/h = LALU LINTAS PADAT
    """
    records, err = await _fetch_fleet_data()
    if err:
        return f"❌ Gagal mengambil data GPS: {err}"

    parsed = [_parse_vehicle(v) for v in records]
    # Deduplikasi berdasarkan nopol
    seen = set()
    unique = []
    for u in parsed:
        if u["nopol"] not in seen:
            seen.add(u["nopol"])
            unique.append(u)
    moving = [u for u in unique if u["status_raw"] == "Driving"]
    stuck = [u for u in moving if u["kecepatan_kmh"] < 5]
    slow = [u for u in moving if 5 <= u["kecepatan_kmh"] < 20]

    if not stuck and not slow:
        return (
            f"✅ Tidak ada unit yang terdeteksi kemacetan atau lalu lintas padat.\n"
            f"Total unit Moving: {len(moving)} unit — semua bergerak normal."
        )

    lines = ["⚠️ DETEKSI KEMACETAN / LALU LINTAS PADAT:\n"]

    if stuck:
        lines.append(f"🔴 MACET / SANGAT LAMBAT ({len(stuck)} unit, speed < 5 km/h):")
        for u in stuck:
            lines.append(f"  • {u['nopol']} | {u['driver']} | {u['kecepatan_kmh']} km/h | {u['lokasi']} [{u['lat']}, {u['lng']}]")

    if slow:
        lines.append(f"\n🟡 LALU LINTAS PADAT ({len(slow)} unit, speed 5-20 km/h):")
        for u in slow:
            lines.append(f"  • {u['nopol']} | {u['driver']} | {u['kecepatan_kmh']} km/h | {u['lokasi']}")

    return "\n".join(lines)


async def get_units_by_status(status: str) -> str:
    """
    Menampilkan daftar unit berdasarkan status operasional.
    status: 'moving'|'idle'|'parkir'
    """
    records, err = await _fetch_fleet_data()
    if err:
        return f"❌ Gagal mengambil data GPS: {err}"

    parsed = [_parse_vehicle(v) for v in records]
    # Deduplikasi berdasarkan nopol
    seen = set()
    unique_parsed = []
    for u in parsed:
        if u["nopol"] not in seen:
            seen.add(u["nopol"])
            unique_parsed.append(u)
    parsed = unique_parsed
    status_lower = status.lower()

    if status_lower in ("moving", "bergerak", "jalan", "driving"):
        filtered = [u for u in parsed if u["status_raw"] == "Driving"]
        label = "Moving (Sedang Bergerak)"
    elif status_lower in ("idle", "loading", "bongkar", "muat"):
        filtered = [u for u in parsed if u["status_raw"] == "Idle"]
        label = "Idle (Mesin Hidup, Berhenti)"
    elif status_lower in ("parkir", "parking", "available", "standby", "pool"):
        filtered = [u for u in parsed if u["status_raw"] == "Parking"]
        label = "Parkir / Standby"
    else:
        filtered = parsed
        label = "Semua Status"

    if not filtered:
        return f"ℹ️ Tidak ada unit dengan status '{label}' saat ini."

    lines = [f"🚛 Unit dengan status **{label}** ({len(filtered)} unit):"]
    for u in filtered[:30]:  # Batasi 30
        spd = f" | {u['kecepatan_kmh']} km/h" if u["kecepatan_kmh"] > 0 else ""
        lines.append(f"  • {u['nopol']} | {u['driver']}{spd} | {u['lokasi']}")
    if len(filtered) > 30:
        lines.append(f"  ... dan {len(filtered) - 30} unit lainnya.")

    return "\n".join(lines)


async def get_fleet_summary_for_monitoring() -> str:
    """
    Laporan ringkas monitoring: total armada, distribusi status, alert kemacetan.
    """
    records, err = await _fetch_fleet_data()
    if err:
        return f"❌ Gagal mengambil data GPS: {err}"

    parsed = [_parse_vehicle(v) for v in records]
    total = len(parsed)
    moving = [u for u in parsed if u["status_raw"] == "Driving"]
    idle = [u for u in parsed if u["status_raw"] == "Idle"]
    parkir = [u for u in parsed if u["status_raw"] == "Parking"]
    stuck = [u for u in moving if u["kecepatan_kmh"] < 5]
    slow = [u for u in moving if 5 <= u["kecepatan_kmh"] < 20]
    avg_speed = (
        round(sum(u["kecepatan_kmh"] for u in moving) / len(moving), 1) if moving else 0
    )

    now = datetime.now().strftime("%d %B %Y, %H:%M WIB")
    lines = [
        f"📡 LAPORAN MONITORING ARMADA — {now}",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Total Armada       : {total} unit",
        f"Sedang Bergerak    : {len(moving)} unit",
        f"Idle (Mesin Hidup) : {len(idle)} unit",
        f"Parkir / Standby   : {len(parkir)} unit",
        f"Kecepatan Rata-rata: {avg_speed} km/h (dari unit Moving)",
    ]

    if stuck:
        lines.append(f"\n🔴 ALERT MACET ({len(stuck)} unit):")
        for u in stuck[:5]:
            lines.append(f"   {u['nopol']} — {u['lokasi']}")
    if slow:
        lines.append(f"\n🟡 LALU LINTAS PADAT ({len(slow)} unit):")
        for u in slow[:5]:
            lines.append(f"   {u['nopol']} — {u['kecepatan_kmh']} km/h — {u['lokasi']}")
    if not stuck and not slow:
        lines.append("\n✅ Tidak ada unit yang terdeteksi terjebak kemacetan.")

    return "\n".join(lines)
