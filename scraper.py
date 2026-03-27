"""
Hlídač bytů — Středočeský kraj
Portály: Sreality (API), Bezrealitky (requests+BS4), Bazoš (requests+BS4), Reas (Playwright)
"""

import os
import re
import time
import logging
import sqlite3
import schedule
import requests
from bs4 import BeautifulSoup
from datetime import datetime

from playwright.sync_api import sync_playwright

# ─────────────────────────────────────────────────────────────
# KONFIGURACE
# ─────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

MAX_PRICE              = 4_500_000      # ← opraveno na 4,5M
CHECK_INTERVAL_MINUTES = 30
MORNING_SUMMARY_HOUR   = 8

# Dispozice — mapování na Sreality category_sub_cb
# 1+kk=2, 1+1=3, 2+kk=4, 2+1=5
SREALITY_DISPOSITIONS = [2, 3, 4, 5]
DISPOSITION_LABELS    = {2: "1+kk", 3: "1+1", 4: "2+kk", 5: "2+1"}

DB_PATH  = "nemovitosti.db"
LOG_PATH = "scraper.log"

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
        log.warning("Telegram není nakonfigurován — nastav TELEGRAM_TOKEN a TELEGRAM_CHAT_ID.")
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
            log.error("Telegram chyba %s: %s", r.status_code, r.text)
    except Exception as e:
        log.error("Telegram výjimka: %s", e)


def notify(listing: dict):
    """Pošle notifikaci o novém inzerátu."""
    msg = (
        f"🏠 <b>{listing['nadpis']}</b>\n"
        f"💰 {listing['cena']}\n"
        f"📍 {listing.get('lokalita', '—')}\n"
        f"🔗 {listing['url']}\n"
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
    try:
        lid = listing["id"]
        if not is_new(lid):
            return
        mark_seen(lid, listing["zdroj"], listing["nadpis"], listing["cena"], listing["url"])
        notify(listing)
        log.info("Nový inzerát [%s]: %s — %s", listing["zdroj"], listing["nadpis"], listing["cena"])
    except Exception as e:
        log.error("process() chyba: %s", e)


COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "cs,en;q=0.9",
}


# ─────────────────────────────────────────────────────────────
# SREALITY  (JSON API)
#
# FIX: URL detailu je jednoduše:
#   https://www.sreality.cz/detail/prodej/byt/<hash_id>
# Složitý formát s dispozicí a lokalitou v cestě způsoboval 404.
# ─────────────────────────────────────────────────────────────
SREALITY_HEADERS = {
    **COMMON_HEADERS,
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.sreality.cz/",
}

SREALITY_API = (
    "https://www.sreality.cz/api/cs/v2/estates"
    "?category_main_cb=1"          # byty
    "&category_type_cb=1"          # prodej
    "&locality_region_id=10"       # Středočeský kraj (Praha=11, záměrně vynecháno)
    "&price_max={price_max}"
    "&category_sub_cb={subs}"
    "&per_page=60"
    "&page={page}"
)


def scrape_sreality():
    log.info("Scrapuji Sreality…")
    subs = "|".join(str(s) for s in SREALITY_DISPOSITIONS)
    found = 0

    for page in range(1, 6):
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
            if not nadpis or is_blocked(nadpis):
                continue

            cena_raw = e.get("price", 0)
            if cena_raw and cena_raw > MAX_PRICE:
                continue

            cena = f"{cena_raw:,} Kč".replace(",", "\u00a0") if cena_raw else "Cena neuvedena"
            hash_id = str(e.get("hash_id", ""))

            # FIX: správný formát URL — jen hash_id stačí
            detail_url = f"https://www.sreality.cz/detail/prodej/byt/{hash_id}"

            locality = e.get("seo", {}).get("locality", "")
            # Pokus o hezčí lokalitu z GPS/name
            lokalita = locality.replace("-", " ").title() if locality else ""

            listing = {
                "id": f"sreality_{hash_id}",
                "zdroj": "Sreality",
                "nadpis": nadpis,
                "cena": cena,
                "lokalita": lokalita,
                "url": detail_url,
            }
            process(listing)
            found += 1

        total = data.get("result_size", 0)
        if page * 60 >= total:
            break

        time.sleep(1)

    log.info("Sreality hotovo — %d inzerátů.", found)


