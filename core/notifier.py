"""
Telegram notifier - odesílá zprávy o nových inzerátech
"""

import requests
from typing import Optional

from core.config import config
from utils.logger import get_logger

logger = get_logger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


class TelegramNotifier:
    def __init__(self):
        config.validate()
        self.token = config.TELEGRAM_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def _send(self, text: str, disable_preview: bool = True) -> bool:
        """Odešle zprávu do Telegramového chatu. Vrátí True při úspěchu."""
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_preview,
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            return True
        except requests.exceptions.HTTPError as e:
            logger.error(f"Telegram HTTP chyba: {e} | Odpověď: {resp.text}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Telegram síťová chyba: {e}")
        return False

    def send_listing(self, listing: dict) -> bool:
        """Naformátuje a odešle inzerát do Telegramu."""
        price_str = f"{listing['price']:,} Kč".replace(",", " ") if listing.get("price") else "Cena neuvedena"
        disposition_str = f" • {listing['disposition']}" if listing.get("disposition") else ""
        description = listing.get("description", "")
        desc_part = f"\n📝 {description[:200]}{'...' if len(description) > 200 else ''}" if description else ""

        source_emoji = {
            "sreality": "🏠",
            "bezrealitky": "🔑",
            "idnes": "📰",
            "bazos": "📋",
        }.get(listing.get("source", ""), "🏡")

        text = (
            f"{source_emoji} <b>{listing.get('title', 'Nový inzerát')}</b>\n"
            f"\n"
            f"💰 <b>{price_str}</b>{disposition_str}\n"
            f"📍 {listing.get('location', 'Lokalita neuvedena')}\n"
            f"🌐 Zdroj: {listing.get('source', '').capitalize()}"
            f"{desc_part}\n"
            f"\n"
            f"🔗 <a href=\"{listing['url']}\">Zobrazit inzerát</a>"
        )

        success = self._send(text)
        if success:
            logger.info(f"Notifikace odeslána: {listing.get('title', listing.get('url'))}")
        return success

    def send_startup_message(self) -> bool:
        text = (
            "🤖 <b>Nemovitosti Bot spuštěn</b>\n"
            "\n"
            f"📍 Lokality: {', '.join(config.LOCATIONS)}\n"
            f"💰 Max cena: {config.MAX_PRICE:,} Kč\n".replace(",", " ")
            + f"🏢 Dispozice: {', '.join(config.DISPOSITIONS)}\n"
            f"⏱ Interval: každých {config.CHECK_INTERVAL // 60} minut\n"
            "\n"
            "Sleduji: Sreality, Bezrealitky, iDnes Reality, Bazoš"
        )
        return self._send(text)

    def send_error_alert(self, source: str, error: str) -> None:
        """Pošle upozornění na opakující se chybu (volitelné)."""
        text = f"⚠️ <b>Chyba scraperu</b>\nZdroj: {source}\n<code>{error[:300]}</code>"
        self._send(text)

    def send_summary(self, stats: dict) -> bool:
        """Pošle denní souhrn statistik."""
        by_source = stats.get("by_source", {})
        source_lines = "\n".join(
            f"  • {src}: {cnt}" for src, cnt in by_source.items()
        )
        text = (
            f"📊 <b>Statistiky bota</b>\n"
            f"Celkem v DB: {stats.get('total', 0)} inzerátů\n"
            f"\nPodle zdroje:\n{source_lines}"
        )
        return self._send(text)
