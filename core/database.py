"""
Databázový modul - SQLite pro ukládání nalezených inzerátů a deduplikaci
"""

import sqlite3
import os
from datetime import datetime
from typing import Optional

from utils.logger import get_logger
from core.config import config

logger = get_logger(__name__)


class Database:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or config.DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self) -> None:
        """Vytvoří tabulky, pokud neexistují."""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS listings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id  TEXT NOT NULL,
                source      TEXT NOT NULL,
                url         TEXT NOT NULL,
                title       TEXT,
                price       INTEGER,
                location    TEXT,
                description TEXT,
                disposition TEXT,
                first_seen  TEXT NOT NULL,
                notified    INTEGER DEFAULT 0,
                UNIQUE(listing_id, source)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_listing_id_source
            ON listings(listing_id, source)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scrape_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                source      TEXT NOT NULL,
                scraped_at  TEXT NOT NULL,
                found_count INTEGER DEFAULT 0,
                new_count   INTEGER DEFAULT 0,
                error       TEXT
            )
        """)
        conn.commit()
        logger.info(f"Databáze inicializována: {self.db_path}")

    def is_known(self, listing_id: str, source: str) -> bool:
        """Vrátí True, pokud inzerát již byl uložen."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT 1 FROM listings WHERE listing_id = ? AND source = ?",
            (listing_id, source),
        ).fetchone()
        return row is not None

    def save_listing(self, listing: dict) -> bool:
        """
        Uloží inzerát do DB.
        Vrátí True, pokud byl inzerát nový (vložen), False pokud již existoval.
        """
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO listings
                    (listing_id, source, url, title, price, location,
                     description, disposition, first_seen, notified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    listing["listing_id"],
                    listing["source"],
                    listing["url"],
                    listing.get("title"),
                    listing.get("price"),
                    listing.get("location"),
                    listing.get("description"),
                    listing.get("disposition"),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            # Duplikát – ignorovat
            return False
        except Exception as e:
            logger.error(f"Chyba při ukládání inzerátu {listing.get('listing_id')}: {e}")
            conn.rollback()
            return False

    def mark_notified(self, listing_id: str, source: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE listings SET notified = 1 WHERE listing_id = ? AND source = ?",
            (listing_id, source),
        )
        conn.commit()

    def log_scrape(
        self,
        source: str,
        found_count: int = 0,
        new_count: int = 0,
        error: Optional[str] = None,
    ) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO scrape_log (source, scraped_at, found_count, new_count, error)
            VALUES (?, ?, ?, ?, ?)
            """,
            (source, datetime.now().isoformat(), found_count, new_count, error),
        )
        conn.commit()

    def get_stats(self) -> dict:
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        by_source = conn.execute(
            "SELECT source, COUNT(*) as cnt FROM listings GROUP BY source"
        ).fetchall()
        return {
            "total": total,
            "by_source": {row["source"]: row["cnt"] for row in by_source},
        }

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
