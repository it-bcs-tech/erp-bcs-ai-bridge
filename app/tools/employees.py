"""
Employee Data Tools
─────────────────────────────────────────
Query data karyawan dari PostgreSQL.
Schema: master | Table: m_karyawan

Tabel referensi:
  - master.m_dept      (dept_code → dept_name)
  - master.m_division  (div_code → div_name)
  - master.m_title     (title_code → title)
  - master.m_lokasi    (loc_code → loc_name)

Kolom penting m_karyawan:
  - id, payroll_id, nama_karyawan
  - title (FK → m_title.title_code)
  - dept_id (FK → m_dept.dept_code)
  - div_id (FK → m_division.div_code)
  - lokasi (FK → m_lokasi.loc_code)
  - status: PERMANENT | CONTRACT | MITRA KERJA | BORONGAN | HARIAN | INTERNSHIP | OTHER
  - aktif: Y/N
  - tgl_masuk, tgl_keluar, tempat_lahir, tgl_lahir
  - jenis_kelamin: MALE | FEMALE
  - agama, pendidikan_terakhir, marital_status
  - email, telp1
  - point_of_hire
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, date
from typing import Optional
import logging

logger = logging.getLogger(__name__)


# ── Query umum dengan JOIN ke tabel referensi ────────────────

BASE_EMPLOYEE_SELECT = """
    SELECT 
        k.id,
        k.payroll_id,
        k.nama_karyawan,
        COALESCE(t.title, k.title) AS jabatan,
        COALESCE(d.dept_name, k.dept_id) AS departemen,
        COALESCE(dv.div_name, k.div_id) AS divisi,
        COALESCE(l.loc_name, k.lokasi) AS lokasi,
        k.status,
        k.aktif,
        k.jenis_kelamin,
        k.tgl_masuk,
        k.tgl_keluar,
        k.tempat_lahir,
        k.tgl_lahir,
        k.agama,
        k.pendidikan_terakhir,
        k.marital_status,
        k.email,
        k.telp1,
        k.point_of_hire
    FROM master.m_karyawan k
    LEFT JOIN master.m_title t ON k.title = t.title_code
    LEFT JOIN master.m_dept d ON k.dept_id = d.dept_code
    LEFT JOIN master.m_division dv ON k.div_id = dv.div_code
    LEFT JOIN master.m_lokasi l ON k.lokasi = l.loc_code
