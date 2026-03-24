"""
Nemovitosti SCK - Real Estate Monitor
Sleduje byty ve Středočeském kraji do 5M Kč, max 1h od Prahy
Portály: Sreality, Bezrealitky, Bazoš, Reas
"""

import os
import time
import logging
import sqlite3
import hashlib
import requests
from bs4 import BeautifulSoup
from datetime import datetime, time as dtime
import schedule

# ─────────────────────────────────────────────
# KONFIGURACE — vyplň své údaje
# ─────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8489502024:AAGJ7c6mtPQVxk8qkL7Uz1ZWFmQU3LggPEE")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "7358077550")
DB_PATH = "nemovitosti.db"
CHECK_INTERVAL_MINUTES = 15  # jak často kontrolovat

# Maximální cena
MAX_PRICE = 5_000_000

# Hledané dispozice
DISPOSITIONS = ["1+kk", "1+1", "2+kk", "2+1"]

# Zakázaná klíčová slova v názvu/popisu
BANNED_KEYWORDS = [
    "dražba", "drazba", "exekuce", "insolvence", "nucený prodej",
    "nuceny prodej", "aukce", "zástavní", "zastavni"
]

# Okresy Středočeského kraje (bez Prahy!)
STREDOCESKE_OKRESY = [
    "Benešov", "Beroun", "Kladno", "Kolín", "Kutná Hora",
    "Mělník", "Mladá Boleslav", "Nymburk", "Praha-východ",
    "Praha-západ", "Příbram", "Rakovník"
]

# Města do 1h od Prahy (přibližný seznam)
MESTA_DO_1H = [
    "Beroun", "Kladno", "Mladá Boleslav", "Mělník", "Neratovice",
    "Brandýs nad Labem", "Čelákovice", "Lysá nad Labem", "Nymburk",
    "Kolín", "Benešov", "Říčany", "Černošice", "Dobříš",
    "Příbram", "Rakovník", "Slaný", "Kralupy nad Vltavou",
    "Roztoky", "Hostivice", "Rudná", "Unhošť", "Stochov",
    "Vlašim", "Votice", "Sedlčany", "Neveklov", "Týnec nad Sázavou",
    "Cerhenice", "Poděbrady", "Sadská", "Milovice", "Kostelec nad Černými Lesy",
    "Úvaly", "Čestlice", "Průhonice", "Jesenice", "Vestec"
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("scraper.log", encoding="utf-8")
    ]
)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "cs-CZ,cs;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ─────────────────────────────────────────────
# DATABÁZE
# ─────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            id TEXT PRIMARY KEY,
            title TEXT,
            price INTEGER,
            location TEXT,
            url TEXT,
            source TEXT,
            disposition TEXT,
            found_at TEXT,
            sent_daily INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()
    log.info("Databáze inicializována")


