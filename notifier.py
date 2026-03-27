"""
notifier.py – Odesílání upozornění přes Telegram Bot API.

Používá python-telegram-bot pro spolehlivé doručení zpráv.
Formátuje inzeráty do přehledných HTML zpráv.
"""

import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)

# Maximální délka Telegram zprávy (limit je 4096 znaků)
MAX_MESSAGE_LENGTH = 4096


def format_price(price: Optional[int]) -> str:
    """Formátuje cenu do čitelného formátu (1 234 567 Kč)."""
    if price is None:
        return "Cena neuvedena"
    return f"{price:,.0f} Kč".replace(",", "\u202f")  # non-breaking space


def format_listing_message(listing: dict) -> str:
    """
    Vytvoří HTML zprávu pro Telegram z dat inzerátu.

    Parametry listing dict:
        source, title, price, location, area_m2, url, description
    """
    source_emoji = {
        "sreality": "🏠",
        "bazos": "📋",
        "realingo": "🔍",
        "reas": "🏡",
        "idnes": "📰",
    }
    emoji = source_emoji.get(listing.get("source", ""), "📌")
    source_name = listing.get("source", "").capitalize()

    price_str = format_price(listing.get("price"))
    title = listing.get("title", "Bez názvu")
    location = listing.get("location", "Lokalita neuvedena")
    area = listing.get("area_m2")
    url = listing.get("url", "")
    description = listing.get("description", "")

    # Zkrátí popis na max 200 znaků
    if description and len(description) > 200:
        description = description[:197] + "..."

    area_str = f" • {area} m²" if area else ""

    msg = (
        f"{emoji} <b>Nový inzerát – {source_name}</b>\n"
        f"\n"
        f"📍 {location}{area_str}\n"
        f"💰 <b>{price_str}</b>\n"
        f"🏷️ {title}\n"
    )

    if description:
        msg += f"\n{description}\n"

    msg += f"\n🔗 <a href=\"{url}\">Zobrazit inzerát</a>"

    return msg


class TelegramNotifier:
    """Odesílá zprávy přes Telegram Bot API."""

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = str(chat_id)
        self.base_url = f"https://api.telegram.org/bot{token}"

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        Odešle textovou zprávu do chatu.
        Vrátí True při úspěchu, False při chybě.
        """
        # Zkrátí zprávu pokud je příliš dlouhá
        if len(text) > MAX_MESSAGE_LENGTH:
            text = text[:MAX_MESSAGE_LENGTH - 3] + "..."

        try:
            response = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": False,
                },
                timeout=15,
            )
            response.raise_for_status()
            result = response.json()
            if not result.get("ok"):
                logger.error("Telegram API chyba: %s", result)
                return False
            return True
        except requests.RequestException as e:
            logger.error("Chyba při odesílání Telegram zprávy: %s", e)
            return False

    def send_listing(self, listing: dict) -> bool:
        """Odešle formátovaný inzerát jako Telegram zprávu."""
        msg = format_listing_message(listing)
        success = self.send_message(msg)
        if success:
            logger.info(
                "Odesláno do Telegramu: [%s] %s",
                listing.get("source"),
                listing.get("title", "")[:50],
            )
        return success

    def send_status(self, is_running: bool, stats: dict) -> bool:
        """Odešle stav bota."""
        status = "✅ Běží" if is_running else "⏸️ Zastaveno"
        by_source = stats.get("by_source", {})
        source_lines = "\n".join(
            f"  • {src}: {cnt}" for src, cnt in by_source.items()
        )

        msg = (
            f"🤖 <b>Stav Reality Bota</b>\n"
            f"\n"
            f"Status: {status}\n"
            f"📊 Celkem nalezeno: {stats.get('total', 0)}\n"
            f"📨 Odesláno: {stats.get('sent', 0)}\n"
            f"\n"
            f"<b>Podle zdroje:</b>\n"
            f"{source_lines if source_lines else '  (žádné inzeráty)'}"
        )
        return self.send_message(msg)

    def send_start_message(self) -> bool:
        """Uvítací zpráva při /start."""
        msg = (
            "🏠 <b>Reality Bot spuštěn!</b>\n"
            "\n"
            "Sleduju nové inzeráty nemovitostí ve Středočeském kraji "
            "(mimo Prahu) do 4 500 000 Kč.\n"
            "\n"
            "⏱️ Kontrola každých <b>15 minut</b>\n"
            "\n"
            "<b>Příkazy:</b>\n"
            "  /start – spustí sledování\n"
            "  /stop – zastaví sledování\n"
            "  /status – zobrazí statistiky"
        )
        return self.send_message(msg)

    def send_stop_message(self) -> bool:
        """Zpráva při /stop."""
        return self.send_message("⏸️ Sledování zastaveno. Pro obnovení pošli /start.")

    def test_connection(self) -> bool:
        """Otestuje připojení k Telegram API (getMe)."""
        try:
            response = requests.get(
                f"{self.base_url}/getMe", timeout=10
            )
            result = response.json()
            if result.get("ok"):
                bot_name = result["result"].get("username", "unknown")
                logger.info("Telegram bot připojen: @%s", bot_name)
                return True
            logger.error("Telegram test selhal: %s", result)
            return False
        except requests.RequestException as e:
            logger.error("Nelze se připojit k Telegram API: %s", e)
            return False
