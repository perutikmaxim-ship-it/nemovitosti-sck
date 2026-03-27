"""
scrapers/realingo.py – Scraper pro realingo.cz

Realingo je realitní agregátor s vlastním vyhledáváním.
Vyhledávací URL: https://www.realingo.cz/vyhledavani/domy-k-prodeji
s parametry pro kraj a cenu.

⚠️ Scraping může porušovat ToS. Používej pouze pro osobní účely.
"""

import logging
import re
from typing import List, Optional
from urllib.parse import urljoin, urlencode

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, Listing

logger = logging.getLogger(__name__)

REALINGO_BASE = "https://www.realingo.cz"
REALINGO_SEARCH = "https://www.realingo.cz/vyhledavani/domy-k-prodeji"


def parse_price(text: str) -> Optional[int]:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def parse_area(text: str) -> Optional[int]:
    match = re.search(r"(\d+)\s*m[²2]", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


class RealingoScraper(BaseScraper):
    """
    Scraper pro realingo.cz – domy k prodeji ve Středočeském kraji.
    """

    SOURCE_NAME = "realingo"

    def _build_url(self) -> str:
        """Sestaví URL pro vyhledávání."""
        params = {
            "kraj": "stredocesky-kraj",
            "cena_do": self.max_price,
        }
        return f"{REALINGO_SEARCH}?{urlencode(params)}"

    def _parse_listing(self, card) -> Optional[Listing]:
        """Parsuje jeden inzerát z výsledkové stránky."""
        try:
            # Odkaz
            link = card.select_one("a[href]")
            if not link:
                return None

            href = link.get("href", "")
            url = urljoin(REALINGO_BASE, href)
            external_id = Listing.make_id(url)

            # Titulek
            title_tag = card.select_one("h2, h3, .title, .name")
            title = title_tag.get_text(strip=True) if title_tag else "Bez názvu"

            # Cena
            price_tag = card.select_one(".price, .cena, [class*='price']")
            price_text = price_tag.get_text(strip=True) if price_tag else ""
            price = parse_price(price_text)

            # Lokalita
            location_tag = card.select_one(".location, .locality, [class*='location']")
            location = location_tag.get_text(strip=True) if location_tag else ""

            # Popis
            desc_tag = card.select_one(".description, .perex, p")
            description = desc_tag.get_text(strip=True) if desc_tag else ""

            # Plocha
            area_m2 = parse_area(title) or parse_area(description)

            # Obrázek
            img_tag = card.select_one("img")
            image_url = ""
            if img_tag:
                image_url = img_tag.get("src", "") or img_tag.get("data-src", "")
                if image_url and not image_url.startswith("http"):
                    image_url = urljoin(REALINGO_BASE, image_url)

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
            logger.warning("[realingo] Chyba při parsování inzerátu: %s", e)
            return None

    def fetch_listings(self) -> List[Listing]:
        """Stáhne a parsuje inzeráty z realingo.cz."""
        url = self._build_url()
        response = self.get(url)
        if response is None:
            logger.error("[realingo] Nepodařilo se načíst stránku")
            return []

        soup = BeautifulSoup(response.text, "lxml")

        # Realingo používá různé selektory – zkusíme více variant
        cards = (
            soup.select(".property-card")
            or soup.select(".listing-item")
            or soup.select("article")
            or soup.select("[class*='card']")
        )

        listings = []
        for card in cards:
            listing = self._parse_listing(card)
            if listing and listing.url != REALINGO_BASE:
                listings.append(listing)

        logger.info("[realingo] Zpracováno %d inzerátů", len(listings))
        return listings
