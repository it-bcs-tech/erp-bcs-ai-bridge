"""
Finance Tools — Financial & Kasir Accounting System Tools
─────────────────────────────────────────────────────────
Tools untuk query data keuangan, kasir, dan penagihan PT BCS Logistics:
- Faktur & Piutang / Invoicing (finance.invoice)
- Uang Jalan Operasional / Cash Advance UJO Driver (finance.cash_advance)
- Buku Kas Kasir / Kas Kecil (finance.kasir_cash_ledger)
- Surat Jalan Penagihan / Delivery Notes (finance.dn_header)
- Riwayat Pembayaran (finance.payment)

Digunakan oleh finance_agent.py (FINA).
"""

from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import text
from app.database import async_session


async def get_finance_overview() -> str:
    """
    Mengambil ringkasan data keuangan, piutang invoice, UJO driver, dan mutasi kasir terkini:
    - Total invoice dan total tagihan (total_amount)
    - Status invoice (Draft, Posted, Paid, dll.)
    - Rekap UJO driver cash advance (total dana jalan, status pembayaran)
    - Mutasi kas kasir (kas masuk vs keluar).
    """
    try:
        async with async_session() as db:
            # 1. Rekap Invoicing
            q_inv = """
                SELECT 
                    COUNT(*) as total_invoices,
                    COALESCE(SUM(total_amount), 0) as total_billing,
                    COUNT(*) FILTER (WHERE UPPER(status::text) = 'PAID') as paid_count,
                    COUNT(*) FILTER (WHERE UPPER(status::text) IN ('POSTED', 'OPEN', 'UNPAID')) as unpaid_count,
                    COALESCE(SUM(total_amount) FILTER (WHERE UPPER(status::text) IN ('POSTED', 'OPEN', 'UNPAID')), 0) as outstanding_amount
                FROM finance.invoice
            """
            res_inv = await db.execute(text(q_inv))
            inv_stats = res_inv.mappings().first()

            # 2. Rekap UJO Cash Advance
            q_ca = """
                SELECT 
                    COUNT(*) as total_ca,
                    COALESCE(SUM(estimated_ujo), 0) as total_ujo_budget,
                    COALESCE(SUM(ujo_makan), 0) as total_ujo_makan,
                    COALESCE(SUM(ujo_tol), 0) as total_ujo_tol,
                    COALESCE(SUM(extra_cost), 0) as total_extra_cost,
                    COUNT(*) FILTER (WHERE UPPER(payment_status) = 'PAID') as ca_paid_count,
                    COUNT(*) FILTER (WHERE UPPER(payment_status) != 'PAID') as ca_pending_count
                FROM finance.cash_advance
            """
            res_ca = await db.execute(text(q_ca))
            ca_stats = res_ca.mappings().first()

            # 3. Rekap Kasir Cash Ledger
            q_kasir = """
                SELECT 
                    COUNT(*) as total_trx,
                    COALESCE(SUM(amount) FILTER (WHERE UPPER(direction) = 'IN'), 0) as cash_in,
                    COALESCE(SUM(amount) FILTER (WHERE UPPER(direction) = 'OUT'), 0) as cash_out
                FROM finance.kasir_cash_ledger
            """
            res_kasir = await db.execute(text(q_kasir))
            kasir_stats = res_kasir.mappings().first()

            total_billing = float(inv_stats["total_billing"])
            outstanding = float(inv_stats["outstanding_amount"])
            total_ujo = float(ca_stats["total_ujo_budget"])
            cash_in = float(kasir_stats["cash_in"])
            cash_out = float(kasir_stats["cash_out"])
            kas_net = cash_in - cash_out

            lines = [
                "💰 RINGKASAN KEUANGAN & KASIR (FINANCE OVERVIEW):",
                f"• Total Invoice Terbit   : {inv_stats['total_invoices']} dokumen (Rp {total_billing:,.2f})",
                f"  ├─ Sudah Lunas (Paid)   : {inv_stats['paid_count']} invoice",
                f"  ├─ Belum Lunas (Unpaid) : {inv_stats['unpaid_count']} invoice",
                f"  └─ Piutang Berjalan     : Rp {outstanding:,.2f}",
                "",
                f"• Uang Jalan Driver (UJO): {ca_stats['total_ca']} trip tercatat",
                f"  ├─ Total Anggaran UJO   : Rp {total_ujo:,.2f}",
                f"  ├─ Komponen Uang Makan  : Rp {float(ca_stats['total_ujo_makan']):,.2f}",
                f"  ├─ Komponen Tol         : Rp {float(ca_stats['total_ujo_tol']):,.2f}",
                f"  ├─ Biaya Tambahan/Extra : Rp {float(ca_stats['total_extra_cost']):,.2f}",
                f"  └─ Status Pembayaran    : {ca_stats['ca_paid_count']} Lunas / {ca_stats['ca_pending_count']} Menunggu",
                "",
                f"• Mutasi Kasir / Kas Kecil:",
                f"  ├─ Total Kas Masuk (IN) : Rp {cash_in:,.2f}",
                f"  ├─ Total Kas Keluar(OUT): Rp {cash_out:,.2f}",
                f"  └─ Saldo Kas Bersih     : Rp {kas_net:,.2f}",
            ]
            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil ringkasan keuangan: {str(e)}"


