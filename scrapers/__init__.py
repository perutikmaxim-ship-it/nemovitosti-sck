"""
scrapers/ – Balíček scraperů pro jednotlivé realitní weby.

Každý scraper dědí z BaseScaper a implementuje metodu fetch_listings().
"""

from scrapers.base import BaseScraper, Listing
from scrapers.sreality import SrealityScraper
from scrapers.bazos import BazosScraper
from scrapers.realingo import RealingoScraper
from scrapers.reas import ReasScraper
from scrapers.idnes import IdnesScraper

__all__ = [
    "BaseScraper",
    "Listing",
    "SrealityScraper",
    "BazosScraper",
    "RealingoScraper",
    "ReasScraper",
    "IdnesScraper",
]
