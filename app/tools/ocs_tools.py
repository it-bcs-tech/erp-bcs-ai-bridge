"""
OCS Tools — Operational Center System Tools
─────────────────────────────────────────────────────────────
Tools untuk query data operasional logistik:
- Target Rencana Harian (operations.contract_daily_plan)
- Target Bulanan Kontrak (operations.contract_monthly_targets)
- Penugasan Trip & Dispatch (fleet.trip)
- Bukti Serah Terima / POD (operations.proof_of_delivery)
- Master Pelanggan Logistik (master.m_customer)

Digunakan oleh ocs_agent.py (ORIS).
"""

from datetime import datetime, date
from sqlalchemy import text
from app.database import async_session


async def get_daily_operational_plan(plan_date: str | None = None, contract_id: str | None = None, limit: int = 10) -> str:
    """
    Mengambil rencana harian operasional (target ritase, tonase, dan kebutuhan unit) per kontrak/pelanggan.
    Args:
        plan_date: Tanggal rencana dalam format 'YYYY-MM-DD'. Jika tidak diisi, mengambil tanggal rencana terdekat/terbaru.
        contract_id: ID kontrak spesifik (misal: 'PO-2026-10-9564').
        limit: Batas jumlah data yang ditampilkan (default: 10).
    """
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": limit}

            if plan_date:
                conditions.append("plan_date = :plan_date")
                params["plan_date"] = plan_date
            if contract_id:
                conditions.append("contract_id ILIKE :contract_id")
                params["contract_id"] = f"%{contract_id.strip()}%"

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
            order_clause = "ORDER BY plan_date DESC, target_tonnage DESC"

            q = f"""
                SELECT id, contract_id, plan_date, target_tonnage, target_ritase, target_units, notes, is_manual
                FROM operations.contract_daily_plan
                {where_clause}
                {order_clause}
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                filter_str = f" untuk tanggal '{plan_date}'" if plan_date else ""
                filter_str += f" kontrak '{contract_id}'" if contract_id else ""
                return f"ℹ️ Tidak ditemukan data rencana harian operasional{filter_str}."

            total_tonnage = sum(float(r["target_tonnage"] or 0) for r in rows)
            total_ritase = sum(int(r["target_ritase"] or 0) for r in rows)
            total_units = sum(int(r["target_units"] or 0) for r in rows)

            lines = [
                f"📋 RENCANA OPERASIONAL HARIAN (DAILY PLAN):",
                f"• Total Data Ditampilkan : {len(rows)} rencana",
                f"• Akumulasi Target Tonase: {total_tonnage:,.2f} Ton",
                f"• Akumulasi Ritase       : {total_ritase} Ritase",
                f"• Kebutuhan Armada       : {total_units} Unit",
                "",
                "Rincian Rencana:"
            ]

            for r in rows:
                p_date = r["plan_date"].strftime("%d %b %Y") if isinstance(r["plan_date"], (date, datetime)) else str(r["plan_date"])
                notes_str = f" | Catatan: {r['notes']}" if r["notes"] else ""
                lines.append(
                    f"  • [{p_date}] Kontrak: {r['contract_id']} ➔ Target: {float(r['target_tonnage'] or 0):,.2f} Ton | "
                    f"{r['target_ritase']} Rit | {r['target_units']} Unit{notes_str}"
                )

            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil data rencana harian operasional: {str(e)}"


async def get_active_trips_and_dispatch(
    status: str | None = None,
    driver_name: str | None = None,
    destination: str | None = None,
    limit: int = 15
) -> str:
    """
    Mengambil data penugasan trip armada, status surat tugas (ST), muatan, rute, dan pengemudi.
    Args:
        status: Status trip ('SCHEDULED', 'RUNNING', 'COMPLETED', 'CANCELED').
        driver_name: Nama driver yang dicari.
        destination: Kota atau lokasi tujuan.
        limit: Batas data yang ditampilkan (default: 15).
    """
    try:
        async with async_session() as db:
            conditions = ["t.deleted_at IS NULL"]
            params = {"limit": limit}

            if status:
                conditions.append("UPPER(t.status::text) = :status")
                params["status"] = status.strip().upper()
            if driver_name:
                conditions.append("t.driver_nama ILIKE :driver_name")
                params["driver_name"] = f"%{driver_name.strip()}%"
            if destination:
                conditions.append("(t.destination ILIKE :destination OR t.customer ILIKE :destination)")
                params["destination"] = f"%{destination.strip()}%"

            where_clause = "WHERE " + " AND ".join(conditions)

            # Hitung rekap status trip secara global
            q_stats = """
                SELECT 
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE UPPER(status::text) = 'SCHEDULED') as scheduled,
                    COUNT(*) FILTER (WHERE UPPER(status::text) = 'RUNNING') as running,
                    COUNT(*) FILTER (WHERE UPPER(status::text) = 'COMPLETED') as completed
                FROM fleet.trip
                WHERE deleted_at IS NULL
            """
            res_stats = await db.execute(text(q_stats))
            row_stats = res_stats.mappings().first()

            # Query data trip
            q = f"""
                SELECT 
                    t.id, t.no_surat_tugas, t.unit_id, t.driver_nama, t.customer, t.cargo,
                    t.origin, t.destination, t.status::text as status_txt, t.tgl_trip, t.distance_km, t.fuel_used_l,
                    u.no_unit
                FROM fleet.trip t
                LEFT JOIN master.m_unit u ON t.unit_id = u.id
                {where_clause}
                ORDER BY t.tgl_trip DESC, t.id DESC
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return "ℹ️ Tidak ditemukan trip operasional yang cocok dengan kriteria filter yang diberikan."

            lines = [
                f"🚛 DATA DISPATCH & TRIP OPERASIONAL ARMADA:",
                f"📊 Ringkasan Status Global: Total {row_stats['total']} Trip (Scheduled: {row_stats['scheduled']}, Running: {row_stats['running']}, Completed: {row_stats['completed']})",
                "",
                f"Daftar Penugasan Trip (Terbaru {len(rows)} data):"
            ]

            for r in rows:
                t_date = r["tgl_trip"].strftime("%d/%m/%Y") if isinstance(r["tgl_trip"], (date, datetime)) else str(r["tgl_trip"])
                unit_str = r["no_unit"] or (f"Unit ID {r['unit_id']}" if r["unit_id"] else "Belum Assign Unit")
                driver_str = r["driver_nama"] or "Belum Ditugaskan"
                cargo_str = f" | Muatan: {r['cargo']}" if r["cargo"] else ""
                lines.append(
                    f"  • [{r['status_txt']}] {r['no_surat_tugas']} ({t_date})\n"
                    f"    Armada: {unit_str} | Driver: {driver_str}{cargo_str}\n"
                    f"    Rute: {r['origin'] or '-'} ➔ {r['destination'] or '-'}"
                )

            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil data trip operasional: {str(e)}"


