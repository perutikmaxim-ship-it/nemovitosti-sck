"""
scrapers/sreality.py – Scraper pro sreality.cz

Sreality.cz má neoficiální JSON API (používané jejich vlastní SPA).
Místo scrapingu HTML proto voláme přímo API endpoint.

API endpoint:
  https://www.sreality.cz/api/cs/v2/estates

Filtruje:
  - Typ: prodej domů (category_main_cb=2, category_type_cb=1)
  - Kraj: Středočeský – per district_id
  - Cena max: z configu
"""

import logging
import re
from typing import List, Optional

from scrapers.base import BaseScraper, Listing

logger = logging.getLogger(__name__)

SREALITY_API = "https://www.sreality.cz/api/cs/v2/estates"
CAT_MAIN_DOMY = 2
CAT_TYPE_PRODEJ = 1


def safe_int(value) -> Optional[int]:
    try:
        cleaned = str(value).replace(" ", "").replace("\u202f", "").replace(",", "")
        return int(float(cleaned))
    except (ValueError, TypeError):
        return None


def extract_text(obj) -> str:
    if isinstance(obj, dict):
        return obj.get("value", "") or obj.get("name", "") or ""
    return str(obj) if obj else ""


class SrealityScraper(BaseScraper):
    """Stahuje inzeráty ze sreality.cz přes neoficiální JSON API."""

    SOURCE_NAME = "sreality"

    def __init__(self, config: dict):
        super().__init__(config)
        self.district_ids = [d["sreality_id"] for d in config.get("districts", [])]
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.sreality.cz/hledani/prodej/domy/stredocesky-kraj",
            "Origin": "https://www.sreality.cz",
        })

    def _fetch_district(self, district_id: int) -> List[dict]:
        params = {
            "category_main_cb": CAT_MAIN_DOMY,
            "category_type_cb": CAT_TYPE_PRODEJ,
            "locality_district_id": district_id,
            "price_max": self.max_price,
            "no_auction": 1,
            "per_page": 20,
            "page": 1,
        }
        response = self.get(SREALITY_API, params=params)
        if response is None:
            return []
        try:
            data = response.json()
            return data.get("_embedded", {}).get("estates", []) or []
        except Exception as e:
            logger.error("[sreality] JSON parse chyba (district %s): %s", district_id, e)
            return []

    def _build_url(self, item: dict, external_id: str) -> str:
        seo = item.get("seo", {})
        main_map = {1: "byty", 2: "domy", 3: "pozemky", 4: "komercni"}
        type_map = {1: "prodej", 2: "pronajem"}
        if seo:
            main_slug = main_map.get(seo.get("category_main_cb", 2), "domy")
            type_slug = type_map.get(seo.get("category_type_cb", 1), "prodej")
            locality = seo.get("locality", "")
            if locality:
                return f"https://www.sreality.cz/detail/{main_slug}/{type_slug}/{locality}/{external_id}"
        return f"https://www.sreality.cz/detail/domy/prodej/dum/{external_id}"

    def _extract_area(self, item: dict) -> Optional[int]:
        for label in item.get("labels", []) or []:
            text = extract_text(label)
            if "m" in text.lower():
                m = re.search(r"(\d+)\s*m", text)
                if m:
                    return safe_int(m.group(1))
        title = extract_text(item.get("name", ""))
        m = re.search(r"(\d+)\s*m[²2]", title, re.IGNORECASE)
        return safe_int(m.group(1)) if m else None

    def _extract_image(self, item: dict) -> str:
        links = item.get("_links", {}) or {}
        for key in ("images", "image_middle", "image"):
            imgs = links.get(key, [])
            if isinstance(imgs, list) and imgs:
                first = imgs[0]
                if isinstance(first, dict):
                    return first.get("href", "")
            elif isinstance(imgs, dict):
                return imgs.get("href", "")
        return ""

    def _parse_listing(self, item: dict) -> Optional[Listing]:
        try:
            external_id = str(item.get("hash_id", "")).strip()
            if not external_id or external_id == "0":
                external_id = Listing.make_id(str(item))

            url = self._build_url(item, external_id)
            title = extract_text(item.get("name", "")) or "Rodinný dům"

            price = safe_int(item.get("price")) or safe_int(item.get("price_czk")) or None

            locality = extract_text(item.get("locality", ""))
            if not locality:
                seo_loc = item.get("seo", {}).get("locality", "")
                locality = seo_loc.replace("-", " ").title() if seo_loc else ""

            return Listing(
                source=self.SOURCE_NAME,
                external_id=external_id,
                url=url,
                title=title,
                price=price,
                location=locality,
                area_m2=self._extract_area(item),
                image_url=self._extract_image(item),
            )
        except Exception as e:
            logger.warning("[sreality] Parse chyba: %s", e)
            return None

    def fetch_listings(self) -> List[Listing]:
        all_listings: List[Listing] = []
        seen_ids: set = set()

        for district_id in self.district_ids:
            logger.debug("[sreality] Načítám okres ID: %s", district_id)
            for item in self._fetch_district(district_id):
                listing = self._parse_listing(item)
                if listing and listing.external_id not in seen_ids:
                    seen_ids.add(listing.external_id)
                    all_listings.append(listing)

        logger.info("[sreality] Celkem %d unikátních inzerátů", len(all_listings))
        return all_listings
