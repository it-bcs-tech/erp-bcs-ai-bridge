"""
Automated Test Suite for FMS Fallback & OCS Integration
======================================================
Verifies:
1. FMS: get_all_fleet_status with DB fallback
2. FMS: get_unit_detail with DB fallback (unit A9176R)
3. OCS: get_daily_operational_plan from operations.contract_daily_plan
4. OCS: get_active_trips_and_dispatch from fleet.trip
5. OCS: get_proof_of_delivery_status from operations.proof_of_delivery
6. OCS: get_monthly_contract_targets from operations.contract_monthly_targets
7. OCS: get_customer_and_partner_info from master.m_customer
"""

import asyncio
import sys
import os

# Set UTF-8 encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.tools.fms_tools import get_all_fleet_status, get_unit_detail
from app.tools.ocs_tools import (
    get_daily_operational_plan,
    get_active_trips_and_dispatch,
    get_proof_of_delivery_status,
    get_monthly_contract_targets,
    get_customer_and_partner_info,
    get_fleet_maintenance_and_readiness,
    check_unit_dispatch_eligibility,
)


async def run_tests():
    passed = 0
    total = 0

    print("=" * 70)
    print("🚀 RUNNING AUTOMATED TESTS FOR FMS & OCS ENHANCEMENT")
    print("=" * 70)

    # ── TEST 1: FMS get_all_fleet_status (DB Fallback) ────────
    total += 1
    print(f"\n[TEST {total}] FMS get_all_fleet_status (PostgreSQL Fallback)")
    res1 = await get_all_fleet_status()
    print(res1[:300] + "...\n")
    assert "Total Terdaftar" in res1, "Fleet total count missing"
    assert "Kategori Armada" in res1, "Category breakdown missing"
    print("✅ TEST 1 PASSED: FMS berhasil memuat data armada dari database.")
    passed += 1

    # ── TEST 2: FMS get_unit_detail (A9176R) ────────
    total += 1
    print(f"\n[TEST {total}] FMS get_unit_detail for A9176R")
    res2 = await get_unit_detail("A9176R")
    print(res2[:300] + "...\n")
    assert "A9176R" in res2, "Nopol missing in detail"
    assert "DUMP TRUCK" in res2, "Vehicle type missing"
    print("✅ TEST 2 PASSED: FMS berhasil memuat detail unit A9176R beserta riwayat trip.")
    passed += 1

    # ── TEST 3: OCS get_daily_operational_plan ────────
    total += 1
    print(f"\n[TEST {total}] OCS get_daily_operational_plan")
    res3 = await get_daily_operational_plan(limit=5)
    print(res3[:300] + "...\n")
    assert "RENCANA OPERASIONAL HARIAN" in res3, "Header missing"
    assert "Akumulasi Target Tonase" in res3, "Target tonnage missing"
    print("✅ TEST 3 PASSED: OCS berhasil mengambil target harian operasional.")
    passed += 1

    # ── TEST 4: OCS get_active_trips_and_dispatch ────────
    total += 1
    print(f"\n[TEST {total}] OCS get_active_trips_and_dispatch")
    res4 = await get_active_trips_and_dispatch(limit=5)
    print(res4[:300] + "...\n")
    assert "DATA DISPATCH & TRIP OPERASIONAL ARMADA" in res4, "Dispatch header missing"
    assert "Ringkasan Status Global" in res4, "Global status missing"
    print("✅ TEST 4 PASSED: OCS berhasil mengambil data dispatch & trip armada.")
    passed += 1

    # ── TEST 5: OCS get_proof_of_delivery_status ────────
    total += 1
    print(f"\n[TEST {total}] OCS get_proof_of_delivery_status")
    res5 = await get_proof_of_delivery_status(limit=5)
    print(res5[:300] + "...\n")
    assert "PROOF OF DELIVERY" in res5, "POD header missing"
    assert "Tonase" in res5, "Weight info missing"
    print("✅ TEST 5 PASSED: OCS berhasil memuat bukti serah terima (POD).")
    passed += 1

    # ── TEST 6: OCS get_monthly_contract_targets ────────
    total += 1
    print(f"\n[TEST {total}] OCS get_monthly_contract_targets")
    res6 = await get_monthly_contract_targets(limit=5)
    print(res6[:300] + "...\n")
    assert "TARGET BULANAN KONTRAK" in res6, "Monthly target header missing"
    print("✅ TEST 6 PASSED: OCS berhasil memuat target bulanan kontrak.")
    passed += 1

    # ── TEST 7: OCS get_customer_and_partner_info ────────
    total += 1
    print(f"\n[TEST {total}] OCS get_customer_and_partner_info (Indocement)")
    res7 = await get_customer_and_partner_info(search="Indocement", limit=3)
    print(res7[:300] + "...\n")
    assert "Indocement" in res7, "Customer name missing"
    print("✅ TEST 7 PASSED: OCS berhasil mencari informasi kontak pelanggan.")
    passed += 1

    # ── TEST 8: OCS get_fleet_maintenance_and_readiness ────────
    total += 1
    print(f"\n[TEST {total}] OCS get_fleet_maintenance_and_readiness")
    res8 = await get_fleet_maintenance_and_readiness()
    print(res8[:300] + "...\n")
    assert "KESIAPAN ARMADA & MAINTENANCE" in res8, "Readiness header missing"
    assert "Sedang Maintenance" in res8, "Maintenance count missing"
    print("✅ TEST 8 PASSED: OCS berhasil memuat data maintenance bengkel & kesiapan armada.")
    passed += 1

    # ── TEST 9: OCS check_unit_dispatch_eligibility ────────
    total += 1
    print(f"\n[TEST {total}] OCS check_unit_dispatch_eligibility (A9357TY - Maintenance)")
    res9 = await check_unit_dispatch_eligibility("A9357TY")
    print(res9[:300] + "...\n")
    assert "TIDAK DAPAT DI-DISPATCH" in res9, "Dispatch eligibility status missing"
    print("✅ TEST 9 PASSED: OCS berhasil memverifikasi status kelayakan dispatch unit.")
    passed += 1

    print("=" * 70)
    print(f"🎉 ALL TESTS PASSED: {passed}/{total} tests completed successfully!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_tests())