async def get_proof_of_delivery_status(
    pod_number: str | None = None,
    sales_order_id: str | None = None,
    status: str | None = None,
    limit: int = 10
) -> str:
    """
    Mengambil data status Bukti Serah Terima / Proof of Delivery (POD), selisih timbangan (shrinkage), dan status penagihan invoice.
    Args:
        pod_number: Nomor POD tertentu (misal: 'POD-2026-0001').
        sales_order_id: ID Sales Order / Surat Jalan terkait (misal: 'DO-PO-591844').
        status: Status POD ('VERIFIED', 'DISPUTED', 'PENDING_VERIFICATION').
        limit: Batas data yang ditampilkan (default: 10).
    """
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": limit}

            if pod_number:
                conditions.append("pod_number ILIKE :pod_number")
                params["pod_number"] = f"%{pod_number.strip()}%"
            if sales_order_id:
                conditions.append("sales_order_id ILIKE :sales_order_id")
                params["sales_order_id"] = f"%{sales_order_id.strip()}%"
            if status:
                conditions.append("UPPER(status::text) = :status")
                params["status"] = status.strip().upper()

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            q = f"""
                SELECT 
                    id, pod_number, sales_order_id, dispatched_weight, received_weight,
                    shrinkage_weight, receiver_name, status::text as status_txt, is_invoiced, created_at
                FROM operations.proof_of_delivery
                {where_clause}
                ORDER BY id DESC
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return "ℹ️ Tidak ditemukan data Proof of Delivery (POD) yang sesuai kriteria."

            lines = [
                f"📑 STATUS PROOF OF DELIVERY (POD) & SURAT JALAN:",
                f"Total Data: {len(rows)} dokumen",
                ""
            ]

            for r in rows:
                disp_w = float(r["dispatched_weight"] or 0)
                recv_w = float(r["received_weight"] or 0)
                shrink = float(r["shrinkage_weight"] or 0)
                inv_status = "Sudah Ditagih (Invoiced)" if r["is_invoiced"] else "Belum Invoiced"
                receiver = r["receiver_name"] or "-"

                warning_shrink = f" ⚠️ [Susut {shrink:,.2f} Ton]" if shrink > 0 else " ✅ [Sesuai]"

                lines.append(
                    f"  • Nomor POD : {r['pod_number']} (DO: {r['sales_order_id']})\n"
                    f"    Status    : {r['status_txt']} | {inv_status}\n"
                    f"    Tonase    : Kirim {disp_w:,.2f} Ton ➔ Diterima {recv_w:,.2f} Ton{warning_shrink}\n"
                    f"    Penerima  : {receiver}\n"
                )

            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil data POD operasional: {str(e)}"


async def get_monthly_contract_targets(contract_id: str | None = None, limit: int = 10) -> str:
    """
    Mengambil target tonase bulanan per kontrak pelanggan.
    """
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": limit}

            if contract_id:
                conditions.append("contract_id ILIKE :contract_id")
                params["contract_id"] = f"%{contract_id.strip()}%"

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            q = f"""
                SELECT id, contract_id, target_month, target_tonnage
                FROM operations.contract_monthly_targets
                {where_clause}
                ORDER BY target_month DESC
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return "ℹ️ Tidak ditemukan data target bulanan kontrak."

            lines = [
                "📊 TARGET BULANAN KONTRAK OPERASIONAL:",
                ""
            ]
            for r in rows:
                m_str = r["target_month"].strftime("%B %Y") if isinstance(r["target_month"], (date, datetime)) else str(r["target_month"])
                lines.append(f"  • Periode: {m_str} | Kontrak: {r['contract_id']} ➔ Target: {float(r['target_tonnage'] or 0):,.2f} Ton")

            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil target bulanan kontrak: {str(e)}"


