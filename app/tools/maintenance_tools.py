"""
Maintenance Tools — Workshop & Fleet Maintenance System Tools
─────────────────────────────────────────────────────────────
Tools untuk query data perawatan dan perbengkelan armada PT BCS Logistics:
- Surat Perintah Kerja / Work Orders (fleet.work_orders)
- Inspeksi Pra-jalan / P2H (fleet.vehicle_inspections)
- Manajemen & Kondisi Ban (fleet.tires)
- Pengeluaran Suku Cadang & Material (fleet.maintenance_dn_header & maintenance_dn_detail)
- Riwayat Servis Unit (master.m_unit & fleet.work_orders)

Digunakan oleh maintenance_agent.py (MARIS).
"""

from datetime import datetime, date
from sqlalchemy import text
from app.database import async_session


async def get_maintenance_overview() -> str:
    """
    Mengambil ringkasan data perawatan armada bengkel terkini:
    - Jumlah Work Order aktif berdasarkan status (Open, Proses, Ready For Reinspection, Dispensation)
    - Kategori perbaikan (Regular Repair, Corrective P2H, Emergency, dsb.)
    - Populasi ban terdaftar dan ban yang membutuhkan perhatian (tread depth menipis)
    - Rekap inspeksi P2H terbaru.
    """
    try:
        async with async_session() as db:
            # 1. Rekap Work Orders
            q_wo = """
                SELECT 
                    COUNT(*) as total_wo,
                    COUNT(*) FILTER (WHERE UPPER(status) NOT IN ('CLOSED', 'CANCELED', 'REJECTED')) as active_wo,
                    COUNT(*) FILTER (WHERE UPPER(status) = 'OPEN') as open_wo,
                    COUNT(*) FILTER (WHERE UPPER(status) = 'PROSES') as in_progress_wo,
                    COUNT(*) FILTER (WHERE UPPER(status) = 'READY_FOR_REINSPECTION') as reinspect_wo,
                    COUNT(*) FILTER (WHERE UPPER(status) = 'DISPENSATION_ACTIVE') as dispensation_wo,
                    COUNT(*) FILTER (WHERE UPPER(status) = 'CLOSED') as closed_wo
                FROM fleet.work_orders
            """
            res_wo = await db.execute(text(q_wo))
            wo_stats = res_wo.mappings().first()

            # 2. Rekap Kategori Perbaikan WO Aktif
            q_cat = """
                SELECT COALESCE(NULLIF(maint_category, ''), 'Lainnya') as category, COUNT(*) as cnt
                FROM fleet.work_orders
                WHERE UPPER(status) NOT IN ('CLOSED', 'CANCELED', 'REJECTED')
                GROUP BY 1
                ORDER BY cnt DESC
            """
            res_cat = await db.execute(text(q_cat))
            cat_rows = res_cat.mappings().all()

            # 3. Rekap Ban (Tires)
            q_tires = """
                SELECT 
                    COUNT(*) as total_tires,
                    COUNT(*) FILTER (WHERE UPPER(status) = 'MOUNTED') as mounted_tires,
                    COUNT(*) FILTER (WHERE UPPER(status) = 'STOCK') as stock_tires,
                    COUNT(*) FILTER (WHERE current_tread_depth_mm <= 3.0) as critical_tread_tires
                FROM fleet.tires
            """
            res_tires = await db.execute(text(q_tires))
            tire_stats = res_tires.mappings().first()

            # 4. Rekap Inspeksi P2H
            q_insp = """
                SELECT 
                    COUNT(*) as total_inspections,
                    COUNT(*) FILTER (WHERE defect_count > 0) as defect_inspections
                FROM fleet.vehicle_inspections
            """
            res_insp = await db.execute(text(q_insp))
            insp_stats = res_insp.mappings().first()

            lines = [
                "🛠️ RINGKASAN BENGKEL & PERAWATAN ARMADA (WORKSHOP OVERVIEW):",
                f"• Total SPK / Work Order   : {wo_stats['total_wo']} dokumen",
                f"• SPK Sedang Dikerjakan/Aktif: {wo_stats['active_wo']} unit dalam penanganan",
                f"  ├─ Open (Menunggu Antrean)  : {wo_stats['open_wo']} SPK",
                f"  ├─ Dalam Proses Pengerjaan  : {wo_stats['in_progress_wo']} SPK",
                f"  ├─ Siap Re-Inspeksi         : {wo_stats['reinspect_wo']} SPK",
                f"  ├─ Dispensasi Operasi Aktif : {wo_stats['dispensation_wo']} SPK",
                f"  └─ SPK Selesai (Closed)     : {wo_stats['closed_wo']} SPK",
                ""
            ]

            if cat_rows:
                cat_summary = ", ".join([f"{c['category']}: {c['cnt']}" for c in cat_rows])
                lines.append(f"• Kategori Servis Aktif   : {cat_summary}")

            lines.extend([
                "",
                "🛞 STATUS MANAJEMEN BAN (TIRES):",
                f"• Total Populasi Ban : {tire_stats['total_tires']} unit ban",
                f"• Ban Terpasang di Unit (Mounted) : {tire_stats['mounted_tires']} unit",
                f"• Ban Cadangan di Gudang (Stock)  : {tire_stats['stock_tires']} unit",
                f"• Ban Kritis (Tapak <= 3mm / Perlu Vulkanisir): {tire_stats['critical_tread_tires']} unit",
                "",
                "📋 STATUS INSPEKSI P2H (PRE-TRIP):",
                f"• Total Inspeksi Tercatat : {insp_stats['total_inspections']} kali",
                f"• Inspeksi dengan Temuan Cacat: {insp_stats['defect_inspections']} kali"
            ])

            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil ringkasan data bengkel & maintenance: {str(e)}"


