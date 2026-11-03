"""
QHSE Tools — Quality, Health, Safety, and Environment System Tools
───────────────────────────────────────────────────────────────────
Tools untuk query data keselamatan kerja (K3), insiden, dan mutu PT BCS Logistics:
- Laporan Insiden & Kecelakaan Kerja (qhse.incidents)
- Safety Briefing & Tool Box Meeting (qhse.safety_briefings)
- Distribusi Alat Pelindung Diri / APD (qhse.apd_distributions)
- Laporan Temuan Proaktif K3 / Near-Miss (qhse.proactive_reports)
- Keluhan Mutu Pelanggan / Customer Complaints (qhse.customer_complaints)

Digunakan oleh qhse_agent.py (QISHA).
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


async def get_qhse_overview() -> str:
    """
    Mengambil ringkasan data K3 (Keselamatan & Kesehatan Kerja), Lingkungan, dan Mutu terkini:
    - Rekap insiden/kecelakaan kerja berdasarkan tingkat keparahan (Severity)
    - Pelaksanaan Safety Briefing & jumlah peserta
    - Distribusi APD (Alat Pelindung Diri) ke karyawan/supir
    - Laporan temuan K3 proaktif (Near-miss, Unsafe Action/Condition)
    - Keluhan mutu pelanggan (Customer Complaints).
    """
    try:
        async with async_session() as db:
            # 1. Rekap Insiden
            q_inc = """
                SELECT 
                    COUNT(*) as total_incidents,
                    COUNT(*) FILTER (WHERE UPPER(severity) IN ('HIGH', 'FATAL', 'MAJOR')) as high_severity,
                    COUNT(*) FILTER (WHERE UPPER(severity) IN ('MEDIUM', 'MODERATE')) as med_severity,
                    COUNT(*) FILTER (WHERE UPPER(severity) IN ('LOW', 'MINOR')) as low_severity
                FROM qhse.incidents
            """
            res_inc = await db.execute(text(q_inc))
            inc_stats = res_inc.mappings().first()

            # 2. Rekap Safety Briefings
            q_sb = """
                SELECT 
                    COUNT(*) as total_briefings,
                    COALESCE(SUM(participant_count), 0) as total_participants
                FROM qhse.safety_briefings
            """
            res_sb = await db.execute(text(q_sb))
            sb_stats = res_sb.mappings().first()

            # 3. Rekap APD
            q_apd = """
                SELECT 
                    COUNT(*) as total_distributions,
                    COALESCE(SUM(quantity), 0) as total_items_issued
                FROM qhse.apd_distributions
            """
            res_apd = await db.execute(text(q_apd))
            apd_stats = res_apd.mappings().first()

            # 4. Rekap Temuan Proaktif K3
            q_pro = """
                SELECT 
                    COUNT(*) as total_proactive,
                    COUNT(*) FILTER (WHERE UPPER(risk_level) = 'HIGH') as high_risk_findings,
                    COUNT(*) FILTER (WHERE UPPER(status) = 'OPEN') as open_findings
                FROM qhse.proactive_reports
            """
            res_pro = await db.execute(text(q_pro))
            pro_stats = res_pro.mappings().first()

            # 5. Rekap Keluhan Pelanggan
            q_comp = """
                SELECT 
                    COUNT(*) as total_complaints,
                    COUNT(*) FILTER (WHERE UPPER(status) IN ('OPEN', 'INVESTIGATING')) as active_complaints
                FROM qhse.customer_complaints
            """
            res_comp = await db.execute(text(q_comp))
            comp_stats = res_comp.mappings().first()

            lines = [
                "🛡️ RINGKASAN QHSE, K3 & MUTU (SAFETY OVERVIEW):",
                f"• Insiden Keselamatan Kerja: {inc_stats['total_incidents']} insiden tercatat",
                f"  ├─ Tingkat Tinggi (High/Major): {inc_stats['high_severity']} kejadian",
                f"  ├─ Tingkat Sedang (Medium)    : {inc_stats['med_severity']} kejadian",
                f"  └─ Tingkat Rendah (Low/Minor) : {inc_stats['low_severity']} kejadian",
                "",
                f"• Safety Briefing / TBM     : {sb_stats['total_briefings']} sesi (Total {sb_stats['total_participants']} peserta diedukasi)",
                f"• Distribusi APD Karyawan   : {apd_stats['total_distributions']} distribusi ({apd_stats['total_items_issued']} unit APD disalurkan)",
                f"• Laporan K3 Proaktif       : {pro_stats['total_proactive']} laporan temuan",
                f"  ├─ Resiko Tinggi (High)    : {pro_stats['high_risk_findings']} temuan",
                f"  └─ Masih Terbuka (Open)    : {pro_stats['open_findings']} tindakan CAPA berjalan",
                f"• Keluhan Mutu Pelanggan    : {comp_stats['total_complaints']} keluhan ({comp_stats['active_complaints']} dalam investigasi)",
            ]
            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil ringkasan QHSE: {str(e)}"


async def get_incident_records(
    severity: str | None = None,
    keyword: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    created_by: str | None = None,
    limit: int | None = 15,
) -> str:
    """
    Mengambil data riwayat insiden / kecelakaan kerja armada dan lapangan lengkap dengan filter waktu dan pembuat data.
    """
    safe_limit = max(1, min(int(limit or 15), 30))
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": safe_limit}

            if severity and severity.strip():
                conditions.append("severity ILIKE :sev")
                params["sev"] = f"%{severity.strip()}%"

            if keyword and keyword.strip():
                conditions.append("(incident_number ILIKE :kw OR location ILIKE :kw OR description ILIKE :kw OR root_cause_analysis ILIKE :kw)")
                params["kw"] = f"%{keyword.strip()}%"

            if date_from and str(date_from).strip():
                dt_from, d_from = _parse_date_or_dt(date_from)
                if dt_from:
                    conditions.append("(incident_date >= :date_from_dt OR created_at >= :date_from_dt)")
                    params["date_from_dt"] = dt_from

            if date_to and str(date_to).strip():
                dt_to, d_to = _parse_date_or_dt(date_to)
                if dt_to:
                    dt_to_end = datetime(dt_to.year, dt_to.month, dt_to.day, 23, 59, 59)
                    conditions.append("(incident_date <= :date_to_dt OR created_at <= :date_to_dt)")
                    params["date_to_dt"] = dt_to_end

            if created_by and str(created_by).strip():
                conditions.append("created_by ILIKE :created_by")
                params["created_by"] = f"%{str(created_by).strip()}%"

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            q = f"""
                SELECT 
                    incident_number, incident_date, incident_type, severity, 
                    location, description, root_cause_analysis, corrective_action, preventive_action,
                    created_at, created_by
                FROM qhse.incidents
                {where_clause}
                ORDER BY COALESCE(incident_date, created_at) DESC NULLS LAST, id DESC
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return "ℹ️ Tidak ditemukan catatan insiden keselamatan kerja yang cocok."

            lines = [f"⚠️ RIWAYAT INSIDEN KESELAMATAN KERJA ({len(rows)} data ditemukan):"]
            for r in rows:
                d_str = r["incident_date"].strftime("%d %b %Y %H:%M") if isinstance(r["incident_date"], (date, datetime)) else str(r["incident_date"] or "-")
                c_str = r["created_at"].strftime("%d/%m/%Y %H:%M") if isinstance(r["created_at"], (date, datetime)) else "-"
                creator = r["created_by"] or "QHSE Officer"
                lines.append(
                    f"• [{r['severity']}] No: {r['incident_number']} ({d_str}) — Tipe: {r['incident_type'] or 'Umum'}\n"
                    f"  Lokasi: {r['location'] or '-'} | Dibuat: {c_str} (Oleh: {creator})\n"
                    f"  Deskripsi: {r['description'] or '-'}\n"
                    f"  Akar Masalah: {r['root_cause_analysis'] or '-'}\n"
                    f"  Tindakan Korektif (CAPA): {r['corrective_action'] or '-'}"
                )
            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil data insiden: {str(e)}"