"""


async def get_employee_count(db: AsyncSession) -> str:
    """Hitung total karyawan berdasarkan status dan jenis kelamin."""
    query = text("""
        SELECT 
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'PERMANENT') AS permanent,
            COUNT(*) FILTER (WHERE status = 'CONTRACT') AS contract,
            COUNT(*) FILTER (WHERE status = 'MITRA KERJA') AS mitra_kerja,
            COUNT(*) FILTER (WHERE status = 'BORONGAN') AS borongan,
            COUNT(*) FILTER (WHERE status = 'HARIAN') AS harian,
            COUNT(*) FILTER (WHERE status = 'INTERNSHIP') AS internship,
            COUNT(*) FILTER (WHERE jenis_kelamin = 'MALE') AS pria,
            COUNT(*) FILTER (WHERE jenis_kelamin = 'FEMALE') AS wanita
        FROM master.m_karyawan
        WHERE aktif = 'Y'
    """)
    result = await db.execute(query)
    row = result.mappings().first()

    if not row:
        return "Tidak ada data karyawan di database."

    return (
        f"📊 STATISTIK KARYAWAN AKTIF:\n"
        f"• Total karyawan aktif: {row['total']}\n"
        f"\n📋 Berdasarkan Status Kepegawaian:\n"
        f"• Permanent (tetap): {row['permanent']}\n"
        f"• Contract (kontrak): {row['contract']}\n"
        f"• Mitra Kerja: {row['mitra_kerja']}\n"
        f"• Borongan: {row['borongan']}\n"
        f"• Harian: {row['harian']}\n"
        f"• Internship (magang): {row['internship']}\n"
        f"\n👥 Berdasarkan Jenis Kelamin:\n"
        f"• Pria: {row['pria']}\n"
        f"• Wanita: {row['wanita']}"
    )


async def search_employee_by_name(db: AsyncSession, name: str) -> str:
    """Cari karyawan berdasarkan nama (partial match)."""
    query = text(f"""
        {BASE_EMPLOYEE_SELECT}
        WHERE LOWER(k.nama_karyawan) LIKE LOWER(:pattern)
          AND k.aktif = 'Y'
        ORDER BY k.nama_karyawan
        LIMIT 10
    """)
    result = await db.execute(query, {"pattern": f"%{name}%"})
    rows = result.mappings().all()

    if not rows:
        return f"Tidak ditemukan karyawan aktif dengan nama mengandung '{name}'."

    lines = [f"🔍 HASIL PENCARIAN KARYAWAN (kata kunci: '{name}') — {len(rows)} hasil:"]
    for row in rows:
        tgl_masuk = row['tgl_masuk'].strftime('%d %B %Y') if row['tgl_masuk'] else '-'
        lines.append(
            f"\n• {row['nama_karyawan']} (ID: {row['payroll_id']})\n"
            f"  Jabatan: {row['jabatan']}\n"
            f"  Departemen: {row['departemen']} | Divisi: {row['divisi']}\n"
            f"  Lokasi: {row['lokasi']} | Status: {row['status']}\n"
            f"  Tanggal Masuk: {tgl_masuk}\n"
            f"  Email: {row['email'] or '-'} | Telp: {row['telp1'] or '-'}"
        )
    return "\n".join(lines)


async def get_employees_by_department(db: AsyncSession, department: str | None = None) -> str:
    """Ambil daftar karyawan per departemen, atau ringkasan semua departemen."""
    if department:
        # Cari karyawan di departemen tertentu
        query = text(f"""
            {BASE_EMPLOYEE_SELECT}
            WHERE (LOWER(d.dept_name) LIKE LOWER(:dept) OR LOWER(k.dept_id) LIKE LOWER(:dept))
              AND k.aktif = 'Y'
            ORDER BY k.nama_karyawan
            LIMIT 20
        """)
        result = await db.execute(query, {"dept": f"%{department}%"})
        rows = result.mappings().all()

        if not rows:
            return f"Tidak ada karyawan aktif di departemen '{department}'."

        lines = [f"👥 KARYAWAN DI DEPARTEMEN YANG MENGANDUNG '{department.upper()}' ({len(rows)} orang):"]
        for row in rows:
            lines.append(f"• {row['nama_karyawan']} — {row['jabatan']} | {row['departemen']} ({row['status']})")
        return "\n".join(lines)
    else:
        # Ringkasan semua departemen
        query = text("""
            SELECT 
                COALESCE(d.dept_name, k.dept_id) AS departemen,
                COUNT(*) AS total
            FROM master.m_karyawan k
            LEFT JOIN master.m_dept d ON k.dept_id = d.dept_code
            WHERE k.aktif = 'Y'
            GROUP BY departemen
            ORDER BY total DESC
        """)
        result = await db.execute(query)
        rows = result.mappings().all()

        if not rows:
            return "Tidak ada data departemen."

        lines = ["📋 RINGKASAN KARYAWAN PER DEPARTEMEN:"]
        for row in rows:
            lines.append(f"• {row['departemen']}: {row['total']} orang")
        return "\n".join(lines)


async def get_employees_by_status(db: AsyncSession, status: str | None = None) -> str:
    """Ambil karyawan berdasarkan status (PERMANENT, CONTRACT, MITRA KERJA, dll)."""
    if status:
        query = text(f"""
            {BASE_EMPLOYEE_SELECT}
            WHERE LOWER(k.status) LIKE LOWER(:status)
              AND k.aktif = 'Y'
            ORDER BY k.nama_karyawan
            LIMIT 20
        """)
        result = await db.execute(query, {"status": f"%{status}%"})
        rows = result.mappings().all()

        if not rows:
            return f"Tidak ada karyawan aktif dengan status '{status}'."

        # Hitung total
        count_query = text("""
            SELECT COUNT(*) FROM master.m_karyawan 
            WHERE LOWER(status) LIKE LOWER(:status) AND aktif = 'Y'
        """)
        count_result = await db.execute(count_query, {"status": f"%{status}%"})
        total = count_result.scalar() or 0

        lines = [f"👤 KARYAWAN DENGAN STATUS '{status.upper()}' (menampilkan {len(rows)} dari {total} total):"]
        for row in rows:
            lines.append(f"• {row['nama_karyawan']} — {row['jabatan']} | {row['departemen']} | {row['lokasi']}")
        return "\n".join(lines)
    else:
        return await get_employee_count(db)


async def get_employee_list(db: AsyncSession, limit: int = 15) -> str:
    """Ambil daftar karyawan aktif (dengan limit)."""
    query = text(f"""
        {BASE_EMPLOYEE_SELECT}
        WHERE k.aktif = 'Y'
        ORDER BY k.nama_karyawan
        LIMIT :limit
    """)
    result = await db.execute(query, {"limit": limit})
    rows = result.mappings().all()

    if not rows:
        return "Tidak ada data karyawan."

    # Hitung total
    count_query = text("SELECT COUNT(*) FROM master.m_karyawan WHERE aktif = 'Y'")
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    lines = [f"📋 DAFTAR KARYAWAN AKTIF (menampilkan {len(rows)} dari {total} total):"]
    for row in rows:
        lines.append(
            f"• {row['nama_karyawan']} ({row['payroll_id']})\n"
            f"  {row['jabatan']} | {row['departemen']} | {row['lokasi']} | {row['status']}"
        )

    if total > limit:
        lines.append(f"\n⚠️ Hanya menampilkan {limit} karyawan pertama dari total {total}.")

    return "\n".join(lines)


async def get_employees_by_location(db: AsyncSession, location: str) -> str:
    """Ambil karyawan berdasarkan lokasi kerja."""
    query = text(f"""
        {BASE_EMPLOYEE_SELECT}
        WHERE (LOWER(l.loc_name) LIKE LOWER(:loc) OR LOWER(k.point_of_hire) LIKE LOWER(:loc))
          AND k.aktif = 'Y'
        ORDER BY k.nama_karyawan
        LIMIT 20
    """)
    result = await db.execute(query, {"loc": f"%{location}%"})
    rows = result.mappings().all()

    if not rows:
        return f"Tidak ada karyawan aktif di lokasi '{location}'."

    lines = [f"📍 KARYAWAN DI LOKASI '{location.upper()}' ({len(rows)} orang):"]
    for row in rows:
        lines.append(f"• {row['nama_karyawan']} — {row['jabatan']} | {row['departemen']} ({row['status']})")
    return "\n".join(lines)


async def get_employees_by_division(db: AsyncSession, division: str | None = None) -> str:
    """Ambil karyawan berdasarkan divisi atau ringkasan semua divisi."""
    if division:
        query = text(f"""
            {BASE_EMPLOYEE_SELECT}
            WHERE (LOWER(dv.div_name) LIKE LOWER(:div) OR LOWER(k.div_id) LIKE LOWER(:div))
              AND k.aktif = 'Y'
            ORDER BY k.nama_karyawan
            LIMIT 20
        """)
        result = await db.execute(query, {"div": f"%{division}%"})
        rows = result.mappings().all()

        if not rows:
            return f"Tidak ada karyawan aktif di divisi '{division}'."

        lines = [f"🏢 KARYAWAN DI DIVISI '{division.upper()}' ({len(rows)} orang):"]
        for row in rows:
            lines.append(f"• {row['nama_karyawan']} — {row['jabatan']} | {row['departemen']} ({row['status']})")
        return "\n".join(lines)
    else:
        query = text("""
            SELECT 
                COALESCE(dv.div_name, k.div_id) AS divisi,
                COUNT(*) AS total
            FROM master.m_karyawan k
            LEFT JOIN master.m_division dv ON k.div_id = dv.div_code
            WHERE k.aktif = 'Y'
            GROUP BY divisi
            ORDER BY total DESC
        """)
        result = await db.execute(query)
        rows = result.mappings().all()

        lines = ["🏢 RINGKASAN KARYAWAN PER DIVISI:"]
        for row in rows:
            lines.append(f"• {row['divisi']}: {row['total']} orang")
        return "\n".join(lines)


# ── Tool 8: Profil Lengkap Karyawan (Strict Salary Guardrail) 
async def get_employee_full_profile(db: AsyncSession, name_or_id: str) -> str:
    """Mengambil biodata dan profil lengkap kepegawaian (non-finansial) seorang karyawan, mencakup masa kerja, sisa kuota cuti tahunan, status kontrak, dan riwayat izin/sakit.

    KEBIJAKAN KEAMANAN: Fungsi ini secara ketat mengecualikan seluruh informasi finansial / nominal gaji.
    """
    try:
        val = name_or_id.strip()
        pattern = f"%{val}%"

        # Explicitly NO salary / slip / THP fields!
        query = text("""
            SELECT 
                k.id,
                k.payroll_id,
                k.nama_karyawan,
                COALESCE(t.title, k.title) AS jabatan,
                COALESCE(d.dept_name, k.dept_id) AS departemen,
                COALESCE(dv.div_name, k.div_id) AS divisi,
                COALESCE(l.loc_name, k.lokasi) AS lokasi,
                k.status,
                k.aktif,
                k.jenis_kelamin,
                k.tgl_masuk,
                k.tgl_keluar,
                k.agreement_expire,
                k.tempat_lahir,
                k.tgl_lahir,
                k.agama,
                k.pendidikan_terakhir,
                k.jurusan,
                k.nama_sekolah_terakhir,
                k.tahun_lulus,
                k.marital_status,
                k.email,
                k.telp1,
                k.point_of_hire,
                mp.id as presensi_user_id
            FROM master.m_karyawan k
            LEFT JOIN master.m_title t ON k.title = t.title_code
            LEFT JOIN master.m_dept d ON k.dept_id = d.dept_code
            LEFT JOIN master.m_division dv ON k.div_id = dv.div_code
            LEFT JOIN master.m_lokasi l ON k.lokasi = l.loc_code
            LEFT JOIN master.m_presensi mp ON mp.karyawan_id = k.id
            WHERE k.payroll_id = :val OR LOWER(k.nama_karyawan) LIKE LOWER(:pattern)
            LIMIT 1
        """)
        result = await db.execute(query, {"val": val, "pattern": pattern})
        row = result.mappings().first()

        if not row:
            return f"INFO DATABASE: Tidak ditemukan profil karyawan dengan nama atau ID '{name_or_id}'."

        # Hitung masa kerja (Tenure)
        tgl_masuk = row["tgl_masuk"]
        tenure_str = "-"
        if tgl_masuk:
            today = date.today()
            years = today.year - tgl_masuk.year
            months = today.month - tgl_masuk.month
            if today.day < tgl_masuk.day:
                months -= 1
            if months < 0:
                years -= 1
                months += 12
            tenure_parts = []
            if years > 0:
                tenure_parts.append(f"{years} tahun")
            if months > 0:
                tenure_parts.append(f"{months} bulan")
            tenure_str = " ".join(tenure_parts) if tenure_parts else "Kurang dari 1 bulan"

        # Status masa berlaku kontrak / agreement
        contract_str = "-"
        agr = row["agreement_expire"]
        if agr:
            today = date.today()
            diff = (agr - today).days
            tgl_agr_str = agr.strftime("%d %B %Y") if hasattr(agr, "strftime") else str(agr)
            if diff > 0:
                contract_str = f"Berlaku s/d {tgl_agr_str} ({diff} hari lagi)"
            elif diff == 0:
                contract_str = f"Berakhir hari ini ({tgl_agr_str})"
            else:
                contract_str = f"Telah berakhir pada {tgl_agr_str} (Perlu Pembaharuan)"
        elif row["status"] == "PERMANENT":
            contract_str = "Karyawan Tetap (Permanen)"
        else:
            contract_str = f"Status: {row['status']} (Tanggal berakhir tidak tercatat)"

        # Cek sisa kuota cuti tahunan
        uid = row["presensi_user_id"]
        leave_quota_str = "Data saldo cuti tidak ditemukan di sistem presensi."
        if uid:
            q_lb = text("""
                SELECT quota, used, (quota - used) as sisa 
                FROM presensi.leave_balances 
                WHERE user_id = :uid AND year = EXTRACT(YEAR FROM CURRENT_DATE)
            """)
            res_lb = await db.execute(q_lb, {"uid": uid})
            lb = res_lb.mappings().first()
            if lb:
                leave_quota_str = f"Kuota: {lb['quota']} hari | Terpakai: {lb['used']} hari | Sisa Saldo: {lb['sisa']} hari"

        tgl_masuk_str = tgl_masuk.strftime("%d %B %Y") if (tgl_masuk and hasattr(tgl_masuk, "strftime")) else str(tgl_masuk or "-")
        tgl_lahir_str = row["tgl_lahir"].strftime("%d %B %Y") if (row["tgl_lahir"] and hasattr(row["tgl_lahir"], "strftime")) else str(row["tgl_lahir"] or "-")

        output = f"""👤 PROFIL LENGKAP KARYAWAN: {row['nama_karyawan']} (Payroll ID: {row['payroll_id']})
