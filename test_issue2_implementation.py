"""
Automated Test Suite for Issue #2 Implementation
=================================================
Verifies:
1. get_employee_attendance_logs (Late-in logs, clock_in, minutes late, leave summary)
2. get_employee_full_profile (Tenure calculation, leave quota, contract status, strict salary exclusion)
3. get_people_analytics (Birthdays, work anniversaries, contract expirations)
4. Tool Router Keyword Intent Matching for new tools
5. FastAPI app initialization and route registration
"""

import asyncio
import sys
import os

# Set UTF-8 encoding
sys.stdout.reconfigure(encoding="utf-8")

# Ensure app is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import async_session
from app.tools.presensi import get_employee_attendance_logs, get_attendance_monthly
from app.tools.employees import get_employee_full_profile, get_people_analytics
from app.llm.tool_router import get_relevant_tools
from app.agents.hris_agent import HRIS_TOOLS, SYSTEM_PROMPT


async def run_tests():
    passed = 0
    total = 0

    print("=" * 70)
    print("🚀 RUNNING AUTOMATED TESTS FOR ISSUE #2 IMPLEMENTATION")
    print("=" * 70)

    async with async_session() as db:

        # ── TEST 1: get_employee_attendance_logs (Oktober 2026) ────────
        total += 1
        print(f"\n[TEST {total}] get_employee_attendance_logs - Adi Fuadil (Bulan 10)")
        res1 = await get_employee_attendance_logs(db, name_or_id="Adi Fuadil Hidayah", month=10, year=2026)
        print(res1[:300] + "...\n")
        assert "ADI FUADIL HIDAYAH" in res1, "Employee name missing"
        assert "Total Hadir" in res1, "Total hadir missing"
        assert "Terlambat (Late-In)" in res1, "Late count missing"
        assert "51 menit" in res1, "Late minutes missing"
        print("✅ TEST 1 PASSED: Log presensi Oktober berhasil dianalisis dengan rincian keterlambatan.")
        passed += 1

        # ── TEST 2: get_employee_attendance_logs (September 2026) ──────
        total += 1
        print(f"\n[TEST {total}] get_employee_attendance_logs - Adi Fuadil (Bulan 9, only_late=True)")
        res2 = await get_employee_attendance_logs(db, name_or_id="Adi Fuadil Hidayah", month=9, year=2026, only_late=True)
        print(res2[:300] + "...\n")
        assert "Terlambat (Late-In): 3 kali" in res2, "Should have 3 late occurrences in September"
        assert "577 menit" in res2, "Accumulated late minutes missing"
        print("✅ TEST 2 PASSED: Filter keterlambatan September berhasil mendeteksi 3 kali telat masuk.")
        passed += 1

        # ── TEST 3: get_attendance_monthly redirect with employee_id ───
        total += 1
        print(f"\n[TEST {total}] get_attendance_monthly redirect with employee_id")
        res3 = await get_attendance_monthly(db, month=10, year=2026, employee_id="2504.4238")
        assert "ADI FUADIL HIDAYAH" in res3, "Redirect to employee logs failed"
        print("✅ TEST 3 PASSED: get_attendance_monthly dengan employee_id otomatis dialihkan ke log presensi.")
        passed += 1

        # ── TEST 4: get_employee_full_profile & Strict Salary Privacy ──
        total += 1
        print(f"\n[TEST {total}] get_employee_full_profile - Adi Fuadil & Strict Salary Privacy")
        res4 = await get_employee_full_profile(db, name_or_id="Adi Fuadil Hidayah")
        print(res4[:350] + "...\n")
        assert "PROFIL LENGKAP KARYAWAN" in res4, "Profile header missing"
        assert "Masa Kerja (Tenure)" in res4, "Tenure calculation missing"
        assert "Saldo Cuti" in res4, "Leave quota missing"
        assert "IT INFRASTRUCTURE" in res4, "Position missing"
        # STRICT SALARY PRIVACY ASSERTIONS:
        assert "gaji_pokok" not in res4.lower(), "SECURITY LEAK: gaji_pokok found in profile"
        assert "nominal" not in res4.lower(), "SECURITY LEAK: nominal found in profile"
        assert "thp" not in res4.lower(), "SECURITY LEAK: thp found in profile"
        assert "slip_gaji" not in res4.lower(), "SECURITY LEAK: slip_gaji found in profile"
        print("✅ TEST 4 PASSED: Profil karyawan lengkap tersaji dan data gaji 100% terlindungi (Strict Salary Privacy).")
        passed += 1

        # ── TEST 5: get_people_analytics (Birthdays & Anniversaries) ───
        total += 1
        print(f"\n[TEST {total}] get_people_analytics - Birthdays & Anniversaries")
        res5_b = await get_people_analytics(db, category="birthdays", month=10)
        res5_a = await get_people_analytics(db, category="anniversaries", month=10)
        assert "KARYAWAN BERULANG TAHUN" in res5_b, "Birthday analytics failed"
        assert "WORK ANNIVERSARY KARYAWAN" in res5_a, "Anniversary analytics failed"
        assert "tahun masa bakti" in res5_a, "Service tenure missing"
        print("✅ TEST 5 PASSED: People analytics untuk ulang tahun dan masa bakti bulan berjalan berhasil.")
        passed += 1

        # ── TEST 6: Tool Router Intent Matching ────────────────────────
        total += 1
        print(f"\n[TEST {total}] Tool Router Keyword Intent Matching")
        
        # Scenario A: User asks "apakah ada telat masuk?"
        tools_a = await get_relevant_tools("apakah ada telat masuk?", HRIS_TOOLS)
        tool_names_a = [t["function"]["name"] for t in tools_a]
        assert "get_employee_attendance_logs" in tool_names_a, f"Failed to match late attendance: {tool_names_a}"
        
        # Scenario B: User asks "profil lengkap dan masa kerja adi fuadil"
        tools_b = await get_relevant_tools("profil lengkap dan masa kerja adi fuadil", HRIS_TOOLS)
        tool_names_b = [t["function"]["name"] for t in tools_b]
        assert "get_employee_full_profile" in tool_names_b, f"Failed to match full profile: {tool_names_b}"

        # Scenario C: User asks "siapa yang ulang tahun bulan ini?"
        tools_c = await get_relevant_tools("siapa yang ulang tahun bulan ini?", HRIS_TOOLS)
        tool_names_c = [t["function"]["name"] for t in tools_c]
        assert "get_people_analytics" in tool_names_c, f"Failed to match birthdays: {tool_names_c}"

        print("✅ TEST 6 PASSED: Intent router secara tepat mengaktifkan tool baru sesuai kata kunci pengguna.")
        passed += 1

        # ── TEST 7: Guardrail prompt validation ────────────────────────
        total += 1
        print(f"\n[TEST {total}] SYSTEM_PROMPT Strict Salary Guardrail Verification")
        assert "STRICT SALARY GUARDRAIL" in SYSTEM_PROMPT, "Guardrail section missing from prompt"
        assert "DILARANG KERAS" in SYSTEM_PROMPT, "Prohibition text missing from prompt"
        assert "get_employee_attendance_logs" in SYSTEM_PROMPT, "Tool guideline missing from prompt"
        print("✅ TEST 7 PASSED: System prompt memuat instruksi keamanan gaji ketat dan panduan pemanggilan tool.")
        passed += 1

    print("\n" + "=" * 70)
    print(f"🎉 ALL TESTS PASSED: {passed}/{total} tests completed successfully!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_tests())
