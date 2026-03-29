"""
Scheduler - řídí spouštění scraperů a odesílání notifikací
"""

import time
from typing import List

from core.config import config
from core.database import Database
from core.notifier import TelegramNotifier
from scrapers.sreality import SrealityScraper
from scrapers.bezrealitky import BezrealitkyScraper
from scrapers.idnes import IdnesScraper
from scrapers.bazos import BazosScraper
from utils.logger import get_logger

logger = get_logger(__name__)


class Scheduler:
    def __init__(self, db: Database, notifier: TelegramNotifier):
        self.db = db
        self.notifier = notifier
        self.scrapers = [
            SrealityScraper(),
            BezrealitkyScraper(),
            IdnesScraper(),
            BazosScraper(),
        ]

    def run_once(self) -> None:
        """Spustí všechny scrapery jednou a odešle notifikace pro nové inzeráty."""
        logger.info("--- Spouštím kontrolu nových inzerátů ---")
        total_new = 0

        for scraper in self.scrapers:
            source_name = scraper.__class__.__name__.replace("Scraper", "")
            logger.info(f"Scrapuji: {source_name}")

            try:
                listings = scraper.fetch()
                new_count = 0

                for listing in listings:
                    listing_id = listing.get("listing_id", "")
                    source = listing.get("source", "")

                    if not listing_id or not source:
                        logger.warning(f"Inzerát bez ID nebo zdroje, přeskakuji: {listing}")
                        continue

                    # Deduplikace - zkontroluj v DB
                    if self.db.is_known(listing_id, source):
                        continue

                    # Nový inzerát - ulož a notifikuj
                    saved = self.db.save_listing(listing)
                    if saved:
                        new_count += 1
                        total_new += 1
                        price = listing.get("price") or 0
                        logger.info(
                            f"Nový inzerát [{source}]: {listing.get('title', listing_id)} "
                            f"| {price:,} Kč"
                        )
                        # Pošli notifikaci
                        success = self.notifier.send_listing(listing)
                        if success:
                            self.db.mark_notified(listing_id, source)
                        # Rate limiting - pauza mezi zprávami
                        time.sleep(0.5)

                self.db.log_scrape(source_name.lower(), len(listings), new_count)
                logger.info(
                    f"{source_name}: nalezeno {len(listings)}, nových {new_count}"
                )

            except Exception as e:
                error_msg = str(e)
                logger.error(f"Chyba při scrapování {source_name}: {error_msg}", exc_info=True)
                self.db.log_scrape(source_name.lower(), 0, 0, error_msg)

            # Prodleva mezi zdroji (rate limiting)
            time.sleep(config.REQUEST_DELAY)

        logger.info(f"--- Kontrola dokončena. Celkem nových: {total_new} ---")
