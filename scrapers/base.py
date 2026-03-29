"""
Základní třída pro všechny scrapery
"""

import time
import requests
from abc import ABC, abstractmethod
from typing import List, Optional

from core.config import config
from utils.logger import get_logger

logger = get_logger(__name__)


class BaseScraper(ABC):
    """Abstraktní základní třída pro scrapery nemovitostí."""

    SOURCE_NAME: str = "base"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        self.timeout = config.REQUEST_TIMEOUT
        self.delay = config.REQUEST_DELAY

    @abstractmethod
    def fetch(self) -> List[dict]:
        """
        Stáhne a vrátí seznam inzerátů jako list slovníků.
        Každý slovník musí obsahovat klíče:
          - listing_id (str): unikátní ID v rámci zdroje
          - source (str): jméno zdroje (sreality, bezrealitky, ...)
          - url (str): přímý odkaz na inzerát
          - title (str, optional): název inzerátu
          - price (int, optional): cena v Kč
          - location (str, optional): lokalita
          - description (str, optional): krátký popis
          - disposition (str, optional): dispozice (2+kk, 2+1, ...)
        """
        pass

    def _get(self, url: str, **kwargs) -> Optional[requests.Response]:
        """HTTP GET s ošetřením chyb a timeoutem."""
        try:
            resp = self.session.get(url, timeout=self.timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.exceptions.Timeout:
            logger.warning(f"[{self.SOURCE_NAME}] Timeout pro URL: {url}")
        except requests.exceptions.HTTPError as e:
            logger.warning(f"[{self.SOURCE_NAME}] HTTP chyba {e.response.status_code}: {url}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"[{self.SOURCE_NAME}] Síťová chyba: {e}")
        return None

    def _post(self, url: str, **kwargs) -> Optional[requests.Response]:
        """HTTP POST s ošetřením chyb a timeoutem."""
        try:
            resp = self.session.post(url, timeout=self.timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.exceptions.Timeout:
            logger.warning(f"[{self.SOURCE_NAME}] Timeout pro URL: {url}")
        except requests.exceptions.HTTPError as e:
            logger.warning(f"[{self.SOURCE_NAME}] HTTP chyba {e.response.status_code}: {url}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"[{self.SOURCE_NAME}] Síťová chyba: {e}")
        return None

    def _is_valid_location(self, location_text: str) -> bool:
        """Ověří, zda lokalita odpovídá povoleným městům (case-insensitive)."""
        if not location_text:
            return False
        location_lower = location_text.lower()
        for allowed in config.LOCATIONS:
            if allowed.lower() in location_lower:
                return True
        return False

    def _is_valid_disposition(self, disposition_text: str) -> bool:
        """Ověří, zda dispozice odpovídá požadovaným."""
        if not disposition_text:
            return False
        for disp in config.DISPOSITIONS:
            if disp.lower() in disposition_text.lower():
                return True
        return False

    def _sleep(self) -> None:
        time.sleep(self.delay)
