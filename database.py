import os
import re
import csv
import io
import logging
from typing import List, Dict, Any, Optional
import aiosqlite

logger = logging.getLogger("UnifiedDatabase")

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

def normalize_text(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r"[^\w\s]", "", text.lower())
    return " ".join(clean.split())

def clean_phone_number(phone: str) -> str:
    if not phone:
        return ""
    digits = re.sub(r"[^\d]", "", phone)
    if digits.startswith("0") and len(digits) == 11:
        return "91" + digits[1:]
    elif len(digits) == 10:
        return "91" + digits
    return digits

class UnifiedDatabase:
    def __init__(self):
        self.is_pg = DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")
        self.pg_pool = None
        self.sqlite_path = "unified.db"

    async def init(self) -> None:
        if self.is_pg:
            import asyncpg
            url = DATABASE_URL.replace("postgres://", "postgresql://")
            # Supabase / Neon connection pool
            self.pg_pool = await asyncpg.create_pool(url, min_size=1, max_size=5)
            async with self.pg_pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS leads (
                        id SERIAL PRIMARY KEY,
                        place_id TEXT UNIQUE,
                        name TEXT NOT NULL,
                        normalized_name TEXT,
                        phone TEXT,
                        clean_phone TEXT,
                        rating REAL,
                        reviews INTEGER,
                        address TEXT,
                        website TEXT,
                        whatsapp_url TEXT,
                        niche TEXT,
                        city TEXT,
                        delivered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        user_id BIGINT,
                        demo_website_url TEXT,
                        demo_website_created_at TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_leads_clean_phone ON leads(clean_phone);
                    CREATE INDEX IF NOT EXISTS idx_leads_niche_city ON leads(niche, city);

                    CREATE TABLE IF NOT EXISTS generated_sites (
                        id SERIAL PRIMARY KEY,
                        business_name TEXT NOT NULL,
                        niche TEXT,
                        city TEXT,
                        phone TEXT,
                        clean_phone TEXT,
                        rating REAL,
                        reviews INTEGER,
                        address TEXT,
                        live_url TEXT NOT NULL,
                        pitch TEXT,
                        user_id BIGINT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_sites_phone ON generated_sites(clean_phone);
                """)
            logger.info("✅ Supabase/Postgres tables verified and ready.")
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS leads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        place_id TEXT UNIQUE,
                        name TEXT NOT NULL,
                        normalized_name TEXT,
                        phone TEXT,
                        clean_phone TEXT,
                        rating REAL,
                        reviews INTEGER,
                        address TEXT,
                        website TEXT,
                        whatsapp_url TEXT,
                        niche TEXT,
                        city TEXT,
                        delivered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        user_id INTEGER,
                        demo_website_url TEXT,
                        demo_website_created_at TIMESTAMP
                    )
                """)
                await db.execute("CREATE INDEX IF NOT EXISTS idx_leads_clean_phone ON leads(clean_phone)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_leads_niche_city ON leads(niche, city)")
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS generated_sites (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        business_name TEXT NOT NULL,
                        niche TEXT,
                        city TEXT,
                        phone TEXT,
                        clean_phone TEXT,
                        rating REAL,
                        reviews INTEGER,
                        address TEXT,
                        live_url TEXT NOT NULL,
                        pitch TEXT,
                        user_id INTEGER,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await db.execute("CREATE INDEX IF NOT EXISTS idx_sites_phone ON generated_sites(clean_phone)")
                await db.commit()
            logger.info("ℹ️ Using local SQLite database (unified.db).")

    # --- Leads methods ---
    async def filter_unseen_leads(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not candidates:
            return []
        place_ids = [c["place_id"] for c in candidates if c.get("place_id")]
        phones = [c["clean_phone"] for c in candidates if c.get("clean_phone")]
        if not place_ids and not phones:
            return candidates

        seen_pids = set()
        seen_phs = set()

        if self.is_pg:
            async with self.pg_pool.acquire() as conn:
                if place_ids:
                    rows = await conn.fetch("SELECT place_id FROM leads WHERE place_id = ANY($1)", place_ids)
                    for r in rows:
                        seen_pids.add(r["place_id"])
                if phones:
                    rows = await conn.fetch("SELECT clean_phone FROM leads WHERE clean_phone = ANY($1)", phones)
                    for r in rows:
                        seen_phs.add(r["clean_phone"])
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                if place_ids:
                    ph_marks = ",".join("?" * len(place_ids))
                    async with db.execute(f"SELECT place_id FROM leads WHERE place_id IN ({ph_marks})", place_ids) as cur:
                        async for row in cur:
                            seen_pids.add(row[0])
                if phones:
                    ph_marks = ",".join("?" * len(phones))
                    async with db.execute(f"SELECT clean_phone FROM leads WHERE clean_phone IN ({ph_marks})", phones) as cur:
                        async for row in cur:
                            seen_phs.add(row[0])

        fresh = []
        for c in candidates:
            if c.get("place_id") and c["place_id"] in seen_pids:
                continue
            if c.get("clean_phone") and c["clean_phone"] in seen_phs:
                continue
            fresh.append(c)
        return fresh

    async def save_leads(self, leads: List[Dict[str, Any]], user_id: int, niche: str, city: str) -> int:
        if not leads:
            return 0
        saved = 0
        if self.is_pg:
            async with self.pg_pool.acquire() as conn:
                for l in leads:
                    pid = l.get("place_id") or ""
                    name = l.get("name") or "Unknown"
                    phone = l.get("phone") or ""
                    c_phone = clean_phone_number(phone)
                    rating = l.get("rating")
                    reviews = l.get("reviews") or 0
                    address = l.get("address") or ""
                    website = l.get("website") or ""
                    wa_url = l.get("whatsapp_url") or ""
                    norm_name = normalize_text(name)

                    try:
                        row = await conn.fetchrow("""
                            INSERT INTO leads (
                                place_id, name, normalized_name, phone, clean_phone,
                                rating, reviews, address, website, whatsapp_url,
                                niche, city, delivered_at, user_id
                            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, CURRENT_TIMESTAMP, $13)
                            ON CONFLICT(place_id) DO UPDATE SET
                                name=EXCLUDED.name,
                                phone=EXCLUDED.phone,
                                clean_phone=EXCLUDED.clean_phone,
                                rating=EXCLUDED.rating,
                                reviews=EXCLUDED.reviews,
                                address=EXCLUDED.address
                            RETURNING id
                        """, pid, name, norm_name, phone, c_phone, rating, reviews, address, website, wa_url, niche, city, user_id)
                        if row:
                            l["db_id"] = row["id"]
                            l["lead_id"] = f"LEAD-{row['id']}"
                        saved += 1
                    except Exception as e:
                        logger.error(f"Error saving lead {name}: {e}")
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                for l in leads:
                    pid = l.get("place_id") or ""
                    name = l.get("name") or "Unknown"
                    phone = l.get("phone") or ""
                    c_phone = clean_phone_number(phone)
                    rating = l.get("rating")
                    reviews = l.get("reviews") or 0
                    address = l.get("address") or ""
                    website = l.get("website") or ""
                    wa_url = l.get("whatsapp_url") or ""
                    norm_name = normalize_text(name)

                    try:
                        cur = await db.execute("""
                            INSERT INTO leads (
                                place_id, name, normalized_name, phone, clean_phone,
                                rating, reviews, address, website, whatsapp_url,
                                niche, city, delivered_at, user_id
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                            ON CONFLICT(place_id) DO UPDATE SET
                                name=excluded.name,
                                phone=excluded.phone,
                                clean_phone=excluded.clean_phone,
                                rating=excluded.rating,
                                reviews=excluded.reviews,
                                address=excluded.address
                            RETURNING id
                        """, (pid, name, norm_name, phone, c_phone, rating, reviews, address, website, wa_url, niche, city, user_id))
                        row = await cur.fetchone()
                        if row:
                            l["db_id"] = row[0]
                            l["lead_id"] = f"LEAD-{row[0]}"
                        saved += 1
                    except Exception as e:
                        logger.error(f"Error saving lead {name}: {e}")
                await db.commit()
        return saved

    async def get_lead(self, identifier: Any) -> Optional[Dict[str, Any]]:
        id_str = str(identifier).strip()
        match = re.search(r"^(?:LEAD-?|#)?(\d+)$", id_str, re.IGNORECASE)
        lead_id = int(match.group(1)) if match else None
        clean_id = clean_phone_number(id_str) if any(c.isdigit() for c in id_str) else id_str

        if self.is_pg:
            async with self.pg_pool.acquire() as conn:
                if lead_id is not None:
                    row = await conn.fetchrow("SELECT * FROM leads WHERE id = $1 LIMIT 1", lead_id)
                    if row:
                        return dict(row)
                row = await conn.fetchrow("SELECT * FROM leads WHERE place_id = $1 OR clean_phone = $2 LIMIT 1", id_str, clean_id)
                return dict(row) if row else None
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                db.row_factory = aiosqlite.Row
                if lead_id is not None:
                    async with db.execute("SELECT * FROM leads WHERE id = ? LIMIT 1", (lead_id,)) as cur:
                        row = await cur.fetchone()
                        if row:
                            return dict(row)
                async with db.execute("SELECT * FROM leads WHERE place_id = ? OR clean_phone = ? LIMIT 1", (id_str, clean_id)) as cur:
                    row = await cur.fetchone()
                    return dict(row) if row else None

    async def update_demo_url(self, identifier: Any, demo_url: str) -> bool:
        id_str = str(identifier).strip()
        match = re.search(r"^(?:LEAD-?|#)?(\d+)$", id_str, re.IGNORECASE)
        lead_id = int(match.group(1)) if match else None
        clean_id = clean_phone_number(id_str) if any(c.isdigit() for c in id_str) else id_str

        if self.is_pg:
            async with self.pg_pool.acquire() as conn:
                if lead_id is not None:
                    await conn.execute("UPDATE leads SET demo_website_url = $1, demo_website_created_at = CURRENT_TIMESTAMP WHERE id = $2", demo_url, lead_id)
                else:
                    await conn.execute("UPDATE leads SET demo_website_url = $1, demo_website_created_at = CURRENT_TIMESTAMP WHERE place_id = $2 OR clean_phone = $3", demo_url, id_str, clean_id)
                return True
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                if lead_id is not None:
                    await db.execute("UPDATE leads SET demo_website_url = ?, demo_website_created_at = CURRENT_TIMESTAMP WHERE id = ?", (demo_url, lead_id))
                else:
                    await db.execute("UPDATE leads SET demo_website_url = ?, demo_website_created_at = CURRENT_TIMESTAMP WHERE place_id = ? OR clean_phone = ?", (demo_url, id_str, clean_id))
                await db.commit()
                return True

    async def get_lead_stats(self) -> Dict[str, Any]:
        if self.is_pg:
            async with self.pg_pool.acquire() as conn:
                r1 = await conn.fetchrow("SELECT COUNT(*) AS total, COUNT(DISTINCT clean_phone) AS phones FROM leads")
                total = r1["total"] if r1 else 0
                phones = r1["phones"] if r1 else 0
                top_niches = await conn.fetch("SELECT niche, COUNT(*) AS count FROM leads GROUP BY niche ORDER BY count DESC LIMIT 5")
                top_cities = await conn.fetch("SELECT city, COUNT(*) AS count FROM leads GROUP BY city ORDER BY count DESC LIMIT 5")
                return {
                    "total_leads": total,
                    "unique_phones": phones,
                    "top_niches": [(r["niche"], r["count"]) for r in top_niches],
                    "top_cities": [(r["city"], r["count"]) for r in top_cities],
                }
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                async with db.execute("SELECT COUNT(*), COUNT(DISTINCT clean_phone) FROM leads") as cur:
                    row = await cur.fetchone()
                    total = row[0] if row else 0
                    phones = row[1] if row else 0
                async with db.execute("SELECT niche, COUNT(*) FROM leads GROUP BY niche ORDER BY COUNT(*) DESC LIMIT 5") as cur:
                    top_niches = await cur.fetchall()
                async with db.execute("SELECT city, COUNT(*) FROM leads GROUP BY city ORDER BY COUNT(*) DESC LIMIT 5") as cur:
                    top_cities = await cur.fetchall()
                return {
                    "total_leads": total,
                    "unique_phones": phones,
                    "top_niches": top_niches,
                    "top_cities": top_cities,
                }

    async def export_leads_csv(self) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Lead ID", "Business Name", "Phone", "Rating", "Reviews", "Address", "Niche", "City", "WhatsApp Link", "Demo Website"])
        if self.is_pg:
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM leads ORDER BY id DESC")
                for r in rows:
                    writer.writerow([
                        f"LEAD-{r['id']}", r['name'], r['phone'], r['rating'], r['reviews'],
                        r['address'], r['niche'], r['city'], r['whatsapp_url'], r['demo_website_url'] or ''
                    ])
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM leads ORDER BY id DESC") as cur:
                    async for r in cur:
                        writer.writerow([
                            f"LEAD-{r['id']}", r['name'], r['phone'], r['rating'], r['reviews'],
                            r['address'], r['niche'], r['city'], r['whatsapp_url'], r['demo_website_url'] or ''
                        ])
        return output.getvalue()

    # --- Generated Sites methods ---
    async def save_site(self, business: Dict[str, Any], live_url: str, pitch: str, user_id: int) -> int:
        name = business.get("name", "Unknown")
        niche = business.get("niche", "Services")
        city = business.get("city", "")
        phone = business.get("phone", "")
        clean_ph = clean_phone_number(phone)
        rating = business.get("rating")
        reviews = business.get("reviews")
        address = business.get("address", "")

        if self.is_pg:
            async with self.pg_pool.acquire() as conn:
                row = await conn.fetchrow("""
                    INSERT INTO generated_sites (
                        business_name, niche, city, phone, clean_phone,
                        rating, reviews, address, live_url, pitch, user_id
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    RETURNING id
                """, name, niche, city, phone, clean_ph, rating, reviews, address, live_url, pitch, user_id)
                return row["id"] if row else 0
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                cur = await db.execute("""
                    INSERT INTO generated_sites (
                        business_name, niche, city, phone, clean_phone,
                        rating, reviews, address, live_url, pitch, user_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (name, niche, city, phone, clean_ph, rating, reviews, address, live_url, pitch, user_id))
                await db.commit()
                return cur.lastrowid or 0

    async def get_recent_sites(self, limit: int = 8) -> List[Dict[str, Any]]:
        if self.is_pg:
            async with self.pg_pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM generated_sites ORDER BY created_at DESC LIMIT $1", limit)
                return [dict(r) for r in rows]
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT * FROM generated_sites ORDER BY created_at DESC LIMIT ?", (limit,)) as cur:
                    rows = await cur.fetchall()
                    return [dict(r) for r in rows]

    async def get_site_stats(self) -> Dict[str, Any]:
        if self.is_pg:
            async with self.pg_pool.acquire() as conn:
                r1 = await conn.fetchrow("SELECT COUNT(*) AS total FROM generated_sites")
                total = r1["total"] if r1 else 0
                top_n = await conn.fetch("SELECT niche, COUNT(*) AS count FROM generated_sites GROUP BY niche ORDER BY count DESC LIMIT 5")
                top_c = await conn.fetch("SELECT city, COUNT(*) AS count FROM generated_sites GROUP BY city ORDER BY count DESC LIMIT 5")
                return {
                    "total_sites": total,
                    "top_niches": [(r["niche"], r["count"]) for r in top_n],
                    "top_cities": [(r["city"], r["count"]) for r in top_c],
                }
        else:
            async with aiosqlite.connect(self.sqlite_path) as db:
                async with db.execute("SELECT COUNT(*) FROM generated_sites") as cur:
                    row = await cur.fetchone()
                    total = row[0] if row else 0
                async with db.execute("SELECT niche, COUNT(*) FROM generated_sites GROUP BY niche ORDER BY COUNT(*) DESC LIMIT 5") as cur:
                    top_n = await cur.fetchall()
                async with db.execute("SELECT city, COUNT(*) FROM generated_sites GROUP BY city ORDER BY COUNT(*) DESC LIMIT 5") as cur:
                    top_c = await cur.fetchall()
                return {
                    "total_sites": total,
                    "top_niches": top_n,
                    "top_cities": top_c,
                }

unified_db = UnifiedDatabase()
