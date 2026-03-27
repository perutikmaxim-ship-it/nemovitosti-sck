"""
test_run.py – Testovací skript pro jednorázové ověření funkčnosti.

Spustí JEDEN cyklus kontrol bez scheduleru a Telegramu.
Výsledky vypíše do konzole – ideální pro debugging.

Použití:
    python test_run.py
    python test_run.py --source sreality     # pouze jeden zdroj
    python test_run.py --no-send             # neposílá do Telegramu
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Nastavení loggeru pro test
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("test_run")

load_dotenv()

CONFIG_PATH = Path(__file__).parent / "config.yaml"
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)


def print_listing(listing, idx: int) -> None:
    """Hezky vypíše inzerát do konzole."""
    price_str = f"{listing.price:,} Kč".replace(",", " ") if listing.price else "N/A"
    area_str = f"{listing.area_m2} m²" if listing.area_m2 else "N/A"

    print(f"\n{'─'*60}")
    print(f"  [{idx}] {listing.source.upper()}")
    print(f"  Titulek:  {listing.title}")
    print(f"  Lokalita: {listing.location}")
    print(f"  Cena:     {price_str}")
    print(f"  Plocha:   {area_str}")
    print(f"  URL:      {listing.url[:80]}{'...' if len(listing.url)>80 else ''}")
    if listing.description:
        desc = listing.description[:100] + ("..." if len(listing.description) > 100 else "")
        print(f"  Popis:    {desc}")


def run_test(source_filter: str = None, send_telegram: bool = False) -> None:
    """Spustí testovací cyklus."""
    from scrapers import (
        SrealityScraper, BazosScraper, RealingoScraper,
        ReasScraper, IdnesScraper,
    )

    scraper_map = {
        "sreality": SrealityScraper,
        "bazos": BazosScraper,
        "realingo": RealingoScraper,
        "reas": ReasScraper,
        "idnes": IdnesScraper,
    }

    # Filtr zdroje
    if source_filter:
        if source_filter not in scraper_map:
            logger.error("Neznámý zdroj: %s. Možnosti: %s",
                         source_filter, list(scraper_map.keys()))
            sys.exit(1)
        scraper_map = {source_filter: scraper_map[source_filter]}

    print(f"\n{'='*60}")
    print(f"  REALITY BOT – TESTOVACÍ BĚH")
    print(f"  Max cena: {config['max_price']:,} Kč".replace(",", " "))
    print(f"  Zdroje:   {', '.join(scraper_map.keys())}")
    print(f"{'='*60}\n")

    all_listings = []

    for name, cls in scraper_map.items():
        print(f"\n>>> Testuju scraper: {name.upper()} ...")
        scraper = cls(config)
        try:
            listings = scraper.run()
            print(f"    ✓ Nalezeno {len(listings)} validních inzerátů")
            for i, listing in enumerate(listings[:3], 1):  # zobrazíme max 3
                print_listing(listing, i)
            if len(listings) > 3:
                print(f"\n    ... a dalších {len(listings)-3} inzerátů")
            all_listings.extend(listings)
        except Exception as e:
            print(f"    ✗ CHYBA: {e}")
            logger.exception("Chyba scraperu %s", name)

    print(f"\n{'='*60}")
    print(f"  CELKEM: {len(all_listings)} inzerátů")
    print(f"{'='*60}\n")

    # Volitelně odeslat první inzerát do Telegramu
    if send_telegram and all_listings:
        token = os.getenv("TELEGRAM_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            print("⚠️  TELEGRAM_TOKEN nebo TELEGRAM_CHAT_ID není nastaven v .env")
        else:
            from notifier import TelegramNotifier
            n = TelegramNotifier(token, chat_id)
            if n.test_connection():
                print(f"Odesílám první inzerát do Telegramu jako test...")
                n.send_listing(all_listings[0].to_dict())
                print("✓ Telegram zpráva odeslána!")
            else:
                print("✗ Nelze se připojit k Telegram API")

    # Test databáze
    print("\nTestuji databázi...")
    import database
    database.init_db()
    if all_listings:
        first = all_listings[0]
        saved = database.save_listing(
            source=first.source,
            external_id=first.external_id + "_test",
            url=first.url,
            title=first.title,
            price=first.price,
            location=first.location,
        )
        if saved:
            print(f"✓ Testovací inzerát uložen do databáze")
            # Ověřuje deduplikaci
            duplicate = database.save_listing(
                source=first.source,
                external_id=first.external_id + "_test",
                url=first.url,
            )
            if not duplicate:
                print("✓ Deduplikace funguje správně")
            stats = database.get_stats()
            print(f"✓ Databázové statistiky: {stats}")
        else:
            print("✗ Uložení do databáze selhalo")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reality Bot – testovací běh")
    parser.add_argument(
        "--source",
        choices=["sreality", "bazos", "realingo", "reas", "idnes"],
        help="Otestuje pouze jeden zdroj",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Odešle první nalezený inzerát do Telegramu",
    )
    args = parser.parse_args()

    run_test(source_filter=args.source, send_telegram=args.send)
