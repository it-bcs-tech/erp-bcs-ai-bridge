"""
Analytical Query Tools — Safe Dynamic SQL & Schema Exploration Engine
────────────────────────────────────────────────────────────────────────
Menyediakan kemampuan analisis data ad-hoc yang fleksibel dan aman:
- execute_analytical_sql: Menjalankan kueri SELECT PostgreSQL dengan validasi keamanan ketat
- inspect_table_schema: Memeriksa struktur kolom, tipe data, dan sampel baris tabel
- search_database_tables: Mencari tabel yang relevan berdasarkan kata kunci

Keamanan:
- Hanya pernyataan SELECT / WITH (read-only)
- Penolakan keras untuk kata kunci mutasi data (INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, dll.)
- Proteksi satu pernyataan (dilarang multi-statement / semicolon injection)
- Enforce LIMIT <= 50 untuk mencegah memory overrun
- Statement timeout 8 detik
"""

import re
import time
from typing import Any
from sqlalchemy import text
from app.database import async_session

FORBIDDEN_KEYWORDS = [
    r"\bINSERT\b", r"\bUPDATE\b", r"\bDELETE\b", r"\bDROP\b", r"\bALTER\b",
    r"\bTRUNCATE\b", r"\bGRANT\b", r"\bREVOKE\b", r"\bCREATE\b", r"\bREPLACE\b",
    r"\bEXECUTE\b", r"\bCOPY\b", r"\bVACUUM\b", r"\bCALL\b", r"\bDO\b",
    r"\bINTO\s+OUTFILE\b", r"\bPG_SLEEP\b", r"\bANALYZE\b", r"\bREINDEX\b"
]

# Peta ringkas tabel inti ERP BCS untuk disuntikkan ke prompt
ERP_CORE_SCHEMA_MAP = """
[MASTER DATA]
- master.m_unit: id (bigint), no_unit (varchar plat nomor cth: 'A9357TY', 'A9138R'), jenis_unit, asset_group, kategori, is_active
- master.m_karyawan: id, payroll_id (varchar cth: '2301.4045'), nama, jabatan, departemen, status_karyawan
- master.m_customer: id, customer_code, customer_name, customer_type (PLATINUM/GOLD/SILVER/STANDARD), is_active
- master.m_materials: id, material_code, name, model, brand, part_no, uom, standard_price, stock
- master.m_rute_ujo: id, origin, destination, rute_name, jarak_km, ujo_driver
- master.m_drivers: id, employee_id, sim_no, sim_type, status

[MAINTENANCE & WORKSHOP (BENGKEL)]
- fleet.work_orders: id, wo_no, wo_date, unit_id (relasi ke no_unit m_unit), mechanic_id (payroll_id karyawan), problem, cause, keluhan_driver, conclusion, status (OPEN, PROSES, READY_FOR_REINSPECTION, DISPENSATION_ACTIVE, CLOSED), status_reason, maint_category
- fleet.vehicle_inspections: id, inspection_no, unit_id (nopol), driver_id, status (APPROVED, REJECTED, NEEDS_REPAIR), odometer, notes
- fleet.tires: id, serial_number, brand, size_spec, pattern_type, current_tread_depth_mm (numeric, <= 3.0 mm KRITIS), original_tread_depth_mm, status (MOUNTED, SPARE_STOCK, RETREADING, SCRAP), current_unit_id, current_position, total_km, cost_per_km
- fleet.maintenance_dn_header: id, dn_no, dn_date, target_unit, wo_no, note, user_group, picked_by, received_by
- fleet.maintenance_dn_detail: id, dn_no, material_id (relasi material_code), qty_request, qty_supply, qty_actual, price, total

[OPERATIONAL & LOGISTICS (OCS & TRIP)]
- fleet.trip: id, no_surat_tugas, unit_id (relasi ke m_unit.id), driver_id, driver_nama, customer, cargo, origin, destination, status (SCHEDULED, EN_ROUTE, DELIVERED, COMPLETED, CANCELLED), tgl_trip, depart_time, arrive_time
- operations.contract_daily_plan: id, contract_id, plan_date, target_tonnage, target_ritase, target_units, notes
- operations.contract_monthly_targets: id, contract_id, period_month (1-12), period_year, monthly_tonnage_target, monthly_ritase_target, total_units_required
- operations.proof_of_delivery: id, trip_id, pod_number, received_date, receiver_name, status

[FINANCE & INVOICING & KASIR]
- finance.invoice: id, invoice_number, customer_id, issue_date, due_date, total_amount, paid_amount, status
- finance.dn_header: id, dn_number, trip_id, sj_number, delivery_date, status
- finance.cash_advance: id, ca_number, employee_id, amount, purpose, status
- finance.kasir_cash_ledger: id, transaction_date, direction (IN/OUT), amount, category, description, recorded_by

[GENERAL AFFAIRS & FASILITAS]
- ga.carpool_requests: id, car_id, requester_name, department, destination, purpose, use_date, return_date, status (PENDING, APPROVED, REJECTED, COMPLETED)
- ga.cars: id, plate_number, brand, model, status, mileage_km
- ga.spd_requests: id, employee_id, department, destination, start_date, end_date, purpose, total_budget, status
- ga.stationery_requests: id, request_number, requester_name, department, request_date, status
- ga.facility_bookings: id, room_id, booked_by, department, start_time, end_time, purpose, status
- ga.fleet_legal_permits: id, unit_id, permit_type (KIR, STNK, IZIN_TRAYEK), permit_number, expiry_date, renewal_cost, status

[QHSE (K3 & MUTU)]
- qhse.incidents: id, incident_date, incident_type, severity (LOW, MEDIUM, HIGH, FATAL), location, description, root_cause, corrective_action, status
- qhse.safety_briefings: id, briefing_date, topic, leader_name, location, total_participants
- qhse.proactive_reports: id, report_date, hazard_type, reported_by, location, action_taken, status
- qhse.apd_distributions: id, employee_id, apd_type, distribution_date, qty, condition
- qhse.customer_complaints: id, complaint_date, customer_id, category, description, resolution, status

[MARKETING & SALES]
- marketing.sales_order: id, so_number, so_date, customer_id, total_amount, target_tonnage, status
- marketing.contract: id, contract_number, customer_id, start_date, end_date, target_tonnage, delivered_tonnage, status
- marketing.deals: id, deal_name, customer_id, deal_stage, estimated_value, closing_date
"""


