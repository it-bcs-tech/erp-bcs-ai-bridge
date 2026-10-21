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
    
    # Jika parameter employee_id diberikan, alihkan langsung ke log detail karyawan tersebut
    if employee_id:
        return await get_employee_attendance_logs(db, name_or_id=employee_id, month=m, year=y)
    
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

# ── Tool 6: Rekap cuti/sakit/izin bulanan ────────────────────────
async def get_absent_monthly(db: AsyncSession, month: Optional[int] = None, year: Optional[int] = None, reason: Optional[str] = None) -> str:
    """Ambil daftar karyawan beserta rincian jumlah hari mereka mengambil cuti, absen, sakit, atau izin secara kumulatif pada bulan tertentu."""
    m = month or datetime.now().month
    y = year or datetime.now().year
    reason_lower = reason.lower() if reason else ""

    if reason_lower == "cuti":
        filter_sql = "AND type NOT ILIKE '%Sakit%'"
        target_tables = ["leaves"]
    elif reason_lower == "sakit":
        filter_sql = "AND type ILIKE '%Sakit%'"
        target_tables = ["leaves"]
    elif reason_lower == "izin":
        filter_sql = ""
        target_tables = ["permission_requests"]
    else:
        filter_sql = ""
        target_tables = ["leaves", "permission_requests"]
        
    union_queries = []
    
    if "leaves" in target_tables:
        q = f"""
            SELECT COALESCE(mk.nama_karyawan, mp.name, 'Karyawan (ID: ' || l.user_id || ')') as name, 
                   COUNT(l.id) as total_days, 
                   'Cuti/Sakit' as category
            FROM presensi.leaves l
            LEFT JOIN master.m_presensi mp ON l.user_id = mp.id
            LEFT JOIN master.m_karyawan mk ON mp.karyawan_id = mk.id
            WHERE EXTRACT(MONTH FROM l.start_date) = {m} AND EXTRACT(YEAR FROM l.start_date) = {y} 
            AND l.status = 'approved' {filter_sql if "leaves" in target_tables else ""}
            GROUP BY 1
        """
        union_queries.append(q)
        
    if "permission_requests" in target_tables:
        q = f"""
            SELECT COALESCE(mk.nama_karyawan, mp.name, 'Karyawan (ID: ' || p.user_id || ')') as name, 
                   COUNT(p.id) as total_days, 
                   'Izin' as category
            FROM presensi.permission_requests p
            LEFT JOIN master.m_presensi mp ON p.user_id = mp.id
            LEFT JOIN master.m_karyawan mk ON mp.karyawan_id = mk.id
            WHERE EXTRACT(MONTH FROM p.start_date) = {m} AND EXTRACT(YEAR FROM p.start_date) = {y} 
            AND p.status = 'approved'
            GROUP BY 1
        """
        union_queries.append(q)

    query = " UNION ALL ".join(union_queries)
    
    try:
        result = await db.execute(text(query))
        rows = result.fetchall()
        
        reason_str = reason or "tidak hadir (izin/sakit/cuti)"
        
        if not rows:
            return f"INFO DATABASE: Tidak ada data karyawan yang {reason_str} pada bulan {m} tahun {y}."
            
        lines = [f"Rekapitulasi karyawan yang {reason_str} pada bulan {m}-{y}:"]
        for r in rows:
            lines.append(f"- {r.name}: {r.total_days} kali pengajuan ({r.category})")
            
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"get_absent_monthly error: {e}")
        return f"INFO DATABASE: Terjadi kesalahan saat membaca rekap cuti bulanan: {str(e)}"