# ─────────────────────────────────────────────────────────────
# BEZREALITKY  (requests + BeautifulSoup)
#
# Nahrazeno Playwright → requests, protože Cloudflare blokoval
# headless prohlížeč. API endpoint je veřejně přístupný.
# regionOsmIds=R439353 = Středočeský kraj (Praha R435514 vynecháno)
# ─────────────────────────────────────────────────────────────
BEZ_API = (
    "https://www.bezrealitky.cz/api/record/markers"
    "?offerType=prodej"
    "&estateType=byt"
    "&regionOsmIds=R439353"
    f"&priceMax={MAX_PRICE}"
    "&disposition[]=DISP_1_KK"
    "&disposition[]=DISP_1_1"
    "&disposition[]=DISP_2_KK"
    "&disposition[]=DISP_2_1"
    "&limit=200"
)

BEZ_DETAIL_API = "https://www.bezrealitky.cz/nemovitosti-byty-domy/{slug}"


def scrape_bezrealitky():
    """Scrape Bezrealitky přes jejich JSON API endpoint."""
    log.info("Scrapuji Bezrealitky…")
    found = 0

    try:
        headers = {
            **COMMON_HEADERS,
            "Accept": "application/json",
            "Referer": "https://www.bezrealitky.cz/",
        }
        r = requests.get(BEZ_API, headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.error("Bezrealitky API chyba: %s", e)
        # Fallback — zkus scrape stránky
        _scrape_bezrealitky_html()
        return

    # API vrací seznam markerů nebo seznam inzerátů
    items = data if isinstance(data, list) else data.get("records", data.get("items", []))
    log.info("Bezrealitky API — %d položek", len(items))

    for item in items:
        try:
            # Různé formáty odpovědi
            lid_raw = item.get("id") or item.get("hashId") or item.get("slug", "")
            if not lid_raw:
                continue
            lid = f"bezrealitky_{lid_raw}"

            slug = item.get("uri") or item.get("slug") or str(lid_raw)
            url = f"https://www.bezrealitky.cz/nemovitosti-byty-domy/{slug}"

            nadpis = item.get("name") or item.get("title") or slug
            if is_blocked(nadpis):
                continue

            price_raw = item.get("price") or item.get("priceAmount") or 0
            if price_raw and int(price_raw) > MAX_PRICE:
                continue
            cena = f"{int(price_raw):,} Kč".replace(",", "\u00a0") if price_raw else "Cena neuvedena"

            lokalita = item.get("address") or item.get("city") or item.get("location") or ""

            listing = {
                "id": lid,
                "zdroj": "Bezrealitky",
                "nadpis": nadpis,
                "cena": cena,
                "lokalita": str(lokalita),
                "url": url,
            }
            process(listing)
            found += 1

        except Exception as e:
            log.debug("Bezrealitky item chyba: %s", e)

    log.info("Bezrealitky hotovo — %d inzerátů.", found)


def _scrape_bezrealitky_html():
    """Fallback: scrape Bezrealitky HTML stránky."""
    BEZ_URL = (
        "https://www.bezrealitky.cz/nemovitosti-byty-domy"
        "?offerType=prodej"
        "&estateType=byt"
        "&regionOsmIds=R439353"
        f"&priceMax={MAX_PRICE}"
        "&disposition%5B%5D=DISP_1_KK"
        "&disposition%5B%5D=DISP_1_1"
        "&disposition%5B%5D=DISP_2_KK"
        "&disposition%5B%5D=DISP_2_1"
    )
    try:
        r = requests.get(BEZ_URL, headers=COMMON_HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "lxml")
        articles = soup.find_all("article")
        log.info("Bezrealitky HTML — %d articleů", len(articles))

        for art in articles:
            try:
                a_el = art.find("a", href=True)
                if not a_el:
                    continue
                href = a_el["href"]
                if href.startswith("/"):
                    href = "https://www.bezrealitky.cz" + href

                m = re.search(r"/(\d{5,})", href)
                lid = f"bezrealitky_{m.group(1)}" if m else f"bezrealitky_{hash(href)}"

                nadpis = art.find(["h2", "h3"])
                nadpis = nadpis.get_text(strip=True) if nadpis else href
                if is_blocked(nadpis):
                    continue

                cena_el = art.find(class_=re.compile(r"price|cena", re.I))
                cena = cena_el.get_text(strip=True) if cena_el else "Cena neuvedena"

                loc_el = art.find(class_=re.compile(r"locat|addres|lokalit", re.I))
                lokalita = loc_el.get_text(strip=True) if loc_el else ""

                process({
                    "id": lid,
                    "zdroj": "Bezrealitky",
                    "nadpis": nadpis,
                    "cena": cena,
                    "lokalita": lokalita,
                    "url": href,
                })
            except Exception as e:
                log.debug("Bezrealitky HTML item: %s", e)
    except Exception as e:
        log.error("Bezrealitky HTML fallback chyba: %s", e)


# ─────────────────────────────────────────────────────────────
# BAZOŠ  (requests + BeautifulSoup)
#
# Středočeský kraj = kraj=st (kód pro Středočeský)
# Kategorie 3110 = byty na prodej
# Filtry: cena do MAX_PRICE, dispozice v nadpisu
# ─────────────────────────────────────────────────────────────
BAZOS_DISPOSITIONS_RE = re.compile(
    r"\b(1\s*\+\s*kk|1\s*\+\s*1|2\s*\+\s*kk|2\s*\+\s*1)\b", re.IGNORECASE
)

# Bazoš Středočeský kraj = kraj ID 2
# URL pro byty k prodeji ve Středočeském kraji
BAZOS_PAGES = [
    f"https://reality.bazos.cz/byt/?kraj=2&cena2={MAX_PRICE}&hledej=Hledat",
    f"https://reality.bazos.cz/byt/?kraj=2&cena2={MAX_PRICE}&hledej=Hledat&order=2",
]


def scrape_bazos():
    """Scrape Bazoš reality — byty ve Středočeském kraji."""
    log.info("Scrapuji Bazoš…")
    found = 0

    for page_url in BAZOS_PAGES:
        try:
            r = requests.get(page_url, headers=COMMON_HEADERS, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
        except Exception as e:
            log.error("Bazoš chyba (%s): %s", page_url, e)
            continue

        inzeraty = soup.find_all("div", class_=re.compile(r"inzeraty", re.I))
        if not inzeraty:
            # zkus alternativní selektory
            inzeraty = soup.find_all("div", class_=re.compile(r"maincontent|list", re.I))

        log.info("Bazoš — nalezeno %d sekcí na %s", len(inzeraty), page_url)

        # Hledej každý inzerát
        items = soup.find_all("div", class_=re.compile(r"^inz$|inzerat(?!y)", re.I))
        if not items:
            items = soup.select("div.maincontent div.inzeraty")
        if not items:
            # Nejagresivnější fallback — všechny divy s odkazem na detail
            items = [a.parent for a in soup.find_all("a", href=re.compile(r"/inzerat/\d+"))]

        for item in items:
            try:
                a_el = item.find("a", href=re.compile(r"/inzerat/\d+")) if hasattr(item, "find") else item
                if not a_el:
                    continue

                href = a_el.get("href", "")
                if not href:
                    continue
                if not href.startswith("http"):
                    href = "https://reality.bazos.cz" + href

                m = re.search(r"/inzerat/(\d+)", href)
                if not m:
                    continue
                lid = f"bazos_{m.group(1)}"

                # Nadpis
                nadpis_el = item.find(["h2", "h3", "strong"]) if hasattr(item, "find") else None
                nadpis = nadpis_el.get_text(strip=True) if nadpis_el else a_el.get_text(strip=True)
                if not nadpis or is_blocked(nadpis):
                    continue

                # Filtr dispozice
                if not BAZOS_DISPOSITIONS_RE.search(nadpis):
                    continue

                # Cena
                cena_el = item.find(class_=re.compile(r"cena|price", re.I)) if hasattr(item, "find") else None
                cena = cena_el.get_text(strip=True) if cena_el else "Cena neuvedena"

                # Vyfiltruj ceny nad limit (pokud je v textu číslo)
                price_nums = re.findall(r"[\d\s]+", cena.replace("\xa0", ""))
                for pn in price_nums:
                    pn_clean = pn.replace(" ", "").strip()
                    if pn_clean.isdigit() and int(pn_clean) > MAX_PRICE:
                        nadpis = ""  # označíme jako přeskočitelný
                        break
                if not nadpis:
                    continue

                # Lokalita
                loc_el = item.find(class_=re.compile(r"locat|region|kraj|adresa", re.I)) if hasattr(item, "find") else None
                lokalita = loc_el.get_text(strip=True) if loc_el else "Středočeský kraj"

                listing = {
                    "id": lid,
                    "zdroj": "Bazoš",
                    "nadpis": nadpis,
                    "cena": cena,
                    "lokalita": lokalita,
                    "url": href,
                }
                process(listing)
                found += 1

            except Exception as e:
                log.debug("Bazoš item chyba: %s", e)
                continue

        time.sleep(1)

    log.info("Bazoš hotovo — %d inzerátů.", found)


# ─────────────────────────────────────────────────────────────
# REAS  (Playwright — React SPA)
# ─────────────────────────────────────────────────────────────
REAS_URL = (
    "https://www.reas.cz/vyhledavani"
    "?typ=prodej"
    "&kategorie=byt"
    "&kraj=stredocesky"
    f"&cenaMax={MAX_PRICE}"
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

    cards = (
        page.query_selector_all("[class*='PropertyCard']")
        or page.query_selector_all("[class*='property-card']")
        or page.query_selector_all("article")
    )
    log.info("Reas — nalezeno %d karet", len(cards))

    for card in cards:
        try:
            h_el = card.query_selector("h2, h3, [class*='title'], [class*='nadpis']")
            nadpis = h_el.inner_text().strip() if h_el else ""
            if not nadpis or is_blocked(nadpis):
                continue

            price_el = card.query_selector("[class*='price'], [class*='cena'], [class*='Price']")
            cena = price_el.inner_text().strip() if price_el else "Cena neuvedena"

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
        lines.append(f"• [{zdroj}] {nadpis} — {cena}\n  {url}")

    if len(rows) > 15:
        lines.append(f"\n…a dalších {len(rows) - 15} inzerátů.")

    send_telegram("\n".join(lines))


# ─────────────────────────────────────────────────────────────
# HLAVNÍ CYKLUS
# ─────────────────────────────────────────────────────────────
def run_all():
    log.info("=== Spouštím kontrolu ===")

    try:
        scrape_sreality()
    except Exception as e:
        log.error("Sreality selhal: %s", e)

    try:
        scrape_bezrealitky()
    except Exception as e:
        log.error("Bezrealitky selhal: %s", e)

    try:
        scrape_bazos()
    except Exception as e:
        log.error("Bazoš selhal: %s", e)

    # Reas běží v Playwright
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
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
    log.info("Hlídač bytů spuštěn. Max cena: %s Kč", f"{MAX_PRICE:,}")

    run_all()

    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(run_all)
    schedule.every().day.at(f"{MORNING_SUMMARY_HOUR:02d}:00").do(morning_summary)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