def _validate_sql_safety(sql: str) -> tuple[bool, str | None]:
    """Memeriksa keamanan kueri SQL sebelum dieksekusi."""
    clean_sql = re.sub(r"--.*?$|/\*.*?\*/", "", sql, flags=re.MULTILINE).strip()

    if not clean_sql:
        return False, "Kueri SQL kosong."

    for pattern in FORBIDDEN_KEYWORDS:
        if re.search(pattern, clean_sql, re.IGNORECASE):
            return False, f"Keamanan: Kata kunci '{pattern}' dilarang. Hanya kueri analitis SELECT yang diizinkan."

    # Periksa multi-statement
    statements = [s.strip() for s in clean_sql.split(";") if s.strip()]
    if len(statements) > 1:
        return False, "Keamanan: Hanya satu pernyataan SQL yang diperbolehkan."

    first_stmt = statements[0] if statements else ""
    if not (first_stmt.upper().startswith("SELECT") or first_stmt.upper().startswith("WITH")):
        return False, "Keamanan: Pernyataan SQL harus diawali dengan SELECT atau WITH."

    return True, None


async def execute_analytical_sql(sql_query: str, purpose: str | None = None) -> str:
    """
    Menjalankan kueri SQL analitis SELECT kustom secara aman ke database PostgreSQL ERP BCS.
    Gunakan tool ini ketika:
    - Pengguna meminta agregasi, ranking, tren perbandingan, atau perhitungan metrik yang tidak ada di tool statis.
    - Pengguna memerlukan korelasi cross-tabel (misal: bengkel dengan trip, ban kritis dengan unit, armada dengan rute).
    - Memerlukan filter atau pengelompokan (GROUP BY, SUM, AVG, COUNT, HAVING, DATE_TRUNC).

    Args:
        sql_query: Pernyataan SQL SELECT lengkap (misal: "SELECT unit_id, COUNT(*) as jml FROM fleet.work_orders GROUP BY unit_id ORDER BY jml DESC LIMIT 10").
        purpose: Ringkasan singkat tujuan analisis (misal: "Mengetahui 5 unit dengan frekuensi servis terbanyak").
    """
    is_safe, error_msg = _validate_sql_safety(sql_query)
    if not is_safe:
        return f"⚠️ [Gagal Validasi SQL]: {error_msg}"

    clean_sql = sql_query.strip().rstrip(";")

    # Otomatis pastikan ada klausa LIMIT <= 50 agar tidak membebani memori dan token
    if not re.search(r"\bLIMIT\s+\d+", clean_sql, re.IGNORECASE):
        clean_sql += " LIMIT 50"
    else:
        def _cap_limit(match):
            val = int(match.group(1))
            return f"LIMIT {min(val, 50)}"
        clean_sql = re.sub(r"\bLIMIT\s+(\d+)", _cap_limit, clean_sql, flags=re.IGNORECASE)

    start_time = time.time()
    try:
        async with async_session() as db:
            await db.execute(text("SET statement_timeout = '8000'"))
            res = await db.execute(text(clean_sql))
            rows = res.mappings().all()
            duration_ms = round((time.time() - start_time) * 1000, 2)

            if not rows:
                return (
                    f"📊 **Hasil Kueri Analitis** (0 baris, {duration_ms} ms):\n"
                    f"Kueri berhasil dijalankan namun tidak mengembalikan data yang cocok.\n"
                    f"*Tujuan: {purpose or 'Analisis data'}*"
                )

            keys = list(rows[0].keys())
            header = "| " + " | ".join(keys) + " |"
            separator = "| " + " | ".join(["---"] * len(keys)) + " |"

            row_lines = []
            for r in rows:
                row_vals = []
                for k in keys:
                    v = r[k]
                    if v is None:
                        row_vals.append("-")
                    elif isinstance(v, float):
                        row_vals.append(f"{v:,.2f}")
                    elif isinstance(v, (int, bool)):
                        row_vals.append(str(v))
                    else:
                        # Bersihkan newline dan pipe untuk format tabel Markdown yang rapi
                        val_str = str(v).replace("\n", " ").replace("|", "/")
                        if len(val_str) > 60:
                            val_str = val_str[:57] + "..."
                        row_vals.append(val_str)
                row_lines.append("| " + " | ".join(row_vals) + " |")

            table_md = "\n".join([header, separator] + row_lines)
            return (
                f"📊 **Hasil Kueri Analitis** ({len(rows)} baris, {duration_ms} ms):\n\n"
                f"{table_md}\n\n"
                f"*Tujuan: {purpose or 'Analisis data ad-hoc'}*"
            )

    except Exception as e:
        err_msg = str(e)
        return (
            f"⚠️ [Error Eksekusi SQL]: {err_msg}\n"
            f"Petunjuk: Periksa kembali nama tabel (misal: fleet.work_orders, master.m_unit), "
            f"nama kolom yang tepat, dan tipe data."
        )


