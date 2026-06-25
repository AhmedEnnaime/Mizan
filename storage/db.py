import sqlite3
import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone

from config import DB_PATH

logger = logging.getLogger(__name__)


@contextmanager
def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume INTEGER,
                UNIQUE(ticker, date)
            );
            CREATE TABLE IF NOT EXISTS briefings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                content TEXT NOT NULL,
                raw_data TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT,
                trigger_reason TEXT NOT NULL,
                content TEXT NOT NULL,
                sent_at TEXT NOT NULL
            );
        """)


def upsert_price(ticker: str, date: str, ohlcv: dict) -> None:
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO prices (ticker, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, date) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low,
                close=excluded.close, volume=excluded.volume
        """, (ticker, date, ohlcv.get("open"), ohlcv.get("high"),
              ohlcv.get("low"), ohlcv.get("close"), ohlcv.get("volume")))


def get_price_history(ticker: str, days: int = 200) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT ticker, date, open, high, low, close, volume
            FROM prices WHERE ticker = ?
            ORDER BY date DESC LIMIT ?
        """, (ticker, days)).fetchall()
    return [dict(r) for r in reversed(rows)]


def save_briefing(date: str, content: str, raw_data: dict) -> None:
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO briefings (date, content, raw_data, created_at)
            VALUES (?, ?, ?, ?)
        """, (date, content, json.dumps(raw_data), datetime.now(timezone.utc).isoformat()))


def get_last_briefing() -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM briefings ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def log_alert(ticker: str | None, trigger_reason: str, content: str) -> None:
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO alerts (ticker, trigger_reason, content, sent_at)
            VALUES (?, ?, ?, ?)
        """, (ticker, trigger_reason, content, datetime.now(timezone.utc).isoformat()))
