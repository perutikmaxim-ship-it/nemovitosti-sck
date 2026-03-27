"""
scrapers/bazos.py – Scraper pro bazos.cz/reality

Bazos nemá veřejné API, používáme BeautifulSoup pro parsování HTML.
Sekce: https://reality.bazos.cz/prodam/dum/

Filtrujeme podle Středočeského kraje a ceny.

⚠️  Scraping porušuje ToS bazos.cz. Používej pouze pro osobní účely.
"""

import logging
import re
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, Listing

logger = logging.getLogger(__name__)

# URL pro domy v Středočeském kraji
# bazos.cz používá textový filtr v URL (kraj=stredocesky)
BAZOS_BASE = "https://reality.bazos.cz"
BAZOS_SEARCH_URL = (
    "https://reality.bazos.cz/prodam/dum/?kraj=stredocesky&cena={max_price}"
)


def parse_price(text: str) -> Optional[int]:
    """Extrahuje číselnou cenu z textu ('3 500 000 Kč' → 3500000)."""
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def parse_area(text: str) -> Optional[int]:
    """Extrahuje plochu v m² z textu."""
    match = re.search(r"(\d+)\s*m[²2]", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


class BazosScraper(BaseScraper):
    """
    Scraper pro bazos.cz/reality – prodej domů ve Středočeském kraji.
    """

    SOURCE_NAME = "bazos"

    def _build_url(self) -> str:
        return BAZOS_SEARCH_URL.format(max_price=self.max_price)

    def _parse_listing(self, article, base_url: str) -> Optional[Listing]:
        """Parsuje jeden inzerátový element (article tag)."""
        try:
            # Odkaz a titulek
            title_tag = article.select_one("h2.nadpis a, .inzeratynadpis a")
            if not title_tag:
                return None

            title = title_tag.get_text(strip=True)
            href = title_tag.get("href", "")
            if not href:
                return None

            url = urljoin(base_url, href)
            external_id = Listing.make_id(url)

            # Cena
            price_tag = article.select_one(".inzeratycena, .cena")
            price_text = price_tag.get_text(strip=True) if price_tag else ""
            price = parse_price(price_text)

            # Lokalita
            location_tag = article.select_one(".inzeratylokace, .lokace")
            location = location_tag.get_text(strip=True) if location_tag else ""

            # Popis
            desc_tag = article.select_one(".popis, .inzeratypopis")
            description = desc_tag.get_text(strip=True) if desc_tag else ""

            # Plocha z popisu nebo titulku
            area_m2 = parse_area(title) or parse_area(description)

            # Obrázek
            img_tag = article.select_one("img")
            image_url = img_tag.get("src", "") if img_tag else ""
            if image_url and not image_url.startswith("http"):
                image_url = urljoin(base_url, image_url)

            return Listing(
                source=self.SOURCE_NAME,
                external_id=external_id,
                url=url,
                title=title,
                price=price,
                location=location,
                area_m2=area_m2,
                description=description[:300],
                image_url=image_url,
            )
        except Exception as e:
            logger.warning("[bazos] Chyba při parsování inzerátu: %s", e)
            return None

    def fetch_listings(self) -> List[Listing]:
        """Stáhne a parsuje inzeráty z bazos.cz."""
        url = self._build_url()
        response = self.get(url)
        if response is None:
            logger.error("[bazos] Nepodařilo se načíst stránku")
            return []

        soup = BeautifulSoup(response.text, "lxml")
        # Bazos zabaluje inzeráty do div.inzeraty nebo article elementů
        articles = soup.select("div.inzeraty, article.inzerat")

        if not articles:
            # Záložní selektor
            articles = soup.select(".maincontent .inzerat")

        listings = []
        for article in articles:
            listing = self._parse_listing(article, BAZOS_BASE)
            if listing:
                listings.append(listing)

        logger.info("[bazos] Zpracováno %d inzerátů", len(listings))
        return listings
