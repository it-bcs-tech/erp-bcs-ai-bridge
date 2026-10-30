"""
GA Tools — General Affairs System Tools
───────────────────────────────────────
Tools untuk query data operasional umum (General Affairs) PT BCS Logistics:
- Peminjaman Kendaraan Dinas / Carpool (ga.carpool_requests & ga.cars)
- Surat Perjalanan Dinas / SPD (ga.spd_requests)
- Permintaan Alat Tulis Kantor / ATK (ga.stationery_requests & stationery_items)
- Peminjaman Ruang Rapat & Fasilitas (ga.facility_bookings)
- Legalitas & Perizinan Armada (ga.fleet_legal_permits)
- Inventaris Aset Kantor (ga.assets)

Digunakan oleh ga_agent.py (GAMA).
"""

from datetime import datetime, date
from sqlalchemy import text
from app.database import async_session


async def get_ga_overview() -> str:
    """
    Mengambil ringkasan data General Affairs terkini:
    - Statistik carpool kendaraan dinas
    - Rekap Surat Perjalanan Dinas (SPD)
    - Rekap pemesanan ATK (stationery)
    - Pemesanan ruang rapat/fasilitas
    - Status legalitas & perizinan armada (dokumen yang mendekati kadaluarsa).
    """
    try:
        async with async_session() as db:
            # 1. Rekap Carpool
            q_cp = """
                SELECT 
                    COUNT(*) as total_carpools,
                    COUNT(*) FILTER (WHERE use_date >= CURRENT_DATE) as upcoming_carpools
                FROM ga.carpool_requests
            """
            res_cp = await db.execute(text(q_cp))
            cp_stats = res_cp.mappings().first()

            # 2. Rekap SPD
            q_spd = """
                SELECT 
                    COUNT(*) as total_spd,
                    COUNT(*) FILTER (WHERE UPPER(status) IN ('APPROVED', 'PROCESSED')) as approved_spd,
                    COUNT(*) FILTER (WHERE UPPER(status) = 'PENDING') as pending_spd
                FROM ga.spd_requests
            """
            res_spd = await db.execute(text(q_spd))
            spd_stats = res_spd.mappings().first()

            # 3. Rekap ATK
            q_atk = """
                SELECT 
                    COUNT(*) as total_atk_req,
                    COUNT(*) FILTER (WHERE UPPER(status) = 'APPROVED') as approved_atk,
                    COUNT(*) FILTER (WHERE UPPER(status) = 'PENDING') as pending_atk
                FROM ga.stationery_requests
            """
            res_atk = await db.execute(text(q_atk))
            atk_stats = res_atk.mappings().first()

            # 4. Rekap Ruang Rapat
            q_room = """
                SELECT 
                    COUNT(*) as total_bookings,
                    COUNT(*) FILTER (WHERE start_time >= CURRENT_DATE) as upcoming_bookings
                FROM ga.facility_bookings
            """
            res_room = await db.execute(text(q_room))
            room_stats = res_room.mappings().first()

            # 5. Rekap Legalitas Armada
            q_permits = """
                SELECT 
                    COUNT(*) as total_permits,
                    COUNT(*) FILTER (WHERE expiry_date <= CURRENT_DATE + INTERVAL '30 days' AND expiry_date >= CURRENT_DATE) as expiring_soon,
                    COUNT(*) FILTER (WHERE expiry_date < CURRENT_DATE) as expired
                FROM ga.fleet_legal_permits
            """
            res_permits = await db.execute(text(q_permits))
            permit_stats = res_permits.mappings().first()

            lines = [
                "🏢 RINGKASAN GENERAL AFFAIRS & FASILITAS (GA OVERVIEW):",
                f"• Kendaraan Dinas (Carpool) : {cp_stats['total_carpools']} trip tercatat ({cp_stats['upcoming_carpools']} trip aktif/akan datang)",
                f"• Surat Perjalanan Dinas(SPD): {spd_stats['total_spd']} dokumen (Approved: {spd_stats['approved_spd']}, Pending: {spd_stats['pending_spd']})",
                f"• Permintaan ATK (Stationery): {atk_stats['total_atk_req']} pengajuan (Approved: {atk_stats['approved_atk']}, Pending: {atk_stats['pending_atk']})",
                f"• Peminjaman Ruang Rapat    : {room_stats['total_bookings']} pemesanan tercatat",
                f"• Legalitas & Izin Armada   : {permit_stats['total_permits']} dokumen perizinan",
                f"  ├─ Kadaluarsa dalam 30 hari: {permit_stats['expiring_soon']} dokumen (Perlu Perpanjangan Segera!)",
                f"  └─ Sudah Kadaluarsa        : {permit_stats['expired']} dokumen",
            ]
            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil ringkasan GA: {str(e)}"


