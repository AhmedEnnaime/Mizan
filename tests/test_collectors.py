from pathlib import Path
from unittest.mock import patch, MagicMock

FIXTURES = Path(__file__).parent / "fixtures"


# --- BVC ---

def test_bvc_parse_response_parses_stocks():
    import json
    from collectors.bvc import _parse_response
    data = json.loads((FIXTURES / "bvc_sample.json").read_text())
    result = _parse_response(data)
    assert result["success"] is True
    stocks = result["data"]["stocks"]
    assert len(stocks) == 2
    ocp = next(s for s in stocks if s["ticker"] == "OCP")
    assert ocp["close"] == 261.5
    assert ocp["change_pct"] == 0.19
    assert ocp["volume"] == 15342


def test_bvc_parse_response_uses_last_transaction_when_no_current_price():
    import json
    from collectors.bvc import _parse_response
    data = json.loads((FIXTURES / "bvc_sample.json").read_text())
    result = _parse_response(data)
    atw = next(s for s in result["data"]["stocks"] if s["ticker"] == "ATW")
    assert atw["close"] == 336.5


def test_bvc_collect_returns_failure_on_error():
    from collectors.bvc import collect
    with patch("collectors.bvc.requests.get", side_effect=Exception("timeout")):
        result = collect()
    assert result["success"] is False
    assert len(result["errors"]) > 0


# --- Commodities ---

def test_commodities_collect_returns_all_keys():
    from collectors.commodities import collect
    mock_ticker = MagicMock()
    mock_hist = MagicMock()
    mock_hist.empty = False
    mock_hist.__len__ = MagicMock(return_value=2)
    mock_hist.iloc = MagicMock()
    mock_hist.iloc.__getitem__ = MagicMock(side_effect=lambda i: MagicMock(**{"__getitem__": lambda self, k: 100.0}))

    import pandas as pd
    hist_df = pd.DataFrame({"Close": [98.0, 100.0]})
    mock_ticker.history.return_value = hist_df

    with patch("collectors.commodities.yf.Ticker", return_value=mock_ticker):
        result = collect()

    assert result["success"] is True
    assert "gold" in result["data"]
    assert "brent_crude" in result["data"]
    assert "phosphate_proxy" in result["data"]
    assert result["data"]["gold"]["price"] == 100.0
    assert abs(result["data"]["gold"]["change_pct"] - 2.04) < 0.1


def test_commodities_collect_handles_single_ticker_failure():
    from collectors.commodities import collect
    import pandas as pd

    good_df = pd.DataFrame({"Close": [98.0, 100.0]})
    call_count = {"n": 0}

    def side_effect(ticker):
        m = MagicMock()
        call_count["n"] += 1
        if call_count["n"] == 1:
            m.history.side_effect = Exception("timeout")
        else:
            m.history.return_value = good_df
        return m

    with patch("collectors.commodities.yf.Ticker", side_effect=side_effect):
        result = collect()

    assert result["success"] is True
    assert len(result["errors"]) >= 1


# --- Macro ---

def test_macro_collect_returns_indices_and_forex():
    from collectors.macro import collect
    import pandas as pd

    good_df = pd.DataFrame({"Close": [98.0, 100.0]})
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = good_df

    mock_rates = {"MAD": 9.95, "EUR": 0.92}

    with patch("collectors.macro.yf.Ticker", return_value=mock_ticker), \
         patch("collectors.macro._fetch_mad_rates", return_value=mock_rates):
        result = collect()

    assert result["success"] is True
    assert "sp500" in result["data"]["indices"]
    assert "usd_mad" in result["data"]["forex"]
    assert result["data"]["forex"]["usd_mad"]["price"] == 9.95


def test_macro_collect_survives_exchange_rate_api_failure():
    from collectors.macro import collect
    import pandas as pd

    good_df = pd.DataFrame({"Close": [98.0, 100.0]})
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = good_df

    with patch("collectors.macro.yf.Ticker", return_value=mock_ticker), \
         patch("collectors.macro._fetch_mad_rates", side_effect=Exception("api down")):
        result = collect()

    assert result["success"] is True
    assert "usd_mad" in result["data"]["forex"]
    assert result["data"]["forex"]["usd_mad"]["price"] is None


# --- News ---

def test_news_collect_parses_rss_articles():
    from collectors.news import collect, _fetch_feed
    fixture_path = FIXTURES / "news_sample.xml"
    result = _fetch_feed(str(fixture_path), "Test Feed")
    assert len(result) == 2
    assert result[0]["title"] == "Morocco raises interest rate to 3%"
    assert result[0]["source"] == "Test Feed"
    assert "Bank Al-Maghrib" in result[0]["summary"]


def test_news_collect_skips_failed_feeds():
    from collectors.news import collect
    feeds = [
        {"name": "Bad Feed", "url": "https://nonexistent.invalid/rss"},
        {"name": "Good Feed", "url": str(FIXTURES / "news_sample.xml")},
    ]
    with patch("collectors.news.RSS_FEEDS", feeds):
        result = collect()
    assert result["success"] is True
    assert len(result["data"]["articles"]) == 2
    assert len(result["errors"]) == 1


# --- Technical Analysis ---

def test_technical_collect_computes_rsi_and_macd(test_db, monkeypatch):
    import storage.db as db_module
    import json
    from pathlib import Path

    monkeypatch.setattr(db_module, "DB_PATH", test_db)
    prices = json.loads((FIXTURES / "prices_sample.json").read_text())
    for p in prices:
        db_module.upsert_price(p["ticker"], p["date"],
            {"open": p["open"], "high": p["high"], "low": p["low"],
             "close": p["close"], "volume": p["volume"]})

    from collectors.technical import collect
    result = collect(["OCP"])

    assert result["success"] is True
    ocp = result["data"]["OCP"]
    assert ocp["rsi"] is not None
    assert 0 < ocp["rsi"] < 100
    assert ocp["macd"]["macd"] is not None
    assert ocp["sma20"] is not None
    assert ocp["volume_trend"] in ("increasing", "decreasing", "stable")
    assert ocp["support"] < ocp["resistance"]
    assert "0.5" in ocp["fibonacci"]


def test_technical_collect_skips_ticker_with_no_history(test_db, monkeypatch):
    import storage.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", test_db)

    from collectors.technical import collect
    result = collect(["NOTEXIST"])

    assert result["success"] is True
    assert len(result["errors"]) == 1
    assert "NOTEXIST" in result["errors"][0]
