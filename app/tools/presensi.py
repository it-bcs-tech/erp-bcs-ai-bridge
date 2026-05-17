"""
Presensi Tools
─────────────────────────────────────────
Query data kehadiran, absensi, dan cuti karyawan
dari schema presensi di database mybcs_db.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ── Tool 1: Rekap kehadiran hari ini ─────────────────────────
async def get_attendance_today(db: AsyncSession, location: Optional[str] = None) -> str:
    """Ambil rekap total kehadiran (hadir, cuti, izin, sakit) untuk hari ini."""
    query = """
        SELECT
            (SELECT COUNT(DISTINCT user_id) FROM presensi.presences WHERE date = CURRENT_DATE) as hadir,
            (SELECT COUNT(DISTINCT user_id) FROM presensi.leaves WHERE CURRENT_DATE BETWEEN start_date AND end_date AND status = 'approved' AND type ILIKE '%Sakit%') as sakit,
            (SELECT COUNT(DISTINCT user_id) FROM presensi.leaves WHERE CURRENT_DATE BETWEEN start_date AND end_date AND status = 'approved' AND type NOT ILIKE '%Sakit%') as cuti,
            (SELECT COUNT(DISTINCT user_id) FROM presensi.permission_requests WHERE CURRENT_DATE BETWEEN start_date AND end_date AND status = 'approved') as izin,
            TO_CHAR(CURRENT_DATE, 'DD Month YYYY') AS tanggal
    """
    try:
        result = await db.execute(text(query))
        row = result.fetchone()
        
        if not row:
            return f"INFO DATABASE: Data presensi kosong untuk hari ini ({_today()})."
            
        return (
            f"Rekap Presensi Tanggal: {row.tanggal}\n"
            f"- 🏢 Hadir: {row.hadir} orang\n"
            f"- 🤒 Sakit: {row.sakit} orang\n"
            f"- 🏖️ Cuti: {row.cuti} orang\n"
            f"- 📝 Izin Lainnya: {row.izin} orang"
        )
    except Exception as e:
        logger.error(f"get_attendance_today error: {e}")
        return f"INFO DATABASE: Terjadi kesalahan database: {str(e)}"


# ── Tool 2: Daftar karyawan yang tidak hadir hari ini ────────
async def get_absent_today(db: AsyncSession, reason: Optional[str] = None, location: Optional[str] = None) -> str:
    """Daftar nama karyawan yang absen, izin, sakit, atau cuti hari ini."""
    
    query = ""
    reason_lower = reason.lower() if reason else ""

    if reason_lower == "cuti":
        query = """
            SELECT COALESCE(mk.nama_karyawan, mp.name, 'Karyawan Tanpa Nama (ID: ' || l.user_id || ')') as name, l.type as ket
            FROM presensi.leaves l
            LEFT JOIN master.m_presensi mp ON l.user_id = mp.id
            LEFT JOIN master.m_karyawan mk ON mp.karyawan_id = mk.id
            WHERE CURRENT_DATE BETWEEN l.start_date AND l.end_date 
            AND l.status = 'approved' AND l.type NOT ILIKE '%Sakit%'
        """
    elif reason_lower == "sakit":
        query = """
            SELECT COALESCE(mk.nama_karyawan, mp.name, 'Karyawan Tanpa Nama (ID: ' || l.user_id || ')') as name, l.type as ket
            FROM presensi.leaves l
            LEFT JOIN master.m_presensi mp ON l.user_id = mp.id
            LEFT JOIN master.m_karyawan mk ON mp.karyawan_id = mk.id
            WHERE CURRENT_DATE BETWEEN l.start_date AND l.end_date 
            AND l.status = 'approved' AND l.type ILIKE '%Sakit%'
        """
    elif reason_lower == "izin":
        query = """
            SELECT COALESCE(mk.nama_karyawan, mp.name, 'Karyawan Tanpa Nama (ID: ' || p.user_id || ')') as name, p.type as ket
            FROM presensi.permission_requests p
            LEFT JOIN master.m_presensi mp ON p.user_id = mp.id
            LEFT JOIN master.m_karyawan mk ON mp.karyawan_id = mk.id
            WHERE CURRENT_DATE BETWEEN p.start_date AND p.end_date 
            AND p.status = 'approved'
        """
    else:
        # Gabungan semua alasan jika tidak dispesifikasi (cuti, sakit, dan izin)
        query = """
            SELECT COALESCE(mk.nama_karyawan, mp.name, 'Karyawan Tanpa Nama (ID: ' || l.user_id || ')') as name, l.type as ket
            FROM presensi.leaves l
            LEFT JOIN master.m_presensi mp ON l.user_id = mp.id
            LEFT JOIN master.m_karyawan mk ON mp.karyawan_id = mk.id
            WHERE CURRENT_DATE BETWEEN l.start_date AND l.end_date 
            AND l.status = 'approved'
            UNION ALL
            SELECT COALESCE(mk2.nama_karyawan, mp2.name, 'Karyawan Tanpa Nama (ID: ' || p.user_id || ')') as name, p.type as ket
            FROM presensi.permission_requests p
            LEFT JOIN master.m_presensi mp2 ON p.user_id = mp2.id
            LEFT JOIN master.m_karyawan mk2 ON mp2.karyawan_id = mk2.id
            WHERE CURRENT_DATE BETWEEN p.start_date AND p.end_date 
            AND p.status = 'approved'
        """

    try:
        result = await db.execute(text(query))
        rows = result.fetchall()
        
        reason_str = reason or "tidak hadir (izin/sakit/cuti)"
        if not rows:
            return f"INFO DATABASE: Tidak ada data karyawan yang {reason_str} hari ini ({_today()}). Jangan membuat data buatan."
            
        lines = [f"Daftar karyawan yang {reason_str} hari ini:"]
        for r in rows:
            lines.append(f"- {r.name} ({r.ket})")
            
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"get_absent_today error: {e}")
        return f"INFO DATABASE: Terjadi kesalahan database: {str(e)}"


# ── Tool 3: Rekap kehadiran bulan ini ────────────────────────
async def get_attendance_monthly(db: AsyncSession, month: Optional[int] = None, year: Optional[int] = None, employee_id: Optional[str] = None) -> str:
    """Ambil rekap total kehadiran bulan ini beserta detail jumlah kehadiran tiap karyawan."""
    m = month or datetime.now().month
    y = year or datetime.now().year
    
    query_aggregate = f"""
        SELECT 
            (SELECT COUNT(*) FROM presensi.presences WHERE EXTRACT(MONTH FROM date) = {m} AND EXTRACT(YEAR FROM date) = {y}) as hadir,
            (SELECT COUNT(*) FROM presensi.leaves WHERE EXTRACT(MONTH FROM start_date) = {m} AND EXTRACT(YEAR FROM start_date) = {y} AND type ILIKE '%Sakit%' AND status='approved') as sakit,
            (SELECT COUNT(*) FROM presensi.leaves WHERE EXTRACT(MONTH FROM start_date) = {m} AND EXTRACT(YEAR FROM start_date) = {y} AND type NOT ILIKE '%Sakit%' AND status='approved') as cuti,
            (SELECT COUNT(*) FROM presensi.permission_requests WHERE EXTRACT(MONTH FROM start_date) = {m} AND EXTRACT(YEAR FROM start_date) = {y} AND status='approved') as izin
    """
    
    query_details = f"""
        SELECT COALESCE(mk.nama_karyawan, mp.name, 'Karyawan (ID: ' || p.user_id || ')') as name, COUNT(p.id) as total_hadir
        FROM presensi.presences p
        LEFT JOIN master.m_presensi mp ON p.user_id = mp.id
        LEFT JOIN master.m_karyawan mk ON mp.karyawan_id = mk.id
        WHERE EXTRACT(MONTH FROM p.date) = {m} AND EXTRACT(YEAR FROM p.date) = {y}
        GROUP BY 1
        ORDER BY total_hadir DESC
    """
    
    try:
        # Eksekusi Aggregate
        res_agg = await db.execute(text(query_aggregate))
        row = res_agg.fetchone()
        
        if not row or (row.hadir == 0 and row.sakit == 0 and row.cuti == 0 and row.izin == 0):
            return f"INFO DATABASE: Belum ada satupun data presensi/absensi untuk bulan {m}-{y}."
            
        result_text = (
            f"Rekap Keseluruhan Bulan {m} Tahun {y}:\n"
            f"- 🏢 Total Rekap Kehadiran: {row.hadir} kali\n"
            f"- 🤒 Total Rekap Sakit: {row.sakit} hari\n"
            f"- 🏖️ Total Rekap Cuti: {row.cuti} hari\n"
            f"- 📝 Total Rekap Izin Tambahan: {row.izin} data\n\n"
            f"Daftar Karyawan yang Hadir (Peringkat Kehadiran):\n"
        )
        
        # Eksekusi Details
        res_details = await db.execute(text(query_details))
        rows_details = res_details.fetchall()
        
        if rows_details:
            for r in rows_details:
                result_text += f"- {r.name}: {r.total_hadir} kali hadir\n"
        else:
            result_text += "- (Belum ada rincian nama karyawan yang hadir)\n"
            
        return result_text
    except Exception as e:
        logger.error(f"get_attendance_monthly error: {e}")
        return f"INFO DATABASE: Terjadi kesalahan database: {str(e)}"


# ── Tool 4: Daftar karyawan cuti/izin hari ini ───────────────
async def get_leave_today(db: AsyncSession) -> str:
    """Shortcut: daftar yang cuti hari ini."""
    return await get_absent_today(db, reason="cuti")


# ── Tool 5: Daftar karyawan yang hadir hari ini ───────────────
async def get_present_today(db: AsyncSession, location: Optional[str] = None) -> str:
    """Daftar nama karyawan yang hadir (clock-in) hari ini."""
    query = """
        SELECT COALESCE(mk.nama_karyawan, mp.name, 'Karyawan Tanpa Nama (ID: ' || p.user_id || ')') as name, p.clock_in, p.status
        FROM presensi.presences p
        LEFT JOIN master.m_presensi mp ON p.user_id = mp.id
        LEFT JOIN master.m_karyawan mk ON mp.karyawan_id = mk.id
        WHERE p.date = CURRENT_DATE
    """
    try:
        result = await db.execute(text(query))
        rows = result.fetchall()
        
        if not rows:
            return f"INFO DATABASE: Belum ada karyawan yang melakukan presensi hadir hari ini ({_today()})."
            
        lines = [f"Daftar {len(rows)} karyawan yang hadir hari ini:"]
        for r in rows:
            lines.append(f"- {r.name} (Jam Masuk: {r.clock_in}, Status: {r.status})")
            
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"get_present_today error: {e}")
        return f"INFO DATABASE: Terjadi kesalahan database saat mengambil data kehadiran: {str(e)}"
