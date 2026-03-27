# 🏠 Reality Bot

Telegram bot pro automatické sledování nových inzerátů nemovitostí ve **Středočeském kraji** (mimo Prahu) do **4 500 000 Kč**.

Kontroluje každých **15 minut** tyto weby:
- sreality.cz (přes JSON API)
- bazos.cz
- realingo.cz
- reas.cz
- reality.idnes.cz

---

## 📋 Požadavky

- Python 3.11+
- Telegram Bot token (z BotFather)
- Chat ID vašeho Telegram účtu

---

## 🚀 Rychlé spuštění

### 1. Klonování repozitáře

```bash
git clone <url-repozitare>
cd reality-bot
```

### 2. Nastavení virtuálního prostředí

```bash
python -m venv .venv
source .venv/bin/activate      # Linux/macOS
# nebo
.venv\Scripts\activate         # Windows
```

### 3. Instalace závislostí

```bash
pip install -r requirements.txt
```

### 4. Nastavení Telegram tokenu

Vytvořte soubor `.env` (nebo upravte existující):

```env
TELEGRAM_TOKEN=váš_token_z_botfather
TELEGRAM_CHAT_ID=váš_chat_id
```

**Jak získat token:**
1. Otevřete Telegram a najděte `@BotFather`
2. Pošlete `/newbot` a postupujte podle instrukcí
3. Token zkopírujte do `.env`

**Jak zjistit Chat ID:**
1. Spusťte bota bez `TELEGRAM_CHAT_ID`
2. Pošlete botovi `/start`
3. Bot si Chat ID uloží automaticky
   *(nebo použijte @userinfobot)*

### 5. Spuštění

```bash
python main.py
```

### 6. Aktivace v Telegramu

Pošlete botovi příkaz `/start`.

---

## 🐳 Docker

```bash
# Sestavení image
docker build -t reality-bot .

# Spuštění (data se ukládají do volume)
docker run -d \
  --name reality-bot \
  --env-file .env \
  -v reality-bot-data:/app/data \
  --restart unless-stopped \
  reality-bot

# Logy
docker logs -f reality-bot
```

---

## ⚙️ Konfigurace

Úpravou `config.yaml` lze změnit:

```yaml
# Interval kontroly (sekundy)
check_interval: 900          # 15 minut

# Maximální cena
max_price: 4500000

# Zapnout/vypnout jednotlivé zdroje
scrapers:
  sreality: true
  bazos: true
  realingo: true
  reas: true
  idnes: true
```

---

## 📱 Telegram příkazy

| Příkaz | Popis |
|--------|-------|
| `/start` | Spustí sledování inzerátů |
| `/stop` | Zastaví sledování |
| `/status` | Zobrazí statistiky (počet nalezených, odeslaných) |

---

## ➕ Jak přidat nový zdroj

1. Vytvořte nový soubor `scrapers/novy_web.py`
2. Dědičnost z `BaseScraper`, nastavte `SOURCE_NAME`
3. Implementujte metodu `fetch_listings() -> List[Listing]`

```python
from scrapers.base import BaseScraper, Listing
from typing import List

class NovyWebScraper(BaseScraper):
    SOURCE_NAME = "novy_web"

    def fetch_listings(self) -> List[Listing]:
        response = self.get("https://novy-web.cz/domy")
        # ... parsování HTML/JSON ...
        return [
            Listing(
                source=self.SOURCE_NAME,
                external_id="unikatni-id",
                url="https://...",
                title="Rodinný dům",
                price=3_500_000,
                location="Kladno",
            )
        ]
```

4. Přidejte do `scrapers/__init__.py`:
   ```python
   from scrapers.novy_web import NovyWebScraper
   ```

5. Přidejte do `main.py` do `build_scrapers()`:
   ```python
   "novy_web": NovyWebScraper,
   ```

6. Přidejte do `config.yaml`:
   ```yaml
   scrapers:
     novy_web: true
   ```

---

## 📂 Struktura projektu

```
reality-bot/
├── main.py          # Hlavní runner (scheduler + Telegram bot)
├── database.py      # SQLite vrstva (deduplikace inzerátů)
├── notifier.py      # Telegram odesílání
├── config.yaml      # Konfigurace (lokality, cena, zdroje)
├── .env             # Tajné klíče (NENAHRÁVAT NA GIT!)
├── .gitignore
├── Dockerfile
├── requirements.txt
├── README.md
├── scrapers/
│   ├── __init__.py
│   ├── base.py      # Abstraktní základní třída
│   ├── sreality.py  # sreality.cz (JSON API)
│   ├── bazos.py     # bazos.cz (scraping)
│   ├── realingo.py  # realingo.cz (scraping)
│   ├── reas.py      # reas.cz (scraping)
│   └── idnes.py     # reality.idnes.cz (scraping)
└── data/
    └── listings.db  # SQLite databáze
```

---

## ⚠️ Právní upozornění

- **sreality.cz** – Bot používá neoficiální JSON API (není zaručena stabilita)
- **Ostatní weby** – Scraping může porušovat podmínky použití daných webů
- Bot je určen **pouze pro osobní použití**
- Bot respektuje servery: náhodné pauzy mezi requesty, slušný User-Agent

---

## 🔍 Logování

Logy se zobrazují v terminálu a ukládají do `reality-bot.log`.

Úroveň logování lze změnit v `main.py`:
```python
logging.basicConfig(level=logging.DEBUG)  # více detailů
logging.basicConfig(level=logging.WARNING)  # méně výpisů
```

---

## 🤝 Přispívání

Pull requesty jsou vítány! Nejprve otevřete Issue s popisem změny.

GitLab CI/CD pipeline lze přidat pomocí `.gitlab-ci.yml`.
