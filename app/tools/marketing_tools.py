"""
Marketing Tools — Commercial, Contracts, Deals & Sales Order Tools
──────────────────────────────────────────────────────────────────
Tools untuk query data komersial, kontrak logistik, dan sales order PT BCS Logistics:
- Sales Order Logistik (marketing.sales_order)
- Kontrak Komersial & Nilai Kontrak (marketing.contract)
- Pipeline Deals & Prospek Penjualan (marketing.deals)
- Analisis Pelanggan & Omzet Muatan (master.m_customer)

Digunakan oleh marketing_agent.py (MARKO).
"""

from datetime import datetime, date
from sqlalchemy import text
from app.database import async_session


def _parse_date_or_dt(val: str | None) -> tuple[datetime | None, date | None]:
    """Helper untuk mem-parsing string tanggal ke datetime dan date aman untuk asyncpg."""
    if not val or not str(val).strip():
        return None, None
    s = str(val).strip()
    try:
        dt = datetime.strptime(s[:10], "%Y-%m-%d")
        return dt, dt.date()
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(s)
        return dt, dt.date()
    except Exception:
        return None, None


async def get_marketing_overview() -> str:
    """
    Mengambil ringkasan data komersial marketing terkini:
    - Total Sales Order (SO) dan rekap status (Confirmed, Pending, In Transit, Completed)
    - Total Nilai Kontrak dan pemenuhan tonase (Target vs Realisasi)
    - Pipeline Deals prospek bisnis
    - Rekap tier pelanggan utama logistik.
    """
    try:
        async with async_session() as db:
            # 1. Rekap Sales Order
            q_so = """
                SELECT 
                    COUNT(*) as total_so,
                    COALESCE(SUM(tariff), 0) as total_tariff_value,
                    COALESCE(SUM(berat_muatan), 0) as total_tonnage,
                    COUNT(*) FILTER (WHERE UPPER(status::text) IN ('COMPLETED', 'DELIVERED')) as completed_so,
                    COUNT(*) FILTER (WHERE UPPER(status::text) NOT IN ('COMPLETED', 'DELIVERED', 'CANCELLED')) as active_so
                FROM marketing.sales_order
            """
            res_so = await db.execute(text(q_so))
            so_stats = res_so.mappings().first()

            # 2. Rekap Kontrak
            q_contract = """
                SELECT 
                    COUNT(*) as total_contracts,
                    COALESCE(SUM(contract_value), 0) as total_contract_value,
                    COALESCE(SUM(target_tonnage), 0) as total_target_tonnage,
                    COALESCE(SUM(delivered_tonnage), 0) as total_delivered_tonnage,
                    COUNT(*) FILTER (WHERE UPPER(status) = 'ACTIVE') as active_contracts
                FROM marketing.contract
            """
            res_contract = await db.execute(text(q_contract))
            c_stats = res_contract.mappings().first()

            # 3. Rekap Deals
            q_deals = """
                SELECT 
                    COUNT(*) as total_deals,
                    COALESCE(SUM(estimated_value), 0) as total_pipeline_value,
                    COUNT(*) FILTER (WHERE is_converted = true) as won_deals
                FROM marketing.deals
            """
            res_deals = await db.execute(text(q_deals))
            deal_stats = res_deals.mappings().first()

            so_val = float(so_stats["total_tariff_value"])
            so_ton = float(so_stats["total_tonnage"])
            c_val = float(c_stats["total_contract_value"])
            c_target = float(c_stats["total_target_tonnage"])
            c_deliv = float(c_stats["total_delivered_tonnage"])
            achievement_pct = round((c_deliv / c_target * 100), 2) if c_target > 0 else 0

            lines = [
                "📊 RINGKASAN KOMERSIAL & MARKETING (MARKETING OVERVIEW):",
                f"• Sales Order (SO) Logistik : {so_stats['total_so']} order terbit (Nilai Tarif: Rp {so_val:,.2f})",
                f"  ├─ Total Tonase Angkutan   : {so_ton:,.2f} Ton",
                f"  ├─ Order Aktif / Berjalan : {so_stats['active_so']} SO",
                f"  └─ Order Selesai Diterima : {so_stats['completed_so']} SO",
                "",
                f"• Kontrak Logistik Berjalan : {c_stats['total_contracts']} kontrak (Nilai: Rp {c_val:,.2f})",
                f"  ├─ Kontrak Aktif          : {c_stats['active_contracts']} kontrak",
                f"  ├─ Target Tonase Kontrak  : {c_target:,.2f} Ton",
                f"  ├─ Realisasi Muatan       : {c_deliv:,.2f} Ton",
                f"  └─ Persentase Pencapaian  : {achievement_pct}%",
                "",
                f"• Pipeline Deals Penjualan  : {deal_stats['total_deals']} prospek (Estimasi Nilai: Rp {float(deal_stats['total_pipeline_value']):,.2f})",
                f"  └─ Deals Berhasil Closed  : {deal_stats['won_deals']} deal terkonversi",
            ]
            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil ringkasan marketing: {str(e)}"