async def get_customer_and_partner_info(search: str | None = None, limit: int = 10) -> str:
    """
    Mencari informasi pelanggan logistik (kode kustomer, nama, tier, nomor kontak, dan alamat).
    """
    try:
        async with async_session() as db:
            conditions = ["is_active = TRUE"]
            params = {"limit": limit}

            if search:
                conditions.append("(nama_kustomer ILIKE :search OR kode_kustomer ILIKE :search)")
                params["search"] = f"%{search.strip()}%"

            where_clause = "WHERE " + " AND ".join(conditions)

            q = f"""
                SELECT id, kode_kustomer, nama_kustomer, contact_person, phone, tier, alamat
                FROM master.m_customer
                {where_clause}
                ORDER BY nama_kustomer ASC
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return f"ℹ️ Tidak ditemukan data pelanggan dengan kata kunci '{search}'."

            lines = [
                f"🏢 INFORMASI PELANGGAN LOGISTIK (MASTER CUSTOMER):",
                ""
            ]
            for r in rows:
                cp = r["contact_person"] or "-"
                ph = r["phone"] or "-"
                tier = f" [Tier {r['tier']}]" if r["tier"] else ""
                lines.append(
                    f"  • {r['nama_kustomer']}{tier} (Kode: {r['kode_kustomer']})\n"
                    f"    Kontak: {cp} ({ph}) | Alamat: {r['alamat'] or '-'}"
                )

            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil data master customer: {str(e)}"


async def get_fleet_maintenance_and_readiness() -> str:
    """
    Mengambil data kesiapan armada operasional untuk dispatch, meliputi:
    - Populasi total armada terdaftar (master.m_unit)
    - Unit yang siap di-dispatch (ready)
    - Unit yang sedang dalam perawatan/bengkel (fleet.work_orders yang masih Open/Proses/Re-inspeksi)
    - Unit yang sedang bertugas / jalan (fleet.trip yang berstatus RUNNING / SCHEDULED)
    - Unit non-aktif / decommissioned
    - Rincian daftar armada yang sedang dalam antrean atau pengerjaan bengkel beserta no WO dan kerusakannya.
    """
    try:
        async with async_session() as db:
            # 1. Summary master unit
            q_units = """
                SELECT 
                    COUNT(*) as total_units,
                    COUNT(*) FILTER (WHERE is_active = TRUE) as active_units,
                    COUNT(*) FILTER (WHERE is_active = FALSE) as inactive_units
                FROM master.m_unit
            """
            res_u = await db.execute(text(q_units))
            u_stats = res_u.mappings().first()

            # 2. Active work orders (sedang perbaikan / maintenance)
            q_wo = """
                SELECT 
                    wo.id, wo.wo_no, wo.wo_date, wo.unit_id, wo.status, wo.problem, 
                    wo.maint_category, wo.status_reason, wo.promised_date,
                    COALESCE(u.jenis_unit, '-') as jenis_unit,
                    COALESCE(u.kategori, '-') as kategori,
                    u.is_active
                FROM fleet.work_orders wo
                LEFT JOIN master.m_unit u ON UPPER(REPLACE(u.no_unit, ' ', '')) = UPPER(REPLACE(wo.unit_id, ' ', ''))
                WHERE UPPER(wo.status) NOT IN ('CLOSED', 'CANCELED', 'REJECTED')
                ORDER BY wo.wo_date DESC, wo.id DESC
            """
            res_wo = await db.execute(text(q_wo))
            active_wos = res_wo.mappings().all()

            # 3. Unit yang sedang bertugas / trip jalan
            q_trips = """
                SELECT COUNT(DISTINCT unit_id) as units_on_trip
                FROM fleet.trip
                WHERE UPPER(status::text) IN ('RUNNING', 'SCHEDULED')
                  AND deleted_at IS NULL
            """
            res_t = await db.execute(text(q_trips))
            t_stats = res_t.mappings().first()
            units_on_trip = t_stats["units_on_trip"] or 0

            total_units = u_stats["total_units"]
            inactive_units = u_stats["inactive_units"]
            active_units = u_stats["active_units"]
            in_maint_count = len(active_wos)
            ready_dispatch = max(0, active_units - in_maint_count - units_on_trip)

            lines = [
                "🚛 STATUS KESIAPAN ARMADA & MAINTENANCE (READINESS & DISPATCH):",
                f"• Total Populasi Armada Terdaftar : {total_units} unit",
                f"• Armada Siap Dispatch (Ready)   : {ready_dispatch} unit",
                f"• Armada Tidak Bisa Dispatch      : {inactive_units + in_maint_count + units_on_trip} unit",
                f"  ├─ Sedang Maintenance di Bengkel : {in_maint_count} unit",
                f"  ├─ Sedang On Trip / Bertugas     : {units_on_trip} unit",
                f"  └─ Non-Aktif / Decommissioned    : {inactive_units} unit",
                ""
            ]

            if active_wos:
                lines.append(f"🔧 DAFTAR UNIT SEDANG DALAM MAINTENANCE ({in_maint_count} Unit):")
                for wo in active_wos:
                    p_date = ""
                    if wo["promised_date"]:
                        p_date = f" (Est. Selesai: {wo['promised_date'].strftime('%d %b %Y') if isinstance(wo['promised_date'], (date, datetime)) else str(wo['promised_date'])})"
                    prob = wo["problem"] or wo["status_reason"] or "Pemeriksaan / Perbaikan rutin"
                    cat = wo["maint_category"] or "Maintenance"
                    lines.append(
                        f"  • {wo['unit_id']} [{wo['status']}] - {cat}\n"
                        f"    No WO: {wo['wo_no']} | Masalah: {prob}{p_date}"
                    )
            else:
                lines.append("✅ Tidak ada unit yang sedang dalam antrean atau proses maintenance bengkel.")

            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil status maintenance & readiness armada: {str(e)}"


async def check_unit_dispatch_eligibility(nopol: str) -> str:
    """
    Mengecek kelayakan dan kesiapan satu unit spesifik (nomor polisi / nopol) untuk di-dispatch.
    Memeriksa status master unit, work order perbaikan di bengkel, dan jadwal trip berjalan.
    Args:
        nopol: Nomor polisi atau nomor unit (misal: 'A 9357 TY' atau 'A9357TY').
    """
    try:
        clean_nopol = nopol.upper().replace(" ", "")
        async with async_session() as db:
            # 1. Cek di m_unit
            q_u = """
                SELECT id, no_unit, jenis_unit, kategori, asset_group, is_active
                FROM master.m_unit
                WHERE UPPER(REPLACE(no_unit, ' ', '')) = :nopol
                LIMIT 1
            """
            res_u = await db.execute(text(q_u), {"nopol": clean_nopol})
            unit = res_u.mappings().first()

            if not unit:
                return f"⚠️ Unit dengan nomor polisi '{nopol}' tidak ditemukan dalam master data armada."

            # 2. Cek apakah ada work order aktif di bengkel
            q_wo = """
                SELECT id, wo_no, wo_date, status, problem, maint_category, promised_date
                FROM fleet.work_orders
                WHERE UPPER(REPLACE(unit_id, ' ', '')) = :nopol
                  AND UPPER(status) NOT IN ('CLOSED', 'CANCELED', 'REJECTED')
                ORDER BY wo_date DESC, id DESC
                LIMIT 1
            """
            res_wo = await db.execute(text(q_wo), {"nopol": clean_nopol})
            active_wo = res_wo.mappings().first()

            # 3. Cek apakah ada trip berjalan
            q_tr = """
                SELECT id, no_surat_tugas, status, origin, destination, driver_nama
                FROM fleet.trip
                WHERE unit_id = :u_id
                  AND UPPER(status::text) IN ('RUNNING', 'SCHEDULED')
                  AND deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
            """
            res_tr = await db.execute(text(q_tr), {"u_id": unit["id"]})
            active_tr = res_tr.mappings().first()

            lines = [
                f"🔍 HASIL CEK STATUS UNIT: {unit['no_unit']}",
                f"• Jenis / Kategori : {unit['jenis_unit'] or '-'} ({unit['kategori'] or unit['asset_group'] or '-'})",
                f"• Status Master    : {'Aktif Operasional' if unit['is_active'] else 'Non-Aktif / Decommissioned'}"
            ]

            if not unit['is_active']:
                lines.append("\n❌ STATUS: TIDAK DAPAT DI-DISPATCH")
                lines.append("Alasan: Unit tercatat Non-Aktif / Decommissioned pada master armada.")
                return "\n".join(lines)

            if active_wo:
                p_date = f" (Est. Selesai: {active_wo['promised_date'].strftime('%d %b %Y') if isinstance(active_wo['promised_date'], (date, datetime)) else str(active_wo['promised_date'])})" if active_wo['promised_date'] else ""
                lines.append("\n⚠️ STATUS: TIDAK DAPAT DI-DISPATCH (SEDANG MAINTENANCE)")
                lines.append(f"• No. WO       : {active_wo['wo_no']}")
                lines.append(f"• Status WO    : {active_wo['status']} ({active_wo['maint_category'] or 'Repair'})")
                lines.append(f"• Kerusakan    : {active_wo['problem'] or '-'}{p_date}")
                return "\n".join(lines)

            if active_tr:
                lines.append("\n⚠️ STATUS: TIDAK DAPAT DI-DISPATCH (SEDANG BERTUGAS / ON TRIP)")
                lines.append(f"• No. Surat Tugas : {active_tr['no_surat_tugas']}")
                lines.append(f"• Driver          : {active_tr['driver_nama'] or '-'}")
                lines.append(f"• Rute            : {active_tr['origin']} ➔ {active_tr['destination']}")
                lines.append(f"• Status Trip     : {active_tr['status']}")
                return "\n".join(lines)

            lines.append("\n✅ STATUS: SIAP DI-DISPATCH (READY)")
            lines.append("Unit dalam kondisi prima, tidak ada Work Order perbaikan aktif, dan belum ditugaskan pada trip aktif.")
            return "\n".join(lines)

    except Exception as e:
        return f"❌ Gagal memeriksa status unit: {str(e)}"
