"""
scrapers/idnes.py – Scraper pro idnes.cz/reality

iDnes Reality: https://reality.idnes.cz/s/prodej/domy/stredocesky-kraj/

⚠️ Scraping může porušovat ToS. Používej pouze pro osobní účely.
"""

import logging
import re
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, Listing

logger = logging.getLogger(__name__)

IDNES_BASE = "https://reality.idnes.cz"
IDNES_SEARCH = (
    "https://reality.idnes.cz/s/prodej/domy/stredocesky-kraj/"
    "?s-qc[price_to]={max_price}"
)


def parse_price(text: str) -> Optional[int]:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def parse_area(text: str) -> Optional[int]:
    match = re.search(r"(\d+)\s*m[²2]", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


class IdnesScraper(BaseScraper):
    """
    Scraper pro reality.idnes.cz – prodej domů ve Středočeském kraji.
    """

    SOURCE_NAME = "idnes"

    def _build_url(self) -> str:
        return IDNES_SEARCH.format(max_price=self.max_price)

    def _parse_listing(self, article) -> Optional[Listing]:
        """Parsuje jeden inzerát."""
        try:
            # Odkaz na detail
            link = article.select_one("a.c-list-products__link, a[href*='/detail/']")
            if not link:
                link = article.select_one("h2 a, h3 a")
            if not link:
                return None

            href = link.get("href", "")
            url = urljoin(IDNES_BASE, href)
            external_id = Listing.make_id(url)

            # Titulek
            title_tag = article.select_one(
                ".c-list-products__title, h2, h3, [class*='title']"
            )
            title = title_tag.get_text(strip=True) if title_tag else "Bez názvu"

            # Cena
            price_tag = article.select_one(
                ".c-list-products__price, .price, [class*='price']"
            )
            price_text = price_tag.get_text(strip=True) if price_tag else ""
            price = parse_price(price_text)

            # Lokalita
            location_tag = article.select_one(
                ".c-list-products__locality, .locality, [class*='locality']"
            )
            location = location_tag.get_text(strip=True) if location_tag else ""

            # Popis / parametry
            desc_tag = article.select_one(".c-list-products__params, .params, p")
            description = desc_tag.get_text(strip=True) if desc_tag else ""

            # Plocha
            area_m2 = parse_area(description) or parse_area(title)

            # Obrázek
            img_tag = article.select_one("img")
            image_url = ""
            if img_tag:
                image_url = (
                    img_tag.get("data-src", "")
                    or img_tag.get("src", "")
                )
                if image_url and not image_url.startswith("http"):
                    image_url = urljoin(IDNES_BASE, image_url)

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
            logger.warning("[idnes] Chyba při parsování inzerátu: %s", e)
            return None

    def fetch_listings(self) -> List[Listing]:
        """Stáhne a parsuje inzeráty z reality.idnes.cz."""
        url = self._build_url()

        # iDnes potřebuje speciální hlavičky
        response = self.get(
            url,
            headers={
                "Referer": "https://reality.idnes.cz/",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        if response is None:
            logger.error("[idnes] Nepodařilo se načíst stránku")
            return []

        soup = BeautifulSoup(response.text, "lxml")

        # iDnes používá třídu c-list-products__item nebo article
        articles = (
            soup.select(".c-list-products__item")
            or soup.select("article.product")
            or soup.select("[class*='product-item']")
            or soup.select("article")
        )

        listings = []
        for article in articles:
            listing = self._parse_listing(article)
            if listing and listing.url != IDNES_BASE:
                listings.append(listing)

        logger.info("[idnes] Zpracováno %d inzerátů", len(listings))
        return listings
