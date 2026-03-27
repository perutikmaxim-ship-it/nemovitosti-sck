"""
main.py – Hlavní runner Reality Bota

Spouští scheduler (APScheduler) pro pravidelnou kontrolu inzerátů
a zároveň poslouchá Telegram příkazy (/start, /stop, /status).

Architektura:
  - APScheduler spouští check_all_sources() každých N sekund (default 900)
  - python-telegram-bot zpracovává příkazy v samostatném vlákně
  - Stav (běží/zastaveno) je sdílen přes threading.Event
"""

import logging
import os
import threading
from pathlib import Path
from typing import List

import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

import database
from notifier import TelegramNotifier
from scrapers import (
    SrealityScraper,
    BazosScraper,
    RealingoScraper,
    ReasScraper,
    IdnesScraper,
    BaseScraper,
    Listing,
)

# ============================================================
# Konfigurace loggeru
# ============================================================
try:
    import colorlog

    handler = colorlog.StreamHandler()
    handler.setFormatter(
        colorlog.ColoredFormatter(
            "%(log_color)s%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            log_colors={
                "DEBUG": "cyan",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "bold_red",
            },
        )
    )
except ImportError:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        handler,
        logging.FileHandler("reality-bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ============================================================
# Načtení konfigurace
# ============================================================
# Načti .env (tajné klíče)
load_dotenv()

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config() -> dict:
    """Načte config.yaml a přepíše hodnotami z .env pokud existují."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # Přepsání z env proměnných
    if os.getenv("MAX_PRICE"):
        cfg["max_price"] = int(os.getenv("MAX_PRICE"))

    return cfg


config = load_config()

# Telegram credentials
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

if not TELEGRAM_TOKEN:
    logger.critical("TELEGRAM_TOKEN není nastaven! Zkontroluj .env soubor.")
    exit(1)

# ============================================================
# Globální stav bota
# ============================================================
is_monitoring = threading.Event()
notifier: TelegramNotifier = None
scheduler: BackgroundScheduler = None

# Statistiky aktuální session
session_stats = {"found": 0, "sent": 0, "errors": 0}
stats_lock = threading.Lock()


# ============================================================
# Inicializace scraperů
# ============================================================
def build_scrapers() -> List[BaseScraper]:
    """Vytvoří aktivní scrapery podle configu."""
    scraper_map = {
        "sreality": SrealityScraper,
        "bazos": BazosScraper,
        "realingo": RealingoScraper,
        "reas": ReasScraper,
        "idnes": IdnesScraper,
    }

    scrapers_cfg = config.get("scrapers", {})
    active = []
    for name, cls in scraper_map.items():
        if scrapers_cfg.get(name, True):
            active.append(cls(config))
            logger.info("Scraper aktivní: %s", name)
        else:
            logger.info("Scraper vypnut: %s", name)

    return active


SCRAPERS = build_scrapers()


# ============================================================
# Hlavní logika: kontrola inzerátů
# ============================================================
def check_all_sources() -> None:
    """
    Provede jednu kontrolu všech zdrojů.
    Volá se schedulererem každých N sekund.
    Pokud není monitorování aktivní, nic nedělá.
    """
    if not is_monitoring.is_set():
        logger.debug("Monitorování zastaveno, přeskakuji kontrolu")
        return

    logger.info("=" * 50)
    logger.info("Spouštím kontrolu všech zdrojů...")

    new_listings: List[Listing] = []

    for scraper in SCRAPERS:
        try:
            listings = scraper.run()
            for listing in listings:
                # Zkusíme uložit – vrátí True, pokud je inzerát nový
                is_new = database.save_listing(
                    source=listing.source,
                    external_id=listing.external_id,
                    url=listing.url,
                    title=listing.title,
                    price=listing.price,
                    location=listing.location,
                    area_m2=listing.area_m2,
                    description=listing.description,
                    image_url=listing.image_url,
                )
                if is_new:
                    new_listings.append(listing)
                    with stats_lock:
                        session_stats["found"] += 1

        except Exception as e:
            logger.error("Chyba ve scraperu %s: %s", scraper.SOURCE_NAME, e)
            with stats_lock:
                session_stats["errors"] += 1

    # Odeslání nových inzerátů
    if new_listings:
        logger.info("Nalezeno %d nových inzerátů, odesílám...", len(new_listings))
        for listing in new_listings:
            success = notifier.send_listing(listing.to_dict())
            if success:
                database.mark_sent(listing.source, listing.external_id)
                with stats_lock:
                    session_stats["sent"] += 1
    else:
        logger.info("Žádné nové inzeráty")

    logger.info("Kontrola dokončena. Čekám na další běh...")


# ============================================================
# Telegram příkazy
# ============================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start – spustí monitorování."""
    chat_id = str(update.effective_chat.id)

    # Uloží chat_id pokud není v .env
    global TELEGRAM_CHAT_ID
    if not TELEGRAM_CHAT_ID:
        TELEGRAM_CHAT_ID = chat_id
        notifier.chat_id = chat_id
        logger.info("Chat ID nastaveno z /start: %s", chat_id)

    if is_monitoring.is_set():
        await update.message.reply_text(
            "✅ Monitorování již běží! Pro stav použij /status"
        )
        return

    is_monitoring.set()
    logger.info("Monitorování SPUŠTĚNO příkazem /start")
    notifier.send_start_message()

    # Ihned spustíme první kontrolu
    threading.Thread(target=check_all_sources, daemon=True).start()


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stop – zastaví monitorování."""
    if not is_monitoring.is_set():
        await update.message.reply_text("⏸️ Monitorování již bylo zastaveno.")
        return

    is_monitoring.clear()
    logger.info("Monitorování ZASTAVENO příkazem /stop")
    notifier.send_stop_message()


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/status – vrátí aktuální stav a statistiky."""
    db_stats = database.get_stats()
    notifier.send_status(is_monitoring.is_set(), db_stats)


# ============================================================
# Inicializace a spuštění
# ============================================================
def setup_notifier() -> TelegramNotifier:
    """Vytvoří a otestuje Telegram notifier."""
    n = TelegramNotifier(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)
    if not n.test_connection():
        logger.critical("Nelze se připojit k Telegram API!")
        exit(1)
    return n


def setup_scheduler() -> BackgroundScheduler:
    """Nastaví APScheduler pro pravidelné spouštění kontrol."""
    interval = config.get("check_interval", 900)
    sched = BackgroundScheduler(timezone="Europe/Prague")
    sched.add_job(
        check_all_sources,
        trigger="interval",
        seconds=interval,
        id="check_sources",
        max_instances=1,       # Nikdy nespouštíme paralelně
        coalesce=True,         # Pokud zmešká, spustí jen jednou
    )
    logger.info("Scheduler nastaven: interval %d sekund (%d min)", interval, interval // 60)
    return sched


def main() -> None:
    """Hlavní vstupní bod aplikace."""
    global notifier, scheduler

    logger.info("Reality Bot se spouští...")
    logger.info("Config: max_price=%s Kč, interval=%ss",
                config.get("max_price"), config.get("check_interval"))

    # Inicializace databáze
    database.init_db()

    # Inicializace notifieru
    notifier = setup_notifier()

    # Pokud je chat_id v .env, rovnou spustíme monitorování
    if TELEGRAM_CHAT_ID:
        is_monitoring.set()
        logger.info("Chat ID nalezeno v .env – monitorování automaticky spuštěno")

    # APScheduler
    scheduler = setup_scheduler()
    scheduler.start()
    logger.info("Scheduler spuštěn")

    # Telegram Bot (blokující smyčka)
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("status", cmd_status))

    logger.info("Telegram bot spuštěn, čekám na příkazy...")
    logger.info("Příkazy: /start /stop /status")

    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        logger.info("Ukončuji...")
    finally:
        scheduler.shutdown(wait=False)
        logger.info("Reality Bot zastaven.")


if __name__ == "__main__":
    main()