async def inspect_table_schema(table_name: str, schema_name: str | None = None) -> str:
    """
    Memeriksa nama kolom, tipe data, dan mengambil 2 baris sampel dari tabel database tertentu.
    Sangat berguna jika Anda ragu tentang nama kolom yang benar sebelum membuat SQL analitis.

    Args:
        table_name: Nama tabel (misal: 'work_orders' atau 'm_unit').
        schema_name: Nama skema database (misal: 'fleet', 'master', 'operations', 'finance').
                     Jika tidak diisi, akan otomatis dicari di seluruh skema.
    """
    clean_table = table_name.strip()
    if "." in clean_table:
        parts = clean_table.split(".", 1)
        schema_name = parts[0]
        clean_table = parts[1]

    try:
        async with async_session() as db:
            if schema_name:
                q_cols = text("""
                    SELECT table_schema, column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = :schema AND table_name = :table
                    ORDER BY ordinal_position;
                """)
                res_cols = await db.execute(q_cols, {"schema": schema_name, "table": clean_table})
            else:
                q_cols = text("""
                    SELECT table_schema, column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_name = :table AND table_schema NOT IN ('pg_catalog', 'information_schema')
                    ORDER BY table_schema, ordinal_position;
                """)
                res_cols = await db.execute(q_cols, {"table": clean_table})

            cols = res_cols.mappings().all()
            if not cols:
                return f"⚠️ Tabel '{clean_table}' tidak ditemukan di database."

            found_schema = cols[0]["table_schema"]
            full_table = f"{found_schema}.{clean_table}"

            col_summary = [f"- **{c['column_name']}** (`{c['data_type']}`, nullable: {c['is_nullable']})" for c in cols]

            # Ambil 2 sampel baris
            sample_text = "Tidak ada sampel baris."
            try:
                q_sample = text(f"SELECT * FROM {full_table} LIMIT 2")
                res_sample = await db.execute(q_sample)
                samples = res_sample.mappings().all()
                if samples:
                    sample_dict = [dict(s) for s in samples]
                    sample_text = str(sample_dict)
            except Exception:
                pass

            return (
                f"📋 **Struktur Skema Tabel `{full_table}`** ({len(cols)} kolom):\n\n"
                + "\n".join(col_summary)
                + f"\n\n**Sampel Data:**\n```json\n{sample_text}\n```"
            )

    except Exception as e:
        return f"⚠️ [Gagal Inspeksi Skema]: {str(e)}"


async def search_database_tables(keyword: str) -> str:
    """
    Mencari tabel di database PostgreSQL yang namanya cocok dengan kata kunci tertentu.
    Args:
        keyword: Kata kunci nama tabel (misal: 'tire', 'trip', 'invoice', 'driver').
    """
    clean_kw = f"%{keyword.strip()}%"
    try:
        async with async_session() as db:
            q = text("""
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_name ILIKE :kw
                  AND table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY table_schema, table_name
                LIMIT 25;
            """)
            res = await db.execute(q, {"kw": clean_kw})
            rows = res.fetchall()

            if not rows:
                return f"Tidak ditemukan tabel dengan kata kunci '{keyword}'."

            lines = [f"- `{s}.{t}`" for s, t in rows]
            return f"🔍 **Daftar Tabel yang Cocok ('{keyword}'):**\n" + "\n".join(lines)

    except Exception as e:
        return f"⚠️ [Gagal Cari Tabel]: {str(e)}"
