"""
iDnes Reality scraper
Scrapuje reality.idnes.cz pomocí BeautifulSoup.
POZNÁMKA: iDnes Reality používá statické HTML, scraping je možný.
"""

import re
from typing import List, Optional
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper
from core.config import config
from utils.logger import get_logger

logger = get_logger(__name__)

BASE_URL = "https://reality.idnes.cz"

# Mapování lokalit na URL segmenty pro iDnes
LOCATION_SLUGS = {
    "Kladno": "kladno",
    "Mělník": "melnik",
    "Kralupy nad Vltavou": "kralupy-nad-vltavou",
}

# Dispozice v URL parametrech iDnes
DISPOSITION_SLUGS = {
    "2+kk": "2-kk",
    "2+1": "2-1",
    "1+kk": "1-kk",
    "1+1": "1-1",
    "3+kk": "3-kk",
    "3+1": "3-1",
}


class IdnesScraper(BaseScraper):
    SOURCE_NAME = "idnes"

    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Referer": "https://reality.idnes.cz/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    def fetch(self) -> List[dict]:
        results = []

        for location in config.LOCATIONS:
            slug = LOCATION_SLUGS.get(location)
            if not slug:
                logger.warning(f"[iDnes] Neznámá lokalita: {location}, přeskakuji")
                continue

            location_results = self._fetch_location(location, slug)
            results.extend(location_results)
            self._sleep()

        logger.info(f"[iDnes] Celkem nalezeno: {len(results)}")
        return results

    def _fetch_location(self, location: str, slug: str) -> List[dict]:
        """Stáhne inzeráty pro jednu lokalitu."""
        # Sestavení dispozičních filtrů
        disposition_slugs = [
            DISPOSITION_SLUGS[d]
            for d in config.DISPOSITIONS
            if d in DISPOSITION_SLUGS
        ]

        listings = []

        # Stáhneme pro každou dispozici zvlášť (iDnes to tak vyžaduje v URL)
        for disp_slug in disposition_slugs or [None]:
            url = self._build_url(slug, disp_slug)
            page_listings = self._fetch_page(url, location)
            listings.extend(page_listings)

            if disp_slug:
                self._sleep()

        return listings

    def _build_url(self, location_slug: str, disposition_slug: Optional[str] = None) -> str:
        """Sestaví URL pro hledání."""
        if disposition_slug:
            url = f"{BASE_URL}/s/prodej/byty/{disposition_slug}/{location_slug}/"
        else:
            url = f"{BASE_URL}/s/prodej/byty/{location_slug}/"

        params = {
            "price-max": config.MAX_PRICE,
        }
        return f"{url}?{urlencode(params)}"

    def _fetch_page(self, url: str, location: str) -> List[dict]:
        """Stáhne a parsuje jednu stránku výsledků."""
        resp = self._get(url)
        if not resp:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        listings = []

        # iDnes Reality - inzeráty jsou v article nebo div.c-products__item
        items = soup.select(".c-products__item, article.c-product")
        
        if not items:
            # Zkus alternativní selektor
            items = soup.select("[data-dot='ogm-reality-list'] .c-product")
        
        if not items:
            logger.debug(f"[iDnes] Žádné inzeráty nalezeny na: {url}")
            return []

        for item in items:
            listing = self._parse_item(item, location)
            if listing:
                listings.append(listing)

        logger.debug(f"[iDnes] {location}: {len(listings)} inzerátů z {url}")
        return listings

    def _parse_item(self, item, location: str) -> Optional[dict]:
        """Parsuje jeden inzerát ze stránky."""
        try:
            # URL a ID
            link_el = item.select_one("a.c-product__link, a[href*='/detail/']")
            if not link_el:
                link_el = item.select_one("a[href]")
            
            if not link_el:
                return None

            url = link_el.get("href", "")
            if not url.startswith("http"):
                url = urljoin(BASE_URL, url)

            # Vyřaď pronájmy podle URL (iDnes má /pronajem/ v cestě)
            if "/pronajem/" in url or "/najem/" in url:
                return None

            # ID z URL
            listing_id = self._extract_id_from_url(url)
            if not listing_id:
                return None

            # Název
            title_el = item.select_one(".c-product__title, h2, h3")
            title = title_el.get_text(strip=True) if title_el else "Byt"

            # Vyřaď pronájmy podle klíčových slov v titulku
            RENTAL_KEYWORDS = ["pronájem", "pronajmu", "nájem", "podnájem", "k pronájmu"]
            if any(kw in title.lower() for kw in RENTAL_KEYWORDS):
                return None

            # Dispozice z titulku
            disposition = self._extract_disposition(title)
            if disposition and not self._is_valid_disposition(disposition):
                return None

            # Cena
            price = self._extract_price(item)
            if price and price > config.MAX_PRICE:
                return None

            # Lokalita
            locality_el = item.select_one(".c-product__info, .c-product__address")
            location_str = locality_el.get_text(strip=True) if locality_el else location

            # Ověření lokality
            if not self._is_valid_location(location_str) and not self._is_valid_location(location):
                return None

            if not self._is_valid_location(location_str):
                location_str = location

            # Popis
            desc_el = item.select_one(".c-product__perex, .c-product__description")
            description = desc_el.get_text(strip=True) if desc_el else ""

            return {
                "listing_id": listing_id,
                "source": self.SOURCE_NAME,
                "url": url,
                "title": title,
                "price": price,
                "location": location_str,
                "description": description,
                "disposition": disposition,
            }

        except Exception as e:
            logger.warning(f"[iDnes] Chyba při parsování: {e}")
            return None

    def _extract_id_from_url(self, url: str) -> Optional[str]:
        """Extrahuje ID inzerátu z URL."""
        match = re.search(r"/detail/([^/]+)/?$", url)
        if match:
            return match.group(1)
        # Fallback - hash z URL
        match = re.search(r"/(\w{8,})/?(\?|$)", url)
        if match:
            return match.group(1)
        return None

    def _extract_price(self, item) -> Optional[int]:
        """Extrahuje cenu z inzerátu."""
        price_el = item.select_one(".c-product__price, [class*='price']")
        if not price_el:
            return None

        price_text = price_el.get_text(strip=True)
        # Odstraň vše kromě číslic
        price_digits = re.sub(r"[^\d]", "", price_text)
        if price_digits:
            price = int(price_digits)
            # Sanity check - cena bytu v ČR
            if 100_000 < price < 50_000_000:
                return price
        return None

    def _extract_disposition(self, title: str) -> Optional[str]:
        """Extrahuje dispozici z titulku."""
        patterns = [
            r"\b(\d+[+]\s*(?:kk|\d))\b",
            r"\b(\d[+]kk)\b",
            r"\b(\d[+]\d)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, title, re.IGNORECASE)
            if match:
                raw = match.group(1).replace(" ", "").lower()
                # Normalizace
                for disp in config.DISPOSITIONS:
                    if disp.lower() == raw:
                        return disp
        return None
