"""
Test Script — Verify Employee Queries
─────────────────────────────────────────
Test semua fungsi di employees.py terhadap database real.
"""

import asyncio
import sys
import os

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker


DATABASE_URL = "postgresql+asyncpg://bcs_admin:sangatrahasia@103.31.205.199:5433/mybcs_db"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def main():
    from app.tools.employees import (
        get_employee_count,
        search_employee_by_name,
        get_employees_by_department,
        get_employees_by_division,
        get_employees_by_status,
        get_employees_by_location,
        get_employee_list,
    )
    from app.agents.intent_detector import detect_intent

    async with async_session() as db:
        print("=" * 60)
        print("🧪 TESTING EMPLOYEE QUERIES")
        print("=" * 60)

        # Test 1: Employee Count
        print("\n📊 TEST 1: get_employee_count()")
        print("-" * 40)
        result = await get_employee_count(db)
        print(result)

        # Test 2: Search by name
        print("\n\n🔍 TEST 2: search_employee_by_name('TRI')")
        print("-" * 40)
        result = await search_employee_by_name(db, "TRI")
        print(result)

        # Test 3: By department
        print("\n\n📂 TEST 3: get_employees_by_department(None) — Ringkasan")
        print("-" * 40)
        result = await get_employees_by_department(db, None)
        print(result)

        # Test 4: By department specific
        print("\n\n📂 TEST 4: get_employees_by_department('FINANCE')")
        print("-" * 40)
        result = await get_employees_by_department(db, "FINANCE")
        print(result)

        # Test 5: By status
        print("\n\n👤 TEST 5: get_employees_by_status('PERMANENT')")
        print("-" * 40)
        result = await get_employees_by_status(db, "PERMANENT")
        print(result)

        # Test 6: By location
        print("\n\n📍 TEST 6: get_employees_by_location('CILEGON')")
        print("-" * 40)
        result = await get_employees_by_location(db, "CILEGON")
        print(result)

        # Test 7: By division
        print("\n\n🏢 TEST 7: get_employees_by_division(None) — Ringkasan")
        print("-" * 40)
        result = await get_employees_by_division(db, None)
        print(result)

        # Test 8: Employee list
        print("\n\n📋 TEST 8: get_employee_list(limit=5)")
        print("-" * 40)
        result = await get_employee_list(db, limit=5)
        print(result)

        # Test 9: Intent Detection
        print("\n\n🧠 TEST 9: Intent Detection")
        print("-" * 40)
        test_messages = [
            "Berapa jumlah karyawan?",
            "Cari karyawan bernama Alimudin",
            "Siapa saja yang di departemen finance?",
            "Karyawan yang status kontrak berapa?",
            "Tampilkan karyawan di Cilegon",
            "Daftar divisi dan jumlah karyawannya",
            "List semua karyawan",
            "Apa kabar?",
        ]
        for msg in test_messages:
            intent = detect_intent(msg)
            print(f"   '{msg}'")
            print(f"   → intent={intent.intent}, confidence={intent.confidence:.2f}, entities={intent.entities}\n")

    await engine.dispose()
    print("\n✅ All tests completed!")


if __name__ == "__main__":
    asyncio.run(main())