async def get_invoices(status: str | None = None, limit: int | None = 10) -> str:
    """
    Mengambil daftar invoice / faktur penagihan pelanggan.
    Args:
        status: Status invoice ('PAID', 'POSTED', 'DRAFT', 'OPEN').
        limit: Batas data (default: 10, max: 25).
    """
    safe_limit = max(1, min(int(limit or 10), 25))
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": safe_limit}

            if status and status.strip():
                conditions.append("UPPER(status::text) = :status")
                params["status"] = status.strip().upper()

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            q = f"""
                SELECT 
                    id, invoice_number, type, date, due_date, currency, 
                    subtotal, tax_amount, total_amount, status, reference, notes
                FROM finance.invoice
                {where_clause}
                ORDER BY date DESC NULLS LAST, id DESC
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return "ℹ️ Tidak ditemukan data invoice yang sesuai kriteria."

            lines = [f"📑 DAFTAR INVOICE KEUANGAN ({len(rows)} ditemukan):"]
            for r in rows:
                d_str = r["date"].strftime("%d %b %Y") if isinstance(r["date"], (date, datetime)) else str(r["date"] or "-")
                due_str = r["due_date"].strftime("%d %b %Y") if isinstance(r["due_date"], (date, datetime)) else str(r["due_date"] or "-")
                tot = float(r["total_amount"] or 0)
                curr = r["currency"] or "IDR"
                lines.append(
                    f"• [{r['status']}] No: {r['invoice_number']} | Tgl: {d_str} (Jatuh Tempo: {due_str})\n"
                    f"  Nilai: {curr} {tot:,.2f} | Tipe: {r['type'] or 'Standard'} | Ref: {r['reference'] or '-'}"
                )
            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil daftar invoice: {str(e)}"


async def get_cash_advances(payment_status: str | None = None, limit: int | None = 10) -> str:
    """
    Mengambil daftar Uang Jalan Operasional (UJO / Cash Advance) untuk supir trip.
    Args:
        payment_status: Status pembayaran ('PAID', 'PENDING', 'UNPAID').
        limit: Batas data (default: 10, max: 25).
    """
    safe_limit = max(1, min(int(limit or 10), 25))
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": safe_limit}

            if payment_status and payment_status.strip():
                conditions.append("UPPER(payment_status) = :payment_status")
                params["payment_status"] = payment_status.strip().upper()

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            q = f"""
                SELECT 
                    id, trip_id, sales_order_id, estimated_ujo, ujo_makan, 
                    ujo_tol, extra_cost, extra_cost_desc, payment_status, created_at
                FROM finance.cash_advance
                {where_clause}
                ORDER BY created_at DESC NULLS LAST
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return "ℹ️ Tidak ditemukan data cash advance UJO."

            lines = [f"🚚 DAFTAR UANG JALAN OPERASIONAL (UJO) ({len(rows)} ditemukan):"]
            for r in rows:
                c_str = r["created_at"].strftime("%d %b %Y") if isinstance(r["created_at"], (date, datetime)) else str(r["created_at"] or "-")
                ujo_val = float(r["estimated_ujo"] or 0)
                makan_val = float(r["ujo_makan"] or 0)
                tol_val = float(r["ujo_tol"] or 0)
                lines.append(
                    f"• [Trip #{r['trip_id'] or '-'}] Status UJO: {r['payment_status']} (Tgl: {c_str})\n"
                    f"  Total UJO: Rp {ujo_val:,.2f} (Makan: Rp {makan_val:,.2f}, Tol: Rp {tol_val:,.2f}) | SO: {r['sales_order_id'] or '-'}"
                )
            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil data cash advance: {str(e)}"


async def get_kasir_ledger(direction: str | None = None, category: str | None = None, limit: int | None = 10) -> str:
    """
    Mengambil mutasi transaksi buku kas kasir / kas kecil.
    Args:
        direction: Arah kas ('IN' untuk masuk, 'OUT' untuk keluar).
        category: Kategori pengeluaran/pemasukan.
        limit: Batas data (default: 10, max: 25).
    """
    safe_limit = max(1, min(int(limit or 10), 25))
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": safe_limit}

            if direction and direction.strip():
                conditions.append("UPPER(direction) = :direction")
                params["direction"] = direction.strip().upper()

            if category and category.strip():
                conditions.append("category ILIKE :category")
                params["category"] = f"%{category.strip()}%"

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            q = f"""
                SELECT 
                    id, transaction_date, direction, category, amount, 
                    reference_id, description, performed_by
                FROM finance.kasir_cash_ledger
                {where_clause}
                ORDER BY transaction_date DESC NULLS LAST
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return "ℹ️ Tidak ditemukan mutasi transaksi kasir."

            lines = [f"💵 MUTASI BUKU KAS KASIR ({len(rows)} transaksi):"]
            for r in rows:
                d_str = r["transaction_date"].strftime("%d %b %Y %H:%M") if isinstance(r["transaction_date"], (date, datetime)) else str(r["transaction_date"] or "-")
                amt = float(r["amount"] or 0)
                sign = "+" if r["direction"] == "IN" else "-"
                lines.append(
                    f"• [{r['direction']}] {d_str} — {sign}Rp {amt:,.2f} ({r['category'] or 'Umum'})\n"
                    f"  Ket: {r['description'] or '-'} | Pelaksana: {r['performed_by'] or '-'}"
                )
            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil mutasi kasir: {str(e)}"