async def get_proactive_safety_reports(
    risk_level: str | None = None,
    keyword: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    created_by: str | None = None,
    limit: int | None = 15,
) -> str:
    """
    Mengambil data temuan keselamatan proaktif (near-miss, kondisi berbahaya, tindakan tidak aman).
    """
    safe_limit = max(1, min(int(limit or 15), 30))
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": safe_limit}

            if risk_level and risk_level.strip():
                conditions.append("risk_level ILIKE :risk")
                params["risk"] = f"%{risk_level.strip()}%"

            if keyword and keyword.strip():
                conditions.append("(report_number ILIKE :kw OR location ILIKE :kw OR finding_description ILIKE :kw OR observer_name ILIKE :kw)")
                params["kw"] = f"%{keyword.strip()}%"

            if date_from and str(date_from).strip():
                dt_from, d_from = _parse_date_or_dt(date_from)
                if dt_from:
                    conditions.append("(date >= :date_from_dt OR created_at >= :date_from_dt)")
                    params["date_from_dt"] = dt_from

            if date_to and str(date_to).strip():
                dt_to, d_to = _parse_date_or_dt(date_to)
                if dt_to:
                    dt_to_end = datetime(dt_to.year, dt_to.month, dt_to.day, 23, 59, 59)
                    conditions.append("(date <= :date_to_dt OR created_at <= :date_to_dt)")
                    params["date_to_dt"] = dt_to_end

            if created_by and str(created_by).strip():
                conditions.append("created_by ILIKE :created_by")
                params["created_by"] = f"%{str(created_by).strip()}%"

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            q = f"""
                SELECT 
                    report_number, report_type, date, location, observer_name, 
                    finding_description, risk_level, status, capa_action,
                    created_at, created_by
                FROM qhse.proactive_reports
                {where_clause}
                ORDER BY COALESCE(date, created_at) DESC NULLS LAST, id DESC
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return "ℹ️ Tidak ditemukan laporan temuan keselamatan proaktif."

            lines = [f"🔍 LAPORAN TEMUAN K3 PROAKTIF ({len(rows)} data ditemukan):"]
            for r in rows:
                d_str = r["date"].strftime("%d %b %Y") if isinstance(r["date"], (date, datetime)) else str(r["date"] or "-")
                c_str = r["created_at"].strftime("%d/%m/%Y %H:%M") if isinstance(r["created_at"], (date, datetime)) else "-"
                creator = r["created_by"] or r["observer_name"] or "Officer"
                lines.append(
                    f"• [{r['risk_level']}] {r['report_number']} ({d_str}) — {r['report_type'] or 'Hazard'}\n"
                    f"  Lokasi: {r['location'] or '-'} | Dibuat: {c_str} (Oleh: {creator})\n"
                    f"  Temuan: {r['finding_description'] or '-'}\n"
                    f"  Status: {r['status'] or 'Open'} | Tindakan: {r['capa_action'] or '-'}"
                )
            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil laporan proaktif: {str(e)}"


async def get_customer_complaints(
    status: str | None = None,
    keyword: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    created_by: str | None = None,
    limit: int | None = 15,
) -> str:
    """
    Mengambil data keluhan mutu dan operasional dari pelanggan (Customer Complaints).
    """
    safe_limit = max(1, min(int(limit or 15), 30))
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": safe_limit}

            if status and status.strip():
                conditions.append("status ILIKE :st")
                params["st"] = f"%{status.strip()}%"

            if keyword and keyword.strip():
                conditions.append("(complaint_number ILIKE :kw OR customer_name ILIKE :kw OR description ILIKE :kw)")
                params["kw"] = f"%{keyword.strip()}%"

            if date_from and str(date_from).strip():
                dt_from, d_from = _parse_date_or_dt(date_from)
                if d_from:
                    conditions.append("(date >= :date_from_d OR created_at::date >= :date_from_d)")
                    params["date_from_d"] = d_from

            if date_to and str(date_to).strip():
                dt_to, d_to = _parse_date_or_dt(date_to)
                if d_to:
                    conditions.append("(date <= :date_to_d OR created_at::date <= :date_to_d)")
                    params["date_to_d"] = d_to

            if created_by and str(created_by).strip():
                conditions.append("created_by ILIKE :created_by")
                params["created_by"] = f"%{str(created_by).strip()}%"

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            q = f"""
                SELECT 
                    complaint_number, customer_name, date, issue_category, 
                    description, investigation_result, car_action, status,
                    created_at, created_by
                FROM qhse.customer_complaints
                {where_clause}
                ORDER BY COALESCE(date, created_at::date) DESC NULLS LAST, id DESC
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return "ℹ️ Tidak ada keluhan mutu pelanggan yang tercatat."

            lines = [f"📢 KELUHAN MUTU PELANGGAN ({len(rows)} data ditemukan):"]
            for r in rows:
                d_str = r["date"].strftime("%d %b %Y") if isinstance(r["date"], (date, datetime)) else str(r["date"] or "-")
                c_str = r["created_at"].strftime("%d/%m/%Y %H:%M") if isinstance(r["created_at"], (date, datetime)) else "-"
                creator = r["created_by"] or "Customer Service"
                lines.append(
                    f"• [{r['status']}] {r['complaint_number']} ({d_str}) — Pelanggan: {r['customer_name'] or '-'}\n"
                    f"  Kategori: {r['issue_category'] or 'Umum'} | Dibuat: {c_str} (Oleh: {creator})\n"
                    f"  Keluhan: {r['description'] or '-'}\n"
                    f"  Hasil Investigasi: {r['investigation_result'] or 'Dalam proses'}"
                )
            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil data keluhan pelanggan: {str(e)}"
