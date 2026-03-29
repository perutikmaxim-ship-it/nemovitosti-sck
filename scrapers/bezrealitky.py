"""
Bezrealitky.cz scraper
Používá veřejné GraphQL API (bez autentizace).
Endpoint: https://api.bezrealitky.cz/graphql/
"""

import json
from typing import List, Optional

from scrapers.base import BaseScraper
from core.config import config
from utils.logger import get_logger

logger = get_logger(__name__)

BEZREALITKY_GRAPHQL = "https://api.bezrealitky.cz/graphql/"

# GraphQL query pro hledání inzerátů
LISTINGS_QUERY = """
query SearchListings(
  $offerType: OfferType!,
  $estateType: [EstateType!],
  $priceMax: Int,
  $disposition: [Disposition],
  $regionOsmIds: [ID],
  $limit: Int,
  $offset: Int
) {
  listAdverts(
    offerType: $offerType,
    estateType: $estateType,
    priceMax: $priceMax,
    disposition: $disposition,
    regionOsmIds: $regionOsmIds,
    limit: $limit,
    offset: $offset,
    order: UPDATED_AT_DESC
  ) {
    list {
      id
      uri
      title
      description
      price
      currency
      disposition
      surface
      gps {
        lat
        lng
      }
      address {
        city
        street
        streetNumber
        district
      }
      mainImage {
        url
      }
    }
    totalCount
  }
}
"""

# Mapování dispozic na Bezrealitky API hodnoty
DISPOSITION_MAP = {
    "1+kk": "DISP_1_kk",
    "1+1": "DISP_1_1",
    "2+kk": "DISP_2_kk",
    "2+1": "DISP_2_1",
    "3+kk": "DISP_3_kk",
    "3+1": "DISP_3_1",
    "4+kk": "DISP_4_kk",
    "4+1": "DISP_4_1",
    "5+kk": "DISP_5_kk",
    "5+1": "DISP_5_1",
}

# OSM ID pro hledané lokality
# (OpenStreetMap ID pro Bezrealitky regionOsmIds)
LOCATION_OSM_IDS = {
    "Kladno": "435397",
    "Mělník": "437808",
    "Kralupy nad Vltavou": "436896",
}


class BezrealitkyScraper(BaseScraper):
    SOURCE_NAME = "bezrealitky"

    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://www.bezrealitky.cz",
            "Referer": "https://www.bezrealitky.cz/",
        })

    def _get_disposition_codes(self) -> List[str]:
        """Vrátí seznam API kódů dispozic."""
        codes = []
        for disp in config.DISPOSITIONS:
            code = DISPOSITION_MAP.get(disp)
            if code:
                codes.append(code)
        return codes

    def fetch(self) -> List[dict]:
        """Stáhne inzeráty ze všech lokalit přes GraphQL API."""
        all_listings = []

        # Stáhneme všechny lokality najednou (Bezrealitky to umí)
        osm_ids = [
            LOCATION_OSM_IDS[loc]
            for loc in config.LOCATIONS
            if loc in LOCATION_OSM_IDS
        ]

        if not osm_ids:
            logger.warning("[Bezrealitky] Žádné platné OSM IDs pro hledání")
            return []

        dispositions = self._get_disposition_codes()

        variables = {
            "offerType": "PRODEJ",
            "estateType": ["BYT"],
            "priceMax": config.MAX_PRICE,
            "disposition": dispositions if dispositions else None,
            "regionOsmIds": osm_ids,
            "limit": 50,
            "offset": 0,
        }

        payload = {
            "query": LISTINGS_QUERY,
            "variables": variables,
        }

        resp = self._post(BEZREALITKY_GRAPHQL, json=payload)
        if not resp:
            return []

        try:
            data = resp.json()
        except ValueError:
            logger.error("[Bezrealitky] Neplatná JSON odpověď")
            return []

        if "errors" in data:
            logger.error(f"[Bezrealitky] GraphQL chyby: {data['errors']}")
            return []

        items = (
            data.get("data", {})
            .get("listAdverts", {})
            .get("list", [])
        )

        logger.debug(f"[Bezrealitky] Nalezeno {len(items)} inzerátů")

        for item in items:
            listing = self._parse_item(item)
            if listing:
                all_listings.append(listing)

        logger.info(f"[Bezrealitky] Po filtraci: {len(all_listings)}")
        return all_listings

    def _parse_item(self, item: dict) -> Optional[dict]:
        """Parsuje jeden inzerát z GraphQL odpovědi."""
        try:
            listing_id = str(item.get("id", ""))
            if not listing_id:
                return None

            # Lokalita
            address = item.get("address") or {}
            city = address.get("city", "")
            district = address.get("district", "")
            street = address.get("street", "")
            location_str = ", ".join(filter(None, [street, city]))
            if not location_str:
                location_str = city or district

            # Ověření lokality
            if not self._is_valid_location(location_str) and not self._is_valid_location(city):
                return None

            # Cena
            price = item.get("price")
            if price:
                price = int(price)
                if price > config.MAX_PRICE:
                    return None

            # Dispozice
            raw_disposition = item.get("disposition", "")
            disposition = self._map_disposition(raw_disposition)

            if disposition and not self._is_valid_disposition(disposition):
                return None

            # URL
            uri = item.get("uri", "")
            url = f"https://www.bezrealitky.cz/nemovitosti-byty-domy/{uri}" if uri else ""
            if not url:
                url = f"https://www.bezrealitky.cz/nemovitosti-byty-domy/{listing_id}"

            # Název a popis
            title = item.get("title") or f"Byt {disposition or ''} - {city}"
            description = item.get("description", "") or ""
            # Bezrealitky občas vrací HTML v popisu
            description = description.replace("<br>", " ").replace("<br/>", " ")

            # Plocha do titulku pokud není
            surface = item.get("surface")
            if surface and "m²" not in title:
                title = f"{title} ({surface} m²)" if title else f"Byt {surface} m²"

            return {
                "listing_id": listing_id,
                "source": self.SOURCE_NAME,
                "url": url,
                "title": title,
                "price": price,
                "location": location_str,
                "description": description[:500] if description else "",
                "disposition": disposition,
            }

        except Exception as e:
            logger.warning(f"[Bezrealitky] Chyba při parsování inzerátu: {e}")
            return None

    def _map_disposition(self, raw: str) -> Optional[str]:
        """Převede Bezrealitky API kód dispozice na čitelný formát."""
        if not raw:
            return None
        reverse_map = {v: k for k, v in DISPOSITION_MAP.items()}
        return reverse_map.get(raw, raw)
