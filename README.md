# 🏠 Nemovitosti SCK — Hlídač bytů

Automatický hlídač bytů ve Středočeském kraji.
- Portály: **Sreality, Bezrealitky, Bazoš, Reas**
- Filtry: byty 1+kk / 1+1 / 2+kk / 2+1, do 5 000 000 Kč, max 1h od Prahy
- Notifikace přes **Telegram**
- Bez duplicit (SQLite databáze)
- Ranní souhrn v 8:00
- Blokuje dražby a exekuce

---

## ⚙️ NASTAVENÍ

### 1. Telegram Bot
1. Otevři Telegram → @BotFather → `/newbot`
2. Zkopíruj API token
3. Napiš svému botovi `/start`
4. Otevři: `https://api.telegram.org/bot<TOKEN>/getUpdates`
5. Najdi `chat.id` → to je tvoje Chat ID

### 2. Lokální spuštění
```bash
pip install -r requirements.txt

# Nastav proměnné prostředí
export TELEGRAM_TOKEN="7123456789:AAF..."
export TELEGRAM_CHAT_ID="123456789"

python scraper.py
```

### 3. Deploy na Railway.app

1. Vytvoř účet na [railway.app](https://railway.app)
2. Nový projekt → **Deploy from GitHub repo**
3. Pushnout kód na GitHub (viz níže)
4. V Railway → **Variables** přidej:
   - `TELEGRAM_TOKEN` = tvůj token
   - `TELEGRAM_CHAT_ID` = tvoje chat ID
5. Railway automaticky spustí `python scraper.py`

### 4. GitHub (potřeba pro Railway)
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/TVUJ_USERNAME/nemovitosti-sck.git
git push -u origin main
```

---

## 📁 Struktura souborů
```
nemovitosti/
├── scraper.py          # Hlavní script
├── requirements.txt    # Python závislosti
├── Procfile            # Railway/Heroku konfigurace
├── railway.toml        # Railway nastavení
├── nemovitosti.db      # SQLite databáze (vytvoří se automaticky)
└── scraper.log         # Log soubor
```

---

## 🔧 Konfigurace v scraper.py

```python
MAX_PRICE = 5_000_000           # Maximální cena
CHECK_INTERVAL_MINUTES = 30     # Jak často kontrolovat portály
DISPOSITIONS = ["1+kk", "1+1", "2+kk", "2+1"]  # Hledané dispozice
```

---

## ❓ Časté problémy

**Bot neodpovídá?**
- Zkontroluj že jsi napsal `/start` svému botovi
- Ověř TOKEN a CHAT_ID

**Žádné výsledky?**
- Zkontroluj log: `cat scraper.log`
- Sreality mění API — zkontroluj URL v kódu

**Railway restartuje?**
- Normální chování při chybě, automaticky se obnoví
