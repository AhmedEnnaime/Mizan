"""Tests for scripts/seed_history.py"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# Ensure the project root is on sys.path so scripts/ can import from it
sys.path.insert(0, str(Path(__file__).parent.parent))

import storage.db as db_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_market_watch_response(tickers: list[str]) -> dict:
    """Build a minimal market_watch JSON response for the given ticker slugs."""
    included = [
        {
            "id": f"sym-{t}",
            "attributes": {"instrument_url": f"https://example.com/equities/{t}"},
        }
        for t in tickers
    ]
    data = [
        {
            "id": f"stock-{t}",
            "relationships": {"symbol": {"data": {"id": f"sym-{t}"}}},
        }
        for t in tickers
    ]
    return {"data": data, "included": included}


def _make_history_response(ticker: str, dates: list[str], close: float = 100.0) -> dict:
    """Build a minimal historic_data JSON response."""
    records = [
        {
            "attributes": {
                "sessionDate": d,
                "openingPrice": close - 1,
                "highPrice": close + 1,
                "lowPrice": close - 2,
                "coursCourant": close,
                "cumulTitresEchanges": 5000,
            }
        }
        for d in dates
    ]
    return {"data": records}


# ---------------------------------------------------------------------------
# _get_all_tickers
# ---------------------------------------------------------------------------

def test_get_all_tickers_parses_response():
    from scripts.seed_history import _get_all_tickers

    mock_resp = MagicMock()
    mock_resp.json.return_value = _make_market_watch_response(["OCP", "ATW", "IAM"])

    with patch("scripts.seed_history.requests.get", return_value=mock_resp) as mock_get:
        tickers = _get_all_tickers()

    mock_get.assert_called_once()
    assert set(tickers) == {"OCP", "ATW", "IAM"}


def test_get_all_tickers_skips_missing_url():
    """Records without an instrument_url should be silently skipped."""
    from scripts.seed_history import _get_all_tickers

    response = {
        "data": [
            {
                "id": "stock-X",
                "relationships": {"symbol": {"data": {"id": "sym-X"}}},
            }
        ],
        "included": [
            {
                "id": "sym-X",
                # no instrument_url attribute
                "attributes": {},
            }
        ],
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = response

    with patch("scripts.seed_history.requests.get", return_value=mock_resp):
        tickers = _get_all_tickers()

    assert tickers == []


# ---------------------------------------------------------------------------
# _fetch_ticker_history
# ---------------------------------------------------------------------------

def test_fetch_ticker_history_returns_rows():
    from scripts.seed_history import _fetch_ticker_history

    dates = ["2026-01-10", "2026-01-11", "2026-01-12"]
    mock_resp = MagicMock()
    mock_resp.json.return_value = _make_history_response("OCP", dates, close=262.0)

    with patch("scripts.seed_history.requests.get", return_value=mock_resp):
        rows = _fetch_ticker_history("OCP", "2026-01-10", "2026-01-12")

    assert len(rows) == 3
    assert rows[0]["date"] == "2026-01-10"
    assert rows[0]["close"] == 262.0
    assert rows[0]["volume"] == 5000


def test_fetch_ticker_history_returns_empty_on_error():
    from scripts.seed_history import _fetch_ticker_history

    with patch("scripts.seed_history.requests.get", side_effect=Exception("network error")):
        rows = _fetch_ticker_history("OCP", "2026-01-01", "2026-06-01")

    assert rows == []


def test_fetch_ticker_history_skips_records_without_date():
    from scripts.seed_history import _fetch_ticker_history

    response = {
        "data": [
            {"attributes": {"openingPrice": 100, "coursCourant": 105, "cumulTitresEchanges": 1000}},
            {"attributes": {"sessionDate": "2026-02-01", "coursCourant": 110, "cumulTitresEchanges": 2000}},
        ]
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = response

    with patch("scripts.seed_history.requests.get", return_value=mock_resp):
        rows = _fetch_ticker_history("OCP", "2026-01-01", "2026-03-01")

    assert len(rows) == 1
    assert rows[0]["date"] == "2026-02-01"


# ---------------------------------------------------------------------------
# main() — integration-level, all I/O mocked
# ---------------------------------------------------------------------------

def test_main_seeds_tickers(test_db, monkeypatch):
    """main() fetches tickers, calls upsert_price for each history row."""
    import scripts.seed_history as seed_mod

    monkeypatch.setattr(db_module, "DB_PATH", test_db)

    tickers = ["OCP", "ATW"]
    dates = ["2026-01-10", "2026-01-11"]

    def fake_get(url, **kwargs):
        mock_resp = MagicMock()
        if "market_watch" in url:
            mock_resp.json.return_value = _make_market_watch_response(tickers)
        else:
            # historic_data endpoint
            ticker = kwargs.get("params", {}).get("ticker", "OCP")
            mock_resp.json.return_value = _make_history_response(ticker, dates)
        return mock_resp

    with patch("scripts.seed_history.requests.get", side_effect=fake_get):
        with patch("scripts.seed_history.init_db"):
            seed_mod.main()

    # Both tickers should now have 2 rows each in the DB
    ocp_rows = db_module.get_price_history("OCP", days=10)
    atw_rows = db_module.get_price_history("ATW", days=10)
    assert len(ocp_rows) == 2
    assert len(atw_rows) == 2


def test_main_skips_well_seeded_tickers(test_db, monkeypatch):
    """Tickers that already have >= 100 rows are skipped (no upsert called)."""
    import scripts.seed_history as seed_mod

    monkeypatch.setattr(db_module, "DB_PATH", test_db)

    # Patch get_price_history to report 100 pre-existing rows for OCP
    pre_seeded = [{"date": f"2026-01-{i+1:02d}", "close": 100.0} for i in range(100)]

    mw_resp = MagicMock()
    mw_resp.json.return_value = _make_market_watch_response(["OCP"])

    with patch("scripts.seed_history.requests.get", return_value=mw_resp), \
         patch("scripts.seed_history.get_price_history", return_value=pre_seeded), \
         patch("scripts.seed_history.upsert_price") as mock_upsert, \
         patch("scripts.seed_history.init_db"):
        seed_mod.main()

    # upsert_price should NOT have been called because the ticker was skipped
    mock_upsert.assert_not_called()


def test_main_is_idempotent(test_db, monkeypatch):
    """Running main() twice inserts each row only once (INSERT OR IGNORE)."""
    import scripts.seed_history as seed_mod

    monkeypatch.setattr(db_module, "DB_PATH", test_db)

    dates = ["2026-01-10", "2026-01-11"]

    def fake_get(url, **kwargs):
        mock_resp = MagicMock()
        if "market_watch" in url:
            mock_resp.json.return_value = _make_market_watch_response(["OCP"])
        else:
            mock_resp.json.return_value = _make_history_response("OCP", dates)
        return mock_resp

    with patch("scripts.seed_history.requests.get", side_effect=fake_get):
        with patch("scripts.seed_history.init_db"):
            seed_mod.main()

    # Second run — OCP now has 2 rows, below the 100-row skip threshold,
    # so it will attempt to insert again; INSERT OR IGNORE keeps count at 2.
    with patch("scripts.seed_history.requests.get", side_effect=fake_get):
        with patch("scripts.seed_history.init_db"):
            seed_mod.main()

    rows = db_module.get_price_history("OCP", days=10)
    assert len(rows) == 2