══════════════════════════════════════════════════════════════
🏢 Informasi Kepegawaian & Penempatan:
• Status Kepegawaian : {row['status']} ({'Aktif' if row['aktif'] == 'Y' else 'Non-Aktif'})
• Jabatan / Posisi    : {row['jabatan']}
• Divisi / Departemen : {row['divisi']} / {row['departemen']}
• Lokasi Kerja / Site : {row['lokasi']} (Point of Hire: {row['point_of_hire'] or '-'})
• Tanggal Bergabung  : {tgl_masuk_str}
• Masa Kerja (Tenure) : {tenure_str}
• Masa Berlaku Kontrak: {contract_str}

🏖️ Hak Cuti & Kedisiplinan:
• Saldo Cuti {datetime.now().year}: {leave_quota_str}

🎓 Pendidikan & Kontak:
• Pendidikan Terakhir : {row['pendidikan_terakhir'] or '-'} ({row['jurusan'] or '-'})
• Asal Institusi      : {row['nama_sekolah_terakhir'] or '-'} (Lulus: {row['tahun_lulus'] or '-'})
• Email               : {row['email'] or '-'}
• No. Telepon         : {row['telp1'] or '-'}
• Tempat / Tgl Lahir  : {row['tempat_lahir'] or '-'}, {tgl_lahir_str}
• Jenis Kelamin / Agm : {row['jenis_kelamin']} / {row['agama'] or '-'}"""

        return output
    except Exception as e:
        logger.error(f"get_employee_full_profile error: {e}")
        return f"INFO DATABASE: Terjadi kesalahan saat membaca profil lengkap karyawan: {str(e)}"


# ── Tool 9: People Analytics & Monitoring ─────────────────────
async def get_people_analytics(
    db: AsyncSession,
    category: str,
    days: Optional[int] = 60,
    month: Optional[int] = None,
) -> str:
    """Analisis SDM cerdas: monitoring kontrak berakhir (contracts_expiring), ulang tahun karyawan bulan berjalan (birthdays), atau peringatan masa kerja / work anniversary (anniversaries)."""
    try:
        today = date.today()
        target_month = month or today.month

        if category == "contracts_expiring":
            days_int = days or 60
            query = text("""
                SELECT 
                    k.payroll_id, 
                    k.nama_karyawan, 
                    COALESCE(t.title, k.title) as jabatan,
                    COALESCE(d.dept_name, k.dept_id) as departemen,
                    COALESCE(l.loc_name, k.lokasi) as lokasi,
                    k.agreement_expire,
                    (k.agreement_expire - CURRENT_DATE) as days_left
                FROM master.m_karyawan k
                LEFT JOIN master.m_title t ON k.title = t.title_code
                LEFT JOIN master.m_dept d ON k.dept_id = d.dept_code
                LEFT JOIN master.m_lokasi l ON k.lokasi = l.loc_code
                WHERE k.aktif = 'Y' 
                  AND k.agreement_expire IS NOT NULL
                  AND k.agreement_expire >= CURRENT_DATE - INTERVAL '30 days'
                  AND k.agreement_expire <= CURRENT_DATE + (:days_val || ' days')::INTERVAL
                ORDER BY k.agreement_expire ASC
                LIMIT 20
            """)
            result = await db.execute(query, {"days_val": str(days_int)})
            rows = result.mappings().all()

            if not rows:
                return f"📋 PEOPLE ANALYTICS: Tidak ada karyawan aktif yang kontraknya akan berakhir dalam {days_int} hari ke depan."

            lines = [f"📋 MONITORING KONTRAK BERAKHIR (Rentang {days_int} hari ke depan) — {len(rows)} karyawan:"]
            for r in rows:
                tgl_str = r["agreement_expire"].strftime("%d %B %Y") if hasattr(r["agreement_expire"], "strftime") else str(r["agreement_expire"])
                dl = r["days_left"]
                status_waktu = f"{dl} hari lagi" if dl > 0 else (f"Berakhir hari ini" if dl == 0 else f"Telah lewat {abs(dl)} hari lalu (Perlu Update)")
                lines.append(f"• {r['nama_karyawan']} ({r['payroll_id']}) — {r['jabatan']} | {r['departemen']}")
                lines.append(f"  Habis Kontrak: {tgl_str} ({status_waktu})")
            return "\n".join(lines)

        elif category == "birthdays":
            query = text("""
                SELECT 
                    k.payroll_id, 
                    k.nama_karyawan, 
                    COALESCE(t.title, k.title) as jabatan,
                    COALESCE(d.dept_name, k.dept_id) as departemen,
                    k.tgl_lahir,
                    EXTRACT(DAY FROM k.tgl_lahir) as tgl
                FROM master.m_karyawan k
                LEFT JOIN master.m_title t ON k.title = t.title_code
                LEFT JOIN master.m_dept d ON k.dept_id = d.dept_code
                WHERE k.aktif = 'Y' AND EXTRACT(MONTH FROM k.tgl_lahir) = :target_m
                ORDER BY tgl ASC
                LIMIT 25
            """)
            result = await db.execute(query, {"target_m": target_month})
            rows = result.mappings().all()

            if not rows:
                return f"🎂 PEOPLE ANALYTICS: Tidak ada karyawan yang berulang tahun pada bulan {target_month}."

            lines = [f"🎂 KARYAWAN BERULANG TAHUN PADA BULAN {target_month} ({len(rows)} orang):"]
            for r in rows:
                tgl_str = r["tgl_lahir"].strftime("%d %B") if hasattr(r["tgl_lahir"], "strftime") else f"Tgl {int(r['tgl'])}"
                lines.append(f"• {tgl_str}: {r['nama_karyawan']} — {r['jabatan']} ({r['departemen']})")
            return "\n".join(lines)

        elif category == "anniversaries":
            query = text("""
                SELECT 
                    k.payroll_id, 
                    k.nama_karyawan, 
                    COALESCE(t.title, k.title) as jabatan,
                    COALESCE(d.dept_name, k.dept_id) as departemen,
                    k.tgl_masuk,
                    (EXTRACT(YEAR FROM CURRENT_DATE) - EXTRACT(YEAR FROM k.tgl_masuk)) as years_service
                FROM master.m_karyawan k
                LEFT JOIN master.m_title t ON k.title = t.title_code
                LEFT JOIN master.m_dept d ON k.dept_id = d.dept_code
                WHERE k.aktif = 'Y' AND EXTRACT(MONTH FROM k.tgl_masuk) = :target_m
                ORDER BY k.tgl_masuk ASC
                LIMIT 25
            """)
            result = await db.execute(query, {"target_m": target_month})
            rows = result.mappings().all()

            if not rows:
                return f"🏆 PEOPLE ANALYTICS: Tidak ada karyawan dengan work anniversary pada bulan {target_month}."

            lines = [f"🏆 WORK ANNIVERSARY KARYAWAN BULAN {target_month} ({len(rows)} orang):"]
            for r in rows:
                tgl_str = r["tgl_masuk"].strftime("%d %B %Y") if hasattr(r["tgl_masuk"], "strftime") else str(r["tgl_masuk"])
                years = int(r["years_service"] or 0)
                lines.append(f"• {r['nama_karyawan']} — {r['jabatan']} ({r['departemen']}) | Bergabung: {tgl_str} ({years} tahun masa bakti)")
            return "\n".join(lines)

        else:
            return f"Kategori analitik '{category}' tidak dikenali. Pilihan yang valid: 'contracts_expiring', 'birthdays', 'anniversaries'."

    except Exception as e:
        logger.error(f"get_people_analytics error: {e}")
        return f"INFO DATABASE: Terjadi kesalahan saat memproses people analytics: {str(e)}"

