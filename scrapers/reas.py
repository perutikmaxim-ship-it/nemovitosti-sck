"""
scrapers/reas.py – Scraper pro reas.cz

Reas.cz je česká realitní platforma.
URL: https://reas.cz/prodam/domy/?kraj=stredocesky

⚠️ Scraping může porušovat ToS. Používej pouze pro osobní účely.
"""

import logging
import re
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, Listing

logger = logging.getLogger(__name__)

REAS_BASE = "https://reas.cz"
REAS_SEARCH = "https://reas.cz/prodam/domy/"


def parse_price(text: str) -> Optional[int]:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def parse_area(text: str) -> Optional[int]:
    match = re.search(r"(\d+)\s*m[²2]", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


class ReasScraper(BaseScraper):
    """
    Scraper pro reas.cz – domy k prodeji ve Středočeském kraji.
    """

    SOURCE_NAME = "reas"

    def _build_url(self) -> str:
        """Sestaví URL s filtry."""
        return f"{REAS_SEARCH}?kraj=stredocesky&cena_max={self.max_price}"

    def _parse_listing(self, item) -> Optional[Listing]:
        """Parsuje jeden inzerát."""
        try:
            # Odkaz
            link = item.select_one("a[href]")
            if not link:
                return None

            href = link.get("href", "")
            url = urljoin(REAS_BASE, href)
            external_id = Listing.make_id(url)

            # Titulek
            title_tag = item.select_one("h2, h3, .title, .heading")
            title = title_tag.get_text(strip=True) if title_tag else link.get_text(strip=True)
            if not title:
                title = "Bez názvu"

            # Cena
            price_tag = item.select_one(".price, .cena, [class*='price']")
            price_text = price_tag.get_text(strip=True) if price_tag else ""
            price = parse_price(price_text)

            # Lokalita
            location_tag = item.select_one(".location, .mesto, .adresa, [class*='location']")
            location = location_tag.get_text(strip=True) if location_tag else ""

            # Popis
            desc_tag = item.select_one(".description, .perex, p")
            description = desc_tag.get_text(strip=True) if desc_tag else ""

            # Plocha
            area_m2 = parse_area(title) or parse_area(description)

            # Obrázek
            img_tag = item.select_one("img")
            image_url = ""
            if img_tag:
                image_url = img_tag.get("src", "") or img_tag.get("data-src", "")
                if image_url and not image_url.startswith("http"):
                    image_url = urljoin(REAS_BASE, image_url)

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
            logger.warning("[reas] Chyba při parsování inzerátu: %s", e)
            return None

    def fetch_listings(self) -> List[Listing]:
        """Stáhne a parsuje inzeráty z reas.cz."""
        url = self._build_url()
        response = self.get(url)
        if response is None:
            logger.error("[reas] Nepodařilo se načíst stránku")
            return []

        soup = BeautifulSoup(response.text, "lxml")

        # Různé možné selektory
        items = (
            soup.select(".property-listing")
            or soup.select(".inzerat")
            or soup.select("article")
            or soup.select(".result-item")
        )

        listings = []
        for item in items:
            listing = self._parse_listing(item)
            if listing and listing.url != REAS_BASE:
                listings.append(listing)

        logger.info("[reas] Zpracováno %d inzerátů", len(listings))
        return listings