async def get_sales_orders(
    status: str | None = None,
    keyword: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    created_by: str | None = None,
    limit: int | None = 15,
) -> str:
    """
    Mengambil daftar Sales Order (SO) komersial logistik lengkap dengan filter waktu dan pembuat data.
    Args:
        status: Status SO ('CONFIRMED', 'DELIVERED', 'COMPLETED', 'DRAFT').
        keyword: Kata kunci nomor SO, nama pelanggan, atau jenis muatan.
        created_from: Tanggal awal filter input SO (format 'YYYY-MM-DD').
        created_to: Tanggal akhir filter input SO (format 'YYYY-MM-DD').
        created_by: Nama user pembuat SO (misal 'superhyperadmin', 'admin').
        limit: Batas data (default: 15, max: 30).
    """
    safe_limit = max(1, min(int(limit or 15), 30))
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": safe_limit}

            if status and status.strip():
                conditions.append("UPPER(so.status::text) = :status")
                params["status"] = status.strip().upper()

            if keyword and keyword.strip():
                conditions.append("(so.id ILIKE :kw OR so.jenis_muatan ILIKE :kw OR c.nama_kustomer ILIKE :kw)")
                params["kw"] = f"%{keyword.strip()}%"

            if created_from and str(created_from).strip():
                dt_from, d_from = _parse_date_or_dt(created_from)
                if dt_from:
                    conditions.append("(so.created_at >= :created_from_dt OR so.tgl_muat >= :created_from_dt)")
                    params["created_from_dt"] = dt_from

            if created_to and str(created_to).strip():
                dt_to, d_to = _parse_date_or_dt(created_to)
                if dt_to:
                    dt_to_end = datetime(dt_to.year, dt_to.month, dt_to.day, 23, 59, 59)
                    conditions.append("(so.created_at <= :created_to_dt OR so.tgl_muat <= :created_to_dt)")
                    params["created_to_dt"] = dt_to_end

            if created_by and str(created_by).strip():
                conditions.append("so.created_by ILIKE :created_by")
                params["created_by"] = f"%{str(created_by).strip()}%"

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            q = f"""
                SELECT 
                    so.id, so.jenis_muatan, so.berat_muatan, so.tariff, 
                    so.status, so.tgl_muat, so.created_at, so.created_by,
                    c.nama_kustomer as customer_name
                FROM marketing.sales_order so
                LEFT JOIN master.m_customer c ON so.customer_id = c.id
                {where_clause}
                ORDER BY COALESCE(so.created_at, so.tgl_muat::timestamp) DESC NULLS LAST, so.id DESC
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return "ℹ️ Tidak ditemukan data Sales Order yang sesuai kriteria pencarian."

            lines = [f"📦 DAFTAR SALES ORDER (SO) ({len(rows)} data ditemukan):"]
            for r in rows:
                d_str = r["tgl_muat"].strftime("%d %b %Y") if isinstance(r["tgl_muat"], (date, datetime)) else str(r["tgl_muat"] or "-")
                c_str = r["created_at"].strftime("%d/%m/%Y %H:%M") if isinstance(r["created_at"], (date, datetime)) else "-"
                creator = r["created_by"] or "System"
                cust = r["customer_name"] or "Pelanggan Umum"
                tariff_val = float(r["tariff"] or 0)
                ton = float(r["berat_muatan"] or 0)
                lines.append(
                    f"• [{r['status']}] No. SO: {r['id']} — {cust}\n"
                    f"  Muatan: {r['jenis_muatan'] or '-'} ({ton:,.2f} Ton) | Tarif: Rp {tariff_val:,.2f}\n"
                    f"  Tgl Muat: {d_str} | Dibuat: {c_str} (Oleh: {creator})"
                )
            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil daftar sales order: {str(e)}"


async def get_commercial_contracts(
    status: str | None = None,
    keyword: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    created_by: str | None = None,
    limit: int | None = 15,
) -> str:
    """
    Mengambil data kontrak komersial pelanggan logistik lengkap dengan target dan progres pemenuhan tonase.
    Args:
        status: Status kontrak ('ACTIVE', 'COMPLETED', 'EXPIRED').
        keyword: Kata kunci nomor kontrak, nama pelanggan, atau catatan.
        created_from: Tanggal awal filter input kontrak (format 'YYYY-MM-DD').
        created_to: Tanggal akhir filter input kontrak (format 'YYYY-MM-DD').
        created_by: Nama user pembuat kontrak.
        limit: Batas data (default: 15, max: 30).
    """
    safe_limit = max(1, min(int(limit or 15), 30))
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": safe_limit}

            if status and status.strip():
                conditions.append("UPPER(ct.status) = :status")
                params["status"] = status.strip().upper()

            if keyword and keyword.strip():
                conditions.append("(ct.id ILIKE :kw OR c.nama_kustomer ILIKE :kw OR ct.notes ILIKE :kw)")
                params["kw"] = f"%{keyword.strip()}%"

            if created_from and str(created_from).strip():
                dt_from, d_from = _parse_date_or_dt(created_from)
                if dt_from:
                    conditions.append("(ct.created_at >= :created_from_dt OR ct.start_date >= :created_from_d)")
                    params["created_from_dt"] = dt_from
                    params["created_from_d"] = d_from

            if created_to and str(created_to).strip():
                dt_to, d_to = _parse_date_or_dt(created_to)
                if dt_to:
                    dt_to_end = datetime(dt_to.year, dt_to.month, dt_to.day, 23, 59, 59)
                    conditions.append("(ct.created_at <= :created_to_dt OR ct.start_date <= :created_to_d)")
                    params["created_to_dt"] = dt_to_end
                    params["created_to_d"] = d_to

            if created_by and str(created_by).strip():
                conditions.append("ct.created_by ILIKE :created_by")
                params["created_by"] = f"%{str(created_by).strip()}%"

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            q = f"""
                SELECT 
                    ct.id, ct.status, ct.start_date, ct.end_date, ct.target_tonnage, 
                    ct.delivered_tonnage, ct.contract_value, ct.notes,
                    ct.created_at, ct.created_by,
                    c.nama_kustomer as customer_name
                FROM marketing.contract ct
                LEFT JOIN master.m_customer c ON ct.customer_id = c.id
                {where_clause}
                ORDER BY COALESCE(ct.created_at, ct.start_date::timestamp) DESC NULLS LAST, ct.end_date DESC NULLS LAST
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return "ℹ️ Tidak ditemukan data kontrak komersial yang sesuai."

            lines = [f"📑 DAFTAR KONTRAK KOMERSIAL ({len(rows)} data ditemukan):"]
            for r in rows:
                s_str = r["start_date"].strftime("%d %b %Y") if isinstance(r["start_date"], (date, datetime)) else str(r["start_date"] or "-")
                e_str = r["end_date"].strftime("%d %b %Y") if isinstance(r["end_date"], (date, datetime)) else str(r["end_date"] or "-")
                c_str = r["created_at"].strftime("%d/%m/%Y %H:%M") if isinstance(r["created_at"], (date, datetime)) else "-"
                creator = r["created_by"] or "System"
                c_val = float(r["contract_value"] or 0)
                target_t = float(r["target_tonnage"] or 0)
                deliv_t = float(r["delivered_tonnage"] or 0)
                pct = round((deliv_t / target_t * 100), 1) if target_t > 0 else 0
                lines.append(
                    f"• [{r['status']}] Kontrak: {r['id']} — {r['customer_name'] or 'Customer'}\n"
                    f"  Nilai: Rp {c_val:,.2f} | Periode: {s_str} s/d {e_str}\n"
                    f"  Realisasi Tonase: {deliv_t:,.2f} / {target_t:,.2f} Ton ({pct}% tercapai)\n"
                    f"  Dibuat: {c_str} (Oleh: {creator})"
                )
            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil data kontrak: {str(e)}"