# ── Tool 7: Log presensi individual & keterlambatan (Late-In) ─
async def get_employee_attendance_logs(
    db: AsyncSession,
    name_or_id: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
    only_late: Optional[bool] = False,
) -> str:
    """Mengambil log presensi detail seorang karyawan pada periode tertentu, mencakup rekap hadir, tepat waktu, rincian hari keterlambatan (jam masuk, menit telat), dan rekap izin/cuti."""
    try:
        val = name_or_id.strip()
        pattern = f"%{val}%"

        # 1. Cari karyawan di master.m_karyawan dan master.m_presensi
        q_find = text("""
            SELECT k.id as karyawan_id, k.payroll_id, k.nama_karyawan, mp.id as presensi_user_id
            FROM master.m_karyawan k
            LEFT JOIN master.m_presensi mp ON mp.karyawan_id = k.id
            WHERE k.payroll_id = :val OR LOWER(k.nama_karyawan) LIKE LOWER(:pattern)
            LIMIT 5
        """)
        res_find = await db.execute(q_find, {"val": val, "pattern": pattern})
        karyawan = res_find.mappings().all()

        if not karyawan:
            # Fallback cari langsung di m_presensi
            q_fallback = text("""
                SELECT mp.karyawan_id, COALESCE(k.payroll_id, '-') as payroll_id, mp.name as nama_karyawan, mp.id as presensi_user_id
                FROM master.m_presensi mp
                LEFT JOIN master.m_karyawan k ON mp.karyawan_id = k.id
                WHERE LOWER(mp.name) LIKE LOWER(:pattern) OR CAST(mp.id AS TEXT) = :val
                LIMIT 5
            """)
            res_fb = await db.execute(q_fallback, {"pattern": pattern, "val": val})
            karyawan = res_fb.mappings().all()

        if not karyawan:
            return f"INFO DATABASE: Tidak ditemukan karyawan dengan nama atau ID '{name_or_id}'."

        emp = karyawan[0]
        uid = emp["presensi_user_id"]
        nama = emp["nama_karyawan"]
        payroll_id = emp["payroll_id"]

        if not uid:
            return f"INFO DATABASE: Karyawan {nama} (ID: {payroll_id}) terdaftar di master data, tetapi belum memiliki akun presensi digital."

        y = year or datetime.now().year
        m = month

        month_clause = f"AND EXTRACT(MONTH FROM p.date) = {m}" if m else ""
        month_label = f"Bulan {m} Tahun {y}" if m else f"Tahun {y}"

        # 2. Query presensi
        q_presences = text(f"""
            SELECT 
                p.date, 
                p.clock_in, 
                p.clock_out, 
                p.status, 
                COALESCE(p.late_minutes, 0) as late_minutes, 
                COALESCE(p.working_hours, 0) as working_hours,
                COALESCE(p.overtime_minutes, 0) as overtime_minutes
            FROM presensi.presences p
            WHERE p.user_id = :uid 
              AND EXTRACT(YEAR FROM p.date) = :y
              {month_clause}
            ORDER BY p.date ASC
        """)
        res_p = await db.execute(q_presences, {"uid": uid, "y": y})
        rows = res_p.mappings().all()

        late_rows = []
        on_time_rows = []
        for r in rows:
            st = (r["status"] or "").lower()
            lm = r["late_minutes"] or 0
            if "terlambat" in st or "late" in st or lm > 0:
                late_rows.append(r)
            else:
                on_time_rows.append(r)

        total_hadir = len(rows)
        total_late = len(late_rows)
        total_on_time = len(on_time_rows)
        total_late_min = sum(r["late_minutes"] for r in late_rows)

        # 3. Query izin/cuti
        leave_m_clause = f"AND EXTRACT(MONTH FROM start_date) = {m}" if m else ""
        q_leaves = text(f"""
            SELECT type, start_date, end_date, reason
            FROM presensi.leaves
            WHERE user_id = :uid AND status = 'approved' AND EXTRACT(YEAR FROM start_date) = :y {leave_m_clause}
            UNION ALL
            SELECT type, start_date, end_date, reason
            FROM presensi.permission_requests
            WHERE user_id = :uid AND status = 'approved' AND EXTRACT(YEAR FROM start_date) = :y {leave_m_clause}
        """)
        res_l = await db.execute(q_leaves, {"uid": uid, "y": y})
        leaves = res_l.mappings().all()

        # 4. Format hasil
        output = [
            f"📋 REKAP PRESENSI & KEDISIPLINAN: {nama} (Payroll ID: {payroll_id})",
            f"Periode: {month_label}\n",
            f"📊 Ringkasan Kehadiran:",
            f"• Total Hadir: {total_hadir} hari kerja",
            f"• Tepat Waktu: {total_on_time} hari",
            f"• Terlambat (Late-In): {total_late} kali (Total akumulasi keterlambatan: {total_late_min} menit)",
        ]

        if leaves:
            leave_types = ", ".join([f"{l['type']} ({l['start_date'].strftime('%d/%m') if hasattr(l['start_date'], 'strftime') else l['start_date']})" for l in leaves])
            output.append(f"• Izin/Cuti Disetujui: {len(leaves)} hari ({leave_types})")
        else:
            output.append("• Izin/Cuti Disetujui: 0 hari")

        output.append(f"\n⏰ Detail Keterlambatan (Late-In):")
        if total_late == 0:
            if total_hadir == 0:
                output.append("• Belum ada catatan kehadiran pada periode ini.")
            else:
                output.append("• Karyawan TIDAK memiliki catatan keterlambatan pada periode ini (Selalu Tepat Waktu! 🎉)")
        else:
            for r in late_rows:
                tgl = r["date"].strftime("%d %B %Y") if hasattr(r["date"], "strftime") else str(r["date"])
                cin = r["clock_in"].strftime("%H:%M:%S") if hasattr(r["clock_in"], "strftime") else str(r["clock_in"] or "-")
                cout = r["clock_out"].strftime("%H:%M:%S") if hasattr(r["clock_out"], "strftime") else str(r["clock_out"] or "-")
                lmin = r["late_minutes"]
                output.append(f"• {tgl}: Masuk pukul {cin} (Terlambat {lmin} menit) | Pulang: {cout}")

        if not only_late and 0 < total_hadir <= 15:
            output.append(f"\n📅 Rincian Seluruh Kehadiran ({total_hadir} hari):")
            for r in rows:
                tgl = r["date"].strftime("%d %B %Y") if hasattr(r["date"], "strftime") else str(r["date"])
                cin = r["clock_in"].strftime("%H:%M:%S") if hasattr(r["clock_in"], "strftime") else str(r["clock_in"] or "-")
                cout = r["clock_out"].strftime("%H:%M:%S") if hasattr(r["clock_out"], "strftime") else str(r["clock_out"] or "-")
                st = r["status"] or "Hadir"
                output.append(f"• {tgl}: {cin} - {cout} ({st})")

        return "\n".join(output)
    except Exception as e:
        logger.error(f"get_employee_attendance_logs error: {e}")
        return f"INFO DATABASE: Terjadi kesalahan saat mengambil log presensi karyawan: {str(e)}"

