"""
DMS Tools — Document Management System Tools
─────────────────────────────────────────────────────────────
Tools untuk query data legalitas, arsip, dan masa berlaku dokumen:
- Dokumen Legalitas (dms.documents)
- Kategori & Tipe Dokumen (dms.m_doc_category, dms.m_doc_type)
- Lokasi Filing Fisik (dms.m_filing_location)
- Peringatan Jatuh Tempo / Expiry Monitoring (STNK, KIR, BPKB, SIM, Kontrak)

Digunakan oleh dms_agent.py (DIMAS).
"""

from datetime import datetime, date
from sqlalchemy import text
from app.database import async_session


def _normalize_entity_type(ent: str | None) -> str | None:
    """Menyelaraskan sinonim entitas ke standar enum database DMS."""
    if not ent:
        return None
    val = ent.strip().upper()
    if val in ("VEHICLE", "TRUCK", "UNIT", "ARMADA", "KENDARAAN", "FLEET"):
        return "FLEET"
    if val in ("SOPIR", "PENGEMUDI", "DRIVER", "KARYAWAN"):
        return "DRIVER"
    if val in ("PERUSAHAAN", "KORPORASI", "PT", "COMPANY", "CORPORATE"):
        return "CORPORATE"
    if val in ("PELANGGAN", "KUSTOMER", "CLIENT", "CUSTOMER"):
        return "CUSTOMER"
    if val in ("PEMASOK", "REKANAN", "VENDOR", "SUPPLIER"):
        return "VENDOR"
    if val in ("TANAH", "SERTIFIKAT", "LAND"):
        return "LAND"
    return val


async def get_dms_summary_stats() -> str:
    """
    Mengambil ringkasan statistik arsip & dokumen perusahaan:
    total dokumen, status aktif/expired, dan jumlah dokumen yang mendekati jatuh tempo (30/60/90 hari).
    """
    try:
        async with async_session() as db:
            q_stats = """
                SELECT 
                    COUNT(*) as total_docs,
                    COUNT(*) FILTER (WHERE UPPER(status) = 'ACTIVE') as active_docs,
                    COUNT(*) FILTER (WHERE UPPER(status) = 'EXPIRED' OR (expiry_date IS NOT NULL AND expiry_date < CURRENT_DATE)) as expired_docs,
                    COUNT(*) FILTER (WHERE expiry_date IS NOT NULL AND expiry_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days') as exp_30_days,
                    COUNT(*) FILTER (WHERE expiry_date IS NOT NULL AND expiry_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '60 days') as exp_60_days,
                    COUNT(*) FILTER (WHERE expiry_date IS NOT NULL AND expiry_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '90 days') as exp_90_days
                FROM dms.documents
            """
            res_stats = await db.execute(text(q_stats))
            row = res_stats.mappings().first()

            # Breakdown per entity type
            q_entities = """
                SELECT COALESCE(entity_type, 'LAINNYA') as ent, COUNT(*) as cnt
                FROM dms.documents
                GROUP BY entity_type
                ORDER BY cnt DESC
                LIMIT 6
            """
            res_ent = await db.execute(text(q_entities))
            ent_lines = [f"  • {r['ent']}: {r['cnt']:,} berkas" for r in res_ent.mappings().all()]

            lines = [
                f"📑 RINGKASAN ARSIP & DOKUMEN PT BCS LOGISTICS (DMS):",
                f"• Total Dokumen Tersimpan: {row['total_docs']:,} berkas",
                f"• Dokumen Berstatus Aktif: {row['active_docs']:,} berkas",
                f"• Dokumen Telah Kedaluwarsa: {row['expired_docs']:,} berkas",
                "",
                "⚠️ PERINGATAN MASA BERLAKU (JATUH TEMPO):",
                f"  🔴 Jatuh tempo dalam 30 hari ke depan : {row['exp_30_days']:,} dokumen",
                f"  🟡 Jatuh tempo dalam 60 hari ke depan : {row['exp_60_days']:,} dokumen",
                f"  🔵 Jatuh tempo dalam 90 hari ke depan : {row['exp_90_days']:,} dokumen",
                "",
                "📂 Distribusi Dokumen per Kategori Entitas:",
                *ent_lines,
                "",
                "💡 Gunakan tool 'get_expiring_documents' untuk melihat rincian dokumen yang segera kedaluwarsa."
            ]
            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mengambil statistik DMS: {str(e)}"


