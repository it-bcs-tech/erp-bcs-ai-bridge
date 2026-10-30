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


async def get_sales_orders(status: str | None = None, limit: int | None = 10) -> str:
    """
    Mengambil daftar Sales Order (SO) komersial logistik.
    Args:
        status: Status SO ('CONFIRMED', 'DELIVERED', 'COMPLETED', 'DRAFT').
        limit: Batas data (default: 10, max: 25).
    """
    safe_limit = max(1, min(int(limit or 10), 25))
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": safe_limit}

            if status and status.strip():
                conditions.append("UPPER(so.status::text) = :status")
                params["status"] = status.strip().upper()

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            q = f"""
                SELECT 
                    so.id, so.jenis_muatan, so.berat_muatan, so.tariff, 
                    so.status, so.tgl_muat, so.created_at,
                    c.customer_name
                FROM marketing.sales_order so
                LEFT JOIN master.m_customer c ON so.customer_id = c.id
                {where_clause}
                ORDER BY so.created_at DESC NULLS LAST, so.id DESC
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return "ℹ️ Tidak ditemukan data Sales Order yang sesuai kriteria."

            lines = [f"📦 DAFTAR SALES ORDER (SO) ({len(rows)} ditemukan):"]
            for r in rows:
                d_str = r["tgl_muat"].strftime("%d %b %Y") if isinstance(r["tgl_muat"], (date, datetime)) else str(r["tgl_muat"] or "-")
                cust = r["customer_name"] or "Pelanggan Umum"
                tariff_val = float(r["tariff"] or 0)
                ton = float(r["berat_muatan"] or 0)
                lines.append(
                    f"• [{r['status']}] SO: {r['id']} — {cust}\n"
                    f"  Muatan: {r['jenis_muatan'] or '-'} ({ton:,.2f} Ton) | Tgl Muat: {d_str}\n"
                    f"  Tarif: Rp {tariff_val:,.2f}"
                )
            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil daftar sales order: {str(e)}"


async def get_commercial_contracts(status: str | None = None, limit: int | None = 10) -> str:
    """
    Mengambil data kontrak komersial pelanggan logistik.
    Args:
        status: Status kontrak ('ACTIVE', 'COMPLETED', 'EXPIRED').
        limit: Batas data (default: 10, max: 25).
    """
    safe_limit = max(1, min(int(limit or 10), 25))
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": safe_limit}

            if status and status.strip():
                conditions.append("UPPER(ct.status) = :status")
                params["status"] = status.strip().upper()

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            q = f"""
                SELECT 
                    ct.id, ct.status, ct.start_date, ct.end_date, ct.target_tonnage, 
                    ct.delivered_tonnage, ct.contract_value, ct.notes,
                    c.customer_name
                FROM marketing.contract ct
                LEFT JOIN master.m_customer c ON ct.customer_id = c.id
                {where_clause}
                ORDER BY ct.end_date DESC NULLS LAST
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return "ℹ️ Tidak ditemukan data kontrak komersial."

            lines = [f"📑 DAFTAR KONTRAK KOMERSIAL ({len(rows)} ditemukan):"]
            for r in rows:
                s_str = r["start_date"].strftime("%d %b %Y") if isinstance(r["start_date"], (date, datetime)) else str(r["start_date"] or "-")
                e_str = r["end_date"].strftime("%d %b %Y") if isinstance(r["end_date"], (date, datetime)) else str(r["end_date"] or "-")
                c_val = float(r["contract_value"] or 0)
                target_t = float(r["target_tonnage"] or 0)
                deliv_t = float(r["delivered_tonnage"] or 0)
                lines.append(
                    f"• [{r['status']}] Kontrak: {r['id']} — {r['customer_name'] or 'Customer'}\n"
                    f"  Nilai: Rp {c_val:,.2f} | Periode: {s_str} s/d {e_str}\n"
                    f"  Progres Tonase: {deliv_t:,.2f} / {target_t:,.2f} Ton"
                )
            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil data kontrak: {str(e)}"
