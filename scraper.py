import os
import logging
from typing import List, Dict, Any, Optional
import httpx

from database import unified_db, clean_phone_number

logger = logging.getLogger("LeadScraper")

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

def has_website(url: Optional[str]) -> bool:
    if not url:
        return False
    u = url.strip().lower()
    return bool(u and u not in ["none", "n/a", "null", ""])

class SerpApiScraper:
    def __init__(self, db=unified_db):
        self.db = db

    async def fetch_fresh_leads(
        self,
        niche: str,
        city: str,
        count: int = 10,
        min_rating: Optional[float] = None,
        max_rating: Optional[float] = None,
        min_reviews: Optional[int] = None,
        max_reviews: Optional[int] = None,
        require_phone: bool = True,
        require_no_website: bool = True,
    ) -> List[Dict[str, Any]]:
        api_key = os.getenv("SERPAPI_KEY", SERPAPI_KEY)
        if not api_key:
            raise ValueError("SERPAPI_KEY environment variable is not configured.")

        collected_leads: List[Dict[str, Any]] = []
        page_offset = 0
        search_query = f"{niche} in {city}".strip()
        max_pages = 5

        async with httpx.AsyncClient(timeout=25.0) as client:
            for page in range(max_pages):
                if len(collected_leads) >= count:
                    break

                params = {
                    "engine": "google_maps",
                    "q": search_query,
                    "api_key": api_key,
                    "type": "search",
                    "start": page_offset,
                }

                logger.info(f"Searching SerpAPI: '{search_query}' (page {page + 1}, start={page_offset})")

                try:
                    resp = await client.get("https://serpapi.com/search.json", params=params)
                    if resp.status_code != 200:
                        logger.error(f"SerpAPI error {resp.status_code}: {resp.text}")
                        break
                    data = resp.json()
                except Exception as e:
                    logger.error(f"Request error calling SerpAPI: {e}")
                    break

                if "error" in data:
                    logger.error(f"SerpAPI Error: {data['error']}")
                    break

                local_results = data.get("local_results", [])
                if not local_results:
                    break

                page_candidates: List[Dict[str, Any]] = []
                for item in local_results:
                    name = item.get("title", "").strip()
                    phone = item.get("phone", "").strip()
                    place_id = item.get("place_id") or item.get("data_id") or ""
                    rating = item.get("rating")
                    reviews = item.get("reviews") or 0
                    address = item.get("address", "").strip()
                    website = item.get("website", "").strip()

                    clean_ph = clean_phone_number(phone)
                    if require_phone and not clean_ph:
                        continue
                    if require_no_website and has_website(website):
                        continue

                    if rating is not None:
                        if min_rating is not None and rating < min_rating:
                            continue
                        if max_rating is not None and rating > max_rating:
                            continue

                    if min_reviews is not None and reviews < min_reviews:
                        continue
                    if max_reviews is not None and reviews > max_reviews:
                        continue

                    whatsapp_url = f"https://wa.me/{clean_ph}" if clean_ph else ""

                    lead = {
                        "place_id": place_id,
                        "name": name,
                        "phone": phone,
                        "clean_phone": clean_ph,
                        "rating": rating,
                        "reviews": reviews,
                        "address": address,
                        "website": website,
                        "whatsapp_url": whatsapp_url,
                        "niche": niche,
                        "city": city,
                    }
                    page_candidates.append(lead)

                fresh_page_leads = await self.db.filter_unseen_leads(page_candidates)

                for lead in fresh_page_leads:
                    collected_leads.append(lead)
                    if len(collected_leads) >= count:
                        break

                page_offset += 20

        return collected_leads
