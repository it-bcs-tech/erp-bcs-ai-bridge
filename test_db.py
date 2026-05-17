"""
Test Script — Explore PostgreSQL Schema
─────────────────────────────────────────
Script ini untuk:
1. Test koneksi ke PostgreSQL
2. Lihat kolom-kolom di tabel master.m_karyawan
3. Ambil sample data
"""

import asyncio
import asyncpg


DATABASE_URL = "postgresql://bcs_admin:sangatrahasia@103.31.205.199:5433/mybcs_db"


async def main():
    print("=" * 60)
    print("🔌 Connecting to PostgreSQL...")
    print(f"   URL: {DATABASE_URL.split('@')[1]}")
    print("=" * 60)

    try:
        conn = await asyncpg.connect(DATABASE_URL)
        print("✅ Connected successfully!\n")

        # ── 1. List semua schema ─────────────────────────────
        print("📂 SCHEMAS:")
        schemas = await conn.fetch("""
            SELECT schema_name 
            FROM information_schema.schemata
            WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
            ORDER BY schema_name
        """)
        for s in schemas:
            print(f"   • {s['schema_name']}")

        # ── 2. List tabel di schema 'master' ─────────────────
        print("\n📋 TABLES IN SCHEMA 'master':")
        tables = await conn.fetch("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'master'
            ORDER BY table_name
        """)
        for t in tables:
            print(f"   • master.{t['table_name']}")

        # ── 3. List tabel di schema 'presensi' ───────────────
        print("\n📋 TABLES IN SCHEMA 'presensi':")
        tables_presensi = await conn.fetch("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'presensi'
            ORDER BY table_name
        """)
        for t in tables_presensi:
            print(f"   • presensi.{t['table_name']}")

        # ── 4. Kolom di master.m_karyawan ────────────────────
        print("\n🔍 COLUMNS IN 'master.m_karyawan':")
        columns = await conn.fetch("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns 
            WHERE table_schema = 'master' AND table_name = 'm_karyawan'
            ORDER BY ordinal_position
        """)
        if columns:
            print(f"   Total: {len(columns)} columns\n")
            for col in columns:
                nullable = "NULL" if col['is_nullable'] == 'YES' else "NOT NULL"
                default = f" (default: {col['column_default']})" if col['column_default'] else ""
                print(f"   • {col['column_name']:30s} {col['data_type']:20s} {nullable}{default}")
        else:
            print("   ⚠️ Table not found or no columns!")

        # ── 5. Sample data (5 rows) ─────────────────────────
        print("\n📊 SAMPLE DATA (5 rows):")
        try:
            rows = await conn.fetch("SELECT * FROM master.m_karyawan LIMIT 5")
            if rows:
                # Print column names
                col_names = list(rows[0].keys())
                print(f"   Columns: {', '.join(col_names)}\n")
                for i, row in enumerate(rows, 1):
                    print(f"   --- Row {i} ---")
                    for key, value in row.items():
                        print(f"   {key}: {value}")
                    print()
            else:
                print("   (no data)")
        except Exception as e:
            print(f"   ⚠️ Error: {e}")

        # ── 6. Count total records ───────────────────────────
        print("📈 TOTAL RECORDS:")
        try:
            count = await conn.fetchval("SELECT COUNT(*) FROM master.m_karyawan")
            print(f"   master.m_karyawan: {count} records")
        except Exception as e:
            print(f"   ⚠️ Error: {e}")

        await conn.close()
        print("\n✅ Connection closed.")

    except Exception as e:
        print(f"\n❌ Connection FAILED: {e}")
        print("\nTips:")
        print("  • Pastikan PostgreSQL bisa diakses dari jaringan ini")
        print("  • Cek firewall port 5433")
        print("  • Cek username/password")


if __name__ == "__main__":
    asyncio.run(main())