async def search_documents(
    keyword: str | None = None,
    entity_type: str | None = None,
    doc_type: str | None = None,
    status: str | None = None,
    limit: int = 15
) -> str:
    """
    Mencari dokumen berdasarkan kata kunci (nomor dokumen, nama, nopol, driver, atau judul), tipe entitas, atau tipe dokumen.
    Args:
        keyword: Kata kunci pencarian (misal: 'SIM', 'STNK', 'KIR', nama driver, atau nomor dokumen).
        entity_type: Tipe entitas ('FLEET', 'DRIVER', 'PARTNER', 'LAND', 'CORPORATE', 'VENDOR').
        doc_type: Nama tipe dokumen (misal: 'SIM Pengemudi', 'STNK', 'KIR').
        status: Status dokumen ('ACTIVE', 'EXPIRED', 'PENDING', 'ARCHIVED').
        limit: Batas hasil yang ditampilkan (default: 15).
    """
    try:
        async with async_session() as db:
            conditions = []
            params = {"limit": limit}

            if keyword:
                clean_kw = keyword.strip()
                tokens = [t.strip() for t in clean_kw.split() if t.strip() and t.lower() not in ("dokumen", "berkas", "cari", "truk", "unit", "untuk")]
                if not tokens:
                    tokens = [clean_kw]
                for idx, token in enumerate(tokens):
                    token_no_space = token.replace(" ", "")
                    conditions.append(
                        f"(d.doc_number ILIKE :t_{idx} OR d.title ILIKE :t_{idx} OR d.notes ILIKE :t_{idx} "
                        f"OR REPLACE(UPPER(d.title), ' ', '') ILIKE :t_ns_{idx} OR REPLACE(UPPER(d.doc_number), ' ', '') ILIKE :t_ns_{idx})"
                    )
                    params[f"t_{idx}"] = f"%{token}%"
                    params[f"t_ns_{idx}"] = f"%{token_no_space.upper()}%"

            normalized_entity = _normalize_entity_type(entity_type)
            if normalized_entity:
                conditions.append("UPPER(d.entity_type) = :entity_type")
                params["entity_type"] = normalized_entity

            if doc_type:
                conditions.append("t.name ILIKE :doc_type")
                params["doc_type"] = f"%{doc_type.strip()}%"
            if status:
                conditions.append("UPPER(d.status) = :status")
                params["status"] = status.strip().upper()

            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

            q = f"""
                SELECT 
                    d.id, d.doc_number, d.title, d.entity_type, d.issue_date, d.expiry_date,
                    d.status, d.physical_status,
                    t.name as type_name,
                    fl.name as filing_location_name
                FROM dms.documents d
                LEFT JOIN dms.m_doc_type t ON d.doc_type_id = t.id
                LEFT JOIN dms.m_filing_location fl ON d.filing_location_id = fl.id
                {where_clause}
                ORDER BY d.created_at DESC
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return f"ℹ️ Tidak ditemukan dokumen arsip yang sesuai dengan kriteria pencarian '{keyword or ''}'."

            lines = [
                f"🔍 HASIL PENCARIAN DOKUMEN ARSIP (Ditemukan {len(rows)} data):",
                ""
            ]

            today = date.today()

            for r in rows:
                exp_date = r["expiry_date"]
                if exp_date:
                    exp_str = exp_date.strftime("%d/%m/%Y")
                    if exp_date < today:
                        exp_label = f"🔴 KEDALUWARSA ({exp_str})"
                    else:
                        days_left = (exp_date - today).days
                        exp_label = f"🟢 Berlaku s/d {exp_str} ({days_left} hari lagi)"
                else:
                    exp_label = "⚪ Tanpa Masa Berlaku (Permanen)"

                loc_str = r["filing_location_name"] or "Belum Diatur"
                doc_no = r["doc_number"] or "-"
                type_name = r["type_name"] or r["entity_type"] or "Dokumen"

                lines.append(
                    f"  • [{type_name}] {r['title']}\n"
                    f"    No. Dokumen: {doc_no} | Status: {r['status']}\n"
                    f"    Masa Berlaku: {exp_label}\n"
                    f"    Lokasi Fisik: {loc_str}\n"
                )

            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal mencari dokumen: {str(e)}"


async def get_expiring_documents(days_ahead: int = 30, entity_type: str | None = None, limit: int = 15) -> str:
    """
    Mengambil daftar dokumen yang akan jatuh tempo / kedaluwarsa dalam jangka waktu tertentu (misal: 30 hari ke depan).
    Sangat berguna untuk alert kepatuhan KIR, STNK, SIM driver, dan perpanjangan lisensi.
    Args:
        days_ahead: Jumlah hari ke depan untuk monitoring (default: 30 hari).
        entity_type: Filter entitas jika perlu ('FLEET', 'DRIVER', 'CORPORATE', dll).
        limit: Batas hasil yang ditampilkan (default: 15).
    """
    try:
        async with async_session() as db:
            conditions = [
                "d.expiry_date IS NOT NULL",
                "d.expiry_date BETWEEN CURRENT_DATE AND CURRENT_DATE + (INTERVAL '1 day' * :days_ahead)",
                "UPPER(d.status) != 'EXPIRED'"
            ]
            params = {"days_ahead": days_ahead, "limit": limit}

            normalized_entity = _normalize_entity_type(entity_type)
            if normalized_entity:
                conditions.append("UPPER(d.entity_type) = :entity_type")
                params["entity_type"] = normalized_entity

            where_clause = "WHERE " + " AND ".join(conditions)

            q = f"""
                SELECT 
                    d.doc_number, d.title, d.entity_type, d.expiry_date,
                    t.name as type_name,
                    fl.name as filing_location_name,
                    (d.expiry_date - CURRENT_DATE) as days_remaining
                FROM dms.documents d
                LEFT JOIN dms.m_doc_type t ON d.doc_type_id = t.id
                LEFT JOIN dms.m_filing_location fl ON d.filing_location_id = fl.id
                {where_clause}
                ORDER BY d.expiry_date ASC
                LIMIT :limit
            """
            res = await db.execute(text(q), params)
            rows = res.mappings().all()

            if not rows:
                return f"✅ Aman! Tidak ada dokumen aktif yang akan kedaluwarsa dalam {days_ahead} hari ke depan."

            lines = [
                f"⚠️ DAFTAR DOKUMEN MENDEKATI JATUH TEMPO (< {days_ahead} Hari):",
                f"Total Terdeteksi: {len(rows)} dokumen mendesak perlu perpanjangan",
                ""
            ]

            for r in rows:
                exp_str = r["expiry_date"].strftime("%d %b %Y")
                days_left = r["days_remaining"]
                badge = "🔴 MENDESAK" if days_left <= 7 else ("🟠 PERHATIAN" if days_left <= 15 else "🟡 PERSIAPKAN")
                loc = r["filing_location_name"] or "Lokasi belum terdaftar"

                lines.append(
                    f"  • {badge} [{days_left} hari lagi: {exp_str}] {r['title']}\n"
                    f"    Nomor : {r['doc_number'] or '-'} | Jenis: {r['type_name'] or r['entity_type']}\n"
                    f"    Lokasi Arsip: {loc}\n"
                )

            return "\n".join(lines)
    except Exception as e:
        return f"❌ Gagal memuat daftar dokumen jatuh tempo: {str(e)}"


async def get_document_detail(doc_number_or_title: str) -> str:
    """
    Mengambil detail lengkap satu dokumen tertentu (termasuk metadata, legalitas, issuer, dan lokasi fisik arsip).
    """
    try:
        async with async_session() as db:
            clean = doc_number_or_title.strip()
            q = """
                SELECT 
                    d.id, d.doc_number, d.title, d.entity_type, d.issue_date, d.expiry_date,
                    d.status, d.physical_status, d.notes, d.metadata, d.file_path,
                    t.name as type_name, c.name as category_name,
                    fl.name as filing_location_name, fl.description as filing_desc
                FROM dms.documents d
                LEFT JOIN dms.m_doc_type t ON d.doc_type_id = t.id
                LEFT JOIN dms.m_doc_category c ON d.category_id = c.id
                LEFT JOIN dms.m_filing_location fl ON d.filing_location_id = fl.id
                WHERE d.doc_number ILIKE :q OR d.title ILIKE :q
                LIMIT 1
            """
            res = await db.execute(text(q), {"q": f"%{clean}%"})
            doc = res.mappings().first()

            if not doc:
                return f"❌ Dokumen dengan nomor atau judul '{doc_number_or_title}' tidak ditemukan."

            issue_str = doc["issue_date"].strftime("%d %B %Y") if doc["issue_date"] else "-"
            exp_str = doc["expiry_date"].strftime("%d %B %Y") if doc["expiry_date"] else "Permanen / Tidak Terbatas"

            notes_str = f"\nCatatan        : {doc['notes']}" if doc["notes"] else ""
            file_str = f"\nFile Lampiran  : {doc['file_path']}" if doc["file_path"] else ""

            return (
                f"📄 DETAIL DOKUMEN ARSIP: {doc['title']}\n"
                f"Nomor Dokumen  : {doc['doc_number'] or '-'}\n"
                f"Tipe Dokumen   : {doc['type_name'] or '-'}\n"
                f"Kategori       : {doc['category_name'] or doc['entity_type'] or '-'}\n"
                f"Status Berkas  : {doc['status']} (Fisik: {doc['physical_status'] or '-'})\n"
                f"Tanggal Terbit : {issue_str}\n"
                f"Jatuh Tempo    : {exp_str}\n"
                f"Lokasi Arsip   : {doc['filing_location_name'] or 'Belum Ditentukan'}\n"
                f"Detail Rak     : {doc['filing_desc'] or '-'}"
                f"{notes_str}"
                f"{file_str}"
            )
    except Exception as e:
        return f"❌ Gagal mengambil detail dokumen: {str(e)}"
