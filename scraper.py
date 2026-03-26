"""
Hlídač bytů — Středočeský kraj
Portály: Sreality (API), Bezrealitky (Playwright), Reas (Playwright)
"""

import os
import re
import time
import logging
import sqlite3
import schedule
import requests
from datetime import datetime

# Playwright — pro Bezrealitky a Reas (JS portály s anti-botem)
from playwright.sync_api import sync_playwright

# ─────────────────────────────────────────────────────────────
# KONFIGURACE
# ─────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

MAX_PRICE              = 5_000_000
CHECK_INTERVAL_MINUTES = 30
MORNING_SUMMARY_HOUR   = 8

# Dispozice — mapování na Sreality category_sub_cb
# 1+kk=2, 1+1=3, 2+kk=4, 2+1=5
SREALITY_DISPOSITIONS = [2, 3, 4, 5]
DISPOSITION_LABELS    = {2: "1+kk", 3: "1+1", 4: "2+kk", 5: "2+1"}

DB_PATH  = "nemovitosti.db"
LOG_PATH = "scraper.log"

# Klíčová slova → blokovat inzeráty (dražby, exekuce)
BLOCK_KEYWORDS = [
    "dražb", "exekuc", "insolvenc", "nucený prodej",
    "zástavní", "předkupní právo",
]

