#!/usr/bin/env python3
"""One-time script to backfill 6 months of BVC price and MASI history."""
import sys
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from storage.db import upsert_price, insert_masi_daily, get_price_history, init_db

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Mizan-Seeder/1.0)",
    "Accept": "application/json",
}

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass


def _get_all_tickers() -> list[str]:
    """Fetch all BVC tickers from the market_watch API."""
    from config import BVC_API_URL
    try:
        r = requests.get(
            BVC_API_URL,
            headers=HEADERS,
            params={"include": "symbol", "page[limit]": "200"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        tickers = []
        included = {i["id"]: i for i in data.get("included", [])}
        for record in data.get("data", []):
            sym_rel = (record.get("relationships") or {}).get("symbol", {}).get("data") or {}
            sym = included.get(sym_rel.get("id"), {})
            url = sym.get("attributes", {}).get("instrument_url", "")
            ticker = url.split("/")[-1] if url else None
            if ticker:
                tickers.append(ticker)
        return tickers
    except Exception as exc:
        logger.error(f"Failed to fetch ticker list: {exc}")
        return []


def _fetch_ticker_history(ticker: str, from_date: str, to_date: str) -> list[dict]:
    """
    Fetch historical OHLCV for a single ticker.

    The BVC API historical endpoint pattern (discovered via DevTools inspection):
    GET https://api.casablanca-bourse.com/fr/api/bourse_data/historic_data
    Params: ticker=OCP&from=2025-12-25&to=2026-06-25

    If the endpoint returns 404, this function returns [] and the caller skips.
    """
    url = "https://api.casablanca-bourse.com/fr/api/bourse_data/historic_data"
    try:
        r = requests.get(
            url,
            headers=HEADERS,
            params={"ticker": ticker, "from": from_date, "to": to_date},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        rows = []
        for record in data.get("data", []):
            attr = record.get("attributes", {})
            date = attr.get("sessionDate") or attr.get("date") or attr.get("transactTime", "")[:10]
            if not date:
                continue
            rows.append({
                "date": date,
                "open": attr.get("openingPrice"),
                "high": attr.get("highPrice"),
                "low": attr.get("lowPrice"),
                "close": attr.get("coursCourant") or attr.get("lastPrice"),
                "volume": int(float(attr.get("cumulTitresEchanges") or 0)),
            })
        return rows
    except Exception as exc:
        logger.warning(f"  [{ticker}] history fetch failed: {exc}")
        return []


MASI_HISTORY_URL = "https://api.casablanca-bourse.com/fr/api/bourse_data/historic_data"


def _seed_masi_history(days: int = 365) -> None:
    """Fetch and insert MASI index daily history for the past `days` days."""
    today = datetime.now(timezone.utc).date()
    from_date = (today - timedelta(days=days)).isoformat()
    to_date = today.isoformat()
    try:
        r = requests.get(
            MASI_HISTORY_URL,
            headers=HEADERS,
            params={"ticker": "MASI", "from": from_date, "to": to_date},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        inserted = 0
        for record in data.get("data", []):
            attr = record.get("attributes", {})
            date = attr.get("sessionDate") or attr.get("date") or attr.get("transactTime", "")[:10]
            if not date:
                continue
            value = attr.get("indexValue") or attr.get("coursCourant") or attr.get("lastPrice")
            if value is None:
                continue
            change_pct = attr.get("changePercent") or attr.get("variationPercent") or attr.get("change_pct")
            insert_masi_daily(date, float(value), float(change_pct) if change_pct is not None else None)
            inserted += 1
        logger.info(f"MASI: inserted {inserted} rows")
    except Exception as exc:
        logger.error(f"MASI history seeding failed: {exc}")


def main():
    init_db()
    today = datetime.now(timezone.utc).date()
    from_date = (today - timedelta(days=180)).isoformat()
    to_date = today.isoformat()

    logger.info(f"Seeding BVC price history from {from_date} to {to_date}")

    tickers = _get_all_tickers()
    if not tickers:
        logger.error("No tickers fetched — aborting price seeding.")
    else:
        logger.info(f"Found {len(tickers)} tickers")

        seeded = 0
        for ticker in tickers:
            existing = get_price_history(ticker, days=200)
            if len(existing) >= 100:
                logger.info(f"  [{ticker}] already has {len(existing)} rows — skipping")
                continue

            rows = _fetch_ticker_history(ticker, from_date, to_date)
            if not rows:
                logger.warning(f"  [{ticker}] no history returned")
                continue

            for row in rows:
                upsert_price(ticker, row["date"], row)

            logger.info(f"  [{ticker}] seeded {len(rows)} rows")
            seeded += 1

        logger.info(f"Done. Seeded history for {seeded} tickers.")

    logger.info("Seeding MASI daily history…")
    _seed_masi_history()
    logger.info("Run 'make dry-run' to verify technical indicators now compute.")


if __name__ == "__main__":
    main()