async def get_marketing_deals(
    stage: str | None = None,
    keyword: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    created_by: str | None = None,
    limit: int | None = 15,
) -> str:
    """
    Mengambil data prospek peluang bisnis / deals penjualan.
    Args:
        stage: Tahap pipeline deal.
        keyword: Kata kunci nama perusahaan, contact person, atau proyek.
        created_from: Tanggal awal filter (format 'YYYY-MM-DD').
        created_to: Tanggal akhir filter (format 'YYYY-MM-DD').
        created_by: Nama pembuat prospek.
        limit: Batas data (default: 15).
    """
    safe_limit = max(1, min(int(limit or 15), 30))
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": safe_limit}

            if stage and stage.strip():
                conditions.append("UPPER(stage::text) = :stage")
                params["stage"] = stage.strip().upper()

            if keyword and keyword.strip():
                conditions.append("(company_name ILIKE :kw OR contact_person ILIKE :kw OR project_category ILIKE :kw)")
                params["kw"] = f"%{keyword.strip()}%"

            if created_from and str(created_from).strip():
                dt_from, d_from = _parse_date_or_dt(created_from)
                if dt_from:
                    conditions.append("created_at >= :created_from_dt")
                    params["created_from_dt"] = dt_from

            if created_to and str(created_to).strip():
                dt_to, d_to = _parse_date_or_dt(created_to)
                if dt_to:
                    dt_to_end = datetime(dt_to.year, dt_to.month, dt_to.day, 23, 59, 59)
                    conditions.append("created_at <= :created_to_dt")
                    params["created_to_dt"] = dt_to_end

            if created_by and str(created_by).strip():
                conditions.append("created_by ILIKE :created_by")
                params["created_by"] = f"%{str(created_by).strip()}%"

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            q = f"""
                SELECT 
                    id, company_name, contact_person, phone, project_category,
                    estimated_tonnage, estimated_value, stage, expected_date,
                    is_converted, created_at, created_by
                FROM marketing.deals
                {where_clause}
                ORDER BY created_at DESC NULLS LAST, id DESC
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return "ℹ️ Tidak ditemukan data pipeline deals yang sesuai kriteria."

            lines = [f"🤝 DAFTAR PIPELINE DEALS ({len(rows)} data ditemukan):"]
            for r in rows:
                val = float(r["estimated_value"] or 0)
                ton = float(r["estimated_tonnage"] or 0)
                exp_date_str = r["expected_date"].strftime("%d %b %Y") if isinstance(r["expected_date"], (date, datetime)) else "-"
                c_str = r["created_at"].strftime("%d/%m/%Y %H:%M") if isinstance(r["created_at"], (date, datetime)) else "-"
                creator = r["created_by"] or "System"
                conv_badge = " [WON/CONVERTED]" if r["is_converted"] else ""
                lines.append(
                    f"• [{r['stage']}{conv_badge}] {r['company_name']} ({r['project_category'] or 'Logistik'})\n"
                    f"  Estimasi Nilai: Rp {val:,.2f} | Potensi Tonase: {ton:,.2f} Ton\n"
                    f"  PIC: {r['contact_person'] or '-'} ({r['phone'] or '-'})\n"
                    f"  Target Closing: {exp_date_str} | Dibuat: {c_str} (Oleh: {creator})"
                )
            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil data deals: {str(e)}"
