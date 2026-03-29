"""
Bazoš.cz scraper
Scrapuje bazos.cz - inzeráty s nemovitostmi.
POZNÁMKA: Bazoš nepoužívá API, scraping přes HTML.
Bazoš je tolerantní ke scrapingu (bez agresivního rate limitingu).
"""

import re
import hashlib
from typing import List, Optional
from urllib.parse import urljoin, quote

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper
from core.config import config
from utils.logger import get_logger

logger = get_logger(__name__)

BASE_URL = "https://reality.bazos.cz"

# URL segmenty pro dispozice na Bazoši
# Bazoš nemá přesný filtr dispozic - filtrujeme z textu
LOCATION_QUERY_MAP = {
    "Kladno": "Kladno",
    "Mělník": "M%C4%9Bln%C3%ADk",  # URL-encoded Mělník
    "Kralupy nad Vltavou": "Kralupy+nad+Vltavou",
}


class BazosScraper(BaseScraper):
    SOURCE_NAME = "bazos"

    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": "https://reality.bazos.cz/",
        })

    def fetch(self) -> List[dict]:
        results = []

        for location in config.LOCATIONS:
            location_results = self._fetch_location(location)
            results.extend(location_results)
            self._sleep()

        logger.info(f"[Bazoš] Celkem nalezeno: {len(results)}")
        return results

    def _fetch_location(self, location: str) -> List[dict]:
        """Stáhne inzeráty pro jednu lokalitu."""
        # Bazoš kategorie: byt (kategorie 105)
        # URL formát: https://reality.bazos.cz/byt/?hledat=Kladno&cenamax=5000000
        
        url = self._build_url(location)
        resp = self._get(url)
        if not resp:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        listings = []

        # Inzeráty na Bazoši jsou v .inzeraty nebo .maincontent
        items = soup.select(".inzeraty .inzerat, .maincontent .inzerat")
        
        if not items:
            # Alternativní selektory
            items = soup.select("article.inzerat, div[class*='inzerat']")

        if not items:
            logger.debug(f"[Bazoš] Žádné inzeráty pro {location} na: {url}")
            return []

        for item in items:
            listing = self._parse_item(item, location)
            if listing:
                listings.append(listing)

        logger.debug(f"[Bazoš] {location}: {len(listings)} inzerátů")
        return listings

    def _build_url(self, location: str) -> str:
        """Sestaví URL pro vyhledávání."""
        # Kategorie byty na Bazoši
        encoded_location = quote(location)
        return (
            f"{BASE_URL}/byt/"
            f"?hledat={encoded_location}"
            f"&cenamax={config.MAX_PRICE}"
            f"&order=&crz=0"
        )

    def _parse_item(self, item, location: str) -> Optional[dict]:
        """Parsuje jeden inzerát ze stránky."""
        try:
            # Název a odkaz
            title_el = item.select_one("h2 a, .nadpis a, a.nadpis")
            if not title_el:
                title_el = item.select_one("a[href*='/inzerce/']")
            
            if not title_el:
                return None

            title = title_el.get_text(strip=True)
            url = title_el.get("href", "")
            if not url.startswith("http"):
                url = urljoin(BASE_URL, url)

            # ID z URL
            listing_id = self._extract_id_from_url(url)
            if not listing_id:
                # Fallback: hash z URL
                listing_id = hashlib.md5(url.encode()).hexdigest()[:16]

            # Cena
            price = self._extract_price(item)
            if price and price > config.MAX_PRICE:
                return None

            # Dispozice z titulku/popisu
            disposition = self._extract_disposition(title)
            
            # Pokud nemáme dispozici z titulku, zkus popis
            if not disposition:
                desc_el = item.select_one(".popis, .text, p")
                desc_text = desc_el.get_text(strip=True) if desc_el else ""
                disposition = self._extract_disposition(desc_text)

            # Filtruj podle dispozice (jen pokud ji máme)
            if disposition and not self._is_valid_disposition(disposition):
                return None

            # Pokud nemáme žádnou dispozici, přeskočíme
            # (Bazoš má hodně smíšených inzerátů)
            if not disposition:
                logger.debug(f"[Bazoš] Inzerát bez rozpoznané dispozice: {title[:60]}")
                return None

            # Lokalita z inzerátu
            location_el = item.select_one(".lokace, .location, [class*='lokac']")
            location_str = location_el.get_text(strip=True) if location_el else ""
            
            # Ověření lokality
            if location_str and not self._is_valid_location(location_str):
                if not self._is_valid_location(location):
                    return None
            
            if not location_str or not self._is_valid_location(location_str):
                location_str = location

            # Popis
            desc_el = item.select_one(".popis, .text, p.popis")
            description = desc_el.get_text(strip=True) if desc_el else ""

            return {
                "listing_id": listing_id,
                "source": self.SOURCE_NAME,
                "url": url,
                "title": title,
                "price": price,
                "location": location_str,
                "description": description[:500],
                "disposition": disposition,
            }

        except Exception as e:
            logger.warning(f"[Bazoš] Chyba při parsování: {e}")
            return None

    def _extract_id_from_url(self, url: str) -> Optional[str]:
        """Extrahuje ID inzerátu z URL Bazoše."""
        # Formát: /inzerce/XXXXX/nazev-inzeratu/
        match = re.search(r"/inzerce/(\d+)/", url)
        if match:
            return match.group(1)
        match = re.search(r"/(\d{5,})/", url)
        if match:
            return match.group(1)
        return None

    def _extract_price(self, item) -> Optional[int]:
        """Extrahuje cenu z inzerátu."""
        price_el = item.select_one(".cena, [class*='price'], [class*='cena']")
        if not price_el:
            # Hledej text s Kč
            for el in item.find_all(string=re.compile(r"Kč|kč")):
                price_text = str(el)
                break
            else:
                return None
            price_el_text = price_text
        else:
            price_el_text = price_el.get_text(strip=True)

        digits = re.sub(r"[^\d]", "", price_el_text)
        if digits:
            price = int(digits)
            if 100_000 < price < 50_000_000:
                return price
        return None

    def _extract_disposition(self, text: str) -> Optional[str]:
        """Extrahuje dispozici z textu."""
        if not text:
            return None

        # Normalizace textu
        text_norm = text.replace(" ", "").lower()

        # Přesné shody dispozic
        disposition_patterns = {
            "2+kk": ["2+kk", "2kk", "dvoupokojový"],
            "2+1": ["2+1", "2pokoj"],
            "1+kk": ["1+kk", "1kk"],
            "1+1": ["1+1"],
            "3+kk": ["3+kk", "3kk"],
            "3+1": ["3+1"],
            "4+kk": ["4+kk", "4kk"],
            "4+1": ["4+1"],
        }

        for disp, patterns in disposition_patterns.items():
            for pattern in patterns:
                if pattern in text_norm:
                    return disp

        # Regex fallback
        match = re.search(r"(\d)[+](\d|kk)", text, re.IGNORECASE)
        if match:
            raw = match.group(0).lower().replace(" ", "")
            return raw if raw in [d.lower() for d in config.DISPOSITIONS] else None

        return None