# ─────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# DATABÁZE
# ─────────────────────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS seen (
            id       TEXT PRIMARY KEY,
            zdroj    TEXT,
            nadpis   TEXT,
            cena     TEXT,
            url      TEXT,
            pridano  TEXT
        )
    """)
    con.commit()
    con.close()


def is_new(listing_id: str) -> bool:
    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT 1 FROM seen WHERE id=?", (listing_id,)).fetchone()
    con.close()
    return row is None


def mark_seen(listing_id: str, zdroj: str, nadpis: str, cena: str, url: str):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT OR IGNORE INTO seen VALUES (?,?,?,?,?,?)",
        (listing_id, zdroj, nadpis, cena, url, datetime.now().isoformat()),
    )
    con.commit()
    con.close()


def get_todays_listings():
    today = datetime.now().strftime("%Y-%m-%d")
    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT zdroj, nadpis, cena, url FROM seen WHERE pridano LIKE ?",
        (f"{today}%",),
    ).fetchall()
    con.close()
    return rows


# ─────────────────────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────────────────────
def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram není nakonfigurován.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=10,
        )
        if not r.ok:
            log.error("Telegram chyba: %s", r.text)
    except Exception as e:
        log.error("Telegram výjimka: %s", e)


def notify(listing: dict):
    """Pošle notifikaci o novém inzerátu."""
    msg = (
        f"🏠 <b>{listing['nadpis']}</b>\n"
        f"💰 {listing['cena']}\n"
        f"📍 {listing.get('lokalita', '—')}\n"
        f"🔗 <a href=\"{listing['url']}\">Zobrazit inzerát</a>\n"
        f"📡 {listing['zdroj']}"
    )
    send_telegram(msg)


# ─────────────────────────────────────────────────────────────
# POMOCNÉ FUNKCE
# ─────────────────────────────────────────────────────────────
def is_blocked(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in BLOCK_KEYWORDS)


def process(listing: dict):
    """Zkontroluje duplicitu a odešle notifikaci."""
    lid = listing["id"]
    if not is_new(lid):
        return
    mark_seen(lid, listing["zdroj"], listing["nadpis"], listing["cena"], listing["url"])
    notify(listing)
    log.info("Nový inzerát [%s]: %s — %s", listing["zdroj"], listing["nadpis"], listing["cena"])


# ─────────────────────────────────────────────────────────────
# SREALITY  (JSON API — čisté requests, bez Playwright)
#
# OPRAVA 1: locality_region_id=10 je Středočeský kraj ✓
#           (původní kód byl správný, Praha by byla =11 — necháme 10)
#
# OPRAVA 2: _sreality_url() — category_sub_cb není v seo{},
#           ale přímo v kořenu objektu estate jako "type" nebo
#           v poli "seo.category_sub_cb" — správně čteme z
#           estate["type"]["value"] nebo jako fallback z názvu.
#           Nejspolehlivější: číst sub_cb přímo z estate dict.
# ─────────────────────────────────────────────────────────────
SREALITY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "cs,en;q=0.9",
    "Referer": "https://www.sreality.cz/",
}

# locality_region_id=10 = Středočeský kraj (Praha = 11, záměrně vynecháno)
SREALITY_API = (
    "https://www.sreality.cz/api/cs/v2/estates"
    "?category_main_cb=1"          # byty
    "&category_type_cb=1"          # prodej
    "&locality_region_id=10"       # Středočeský kraj BEZ Prahy
    "&price_max={price_max}"
    "&category_sub_cb={subs}"
    "&per_page=60"
    "&page={page}"
)

# FIX: Správný slovník slug → musí odpovídat tomu co Sreality čeká v URL
# Formát detailu: /detail/prodej/byt/2+1/lokalita/hash_id
# Sreality používá "2+1" (s plusem), ne "2%2B1"
DISPOSITION_SLUGS = {2: "1+kk", 3: "1+1", 4: "2+kk", 5: "2+1"}


def _sreality_url(estate: dict) -> str:
    """
    Sestaví klikatelné URL detailu ze slovníku inzerátu.

    OPRAVA: category_sub_cb není v seo{} — je přímo v estate dict
    pod klíčem "type" (nested) nebo jako samostatné pole.
    Bezpečně ho extrahujeme ze všech možných míst.

    Správný formát URL:
      https://www.sreality.cz/detail/prodej/byt/2+kk/stredocesky-kraj-Praha-vychod-ricany/123456789
    """
    hash_id = estate.get("hash_id", "")
    locality = estate.get("seo", {}).get("locality", "")

    # FIX: sub_cb čteme z kořene estate dict, ne z seo{}
    # API vrací např. estate["type"]["value"] = 4  nebo  estate["category_sub_cb"] = 4
    sub_cb = (
        estate.get("category_sub_cb")                          # přímé pole (někdy přítomno)
        or estate.get("type", {}).get("value")                 # nested type objekt
        or _guess_sub_cb_from_name(estate.get("name", ""))     # fallback z názvu
        or 4                                                    # poslední záchrana = 2+kk
    )

    disp_slug = DISPOSITION_SLUGS.get(int(sub_cb), "byt")

    return f"https://www.sreality.cz/detail/prodej/byt/{disp_slug}/{locality}/{hash_id}"


def _guess_sub_cb_from_name(name: str) -> int | None:
    """Odhadne dispozici z názvu inzerátu jako záložní řešení."""
    name_lower = name.lower()
    if "1+kk" in name_lower: return 2
    if "1+1"  in name_lower: return 3
    if "2+kk" in name_lower: return 4
    if "2+1"  in name_lower: return 5
    return None


def scrape_sreality():
    log.info("Scrapuji Sreality…")
    subs = "|".join(str(s) for s in SREALITY_DISPOSITIONS)
    found = 0

    for page in range(1, 6):   # max 5 stránek = 300 inzerátů
        url = SREALITY_API.format(
            price_max=MAX_PRICE,
            subs=subs,
            page=page,
        )
        try:
            r = requests.get(url, headers=SREALITY_HEADERS, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.error("Sreality API chyba (strana %d): %s", page, e)
            break

        estates = data.get("_embedded", {}).get("estates", [])
        if not estates:
            break

        for e in estates:
            nadpis = e.get("name", "").strip()
            if is_blocked(nadpis):
                continue

            cena_raw = e.get("price", 0)
            if cena_raw and cena_raw > MAX_PRICE:
                continue

            cena = f"{cena_raw:,} Kč".replace(",", "\u00a0") if cena_raw else "Cena neuvedena"
            detail_url = _sreality_url(e)
            locality = e.get("seo", {}).get("locality", "")
            hash_id = str(e.get("hash_id", ""))

            listing = {
                "id": f"sreality_{hash_id}",
                "zdroj": "Sreality",
                "nadpis": nadpis,
                "cena": cena,
                "lokalita": locality.replace("-", " ").title() if locality else "",
                "url": detail_url,
            }
            process(listing)
            found += 1

        # Zkontroluj, jestli je další stránka
        total = data.get("result_size", 0)
        if page * 60 >= total:
            break

        time.sleep(1)

    log.info("Sreality hotovo — %d inzerátů.", found)


# ─────────────────────────────────────────────────────────────
# BEZREALITKY  (Playwright — Cloudflare ochrana)
#
# OPRAVA 3: Přidán OSM region ID pro Středočeský kraj.
#           R439353 = Středočeský kraj ✓  (Praha = R435514, záměrně vynecháno)
#
# OPRAVA 4: Dispozice v URL — Bezrealitky používá jiné hodnoty:
#           DISP_1_KK=1, DISP_1_1=2, DISP_2_KK=3, DISP_2_1=4
#           Předáváme jako disposition[]=DISP_X_XX ve správném formátu.
# ─────────────────────────────────────────────────────────────
BEZ_URL = (
    "https://www.bezrealitky.cz/nemovitosti-byty-domy"
    "?offerType=prodej"
    "&estateType=byt"
    "&regionOsmIds=R439353"        # Středočeský kraj (bez Prahy R435514)
    f"&priceMax={MAX_PRICE}"
    # FIX: správné hodnoty dispozic pro Bezrealitky
    "&disposition%5B%5D=DISP_1_KK"
    "&disposition%5B%5D=DISP_1_1"
    "&disposition%5B%5D=DISP_2_KK"
    "&disposition%5B%5D=DISP_2_1"
    "&currency=czk"
)


def scrape_bezrealitky(page):
    """Scrape Bezrealitky přes Playwright page objekt."""
    log.info("Scrapuji Bezrealitky…")
    found = 0

    try:
        page.goto(BEZ_URL, wait_until="domcontentloaded", timeout=30_000)
        # Počkej na výpis inzerátů
        page.wait_for_selector("article", timeout=15_000)
    except Exception as e:
        log.error("Bezrealitky načítání: %s", e)
        return

    articles = page.query_selector_all("article")
    log.info("Bezrealitky — nalezeno %d articleů", len(articles))

    for art in articles:
        try:
            # Nadpis
            h2 = art.query_selector("h2, h3, [class*='title']")
            nadpis = h2.inner_text().strip() if h2 else ""

            if not nadpis or is_blocked(nadpis):
                continue

            # Cena
            cena_el = art.query_selector("[class*='price'], [class*='cena']")
            cena = cena_el.inner_text().strip() if cena_el else "Cena neuvedena"

            # URL
            a_el = art.query_selector("a[href]")
            href = a_el.get_attribute("href") if a_el else ""
            if not href:
                continue
            if href.startswith("/"):
                href = "https://www.bezrealitky.cz" + href
            if "bezrealitky.cz" not in href:
                continue

            # ID z URL
            m = re.search(r"/(\d{5,})", href)
            lid = f"bezrealitky_{m.group(1)}" if m else f"bezrealitky_{hash(href)}"

            # Lokalita
            loc_el = art.query_selector("[class*='location'], [class*='address'], [class*='lokalit']")
            lokalita = loc_el.inner_text().strip() if loc_el else ""

            listing = {
                "id": lid,
                "zdroj": "Bezrealitky",
                "nadpis": nadpis,
                "cena": cena,
                "lokalita": lokalita,
                "url": href,
            }
            process(listing)
            found += 1

        except Exception as e:
            log.debug("Bezrealitky item chyba: %s", e)
            continue

    log.info("Bezrealitky hotovo — %d inzerátů.", found)


# ─────────────────────────────────────────────────────────────
# REAS  (Playwright — React SPA)
#
# OPRAVA 5: Dispozice v URL byly špatně enkódované.
#           Reas používá hodnoty: 1kk, 1_1, 2kk, 2_1
#           (bez plus znaků — plus v URL způsoboval ignorování filtru)
# ─────────────────────────────────────────────────────────────
REAS_URL = (
    "https://www.reas.cz/vyhledavani"
    "?typ=prodej"
    "&kategorie=byt"
    "&kraj=stredocesky"            # Středočeský kraj (Praha záměrně vynecháno)
    f"&cenaMax={MAX_PRICE}"
    # FIX: správné hodnoty dispozic pro Reas (bez %2B enkódování)
    "&dispozice[]=1kk"
    "&dispozice[]=1_1"
    "&dispozice[]=2kk"
    "&dispozice[]=2_1"
)


def scrape_reas(page):
    """Scrape Reas.cz přes Playwright page objekt."""
    log.info("Scrapuji Reas…")
    found = 0

    try:
        page.goto(REAS_URL, wait_until="networkidle", timeout=40_000)
        page.wait_for_selector(
            "[class*='PropertyCard'], [class*='property-card'], [class*='listing'], article",
            timeout=20_000,
        )
    except Exception as e:
        log.error("Reas načítání: %s", e)
        return

    # Zkus více možných selektorů karet
    cards = (
        page.query_selector_all("[class*='PropertyCard']")
        or page.query_selector_all("[class*='property-card']")
        or page.query_selector_all("article")
    )
    log.info("Reas — nalezeno %d karet", len(cards))

    for card in cards:
        try:
            # Nadpis
            h_el = card.query_selector("h2, h3, [class*='title'], [class*='nadpis']")
            nadpis = h_el.inner_text().strip() if h_el else ""
            if not nadpis or is_blocked(nadpis):
                continue

            # Cena
            price_el = card.query_selector("[class*='price'], [class*='cena'], [class*='Price']")
            cena = price_el.inner_text().strip() if price_el else "Cena neuvedena"

            # URL
            a_el = card.query_selector("a[href]")
            href = a_el.get_attribute("href") if a_el else ""
            if not href:
                continue
            if href.startswith("/"):
                href = "https://www.reas.cz" + href

            m = re.search(r"/(\d{4,})", href)
            lid = f"reas_{m.group(1)}" if m else f"reas_{hash(href)}"

            loc_el = card.query_selector("[class*='location'], [class*='address'], [class*='lokalit']")
            lokalita = loc_el.inner_text().strip() if loc_el else ""

            listing = {
                "id": lid,
                "zdroj": "Reas",
                "nadpis": nadpis,
                "cena": cena,
                "lokalita": lokalita,
                "url": href,
            }
            process(listing)
            found += 1

        except Exception as e:
            log.debug("Reas item chyba: %s", e)
            continue

    log.info("Reas hotovo — %d inzerátů.", found)


# ─────────────────────────────────────────────────────────────
# RANNÍ SOUHRN
# ─────────────────────────────────────────────────────────────
def morning_summary():
    rows = get_todays_listings()
    if not rows:
        send_telegram("🌅 Ranní souhrn: Dnes zatím žádné nové inzeráty.")
        return

    lines = [f"🌅 <b>Ranní souhrn — {datetime.now().strftime('%d.%m.%Y')}</b>"]
    lines.append(f"Celkem dnes nalezeno: <b>{len(rows)}</b> inzerátů\n")

    for zdroj, nadpis, cena, url in rows[:15]:
        lines.append(f"• [{zdroj}] {nadpis} — {cena}\n  <a href=\"{url}\">odkaz</a>")

    if len(rows) > 15:
        lines.append(f"\n…a dalších {len(rows) - 15} inzerátů.")

    send_telegram("\n".join(lines))


# ─────────────────────────────────────────────────────────────
# HLAVNÍ CYKLUS
# ─────────────────────────────────────────────────────────────
def run_all():
    log.info("=== Spouštím kontrolu ===")

    # Sreality jede přes requests — bez Playwright
    try:
        scrape_sreality()
    except Exception as e:
        log.error("Sreality selhal: %s", e)

    # Bezrealitky + Reas jedou v jednom Playwright kontextu
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="cs-CZ",
                viewport={"width": 1280, "height": 800},
            )

            # Bezrealitky
            try:
                page = context.new_page()
                scrape_bezrealitky(page)
                page.close()
            except Exception as e:
                log.error("Bezrealitky selhal: %s", e)

            # Reas
            try:
                page = context.new_page()
                scrape_reas(page)
                page.close()
            except Exception as e:
                log.error("Reas selhal: %s", e)

            browser.close()

    except Exception as e:
        log.error("Playwright selhal: %s", e)

    log.info("=== Kontrola dokončena ===")


def main():
    init_db()
    log.info("Hlídač bytů spuštěn.")

    # Spusť hned při startu
    run_all()

    # Naplánuj opakování
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(run_all)
    schedule.every().day.at(f"{MORNING_SUMMARY_HOUR:02d}:00").do(morning_summary)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
