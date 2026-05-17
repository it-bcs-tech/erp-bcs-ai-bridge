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
