"""
Konfigurace aplikace - načítá hodnoty z .env souboru
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # --- Telegram ---
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # --- Lokality (výchozí: pouze tyto 3, lze rozšířit přes .env) ---
    _LOCATIONS_ENV = os.getenv("LOCATIONS", "")
    LOCATIONS: list[str] = (
        [loc.strip() for loc in _LOCATIONS_ENV.split(",") if loc.strip()]
        if _LOCATIONS_ENV
        else ["Kladno", "Mělník", "Kralupy nad Vltavou"]
    )

    # --- Filtr ceny ---
    MAX_PRICE: int = int(os.getenv("MAX_PRICE", "5000000"))

    # --- Filtr dispozic ---
    # Výchozí: 2+kk a 2+1
    _DISPOSITIONS_ENV = os.getenv("DISPOSITIONS", "")
    DISPOSITIONS: list[str] = (
        [d.strip() for d in _DISPOSITIONS_ENV.split(",") if d.strip()]
        if _DISPOSITIONS_ENV
        else ["2+kk", "2+1"]
    )

    # --- Scheduler ---
    CHECK_INTERVAL: int = int(os.getenv("CHECK_INTERVAL", "900"))  # 15 minut

    # --- Databáze ---
    DB_PATH: str = os.getenv("DB_PATH", "data/listings.db")

    # --- Scraping ---
    REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "15"))
    REQUEST_DELAY: float = float(os.getenv("REQUEST_DELAY", "2.0"))  # prodleva mezi requesty
    USER_AGENT: str = os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36",
    )

    # --- Mapování dispozic pro jednotlivé zdroje ---
    # Sreality kódy dispozic: 2+kk=2, 2+1=3
    SREALITY_DISPOSITION_CODES: dict[str, int] = {
        "1+kk": 1,
        "2+kk": 2,
        "2+1": 3,
        "3+kk": 4,
        "3+1": 5,
        "4+kk": 6,
        "4+1": 7,
    }

    # Bezrealitky kódy dispozic
    BEZREALITKY_DISPOSITION_CODES: dict[str, str] = {
        "1+kk": "1+kk",
        "2+kk": "2+kk",
        "2+1": "2+1",
        "3+kk": "3+kk",
        "3+1": "3+1",
        "4+kk": "4+kk",
        "4+1": "4+1",
    }

    def validate(self) -> None:
        """Ověří, že jsou nastaveny povinné hodnoty."""
        if not self.TELEGRAM_TOKEN:
            raise ValueError("TELEGRAM_TOKEN není nastaven v .env!")
        if not self.TELEGRAM_CHAT_ID:
            raise ValueError("TELEGRAM_CHAT_ID není nastaven v .env!")

    def __repr__(self) -> str:
        return (
            f"Config(locations={self.LOCATIONS}, max_price={self.MAX_PRICE}, "
            f"dispositions={self.DISPOSITIONS}, interval={self.CHECK_INTERVAL}s)"
        )


config = Config()