async def get_carpool_schedule(date_str: str | None = None, requester: str | None = None, limit: int | None = 10) -> str:
    """
    Mengambil jadwal peminjaman kendaraan dinas (carpool).
    Args:
        date_str: Tanggal penggunaan format 'YYYY-MM-DD'.
        requester: Nama peminjam atau NIK.
        limit: Batas data (default: 10, max: 25).
    """
    safe_limit = max(1, min(int(limit or 10), 25))
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": safe_limit}

            if date_str and date_str.strip():
                conditions.append("use_date = :use_date")
                params["use_date"] = date_str.strip()

            if requester and requester.strip():
                conditions.append("(requester_name ILIKE :req OR requester_nik ILIKE :req)")
                params["req"] = f"%{requester.strip()}%"

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            q = f"""
                SELECT 
                    cp.carpool_number, cp.use_date, cp.end_date, cp.requester_name, 
                    cp.destination, cp.reason, cp.city_type, c.car_name, c.police_number
                FROM ga.carpool_requests cp
                LEFT JOIN ga.cars c ON cp.car_id = c.id
                {where_clause}
                ORDER BY cp.use_date DESC, cp.id DESC
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return "ℹ️ Tidak ditemukan data jadwal peminjaman kendaraan dinas."

            lines = [f"🚗 JADWAL KENDARAAN DINAS (CARPOOL) ({len(rows)} ditemukan):"]
            for r in rows:
                d_str = r["use_date"].strftime("%d %b %Y") if isinstance(r["use_date"], (date, datetime)) else str(r["use_date"] or "-")
                mobil = f"{r['car_name'] or 'Mobil Dinas'} ({r['police_number'] or '-'})"
                lines.append(
                    f"• [{d_str}] {r['carpool_number']} — {r['requester_name']}\n"
                    f"  Tujuan: {r['destination']} ({r['city_type'] or 'Lokal'}) | Armada: {mobil}\n"
                    f"  Keperluan: {r['reason'] or '-'}"
                )
            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil jadwal carpool: {str(e)}"


async def get_spd_requests(status: str | None = None, department: str | None = None, limit: int | None = 10) -> str:
    """
    Mengambil data Surat Perjalanan Dinas (SPD) karyawan.
    Args:
        status: Status pengajuan ('APPROVED', 'PENDING', 'REJECTED').
        department: Nama departemen pemohon.
        limit: Batas data (default: 10, max: 25).
    """
    safe_limit = max(1, min(int(limit or 10), 25))
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": safe_limit}

            if status and status.strip():
                conditions.append("UPPER(status) = :status")
                params["status"] = status.strip().upper()

            if department and department.strip():
                conditions.append("department ILIKE :dept")
                params["dept"] = f"%{department.strip()}%"

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            q = f"""
                SELECT 
                    spd_number, start_date, end_date, requester_name, 
                    destination, reason, department, status, is_overnight
                FROM ga.spd_requests
                {where_clause}
                ORDER BY start_date DESC NULLS LAST, id DESC
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return "ℹ️ Tidak ditemukan data Surat Perjalanan Dinas (SPD)."

            lines = [f"✈️ DAFTAR SURAT PERJALANAN DINAS (SPD) ({len(rows)} ditemukan):"]
            for r in rows:
                s_str = r["start_date"].strftime("%d %b %Y") if isinstance(r["start_date"], (date, datetime)) else str(r["start_date"] or "-")
                e_str = r["end_date"].strftime("%d %b %Y") if isinstance(r["end_date"], (date, datetime)) else str(r["end_date"] or "-")
                menginap = "Menginap" if r["is_overnight"] else "PP (Pulang-Pergi)"
                lines.append(
                    f"• [{r['status']}] {r['spd_number']} — {r['requester_name']} ({r['department'] or 'Umum'})\n"
                    f"  Tujuan: {r['destination']} ({s_str} s/d {e_str}) | {menginap}\n"
                    f"  Alasan: {r['reason'] or '-'}"
                )
            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil data SPD: {str(e)}"


async def get_fleet_permits_expiry(only_urgent: bool = True, limit: int | None = 10) -> str:
    """
    Mengambil data masa berlaku izin dan legalitas armada (KIR, STNK, Izin Trayek, Pajak).
    Args:
        only_urgent: Jika True, hanya menampilkan yang mendekati expired (<= 60 hari) atau sudah expired.
        limit: Batas data (default: 10, max: 25).
    """
    safe_limit = max(1, min(int(limit or 10), 25))
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": safe_limit}

            if only_urgent:
                conditions.append("expiry_date <= CURRENT_DATE + INTERVAL '60 days'")

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            q = f"""
                SELECT 
                    unit_number, police_number, permit_type, document_number, 
                    institution, issue_date, expiry_date, status, renewal_cost
                FROM ga.fleet_legal_permits
                {where_clause}
                ORDER BY expiry_date ASC
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return "ℹ️ Semua dokumen legalitas armada dalam kondisi aman (tidak ada yang mendekati kadaluarsa)."

            lines = [f"📋 MONITORING LEGALITAS & PERIZINAN ARMADA ({len(rows)} dokumen):"]
            for r in rows:
                exp_str = r["expiry_date"].strftime("%d %b %Y") if isinstance(r["expiry_date"], (date, datetime)) else str(r["expiry_date"] or "-")
                cost = f"Rp {float(r['renewal_cost']):,.2f}" if r["renewal_cost"] else "-"
                lines.append(
                    f"• [{r['permit_type']}] Unit {r['unit_number'] or '-'} ({r['police_number'] or '-'})\n"
                    f"  No Dokumen: {r['document_number'] or '-'} | Kadaluarsa: {exp_str}\n"
                    f"  Instansi: {r['institution'] or '-'} | Biaya Perpanjangan: {cost}"
                )
            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil data perizinan armada: {str(e)}"
