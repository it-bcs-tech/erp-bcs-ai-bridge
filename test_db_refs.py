"""
Test Script 2 — Explore Reference Tables
─────────────────────────────────────────
Explore tabel referensi: m_dept, m_division, m_title, m_lokasi
agar query chatbot bisa tampilkan nama yang readable.
"""

import asyncio
import asyncpg

DATABASE_URL = "postgresql://bcs_admin:sangatrahasia@103.31.205.199:5433/mybcs_db"


async def main():
    conn = await asyncpg.connect(DATABASE_URL)

    # ── m_dept ───────────────────────────────────────────
    print("📂 master.m_dept (Departemen):")
    cols = await conn.fetch("""
        SELECT column_name, data_type FROM information_schema.columns 
        WHERE table_schema = 'master' AND table_name = 'm_dept'
        ORDER BY ordinal_position
    """)
    print(f"   Columns: {', '.join(c['column_name'] for c in cols)}")
    rows = await conn.fetch("SELECT * FROM master.m_dept LIMIT 10")
    for r in rows:
        print(f"   {dict(r)}")

    # ── m_division ───────────────────────────────────────
    print("\n📂 master.m_division (Divisi):")
    cols = await conn.fetch("""
        SELECT column_name, data_type FROM information_schema.columns 
        WHERE table_schema = 'master' AND table_name = 'm_division'
        ORDER BY ordinal_position
    """)
    print(f"   Columns: {', '.join(c['column_name'] for c in cols)}")
    rows = await conn.fetch("SELECT * FROM master.m_division LIMIT 10")
    for r in rows:
        print(f"   {dict(r)}")

    # ── m_title ──────────────────────────────────────────
    print("\n📂 master.m_title (Jabatan):")
    cols = await conn.fetch("""
        SELECT column_name, data_type FROM information_schema.columns 
        WHERE table_schema = 'master' AND table_name = 'm_title'
        ORDER BY ordinal_position
    """)
    print(f"   Columns: {', '.join(c['column_name'] for c in cols)}")
    rows = await conn.fetch("SELECT * FROM master.m_title LIMIT 10")
    for r in rows:
        print(f"   {dict(r)}")

    # ── m_lokasi ─────────────────────────────────────────
    print("\n📂 master.m_lokasi (Lokasi):")
    cols = await conn.fetch("""
        SELECT column_name, data_type FROM information_schema.columns 
        WHERE table_schema = 'master' AND table_name = 'm_lokasi'
        ORDER BY ordinal_position
    """)
    print(f"   Columns: {', '.join(c['column_name'] for c in cols)}")
    rows = await conn.fetch("SELECT * FROM master.m_lokasi LIMIT 10")
    for r in rows:
        print(f"   {dict(r)}")

    # ── Status unik ──────────────────────────────────────
    print("\n📊 Unique values of 'status' in m_karyawan:")
    rows = await conn.fetch("""
        SELECT status, COUNT(*) as total 
        FROM master.m_karyawan 
        GROUP BY status 
        ORDER BY total DESC
    """)
    for r in rows:
        print(f"   • {r['status']}: {r['total']}")

    # ── Aktif unik ───────────────────────────────────────
    print("\n📊 Unique values of 'aktif' in m_karyawan:")
    rows = await conn.fetch("""
        SELECT aktif, COUNT(*) as total 
        FROM master.m_karyawan 
        GROUP BY aktif 
        ORDER BY total DESC
    """)
    for r in rows:
        print(f"   • '{r['aktif']}': {r['total']}")

    await conn.close()
    print("\n✅ Done.")


if __name__ == "__main__":
    asyncio.run(main())