def is_duplicate(listing_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM listings WHERE id = ?", (listing_id,))
    result = c.fetchone()
    conn.close()
    return result is not None


def save_listing(listing: dict):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO listings
        (id, title, price, location, url, source, disposition, found_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        listing["id"],
        listing["title"],
        listing["price"],
        listing["location"],
        listing["url"],
        listing["source"],
        listing.get("disposition", ""),
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()


def get_unsent_daily() -> list:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT title, price, location, url, source, disposition, found_at
        FROM listings
        WHERE sent_daily = 0
        ORDER BY found_at DESC
    """)
    rows = c.fetchall()
    conn.close()
    return rows


def mark_all_sent_daily():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE listings SET sent_daily = 1 WHERE sent_daily = 0")
    conn.commit()
    conn.close()


def make_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


# ─────────────────────────────────────────────
# FILTRY
# ─────────────────────────────────────────────

def is_banned(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in BANNED_KEYWORDS)


def is_valid_location(location: str) -> bool:
    loc_lower = location.lower()
    # Vyloučit Prahu
    if loc_lower.startswith("praha") and "západ" not in loc_lower and "východ" not in loc_lower:
        return False
    # Kontrola zda je ve Středočeském kraji / blízko Prahy
    for mesto in MESTA_DO_1H:
        if mesto.lower() in loc_lower:
            return True
    for okres in STREDOCESKE_OKRESY:
        if okres.lower() in loc_lower:
            return True
    return False


def parse_price(price_str: str) -> int:
    """Parsuje cenu z textu na celé číslo."""
    if not price_str:
        return 0
    cleaned = price_str.replace(" ", "").replace("\xa0", "").replace("Kč", "").replace(",", "")
    digits = "".join(filter(str.isdigit, cleaned))
    return int(digits) if digits else 0


# ─────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────

def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        r = SESSION.post(url, json=payload, timeout=10)
        r.raise_for_status()
        log.info("Telegram zpráva odeslána")
    except Exception as e:
        log.error(f"Chyba při odesílání Telegramu: {e}")


def format_listing_message(listing: dict) -> str:
    price_fmt = f"{listing['price']:,}".replace(",", " ")
    emoji_source = {
        "Sreality": "🏠",
        "Bezrealitky": "🔑",
        "Bazoš": "📦",
        "Reas": "🏢",
    }.get(listing["source"], "📍")

    distance_note = get_distance_note(listing["location"])

    msg = (
        f"{emoji_source} <b>{listing['title']}</b>\n"
        f"💰 <b>{price_fmt} Kč</b>\n"
        f"📍 {listing['location']}{distance_note}\n"
        f"🛏 {listing.get('disposition', 'N/A')}\n"
        f"🌐 {listing['source']}\n"
        f"🔗 <a href=\"{listing['url']}\">Zobrazit inzerát</a>"
    )
    return msg


def get_distance_note(location: str) -> str:
    """Přibližná vzdálenost od Prahy podle města."""
    distances = {
        "Černošice": " (~20 min)", "Roztoky": " (~20 min)", "Hostivice": " (~20 min)",
        "Rudná": " (~25 min)", "Říčany": " (~25 min)", "Unhošť": " (~30 min)",
        "Beroun": " (~35 min)", "Kladno": " (~35 min)", "Kralupy nad Vltavou": " (~35 min)",
        "Brandýs nad Labem": " (~35 min)", "Neratovice": " (~40 min)",
        "Benešov": " (~45 min)", "Slaný": " (~45 min)", "Mělník": " (~45 min)",
        "Dobříš": " (~50 min)", "Nymburk": " (~50 min)", "Poděbrady": " (~55 min)",
        "Mladá Boleslav": " (~60 min)", "Příbram": " (~60 min)", "Kolín": " (~55 min)",
        "Rakovník": " (~60 min)",
    }
    loc_lower = location.lower()
    for mesto, dist in distances.items():
        if mesto.lower() in loc_lower:
            return dist
    return ""


# ─────────────────────────────────────────────
# SCRAPER: SREALITY
# ─────────────────────────────────────────────

def scrape_sreality() -> list:
    """
    Sreality API — filtruje byty ve Středočeském kraji.
    category_main_cb=1 (byty), category_type_cb=1 (prodej)
    region_id pro Středočeský kraj = 13
    """
    results = []

    # Dispozice kódy pro Sreality: 2=1+kk, 3=1+1, 4=2+kk, 5=2+1
    disposition_codes = "2%7C3%7C4%7C5"  # URL encoded pipe

    url = (
        "https://www.sreality.cz/api/cs/v2/estates"
        "?category_main_cb=1"           # byty
        "&category_type_cb=1"           # prodej
        "&region_id=13"                 # Středočeský kraj
        "&czk_price_summary_order2=0%7C5000000"  # do 5M
        f"&category_sub_cb={disposition_codes}"
        "&per_page=60"
        "&sort=0"                       # nejnovější první
    )

    try:
        r = SESSION.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        estates = data.get("_embedded", {}).get("estates", [])
        log.info(f"Sreality: nalezeno {len(estates)} inzerátů")

        for estate in estates:
            try:
                title = estate.get("name", "")
                price = estate.get("price", 0)
                locality = estate.get("locality", "")
                estate_id = str(estate.get("hash_id", ""))
                seo = estate.get("seo", {})
                locality_url = seo.get("locality", "stredocesky-kraj")
                listing_url = f"https://www.sreality.cz/detail/prodej/byt/{locality_url}/{estate_id}"

                if is_banned(title):
                    continue
                if price > MAX_PRICE or price == 0:
                    continue
                if not is_valid_location(locality):
                    continue

                listing_hash = make_id(listing_url)
                if is_duplicate(listing_hash):
                    continue

                # Zjisti dispozici z názvu
                disposition = ""
                for d in DISPOSITIONS:
                    if d.lower() in title.lower():
                        disposition = d
                        break

                listing = {
                    "id": listing_hash,
                    "title": title,
                    "price": price,
                    "location": locality,
                    "url": listing_url,
                    "source": "Sreality",
                    "disposition": disposition,
                }
                results.append(listing)
            except Exception as e:
                log.warning(f"Sreality — chyba při parsování inzerátu: {e}")

    except Exception as e:
        log.error(f"Sreality — chyba při stahování: {e}")

    return results


# ─────────────────────────────────────────────
# SCRAPER: BEZREALITKY (GraphQL API)
# ─────────────────────────────────────────────

def scrape_bezrealitky() -> list:
    results = []

    # Bezrealitky používá GraphQL API
    url = "https://api.bezrealitky.cz/graphql/"

    query = """
    query AdvertList($offerType: OfferType, $estateType: [EstateType], $priceMax: Int, $disposition: [Disposition], $limit: Int, $order: ResultOrder) {
      listAdverts(
        offerType: $offerType
        estateType: $estateType
        priceMax: $priceMax
        disposition: $disposition
        limit: $limit
        order: $order
        regionOsmIds: ["R435514"]
      ) {
        list {
          id
          uri
          price
          estateType
          offerType
          disposition
          address {
            city
            district
            street
          }
        }
      }
    }
    """

    variables = {
        "offerType": "PRODEJ",
        "estateType": ["BYT"],
        "priceMax": 5000000,
        "disposition": ["DISP_1_KK", "DISP_1_1", "DISP_2_KK", "DISP_2_1"],
        "limit": 60,
        "order": "TIMEORDER_DESC",
    }

    headers_gql = {
        **HEADERS,
        "Content-Type": "application/json",
        "Origin": "https://www.bezrealitky.cz",
        "Referer": "https://www.bezrealitky.cz/",
    }

    try:
        r = requests.post(
            url,
            json={"query": query, "variables": variables},
            headers=headers_gql,
            timeout=15
        )
        r.raise_for_status()
        data = r.json()
        items = data.get("data", {}).get("listAdverts", {}).get("list", [])
        log.info(f"Bezrealitky: nalezeno {len(items)} inzerátů")

        for item in items:
            try:
                addr = item.get("address", {})
                city = addr.get("city", "")
                district = addr.get("district", "")
                location = f"{city}, {district}".strip(", ")

                price = int(item.get("price", 0) or 0)
                slug = item.get("uri", "")
                listing_url = f"https://www.bezrealitky.cz/nemovitosti-byty-domy/{slug}"

                disp_raw = item.get("disposition", "")
                disp_map = {
                    "DISP_1_KK": "1+kk", "DISP_1_1": "1+1",
                    "DISP_2_KK": "2+kk", "DISP_2_1": "2+1",
                }
                disposition = disp_map.get(disp_raw, disp_raw)
                title = f"Byt {disposition} – {city}"

                if is_banned(title) or is_banned(location):
                    continue
                if price > MAX_PRICE or price == 0:
                    continue
                if not is_valid_location(location):
                    continue

                listing_hash = make_id(listing_url)
                if is_duplicate(listing_hash):
                    continue

                listing = {
                    "id": listing_hash,
                    "title": title,
                    "price": price,
                    "location": location,
                    "url": listing_url,
                    "source": "Bezrealitky",
                    "disposition": disposition,
                }
                results.append(listing)
            except Exception as e:
                log.warning(f"Bezrealitky — chyba při parsování: {e}")

    except Exception as e:
        log.error(f"Bezrealitky — chyba při stahování: {e}")

    return results


# ─────────────────────────────────────────────
# SCRAPER: BAZOŠ
# ─────────────────────────────────────────────

def scrape_bazos() -> list:
    results = []

    # Bazoš reality — Středočeský kraj, byty, do 5M
    # Procházíme více stránek výsledků
    base_urls = [
        "https://reality.bazos.cz/byt/prodam/?hledat=&kraj=S&cena=0-5000000",
        "https://reality.bazos.cz/byt/prodam/20/?hledat=&kraj=S&cena=0-5000000",
        "https://reality.bazos.cz/byt/prodam/40/?hledat=&kraj=S&cena=0-5000000",
    ]

    for search_url in base_urls:
        try:
            r = SESSION.get(search_url, timeout=20)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            # Bazoš používá různé selektory
            ads = soup.select(".inzerat")
            if not ads:
                ads = soup.select("div[class*='inzerat']")
            log.info(f"Bazoš ({search_url[-30:]}): nalezeno {len(ads)} inzerátů")

            for ad in ads:
                try:
                    title_el = ad.select_one("h2 a, .nadpis a")
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)
                    href = title_el.get("href", "")
                    if not href.startswith("http"):
                        href = "https://reality.bazos.cz" + href

                    # Cena
                    price_el = ad.select_one(".inzeratycena b, b")
                    price_text = price_el.get_text(strip=True) if price_el else "0"
                    price = parse_price(price_text)

                    # Lokace
                    location_el = ad.select_one(".inzeratylok, .lokace")
                    location = location_el.get_text(strip=True) if location_el else ""
                    # Bazoš má formát "Praha - Středočeský kraj" nebo jen "Beroun"
                    if " - " in location:
                        location = location.split(" - ")[0].strip()

                    # Zkontroluj dispozici v názvu
                    disposition = ""
                    for d in DISPOSITIONS:
                        if d.lower() in title.lower():
                            disposition = d
                            break
                    if not disposition:
                        continue

                    if is_banned(title):
                        continue
                    if price > MAX_PRICE or price == 0:
                        continue
                    if not is_valid_location(location):
                        continue

                    listing_hash = make_id(href)
                    if is_duplicate(listing_hash):
                        continue

                    listing = {
                        "id": listing_hash,
                        "title": title,
                        "price": price,
                        "location": location,
                        "url": href,
                        "source": "Bazoš",
                        "disposition": disposition,
                    }
                    results.append(listing)
                except Exception as e:
                    log.warning(f"Bazoš — chyba při parsování inzerátu: {e}")

            time.sleep(2)  # pauza mezi stránkami

        except Exception as e:
            log.error(f"Bazoš — chyba při stahování {search_url}: {e}")

    return results


# ─────────────────────────────────────────────
# SCRAPER: REAS
# ─────────────────────────────────────────────

def scrape_reas() -> list:
    results = []

    # Reas.cz — byty k prodeji ve Středočeském kraji
    urls = [
        (
            "https://www.reas.cz/nemovitosti/byty/prodej/stredocesky-kraj"
            "?price_to=5000000"
            "&disposition[]=1%2Bkk&disposition[]=1%2B1"
            "&disposition[]=2%2Bkk&disposition[]=2%2B1"
            "&order=date_desc"
        ),
    ]

    for url in urls:
        try:
            r = SESSION.get(url, timeout=20)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            # Reas používá různé layouty — zkusíme více selektorů
            ads = (
                soup.select("div.property-listing-item") or
                soup.select("article.property") or
                soup.select(".listing-item") or
                soup.select("[class*='property-item']") or
                soup.select("li.result-item")
            )
            log.info(f"Reas: nalezeno {len(ads)} inzerátů")

            for ad in ads:
                try:
                    title_el = ad.select_one("a[href*='/nemovitosti/'], a[href*='/byt/'], h2 a, h3 a, .title a")
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)
                    href = title_el.get("href", "")
                    if not href.startswith("http"):
                        href = "https://www.reas.cz" + href

                    # Cena
                    price_el = ad.select_one("[class*='price'], [class*='cena'], strong")
                    price_text = price_el.get_text(strip=True) if price_el else "0"
                    price = parse_price(price_text)

                    # Lokace
                    location_el = ad.select_one("[class*='location'], [class*='locality'], [class*='place'], [class*='address']")
                    location = location_el.get_text(strip=True) if location_el else ""

                    disposition = ""
                    for d in DISPOSITIONS:
                        if d.lower() in title.lower():
                            disposition = d
                            break
                    if not disposition:
                        continue

                    if is_banned(title):
                        continue
                    if price > MAX_PRICE or price == 0:
                        continue
                    if not is_valid_location(location):
                        continue

                    listing_hash = make_id(href)
                    if is_duplicate(listing_hash):
                        continue

                    listing = {
                        "id": listing_hash,
                        "title": title,
                        "price": price,
                        "location": location,
                        "url": href,
                        "source": "Reas",
                        "disposition": disposition,
                    }
                    results.append(listing)
                except Exception as e:
                    log.warning(f"Reas — chyba při parsování inzerátu: {e}")

        except Exception as e:
            log.error(f"Reas — chyba při stahování: {e}")

    return results


# ─────────────────────────────────────────────
# HLAVNÍ LOGIKA
# ─────────────────────────────────────────────

def check_all_portals():
    log.info("═══════════════════════════════════════")
    log.info(f"Kontrola portálů: {datetime.now().strftime('%d.%m.%Y %H:%M')}")

    all_new = []

    scrapers = [
        scrape_sreality,
        scrape_bezrealitky,
        scrape_bazos,
        scrape_reas,
    ]

    for scraper in scrapers:
        try:
            listings = scraper()
            for listing in listings:
                save_listing(listing)
                all_new.append(listing)
            time.sleep(3)  # pauza mezi portály
        except Exception as e:
            log.error(f"Chyba ve scraperu {scraper.__name__}: {e}")

    log.info(f"Celkem nových inzerátů: {len(all_new)}")

    for listing in all_new:
        msg = format_listing_message(listing)
        send_telegram(msg)
        time.sleep(1)


def send_daily_summary():
    """Ranní souhrn v 8:00 — přehled nových za posledních 24h."""
    unsent = get_unsent_daily()
    if not unsent:
        send_telegram("☀️ <b>Ranní souhrn</b>\n\nŽádné nové inzeráty za posledních 24 hodin.")
        return

    header = f"☀️ <b>Ranní souhrn — {datetime.now().strftime('%d.%m.%Y')}</b>\n"
    header += f"📊 Nových inzerátů za 24h: <b>{len(unsent)}</b>\n\n"

    send_telegram(header)

    for row in unsent[:20]:  # max 20 v souhrnu
        title, price, location, url, source, disposition, found_at = row
        price_fmt = f"{price:,}".replace(",", " ")
        emoji = {"Sreality": "🏠", "Bezrealitky": "🔑", "Bazoš": "📦", "Reas": "🏢"}.get(source, "📍")
        msg = (
            f"{emoji} <b>{title}</b>\n"
            f"💰 {price_fmt} Kč | 🛏 {disposition}\n"
            f"📍 {location}\n"
            f"🔗 <a href=\"{url}\">{source}</a>"
        )
        send_telegram(msg)
        time.sleep(0.5)

    mark_all_sent_daily()
    log.info(f"Denní souhrn odeslán: {len(unsent)} inzerátů")


def main():
    log.info("🚀 Nemovitosti SCK scraper spuštěn")
    init_db()

    # Okamžitá první kontrola
    check_all_portals()

    # Plánování opakování
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(check_all_portals)
    schedule.every().day.at("08:00").do(send_daily_summary)

    log.info(f"Kontrola každých {CHECK_INTERVAL_MINUTES} minut")
    log.info("Denní souhrn ve 08:00")

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
