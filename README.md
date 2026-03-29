# 🏠 Nemovitosti Bot

Telegram bot pro sledování nových bytových inzerátů v **Kladně, Mělníku a Kralupech nad Vltavou**.
Automaticky kontroluje 4 realitní portály každých 15 minut a posílá notifikace o nových nabídkách.

## Funkce

- ✅ Sleduje: Sreality, Bezrealitky, iDnes Reality, Bazoš
- ✅ Filtry: lokalita, max. cena, dispozice (2+kk, 2+1)
- ✅ Deduplikace přes SQLite (žádné opakující se inzeráty)
- ✅ Strukturované Telegram notifikace s odkazem
- ✅ Rotující logy (info + error)
- ✅ Připraven pro Railway.app deploy

---

## Rychlý start (lokálně)

### 1. Klonování repozitáře

```bash
git clone https://github.com/TVUJ_USERNAME/nemovitosti-bot.git
cd nemovitosti-bot
```

### 2. Virtuální prostředí a závislosti

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/macOS
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Nastavení .env

```bash
cp .env.example .env
```

Otevři `.env` a vyplň:

```env
TELEGRAM_TOKEN=1234567890:ABC-tvuj-token
TELEGRAM_CHAT_ID=-1003647760694
```

> **Jak získat TOKEN:** Napiš [@BotFather](https://t.me/BotFather) → `/newbot` → zkopíruj token  
> **Jak získat CHAT_ID:** Přidej bota do skupiny, napiš zprávu, pak zavolej  
> `https://api.telegram.org/bot<TOKEN>/getUpdates`

### 4. Spuštění

```bash
python main.py
```

Bot se spustí, pošle startup zprávu do Telegramu a začne kontrolovat inzeráty.

---

## Konfigurace (.env)

| Proměnná | Výchozí | Popis |
|---|---|---|
| `TELEGRAM_TOKEN` | *(povinné)* | Token Telegram bota |
| `TELEGRAM_CHAT_ID` | *(povinné)* | ID cílového chatu / skupiny |
| `MAX_PRICE` | `5000000` | Maximální cena v Kč |
| `DISPOSITIONS` | `2+kk,2+1` | Dispozice oddělené čárkou |
| `LOCATIONS` | `Kladno,Mělník,Kralupy nad Vltavou` | Lokality oddělené čárkou |
| `CHECK_INTERVAL` | `900` | Interval kontroly v sekundách |
| `DB_PATH` | `data/listings.db` | Cesta k SQLite databázi |
| `LOG_LEVEL` | `INFO` | Úroveň logování (DEBUG/INFO/WARNING/ERROR) |
| `REQUEST_DELAY` | `2.0` | Prodleva mezi requesty (rate limiting) |
| `REQUEST_TIMEOUT` | `15` | HTTP timeout v sekundách |

### Přidání lokality

```env
LOCATIONS=Kladno,Mělník,Kralupy nad Vltavou,Neratovice
```

### Změna dispozic

```env
DISPOSITIONS=2+kk,2+1,3+kk
```

---

## Deploy na Railway.app

### 1. Příprava repozitáře

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/TVUJ_USERNAME/nemovitosti-bot.git
git push -u origin main
```

### 2. Vytvoření projektu na Railway

1. Jdi na [railway.app](https://railway.app) → **New Project**
2. Vyber **Deploy from GitHub repo**
3. Vyber svůj repozitář `nemovitosti-bot`
4. Railway automaticky detekuje `Procfile` a spustí `worker`

### 3. Nastavení environment proměnných

V Railway dashboardu → tvůj projekt → **Variables**:

```
TELEGRAM_TOKEN     = tvuj_bot_token
TELEGRAM_CHAT_ID   = -1003647760694
```

Ostatní proměnné jsou volitelné (mají výchozí hodnoty).

### 4. Ověření deploye

- Jdi na **Deployments** → zkontroluj logy
- Bot by měl poslat startup zprávu do Telegramu
- Ve Variables nastav `LOG_LEVEL=DEBUG` pro detailnější výpis

> **Důležité:** Railway ukládá data persistentně jen při použití Volume.  
> Bez Volume se SQLite databáze resetuje při každém redeployi.  
> Pro persistenci: Railway → tvůj projekt → **Add Volume** → nastav mount path na `/app/data`  
> a v `.env` nastav `DB_PATH=/app/data/listings.db`

---

## Struktura projektu

```
nemovitosti-bot/
├── main.py                  # Vstupní bod
├── Procfile                 # Railway worker definice
├── requirements.txt
├── .env.example
├── .gitignore
│
├── core/
│   ├── config.py            # Konfigurace z .env
│   ├── database.py          # SQLite (deduplikace)
│   ├── notifier.py          # Telegram odesílání
│   └── scheduler.py         # Orchestrace scraperů
│
├── scrapers/
│   ├── base.py              # Abstraktní základní třída
│   ├── sreality.py          # Sreality JSON API
│   ├── bezrealitky.py       # Bezrealitky GraphQL API
│   ├── idnes.py             # iDnes Reality scraper
│   └── bazos.py             # Bazoš scraper
│
├── utils/
│   └── logger.py            # Centrální logging + rotace
│
├── data/                    # SQLite DB (gitignore)
└── logs/                    # Log soubory (gitignore)
```

---

## Zdroje a přístup

| Portál | Metoda | Poznámka |
|---|---|---|
| Sreality | JSON API | Neoficiální API z frontendu |
| Bezrealitky | GraphQL API | Veřejné API bez klíče |
| iDnes Reality | HTML scraping | BeautifulSoup + lxml |
| Bazoš | HTML scraping | Filtruje dle dispozice z textu |

---

## Troubleshooting

**Bot se nespustí:**
```
ValueError: TELEGRAM_TOKEN není nastaven v .env!
```
→ Zkontroluj `.env` soubor, musí být ve stejném adresáři jako `main.py`

**Žádné inzeráty:**
- Nastav `LOG_LEVEL=DEBUG` pro detailní výpis
- Zkontroluj logy v `logs/bot.log`
- Portály mohou změnit HTML strukturu → otevři issue

**Scraper vrací chybu 403/429:**
- Zvyš `REQUEST_DELAY=5.0` v `.env`
- Portál může blokovat scraping

**Railway: databáze se resetuje:**
→ Přidej Volume (viz sekce Deploy)
