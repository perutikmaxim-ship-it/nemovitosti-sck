"""
Nemovitosti Bot - hlavní vstupní bod
Sleduje nové byty v Kladně, Mělníku a Kralupech nad Vltavou
"""

import time
import signal
import sys

from core.scheduler import Scheduler
from core.database import Database
from core.notifier import TelegramNotifier
from core.config import config
from utils.logger import get_logger

logger = get_logger(__name__)


def main():
    logger.info("=== Nemovitosti Bot se spouští ===")
    logger.info(f"Lokality: {', '.join(config.LOCATIONS)}")
    logger.info(f"Max cena: {config.MAX_PRICE:,} Kč")
    logger.info(f"Dispozice: {', '.join(config.DISPOSITIONS)}")
    logger.info(f"Interval kontroly: {config.CHECK_INTERVAL} sekund")

    db = Database()
    notifier = TelegramNotifier()
    scheduler = Scheduler(db=db, notifier=notifier)

    # Graceful shutdown
    def handle_shutdown(signum, frame):
        logger.info("Přijat signál pro ukončení, zavírám bot...")
        db.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    # Pošli startup zprávu
    try:
        notifier.send_startup_message()
    except Exception as e:
        logger.warning(f"Nepodařilo se odeslat startup zprávu: {e}")

    logger.info("Bot běží. Stiskni Ctrl+C pro ukončení.")

    while True:
        try:
            scheduler.run_once()
        except Exception as e:
            logger.error(f"Neočekávaná chyba v hlavní smyčce: {e}", exc_info=True)

        logger.info(f"Čekám {config.CHECK_INTERVAL // 60} minut do další kontroly...")
        time.sleep(config.CHECK_INTERVAL)


if __name__ == "__main__":
    main()
