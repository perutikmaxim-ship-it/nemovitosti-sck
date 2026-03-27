"""
database.py – SQLite vrstva pro ukládání nalezených inzerátů.

Zajišťuje deduplikaci: každý inzerát je uložen pouze jednou
na základě jeho unikátní URL nebo externího ID.
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Cesta k databázi
DB_PATH = Path(__file__).parent / "data" / "listings.db"


def get_connection() -> sqlite3.Connection:
    """Vytvoří a vrátí připojení k SQLite databázi."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row  # přístup ke sloupcům přes jméno
    return conn


def init_db() -> None:
    """Inicializuje databázové schéma (vytvoří tabulky, pokud neexistují)."""
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS listings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                external_id TEXT    NOT NULL,  -- ID z původního webu nebo hash URL
                source      TEXT    NOT NULL,  -- 'sreality', 'bazos', atd.
                url         TEXT    NOT NULL,
                title       TEXT,
                price       INTEGER,
                location    TEXT,
                area_m2     INTEGER,
                description TEXT,
                image_url   TEXT,
                found_at    TEXT    NOT NULL,  -- ISO datetime
                sent        INTEGER DEFAULT 0  -- 0 = ještě neodeslano, 1 = odesláno
            )
        """)
        # Unikátní index – zamezuje duplicitám
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_listings_source_id
            ON listings (source, external_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_listings_sent
            ON listings (sent)
        """)
        conn.commit()
        logger.info("Databáze inicializována: %s", DB_PATH)
    finally:
        conn.close()


def is_known(source: str, external_id: str) -> bool:
    """Vrátí True, pokud inzerát již existuje v databázi."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM listings WHERE source = ? AND external_id = ?",
            (source, external_id),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def save_listing(
    source: str,
    external_id: str,
    url: str,
    title: str = "",
    price: Optional[int] = None,
    location: str = "",
    area_m2: Optional[int] = None,
    description: str = "",
    image_url: str = "",
) -> bool:
    """
    Uloží nový inzerát do databáze.

    Vrátí True, pokud byl inzerát skutečně nový a uložen.
    Vrátí False, pokud již existoval (duplicita).
    """
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO listings
                (external_id, source, url, title, price, location, area_m2,
                 description, image_url, found_at, sent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                external_id,
                source,
                url,
                title,
                price,
                location,
                area_m2,
                description,
                image_url,
                datetime.now().isoformat(),
            ),
        )
        inserted = conn.total_changes > 0
        conn.commit()
        if inserted:
            logger.debug("Uložen nový inzerát [%s] %s", source, external_id)
        return inserted
    except sqlite3.Error as e:
        logger.error("Chyba při ukládání inzerátu: %s", e)
        return False
    finally:
        conn.close()


def mark_sent(source: str, external_id: str) -> None:
    """Označí inzerát jako odeslaný do Telegramu."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE listings SET sent = 1 WHERE source = ? AND external_id = ?",
            (source, external_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_stats() -> dict:
    """Vrátí statistiky z databáze."""
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        sent = conn.execute("SELECT COUNT(*) FROM listings WHERE sent = 1").fetchone()[0]
        by_source = conn.execute(
            "SELECT source, COUNT(*) as cnt FROM listings GROUP BY source"
        ).fetchall()
        return {
            "total": total,
            "sent": sent,
            "unsent": total - sent,
            "by_source": {row["source"]: row["cnt"] for row in by_source},
        }
    finally:
        conn.close()
