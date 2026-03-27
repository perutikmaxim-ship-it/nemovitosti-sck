"""
scrapers/base.py – Abstraktní základní třída pro všechny scrapery.

Definuje společné rozhraní, HTTP session se slušnými hlavičkami
a pomocné metody pro filtrování a normalizaci dat.
"""

import hashlib
import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# Rotující User-Agent hlavičky (simuluje reálné prohlížeče)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


@dataclass
class Listing:
    """Reprezentuje jeden realitní inzerát."""

    source: str                     # název zdroje ('sreality', 'bazos', ...)
    external_id: str                # unikátní ID v rámci zdroje
    url: str                        # odkaz na inzerát
    title: str = ""                 # název inzerátu
    price: Optional[int] = None    # cena v Kč (None = neuvedena)
    location: str = ""             # textová lokalita
    area_m2: Optional[int] = None  # plocha v m²
    description: str = ""          # krátký popis
    image_url: str = ""            # URL náhledového obrázku

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "external_id": self.external_id,
            "url": self.url,
            "title": self.title,
            "price": self.price,
            "location": self.location,
            "area_m2": self.area_m2,
            "description": self.description,
            "image_url": self.image_url,
        }

    @staticmethod
    def make_id(url: str) -> str:
        """Vytvoří stabilní hash ID z URL (fallback, když web nemá vlastní ID)."""
        return hashlib.md5(url.encode()).hexdigest()[:16]


class BaseScraper(ABC):
    """
    Abstraktní základní třída pro všechny scrapery.

    Dědící třídy musí implementovat:
        - SOURCE_NAME: str
        - fetch_listings() -> List[Listing]
    """

    SOURCE_NAME: str = "base"

    def __init__(self, config: dict):
        """
        Parametry:
            config: celý config dict (z config.yaml)
        """
        self.config = config
        self.max_price = config.get("max_price", 4_500_000)
        self.min_price = config.get("min_price", 0)
        self.exclude_keywords = [
            kw.lower() for kw in config.get("exclude_keywords", [])
        ]
        self.location_keywords = [
            kw.lower() for kw in config.get("location_keywords", [])
        ]
        self.session = self._build_session(config.get("http", {}))
        logger.debug("Inicializován scraper: %s", self.SOURCE_NAME)

    def _build_session(self, http_config: dict) -> requests.Session:
        """Vytvoří requests Session s retry logikou a slušnými hlavičkami."""
        session = requests.Session()

        # Automatický retry při síťových chybách
        retry_strategy = Retry(
            total=http_config.get("max_retries", 3),
            backoff_factor=http_config.get("retry_delay", 5),
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        # Základní hlavičky pro všechny requesty
        session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                      "image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })

        return session

    def _polite_delay(self) -> None:
        """Krátká pauza mezi requesty – slušné chování vůči serverům."""
        http_cfg = self.config.get("http", {})
        min_d = http_cfg.get("min_delay", 1.0)
        max_d = http_cfg.get("max_delay", 3.0)
        delay = random.uniform(min_d, max_d)
        time.sleep(delay)

    def get(self, url: str, **kwargs) -> Optional[requests.Response]:
        """
        Provede GET request se slušnou pauzou a rotací User-Agenta.
        Při chybě vrátí None (nehroutí aplikaci).
        """
        # Rotace User-Agent pro každý request
        self.session.headers["User-Agent"] = random.choice(USER_AGENTS)
        self._polite_delay()

        timeout = self.config.get("http", {}).get("timeout", 30)
        try:
            response = self.session.get(url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return response
        except requests.Timeout:
            logger.warning("[%s] Timeout pro URL: %s", self.SOURCE_NAME, url)
        except requests.HTTPError as e:
            logger.warning("[%s] HTTP chyba %s pro URL: %s", self.SOURCE_NAME, e.response.status_code, url)
        except requests.RequestException as e:
            logger.warning("[%s] Síťová chyba: %s", self.SOURCE_NAME, e)
        return None

    def is_valid_price(self, price: Optional[int]) -> bool:
        """Zkontroluje, zda cena spadá do povoleného rozsahu."""
        if price is None:
            return True  # inzeráty bez ceny nevylučujeme automaticky
        return self.min_price <= price <= self.max_price

    def is_excluded_location(self, location: str) -> bool:
        """Vrátí True, pokud lokalita obsahuje vylučující klíčové slovo (Praha)."""
        loc_lower = location.lower()
        return any(kw in loc_lower for kw in self.exclude_keywords)

    def is_valid_listing(self, listing: Listing) -> bool:
        """
        Kombinovaná validace inzerátu:
        - cena v rozsahu
        - lokalita není vylučující
        """
        if not self.is_valid_price(listing.price):
            logger.debug(
                "[%s] Vyřazen (cena %s): %s",
                self.SOURCE_NAME, listing.price, listing.title
            )
            return False
        if self.is_excluded_location(listing.location):
            logger.debug(
                "[%s] Vyřazen (Praha): %s",
                self.SOURCE_NAME, listing.location
            )
            return False
        return True

    @abstractmethod
    def fetch_listings(self) -> List[Listing]:
        """
        Stáhne a vrátí seznam nových inzerátů.
        Musí být implementováno v každé dědící třídě.
        """
        ...

    def run(self) -> List[Listing]:
        """
        Spustí scraper a vrátí validní inzeráty.
        Zachytí výjimky aby nepadl celý bot.
        """
        try:
            logger.info("[%s] Spouštím kontrolu...", self.SOURCE_NAME)
            listings = self.fetch_listings()
            valid = [l for l in listings if self.is_valid_listing(l)]
            logger.info(
                "[%s] Nalezeno %d inzerátů (%d po filtraci)",
                self.SOURCE_NAME, len(listings), len(valid)
            )
            return valid
        except Exception as e:
            logger.error("[%s] Neočekávaná chyba: %s", self.SOURCE_NAME, e, exc_info=True)
            return []