async def get_work_orders(
    status: str | None = None,
    unit_id: str | None = None,
    maint_category: str | None = None,
    limit: int | None = 10
) -> str:
    """
    Mengambil daftar Surat Perintah Kerja (SPK / Work Orders) di bengkel.
    Args:
        status: Status SPK ('OPEN', 'PROSES', 'READY_FOR_REINSPECTION', 'DISPENSATION_ACTIVE', 'CLOSED').
        unit_id: Nomor polisi atau nomor unit armada (misal: 'A9357TY' atau 'A 9138 R').
        maint_category: Kategori perawatan ('Regular Repair', 'Corrective Repair (P2H)', 'Periodic Service', dsb.).
        limit: Batas data yang ditampilkan (default: 10, max: 25).
    """
    safe_limit = max(1, min(int(limit or 10), 25))
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": safe_limit}

            if status and status.strip():
                clean_status = status.strip().upper()
                if clean_status == "AKTIF":
                    conditions.append("UPPER(wo.status) NOT IN ('CLOSED', 'CANCELED', 'REJECTED')")
                else:
                    conditions.append("UPPER(wo.status) = :status")
                    params["status"] = clean_status

            if unit_id and unit_id.strip():
                clean_unit = unit_id.upper().replace(" ", "")
                conditions.append("UPPER(REPLACE(wo.unit_id, ' ', '')) LIKE :unit_id")
                params["unit_id"] = f"%{clean_unit}%"

            if maint_category and maint_category.strip():
                conditions.append("wo.maint_category ILIKE :maint_category")
                params["maint_category"] = f"%{maint_category.strip()}%"

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            q = f"""
                SELECT 
                    wo.id, wo.wo_no, wo.wo_date, wo.unit_id, wo.status, wo.problem, 
                    wo.cause, wo.keluhan_driver, wo.conclusion, wo.maint_category,
                    wo.mechanic_id, wo.kilometer, wo.promised_date,
                    COALESCE(k.nama_karyawan, wo.mechanic_id) as nama_mekanik
                FROM fleet.work_orders wo
                LEFT JOIN master.m_karyawan k ON k.payroll_id = wo.mechanic_id
                {where_clause}
                ORDER BY wo.wo_date DESC, wo.id DESC
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                filter_str = f" dengan kriteria status '{status}'" if status else ""
                filter_str += f" unit '{unit_id}'" if unit_id else ""
                return f"ℹ️ Tidak ditemukan data Work Order (SPK){filter_str}."

            lines = [
                f"📋 DAFTAR WORK ORDER / SPK BENGKEL (Menampilkan {len(rows)} data):",
                ""
            ]

            for r in rows:
                d_str = r["wo_date"].strftime("%d %b %Y") if isinstance(r["wo_date"], (date, datetime)) else str(r["wo_date"])
                p_date = f" | Est. Selesai: {r['promised_date'].strftime('%d %b %Y')}" if r["promised_date"] and isinstance(r["promised_date"], (date, datetime)) else ""
                prob = r["problem"] or r["keluhan_driver"] or "Pemeriksaan berkala"
                mekanik = r["nama_mekanik"] or "Belum ditugaskan"
                km_info = f" ({r['kilometer']:,} KM)" if r["kilometer"] else ""

                lines.append(
                    f"  • [{r['status']}] No. SPK: {r['wo_no']} | Unit: {r['unit_id']}{km_info}\n"
                    f"    Kategori: {r['maint_category'] or 'Umum'} | Tanggal: {d_str}{p_date}\n"
                    f"    Mekanik : {mekanik}\n"
                    f"    Kendala : {prob}"
                )
                if r["conclusion"]:
                    lines.append(f"    Tindakan: {r['conclusion']}")
                lines.append("")

            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil daftar Work Order: {str(e)}"


async def get_unit_maintenance_history(nopol: str) -> str:
    """
    Mengambil riwayat perbaikan, servis berkala, dan catatan bengkel lengkap untuk satu unit armada spesifik.
    Args:
        nopol: Nomor polisi unit (misal: 'A 9357 TY' atau 'A9138R').
    """
    clean_nopol = nopol.upper().replace(" ", "")
    try:
        async with async_session() as db:
            # 1. Info master unit
            q_unit = """
                SELECT id, no_unit, jenis_unit, kategori, asset_group, is_active
                FROM master.m_unit
                WHERE UPPER(REPLACE(no_unit, ' ', '')) = :nopol
                LIMIT 1
            """
            res_u = await db.execute(text(q_unit), {"nopol": clean_nopol})
            unit = res_u.mappings().first()

            # 2. Riwayat Work Orders unit
            q_wo = """
                SELECT 
                    wo.id, wo.wo_no, wo.wo_date, wo.status, wo.problem, wo.cause, 
                    wo.conclusion, wo.maint_category, wo.kilometer, wo.spareparts_used,
                    COALESCE(k.nama_karyawan, wo.mechanic_id) as nama_mekanik
                FROM fleet.work_orders wo
                LEFT JOIN master.m_karyawan k ON k.payroll_id = wo.mechanic_id
                WHERE UPPER(REPLACE(wo.unit_id, ' ', '')) = :nopol
                ORDER BY wo.wo_date DESC, wo.id DESC
                LIMIT 10
            """
            res_wo = await db.execute(text(q_wo), {"nopol": clean_nopol})
            wos = res_wo.mappings().all()

            # 3. Riwayat Inspeksi P2H unit
            q_insp = """
                SELECT inspection_no, inspection_date, inspection_type, defect_count, status, notes
                FROM fleet.vehicle_inspections
                WHERE UPPER(REPLACE(unit_id, ' ', '')) = :nopol
                ORDER BY inspection_date DESC
                LIMIT 5
            """
            res_insp = await db.execute(text(q_insp), {"nopol": clean_nopol})
            insps = res_insp.mappings().all()

            title_unit = unit["no_unit"] if unit else nopol
            tipe_unit = f" - {unit['jenis_unit']} ({unit['kategori'] or 'Truk'})" if unit else ""
            status_unit = "Aktif" if unit and unit["is_active"] else "Non-Aktif"

            lines = [
                f"🚛 RIWAYAT PERAWATAN & SERVIS UNIT: {title_unit}{tipe_unit}",
                f"• Status Master Unit : {status_unit}",
                f"• Total Histori SPK  : {len(wos)} riwayat ditemukan",
                ""
            ]

            if not wos:
                lines.append(f"ℹ️ Belum ada catatan Work Order / perbaikan bengkel untuk unit {title_unit}.")
            else:
                lines.append("🔧 Riwayat Pengerjaan Bengkel:")
                for w in wos:
                    d_str = w["wo_date"].strftime("%d %b %Y") if isinstance(w["wo_date"], (date, datetime)) else str(w["wo_date"])
                    prob = w["problem"] or "Pemeriksaan umum"
                    mekanik = w["nama_mekanik"] or "-"
                    lines.append(
                        f"  • [{w['status']}] SPK {w['wo_no']} ({d_str})\n"
                        f"    Kategori: {w['maint_category'] or 'Repair'} | Mekanik: {mekanik}\n"
                        f"    Kendala : {prob}"
                    )
                    if w["conclusion"]:
                        lines.append(f"    Hasil   : {w['conclusion']}")

            if insps:
                lines.append("\n📋 Riwayat Inspeksi Pra-Jalan (P2H):")
                for ins in insps:
                    i_date = ins["inspection_date"].strftime("%d %b %Y") if isinstance(ins["inspection_date"], (date, datetime)) else str(ins["inspection_date"])
                    defect_str = f" | Temuan Cacat: {ins['defect_count']}" if ins["defect_count"] else " | Lolos Cek"
                    lines.append(f"  • [{ins['status']}] {ins['inspection_no']} ({i_date}){defect_str}")

            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil riwayat perbaikan unit {nopol}: {str(e)}"


async def get_tire_inventory_and_condition(
    status: str | None = None,
    brand: str | None = None,
    only_critical: bool = False,
    limit: int | None = 10
) -> str:
    """
    Mengambil data inventaris ban armada, status pemakaian, dan ketebalan tapak ban.
    Args:
        status: Status ban ('MOUNTED', 'STOCK', 'RETREAD', 'SCRAP').
        brand: Merk ban yang dicari (misal: 'Bridgestone', 'Gajah Tunggal', 'Michelin').
        only_critical: Jika True, hanya menampilkan ban dengan tapak tipis (<= 3.0 mm) yang memerlukan perhatian.
        limit: Batas data (default: 10, max: 25).
    """
    safe_limit = max(1, min(int(limit or 10), 25))
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": safe_limit}

            if status and status.strip():
                conditions.append("UPPER(status) = :status")
                params["status"] = status.strip().upper()

            if brand and brand.strip():
                conditions.append("brand ILIKE :brand")
                params["brand"] = f"%{brand.strip()}%"

            if only_critical:
                conditions.append("current_tread_depth_mm <= 3.0")

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            # 1. Total statistics
            q_stats = """
                SELECT 
                    COUNT(*) as total_tires,
                    COUNT(*) FILTER (WHERE UPPER(status) = 'MOUNTED') as mounted,
                    COUNT(*) FILTER (WHERE UPPER(status) = 'STOCK') as stock,
                    COUNT(*) FILTER (WHERE current_tread_depth_mm <= 3.0) as critical
                FROM fleet.tires
            """
            res_stats = await db.execute(text(q_stats))
            stats = res_stats.mappings().first()

            # 2. List tires
            q_list = f"""
                SELECT 
                    id, serial_number, brand, size_spec, pattern_type, status, 
                    current_tread_depth_mm, original_tread_depth_mm, total_km_run, cost_per_km
                FROM fleet.tires
                {where_clause}
                ORDER BY current_tread_depth_mm ASC, id ASC
                LIMIT :limit
            """
            res_list = await db.execute(text(q_list), params)
            rows = res_list.mappings().all()

            lines = [
                "🛞 STATISTIK & INVENTARIS BAN ARMADA (TIRES):",
                f"• Total Populasi Ban : {stats['total_tires']} ban",
                f"• Terpasang di Unit  : {stats['mounted']} ban",
                f"• Stok Gudang        : {stats['stock']} ban",
                f"• Perlu Perhatian    : {stats['critical']} ban (Tapak <= 3mm)",
                ""
            ]

            if not rows:
                lines.append("ℹ️ Tidak ditemukan data ban yang sesuai filter.")
            else:
                filter_label = "Ban Kritis (Tapak Tipis):" if only_critical else f"Daftar Ban (Menampilkan {len(rows)} data):"
                lines.append(filter_label)
                for r in rows:
                    depth = float(r["current_tread_depth_mm"] or 0)
                    warn_tag = " ⚠️ [KRITIS / TIPIS]" if depth <= 3.0 else ""
                    km_run = f" | Total KM: {int(r['total_km_run']):,}" if r["total_km_run"] else ""
                    cpk = f" | CPK: Rp {float(r['cost_per_km']):,.0f}" if r["cost_per_km"] else ""
                    lines.append(
                        f"  • SN: {r['serial_number']} | Merk: {r['brand']} ({r['size_spec'] or '-'})\n"
                        f"    Status: {r['status']} | Tapak: {depth:.1f} mm{warn_tag}{km_run}{cpk}"
                    )

            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil data inventaris ban: {str(e)}"


async def get_spareparts_and_dn_usage(
    wo_no: str | None = None,
    target_unit: str | None = None,
    limit: int | None = 10
) -> str:
    """
    Mengambil data pemakaian suku cadang dan Surat Jalan / Delivery Note pengeluaran material bengkel.
    Args:
        wo_no: Nomor Work Order terkait (misal: '01427/WO/WSP/06/2026').
        target_unit: Nomor unit yang menerima suku cadang (misal: 'A9357TY').
        limit: Batas data (default: 10, max: 20).
    """
    safe_limit = max(1, min(int(limit or 10), 20))
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": safe_limit}

            if wo_no and wo_no.strip():
                conditions.append("h.wo_no ILIKE :wo_no")
                params["wo_no"] = f"%{wo_no.strip()}%"

            if target_unit and target_unit.strip():
                clean_unit = target_unit.upper().replace(" ", "")
                conditions.append("UPPER(REPLACE(h.target_unit, ' ', '')) LIKE :target_unit")
                params["target_unit"] = f"%{clean_unit}%"

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            q = f"""
                SELECT 
                    h.dn_no, h.dn_date, h.target_unit, h.wo_no, h.note, h.picked_by,
                    d.material_id, d.qty_actual, d.price, d.total
                FROM fleet.maintenance_dn_header h
                LEFT JOIN fleet.maintenance_dn_detail d ON d.dn_no = h.dn_no
                {where_clause}
                ORDER BY h.dn_date DESC, h.id DESC
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return "ℹ️ Tidak ditemukan catatan pengeluaran suku cadang / material yang sesuai kriteria."

            lines = [
                f"🔩 PEMAKAIAN SUKU CADANG & MATERIAL BENGKEL (Menampilkan {len(rows)} item):",
                ""
            ]

            total_biaya = sum(float(r["total"] or 0) for r in rows)

            for r in rows:
                d_date = r["dn_date"].strftime("%d %b %Y") if isinstance(r["dn_date"], (date, datetime)) else str(r["dn_date"])
                qty = r["qty_actual"] or 0
                price = float(r["price"] or 0)
                tot = float(r["total"] or 0)
                mat = r["material_id"] or "Material Umum"

                lines.append(
                    f"  • Surat Jalan: {r['dn_no']} ({d_date}) ➔ Unit: {r['target_unit'] or '-'}\n"
                    f"    No. SPK : {r['wo_no'] or '-'}\n"
                    f"    Part    : {mat} | Qty: {qty} | Biaya: Rp {tot:,.0f}"
                )

            if total_biaya > 0:
                lines.append(f"\n💰 Total Akumulasi Biaya Part Ditampilkan: Rp {total_biaya:,.0f}")

            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil data pemakaian suku cadang: {str(e)}"
