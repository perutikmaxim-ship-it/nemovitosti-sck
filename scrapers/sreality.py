"""
Sreality.cz scraper
Používá neoficiální JSON API, které Sreality využívá pro svůj frontend.
Endpoint: https://www.sreality.cz/api/cs/v2/estates
"""

from typing import List, Optional

from scrapers.base import BaseScraper
from core.config import config
from utils.logger import get_logger

logger = get_logger(__name__)

SREALITY_API = "https://www.sreality.cz/api/cs/v2/estates"

# Kategorie: 1 = byt, 2 = dům, 3 = pozemek...
CATEGORY_MAIN = 1  # byty

# Typ transakce: 1 = prodej, 2 = pronájem
CATEGORY_TYPE = 1  # prodej

# Dispozice kódy pro Sreality API
DISPOSITION_MAP = {
    "1+kk": 1,
    "1+1": 2,
    "2+kk": 3,
    "2+1": 4,
    "3+kk": 5,
    "3+1": 6,
    "4+kk": 7,
    "4+1": 8,
    "5+kk": 9,
    "5+1": 10,
    "6+": 11,
    "atypický": 12,
}


class SrealityScraper(BaseScraper):
    SOURCE_NAME = "sreality"

    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": "https://www.sreality.cz/",
            "Accept": "application/json, text/plain, */*",
        })

    def _get_disposition_codes(self) -> List[int]:
        """Vrátí seznam kódů dispozic pro API dotaz."""
        codes = []
        for disp in config.DISPOSITIONS:
            code = DISPOSITION_MAP.get(disp)
            if code:
                codes.append(code)
        return codes

    def fetch(self) -> List[dict]:
        results = []

        for location in config.LOCATIONS:
            logger.debug(f"[Sreality] Hledám v: {location}")
            page_results = self._fetch_location(location)
            results.extend(page_results)
            self._sleep()

        logger.info(f"[Sreality] Celkem nalezeno: {len(results)}")
        return results

    def _fetch_location(self, location: str) -> List[dict]:
        """Stáhne inzeráty pro jednu lokalitu."""
        disposition_codes = self._get_disposition_codes()
        
        params = {
            "category_main_cb": CATEGORY_MAIN,
            "category_type_cb": CATEGORY_TYPE,
            "locality_region_id": self._get_region_id(location),
            "price_max": config.MAX_PRICE,
            "per_page": 60,
            "page": 1,
        }

        # Přidej dispozice jako opakující se parametr
        if disposition_codes:
            # Sreality bere category_sub_cb jako seznam
            params["category_sub_cb"] = "|".join(str(c) for c in disposition_codes)

        # Alternativní přístup přes locality_district_id nebo textové hledání
        # Použijeme locality search parametr
        params_with_locality = {
            "category_main_cb": CATEGORY_MAIN,
            "category_type_cb": CATEGORY_TYPE,
            "price_max": config.MAX_PRICE,
            "per_page": 60,
            "locality_district_id": self._get_district_id(location),
        }
        if disposition_codes:
            params_with_locality["category_sub_cb"] = "|".join(str(c) for c in disposition_codes)

        resp = self._get(SREALITY_API, params=params_with_locality)
        if not resp:
            return []

        try:
            data = resp.json()
        except ValueError:
            logger.error(f"[Sreality] Neplatná JSON odpověď pro lokalitu {location}")
            return []

        estates = data.get("_embedded", {}).get("estates", [])
        logger.debug(f"[Sreality] {location}: {len(estates)} výsledků")

        listings = []
        for estate in estates:
            listing = self._parse_estate(estate, location)
            if listing:
                listings.append(listing)

        return listings

    def _parse_estate(self, estate: dict, location_hint: str) -> Optional[dict]:
        """Parsuje jeden inzerát ze Sreality API."""
        try:
            estate_id = str(estate.get("hash_id", ""))
            if not estate_id:
                return None

            # Název inzerátu
            name = estate.get("name", {})
            title = name if isinstance(name, str) else name.get("value", "Byt")

            # Cena
            price_raw = estate.get("price", 0)
            price = int(price_raw) if price_raw else None

            # Ověření ceny
            if price and price > config.MAX_PRICE:
                return None

            # Lokalita
            locality = estate.get("locality", {})
            location_str = locality if isinstance(locality, str) else locality.get("value", location_hint)

            # Ověření lokality
            if not self._is_valid_location(location_str):
                # Zkus location_hint jako fallback
                if not self._is_valid_location(location_hint):
                    return None
                location_str = location_hint

            # URL
            seo = estate.get("seo", {})
            locality_seo = seo.get("locality", "")
            url = f"https://www.sreality.cz/detail/prodej/byt/{estate_id}/{locality_seo}"

            # Dispozice z názvu nebo labels
            labels = estate.get("labels", [])
            disposition = self._extract_disposition(title, labels)

            if disposition and not self._is_valid_disposition(disposition):
                return None

            # Popis (Sreality API základní endpoint nemá popis, jen metadata)
            description = ""
            if "locality" in estate:
                loc_val = estate["locality"]
                if isinstance(loc_val, dict):
                    description = loc_val.get("value", "")

            return {
                "listing_id": estate_id,
                "source": self.SOURCE_NAME,
                "url": url,
                "title": title,
                "price": price,
                "location": location_str,
                "description": description,
                "disposition": disposition,
            }

        except Exception as e:
            logger.warning(f"[Sreality] Chyba při parsování inzerátu: {e}")
            return None

    def _extract_disposition(self, title: str, labels: list) -> Optional[str]:
        """Pokusí se extrahovat dispozici z titulku nebo labels."""
        # Hledej v titulku
        for disp in config.DISPOSITIONS:
            if disp.lower() in title.lower():
                return disp

        # Hledej v labels
        for label in labels:
            label_text = label if isinstance(label, str) else label.get("name", "")
            for disp in config.DISPOSITIONS:
                if disp.lower() in label_text.lower():
                    return disp

        return None

    def _get_district_id(self, location: str) -> int:
        """
        Vrátí ID okresu pro Sreality API.
        Sreality používá číselné ID pro okresy.
        """
        district_map = {
            "Kladno": 5105,           # okres Kladno
            "Mělník": 5110,           # okres Mělník
            "Kralupy nad Vltavou": 5105,  # součást okresu Kladno
        }
        return district_map.get(location, 5105)

    def _get_region_id(self, location: str) -> int:
        """Vrátí ID kraje (Středočeský = 8)."""
        return 8
