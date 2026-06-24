# BVC AI Investment Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python AI agent that scrapes the Casablanca Stock Exchange daily, aggregates macro/news/commodity data, and sends an 8:00 AM morning briefing email + real-time alert emails during market hours — all containerized in Docker.

**Architecture:** Five independent data collectors produce standardized result dicts bundled into a context package; a Claude-powered analyst generates structured JSON output; a Jinja2 formatter renders HTML; Gmail SMTP delivers emails; APScheduler orchestrates the pipeline with Morocco timezone awareness; SQLite stores price history enabling technical analysis.

**Tech Stack:** Python 3.12, anthropic SDK, yfinance, pandas + pandas-ta, BeautifulSoup4 + requests, feedparser, APScheduler, Jinja2, sqlite3 (stdlib), smtplib (stdlib), python-dotenv, pytz, Docker

## Global Constraints
- Python 3.12+
- Secrets in `.env` (never committed); non-secret config in `stocks/config.py`
- All collectors return `{"success": bool, "data": dict, "errors": list[str]}`; one collector failure never crashes the pipeline
- All errors logged to `stocks/logs/errors.log` with ISO timestamp and stack trace; no silent failures
- BVC market hours: 10:00–15:30 Morocco time (`Africa/Casablanca` = UTC+1 year-round)
- Morning collect: 07:30 MET; briefing email: 08:00 MET; alert check: every 30 min 10:00–15:30 MET
- Price move alert threshold: >3% single-session move (configurable: `PRICE_MOVE_THRESHOLD_PCT` in config.py)
- Claude model for morning briefing: `claude-sonnet-4-6`; for alerts: `claude-haiku-4-5-20251001`
- All test commands run from `stocks/` directory: `python -m pytest tests/ -v`
- Dry-run mode: `python main.py --dry-run` — full pipeline, prints output to terminal, skips all email sends
- SQLite DB at `stocks/storage/stocks.db`, mounted as Docker volume at `/app/storage/`
- All file paths below are relative to `Mizan/` (the repo root)

---

### Task 1: Project Scaffold, Configuration, and Storage

**Files:**
- Create: `stocks/requirements.txt`
- Create: `stocks/pytest.ini`
- Create: `stocks/.env.example`
- Create: `stocks/config.py`
- Create: `stocks/watchlist.json`
- Create: `stocks/storage/__init__.py` (empty)
- Create: `stocks/storage/db.py`
- Create: `stocks/collectors/__init__.py` (empty)
- Create: `stocks/agent/__init__.py` (empty)
- Create: `stocks/delivery/__init__.py` (empty)
- Create: `stocks/scheduler/__init__.py` (empty)
- Create: `stocks/logs/.gitkeep`
- Create: `stocks/tests/__init__.py` (empty)
- Create: `stocks/tests/fixtures/.gitkeep`
- Create: `stocks/conftest.py`
- Create: `stocks/tests/test_storage.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `storage.db.init_db() → None` — creates 3 tables if not exist
  - `storage.db.get_connection()` — context manager yielding `sqlite3.Connection` (auto-commit/rollback/close)
  - `storage.db.upsert_price(ticker: str, date: str, ohlcv: dict) → None` — ohlcv keys: `open, high, low, close, volume`; duplicate `(ticker, date)` updates in place
  - `storage.db.get_price_history(ticker: str, days: int = 200) → list[dict]` — each dict: `{ticker, date, open, high, low, close, volume}`, oldest-first
  - `storage.db.save_briefing(date: str, content: str, raw_data: dict) → None`
  - `storage.db.get_last_briefing() → dict | None` — keys: `id, date, content, raw_data, created_at`
  - `storage.db.log_alert(ticker: str | None, trigger_reason: str, content: str) → None`
  - `config.DB_PATH: Path`, `config.WATCHLIST_PATH: Path`, `config.LOG_PATH: Path`
  - `config.PRICE_MOVE_THRESHOLD_PCT: float` = 3.0
  - `config.MORNING_BRIEFING_MODEL: str` = `"claude-sonnet-4-6"`
  - `config.ALERT_MODEL: str` = `"claude-haiku-4-5-20251001"`
  - `config.RSS_FEEDS: list[dict]` — each `{"name": str, "url": str}`
  - `config.COMMODITY_TICKERS: dict[str, str]`, `config.GLOBAL_INDEX_TICKERS: dict[str, str]`, `config.FOREX_TICKERS: dict[str, str]`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p stocks/{collectors,agent,delivery/templates,scheduler,storage,tests/fixtures,logs}
touch stocks/storage/__init__.py stocks/collectors/__init__.py stocks/agent/__init__.py \
  stocks/delivery/__init__.py stocks/scheduler/__init__.py stocks/tests/__init__.py \
  stocks/logs/.gitkeep stocks/tests/fixtures/.gitkeep
```

- [ ] **Step 2: Create `stocks/requirements.txt`**

```
anthropic>=0.40.0
yfinance>=0.2.40
pandas>=2.2.0
pandas-ta>=0.3.14b
beautifulsoup4>=4.12.0
requests>=2.32.0
feedparser>=6.0.11
APScheduler>=3.10.4
Jinja2>=3.1.4
python-dotenv>=1.0.1
pytz>=2024.1
lxml>=5.2.0
pytest>=8.0.0
```

- [ ] **Step 3: Create `stocks/pytest.ini`**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
addopts = -v
```

- [ ] **Step 4: Create `stocks/.env.example`**

```
ANTHROPIC_API_KEY=sk-ant-...
EXCHANGE_RATE_API_KEY=your_key_here
GMAIL_USER=your@gmail.com
GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
RECIPIENT_EMAIL=recipient@email.com
```

- [ ] **Step 5: Create `stocks/config.py`**

```python
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
EXCHANGE_RATE_API_KEY = os.environ.get("EXCHANGE_RATE_API_KEY", "")
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
RECIPIENT_EMAIL = os.environ["RECIPIENT_EMAIL"]

DB_PATH = BASE_DIR / "storage" / "stocks.db"
WATCHLIST_PATH = BASE_DIR / "watchlist.json"
LOG_PATH = BASE_DIR / "logs" / "errors.log"

PRICE_MOVE_THRESHOLD_PCT = 3.0

MARKET_OPEN_HOUR = 10
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30

MORNING_BRIEFING_MODEL = "claude-sonnet-4-6"
ALERT_MODEL = "claude-haiku-4-5-20251001"

COLLECT_HOUR = 7
COLLECT_MINUTE = 30
BRIEFING_HOUR = 8
BRIEFING_MINUTE = 0
ALERT_INTERVAL_MINUTES = 30

BVC_URL = "https://www.bvc.ma/bourse/cours.html"

RSS_FEEDS = [
    {"name": "Reuters Business", "url": "https://feeds.reuters.com/reuters/businessNews"},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"name": "Medias24", "url": "https://medias24.com/feed"},
    {"name": "Le Matin", "url": "https://www.lematin.ma/rss/news.xml"},
    {"name": "MAP", "url": "https://www.mapnews.ma/en/rss.xml"},
]

COMMODITY_TICKERS = {
    "brent_crude": "BZ=F",
    "natural_gas": "NG=F",
    "gold": "GC=F",
    "silver": "SI=F",
    "copper": "HG=F",
    "wheat": "ZW=F",
    "corn": "ZC=F",
    "phosphate_proxy": "MOS",  # Mosaic Co — largest public phosphate producer; proxy for OCP's commodity
}

GLOBAL_INDEX_TICKERS = {
    "sp500": "^GSPC",
    "cac40": "^FCHI",
    "msci_em": "EEM",
    "msci_frontier": "FM",
    "vix": "^VIX",
    "us_10y": "^TNX",
}

FOREX_TICKERS = {
    "eurusd": "EURUSD=X",
    "dxy": "DX-Y.NYB",
}
```

- [ ] **Step 6: Create `stocks/watchlist.json`**

```json
[
  { "ticker": "OCP", "name": "OCP Group", "note_price": 261.0 },
  { "ticker": "ATW", "name": "Attijariwafa Bank", "note_price": null }
]
```

- [ ] **Step 7: Create `stocks/conftest.py`**

```python
import os

# Must be set before any module imports config.py
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("GMAIL_USER", "test@gmail.com")
os.environ.setdefault("GMAIL_APP_PASSWORD", "test-password")
os.environ.setdefault("RECIPIENT_EMAIL", "recipient@test.com")

import pytest
import storage.db as db_module


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")
    db_module.init_db()
    return tmp_path / "test.db"
```

- [ ] **Step 8: Write failing tests in `stocks/tests/test_storage.py`**

```python
import storage.db as db_module


def test_init_creates_all_tables(test_db):
    with db_module.get_connection() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()}
    assert tables == {"prices", "briefings", "alerts"}


def test_upsert_price_and_retrieve(test_db):
    db_module.upsert_price("OCP", "2026-06-24", {
        "open": 260.0, "high": 265.0, "low": 258.0, "close": 262.0, "volume": 15000
    })
    history = db_module.get_price_history("OCP", days=10)
    assert len(history) == 1
    assert history[0]["close"] == 262.0
    assert history[0]["ticker"] == "OCP"


def test_upsert_price_deduplicates(test_db):
    db_module.upsert_price("OCP", "2026-06-24", {"open": 260.0, "high": 265.0, "low": 258.0, "close": 262.0, "volume": 15000})
    db_module.upsert_price("OCP", "2026-06-24", {"open": 260.0, "high": 267.0, "low": 258.0, "close": 263.0, "volume": 16000})
    history = db_module.get_price_history("OCP", days=10)
    assert len(history) == 1
    assert history[0]["close"] == 263.0


def test_save_and_retrieve_briefing(test_db):
    db_module.save_briefing("2026-06-24", "<p>Analysis</p>", {"key": "value"})
    briefing = db_module.get_last_briefing()
    assert briefing["date"] == "2026-06-24"
    assert briefing["content"] == "<p>Analysis</p>"


def test_log_alert_stores_record(test_db):
    db_module.log_alert("OCP", "price_move_4pct", "OCP moved 4%")
    with db_module.get_connection() as conn:
        row = dict(conn.execute("SELECT * FROM alerts").fetchone())
    assert row["ticker"] == "OCP"
    assert row["trigger_reason"] == "price_move_4pct"
```

- [ ] **Step 9: Run tests — confirm failure**

```bash
cd stocks && python -m pytest tests/test_storage.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'storage'`

- [ ] **Step 10: Install dependencies**

```bash
cd stocks && pip install -r requirements.txt
```
Expected: All packages install without error

- [ ] **Step 11: Create `stocks/storage/db.py`**

```python
import sqlite3
import json
import logging
from contextlib import contextmanager
from datetime import datetime

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
        """, (date, content, json.dumps(raw_data), datetime.utcnow().isoformat()))


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
        """, (ticker, trigger_reason, content, datetime.utcnow().isoformat()))
```

- [ ] **Step 12: Run tests — confirm all pass**

```bash
cd stocks && python -m pytest tests/test_storage.py -v
```
Expected: 5 passed

- [ ] **Step 13: Commit**

```bash
cd stocks && git init && git add -A && git commit -m "feat: project scaffold, config, and SQLite storage layer"
```

---

### Task 2: BVC Stock Price Collector

**Files:**
- Create: `stocks/collectors/bvc.py`
- Create: `stocks/tests/fixtures/bvc_sample.html`
- Modify: `stocks/tests/test_collectors.py` (create with BVC tests)

**Interfaces:**
- Consumes: `config.BVC_URL`
- Produces:
  - `collectors.bvc.collect() → dict` with shape:
    ```
    {
      "success": bool,
      "data": {
        "date": "2026-06-24",
        "masi": {"value": 13245.5, "change_pct": 0.3},
        "madex": {"value": 10812.0, "change_pct": 0.2},
        "stocks": [
          {
            "ticker": "OCP",
            "name": "OCP Group",
            "open": 260.0, "high": 262.0, "low": 258.0, "close": 261.5,
            "change_pct": 0.19, "volume": 15342
          }
        ]
      },
      "errors": []
    }
    ```

**Note:** bvc.ma renders data as server-side HTML. If scraping returns 0 stocks after go-live, the site may have switched to client-side rendering — in that case replace `requests` with `playwright`. The fixture below represents the expected table structure; adjust column indices after inspecting the live page.

- [ ] **Step 1: Create fixture `stocks/tests/fixtures/bvc_sample.html`**

```html
<!DOCTYPE html>
<html lang="fr">
<body>
<div class="indices">
  <span class="masi-value">13 245,50</span>
  <span class="masi-var">+0,30%</span>
  <span class="madex-value">10 812,00</span>
  <span class="madex-var">+0,20%</span>
</div>
<table id="cours-table">
  <thead>
    <tr>
      <th>Valeur</th><th>Code</th><th>Ouverture</th>
      <th>Haut</th><th>Bas</th><th>Dernier</th><th>Var%</th><th>Volume</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>OCP Group</td><td>OCP</td><td>260,00</td>
      <td>262,00</td><td>258,00</td><td>261,50</td><td>+0,19%</td><td>15 342</td>
    </tr>
    <tr>
      <td>Attijariwafa Bank</td><td>ATW</td><td>452,00</td>
      <td>453,50</td><td>449,00</td><td>450,80</td><td>-0,44%</td><td>8 721</td>
    </tr>
  </tbody>
</table>
</body>
</html>
```

- [ ] **Step 2: Write failing tests in `stocks/tests/test_collectors.py`**

```python
from pathlib import Path
from unittest.mock import patch, MagicMock

FIXTURES = Path(__file__).parent / "fixtures"


# --- BVC ---

def test_bvc_collect_parses_stocks():
    from collectors.bvc import collect, _parse_html
    html = (FIXTURES / "bvc_sample.html").read_text()
    result = _parse_html(html)
    assert result["success"] is True
    stocks = result["data"]["stocks"]
    assert len(stocks) == 2
    ocp = next(s for s in stocks if s["ticker"] == "OCP")
    assert ocp["close"] == 261.5
    assert ocp["change_pct"] == 0.19
    assert ocp["volume"] == 15342


def test_bvc_collect_parses_indices():
    from collectors.bvc import _parse_html
    html = (FIXTURES / "bvc_sample.html").read_text()
    result = _parse_html(html)
    assert result["data"]["masi"]["value"] == 13245.5
    assert result["data"]["masi"]["change_pct"] == 0.3


def test_bvc_collect_returns_failure_on_error():
    from collectors.bvc import collect
    with patch("collectors.bvc.requests.get", side_effect=Exception("timeout")):
        result = collect()
    assert result["success"] is False
    assert len(result["errors"]) > 0
```

- [ ] **Step 3: Run tests — confirm failure**

```bash
cd stocks && python -m pytest tests/test_collectors.py::test_bvc_collect_parses_stocks -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'collectors.bvc'`

- [ ] **Step 4: Create `stocks/collectors/bvc.py`**

```python
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime

from config import BVC_URL

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BVC-Monitor/1.0)",
    "Accept-Language": "fr-MA,fr;q=0.9",
}


def _parse_french_number(s: str) -> float | None:
    if not s:
        return None
    try:
        return float(s.strip().replace("\xa0", "").replace(" ", "").replace(",", ".").replace("%", "").replace("+", ""))
    except ValueError:
        return None


def _parse_html(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    errors = []

    # Parse indices
    masi_val = soup.select_one(".masi-value")
    masi_var = soup.select_one(".masi-var")
    madex_val = soup.select_one(".madex-value")
    madex_var = soup.select_one(".madex-var")

    masi = {
        "value": _parse_french_number(masi_val.text) if masi_val else None,
        "change_pct": _parse_french_number(masi_var.text) if masi_var else None,
    }
    madex = {
        "value": _parse_french_number(madex_val.text) if madex_val else None,
        "change_pct": _parse_french_number(madex_var.text) if madex_var else None,
    }

    if masi["value"] is None:
        errors.append("Could not parse MASI index value")

    # Parse stocks table
    table = soup.select_one("#cours-table")
    stocks = []
    if table:
        for row in table.select("tbody tr"):
            cells = row.find_all("td")
            if len(cells) < 8:
                continue
            stocks.append({
                "name": cells[0].text.strip(),
                "ticker": cells[1].text.strip(),
                "open": _parse_french_number(cells[2].text),
                "high": _parse_french_number(cells[3].text),
                "low": _parse_french_number(cells[4].text),
                "close": _parse_french_number(cells[5].text),
                "change_pct": _parse_french_number(cells[6].text),
                "volume": int(_parse_french_number(cells[7].text) or 0),
            })
    else:
        errors.append("Stock table #cours-table not found — page structure may have changed")

    return {
        "success": len(stocks) > 0,
        "data": {
            "date": datetime.utcnow().date().isoformat(),
            "masi": masi,
            "madex": madex,
            "stocks": stocks,
        },
        "errors": errors,
    }


def collect() -> dict:
    try:
        resp = requests.get(BVC_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return _parse_html(resp.text)
    except Exception as exc:
        logger.error(f"BVC collector failed: {exc}", exc_info=True)
        return {"success": False, "data": {"stocks": [], "masi": {}, "madex": {}}, "errors": [str(exc)]}
```

- [ ] **Step 5: Run BVC tests — confirm all pass**

```bash
cd stocks && python -m pytest tests/test_collectors.py -k bvc -v
```
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
cd stocks && git add collectors/bvc.py tests/test_collectors.py tests/fixtures/bvc_sample.html
git commit -m "feat: BVC stock price collector with HTML fixture tests"
```

---

### Task 3: Commodities Collector

**Files:**
- Create: `stocks/collectors/commodities.py`
- Modify: `stocks/tests/test_collectors.py` (add commodities tests)

**Interfaces:**
- Consumes: `config.COMMODITY_TICKERS`
- Produces:
  - `collectors.commodities.collect() → dict` with shape:
    ```
    {
      "success": bool,
      "data": {
        "brent_crude": {"price": 78.5, "change_pct": 1.2},
        "gold": {"price": 2340.0, "change_pct": -0.5},
        "natural_gas": {"price": 2.1, "change_pct": 0.8},
        "silver": {"price": 29.4, "change_pct": -0.3},
        "copper": {"price": 4.5, "change_pct": 0.6},
        "wheat": {"price": 540.0, "change_pct": -1.1},
        "corn": {"price": 420.0, "change_pct": 0.2},
        "phosphate_proxy": {"price": 15.3, "change_pct": 2.1}
      },
      "errors": []
    }
    ```

- [ ] **Step 1: Add failing tests to `stocks/tests/test_collectors.py`**

Append to the file:

```python
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
```

- [ ] **Step 2: Run tests — confirm failure**

```bash
cd stocks && python -m pytest tests/test_collectors.py -k commodities -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'collectors.commodities'`

- [ ] **Step 3: Create `stocks/collectors/commodities.py`**

```python
import time
import logging
import yfinance as yf

from config import COMMODITY_TICKERS

logger = logging.getLogger(__name__)


def _fetch_ticker(ticker_symbol: str) -> dict:
    for attempt in range(3):
        try:
            hist = yf.Ticker(ticker_symbol).history(period="2d")
            if hist.empty:
                return {}
            latest_close = float(hist["Close"].iloc[-1])
            prev_close = float(hist["Close"].iloc[-2]) if len(hist) > 1 else latest_close
            change_pct = round((latest_close - prev_close) / prev_close * 100, 2) if prev_close else 0.0
            return {"price": round(latest_close, 4), "change_pct": change_pct}
        except Exception as exc:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    return {}


def collect() -> dict:
    data = {}
    errors = []

    for name, symbol in COMMODITY_TICKERS.items():
        try:
            data[name] = _fetch_ticker(symbol)
        except Exception as exc:
            logger.error(f"Commodities: failed to fetch {name} ({symbol}): {exc}")
            errors.append(f"{name}: {exc}")
            data[name] = {}

    return {
        "success": len(data) > len(errors),
        "data": data,
        "errors": errors,
    }
```

- [ ] **Step 4: Run tests — confirm all pass**

```bash
cd stocks && python -m pytest tests/test_collectors.py -k commodities -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
cd stocks && git add collectors/commodities.py tests/test_collectors.py
git commit -m "feat: commodities collector with yfinance and exponential backoff"
```

---

### Task 4: Macro and Forex Collector

**Files:**
- Create: `stocks/collectors/macro.py`
- Modify: `stocks/tests/test_collectors.py` (add macro tests)

**Interfaces:**
- Consumes: `config.GLOBAL_INDEX_TICKERS`, `config.FOREX_TICKERS`, `config.EXCHANGE_RATE_API_KEY`
- Produces:
  - `collectors.macro.collect() → dict` with shape:
    ```
    {
      "success": bool,
      "data": {
        "indices": {
          "sp500": {"price": 5400.0, "change_pct": 0.5},
          "cac40": {"price": 7850.0, "change_pct": -0.2},
          "msci_em": {"price": 44.1, "change_pct": 0.3},
          "msci_frontier": {"price": 18.2, "change_pct": 0.1},
          "vix": {"price": 14.5, "change_pct": -2.1},
          "us_10y": {"price": 4.25, "change_pct": 0.02}
        },
        "forex": {
          "eurusd": {"price": 1.085, "change_pct": 0.1},
          "dxy": {"price": 104.2, "change_pct": -0.3},
          "usd_mad": {"price": 9.95, "change_pct": 0.05},
          "eur_mad": {"price": 10.80, "change_pct": 0.1}
        }
      },
      "errors": []
    }
    ```

- [ ] **Step 1: Add failing tests to `stocks/tests/test_collectors.py`**

Append:

```python
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
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd stocks && python -m pytest tests/test_collectors.py -k macro -v
```
Expected: FAIL

- [ ] **Step 3: Create `stocks/collectors/macro.py`**

```python
import logging
import time
import requests
import yfinance as yf

from config import GLOBAL_INDEX_TICKERS, FOREX_TICKERS, EXCHANGE_RATE_API_KEY

logger = logging.getLogger(__name__)

EXCHANGE_RATE_URL = "https://open.exchangerate-api.com/v6/latest/USD"


def _fetch_mad_rates() -> dict:
    url = (
        f"https://v6.exchangerate-api.com/v6/{EXCHANGE_RATE_API_KEY}/latest/USD"
        if EXCHANGE_RATE_API_KEY
        else EXCHANGE_RATE_URL
    )
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json().get("conversion_rates", resp.json().get("rates", {}))


def _fetch_yf(symbol: str) -> dict:
    for attempt in range(3):
        try:
            hist = yf.Ticker(symbol).history(period="2d")
            if hist.empty:
                return {"price": None, "change_pct": None}
            latest = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else latest
            return {
                "price": round(latest, 4),
                "change_pct": round((latest - prev) / prev * 100, 2) if prev else 0.0,
            }
        except Exception as exc:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    return {}


def collect() -> dict:
    errors = []
    indices = {}
    forex = {}

    for name, symbol in GLOBAL_INDEX_TICKERS.items():
        try:
            indices[name] = _fetch_yf(symbol)
        except Exception as exc:
            logger.error(f"Macro index {name}: {exc}")
            errors.append(f"{name}: {exc}")
            indices[name] = {"price": None, "change_pct": None}

    for name, symbol in FOREX_TICKERS.items():
        try:
            forex[name] = _fetch_yf(symbol)
        except Exception as exc:
            logger.error(f"Macro forex {name}: {exc}")
            errors.append(f"{name}: {exc}")
            forex[name] = {"price": None, "change_pct": None}

    try:
        rates = _fetch_mad_rates()
        usd_mad = rates.get("MAD")
        eur_rate = rates.get("EUR")
        eur_mad = round(usd_mad / eur_rate, 4) if usd_mad and eur_rate else None
        forex["usd_mad"] = {"price": usd_mad, "change_pct": None}
        forex["eur_mad"] = {"price": eur_mad, "change_pct": None}
    except Exception as exc:
        logger.error(f"Macro MAD rates: {exc}")
        errors.append(f"MAD rates: {exc}")
        forex["usd_mad"] = {"price": None, "change_pct": None}
        forex["eur_mad"] = {"price": None, "change_pct": None}

    return {
        "success": bool(indices),
        "data": {"indices": indices, "forex": forex},
        "errors": errors,
    }
```

- [ ] **Step 4: Run — confirm all pass**

```bash
cd stocks && python -m pytest tests/test_collectors.py -k macro -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
cd stocks && git add collectors/macro.py tests/test_collectors.py
git commit -m "feat: macro and forex collector (yfinance + exchange rate API)"
```

---

### Task 5: News Collector

**Files:**
- Create: `stocks/collectors/news.py`
- Create: `stocks/tests/fixtures/news_sample.xml`
- Modify: `stocks/tests/test_collectors.py` (add news tests)

**Interfaces:**
- Consumes: `config.RSS_FEEDS`
- Produces:
  - `collectors.news.collect() → dict` with shape:
    ```
    {
      "success": bool,
      "data": {
        "articles": [
          {
            "title": "Morocco raises interest rate",
            "summary": "Bank Al-Maghrib...",
            "published": "Tue, 24 Jun 2026 08:00:00 +0000",
            "link": "https://...",
            "source": "Reuters Business"
          }
        ]
      },
      "errors": []
    }
    ```

- [ ] **Step 1: Create `stocks/tests/fixtures/news_sample.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test News Feed</title>
    <item>
      <title>Morocco raises interest rate to 3%</title>
      <description>Bank Al-Maghrib announced a rate hike amid inflation pressures.</description>
      <pubDate>Tue, 24 Jun 2026 08:00:00 +0000</pubDate>
      <link>https://example.com/article1</link>
    </item>
    <item>
      <title>OCP Group signs new export deal</title>
      <description>Morocco's OCP Group secured a multi-year phosphate contract.</description>
      <pubDate>Tue, 24 Jun 2026 07:30:00 +0000</pubDate>
      <link>https://example.com/article2</link>
    </item>
  </channel>
</rss>
```

- [ ] **Step 2: Add failing tests to `stocks/tests/test_collectors.py`**

Append:

```python
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
```

- [ ] **Step 3: Run — confirm failure**

```bash
cd stocks && python -m pytest tests/test_collectors.py -k news -v
```
Expected: FAIL

- [ ] **Step 4: Create `stocks/collectors/news.py`**

```python
import logging
import feedparser

from config import RSS_FEEDS

logger = logging.getLogger(__name__)

MAX_ARTICLES_PER_FEED = 10


def _fetch_feed(url: str, name: str) -> list[dict]:
    feed = feedparser.parse(url)
    if feed.bozo and not feed.entries:
        raise ValueError(f"Failed to parse feed: {feed.bozo_exception}")
    articles = []
    for entry in feed.entries[:MAX_ARTICLES_PER_FEED]:
        articles.append({
            "title": entry.get("title", ""),
            "summary": entry.get("summary", entry.get("description", "")),
            "published": entry.get("published", ""),
            "link": entry.get("link", ""),
            "source": name,
        })
    return articles


def collect() -> dict:
    all_articles = []
    errors = []

    for feed_cfg in RSS_FEEDS:
        try:
            articles = _fetch_feed(feed_cfg["url"], feed_cfg["name"])
            all_articles.extend(articles)
        except Exception as exc:
            logger.error(f"News: failed to fetch {feed_cfg['name']}: {exc}")
            errors.append(f"{feed_cfg['name']}: {exc}")

    return {
        "success": len(all_articles) > 0 or len(RSS_FEEDS) == 0,
        "data": {"articles": all_articles},
        "errors": errors,
    }
```

- [ ] **Step 5: Run — confirm all pass**

```bash
cd stocks && python -m pytest tests/test_collectors.py -k news -v
```
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
cd stocks && git add collectors/news.py tests/test_collectors.py tests/fixtures/news_sample.xml
git commit -m "feat: news collector from RSS feeds with per-feed error isolation"
```

---

### Task 6: Technical Analysis Collector

**Files:**
- Create: `stocks/collectors/technical.py`
- Create: `stocks/tests/fixtures/prices_sample.json`
- Modify: `stocks/tests/test_collectors.py` (add technical tests)

**Interfaces:**
- Consumes: `storage.db.get_price_history(ticker, days=200)`
- Produces:
  - `collectors.technical.collect(tickers: list[str]) → dict` with shape:
    ```
    {
      "success": bool,
      "data": {
        "OCP": {
          "rsi": 58.3,
          "macd": {"macd": 1.23, "signal": 0.98, "histogram": 0.25},
          "sma20": 259.4, "sma50": 255.1, "sma200": 248.0,
          "bollinger": {"upper": 268.0, "middle": 259.4, "lower": 250.8},
          "current_price": 261.5,
          "volume_trend": "increasing",
          "support": 252.0, "resistance": 270.0,
          "fibonacci": {"0.0": 240.0, "0.236": 254.7, "0.382": 261.1,
                        "0.5": 265.0, "0.618": 268.9, "1.0": 290.0}
        }
      },
      "errors": []
    }
    ```

- [ ] **Step 1: Generate `stocks/tests/fixtures/prices_sample.json`**

Run this once to create the fixture (uses numpy to generate realistic price data):

```python
# Run from stocks/ directory: python -c "exec(open('tests/generate_fixture.py').read())"
# Or copy this block into a Python shell

import json, math, random
random.seed(42)

prices = []
base = 260.0
for i in range(100):
    base += random.gauss(0, 2)
    daily_range = abs(random.gauss(0, 1.5))
    prices.append({
        "ticker": "OCP",
        "date": f"2026-0{3 if i < 31 else 4}-{(i % 28) + 1:02d}",
        "open": round(base - daily_range / 2, 2),
        "high": round(base + daily_range, 2),
        "low": round(base - daily_range, 2),
        "close": round(base, 2),
        "volume": random.randint(5000, 30000)
    })

with open("tests/fixtures/prices_sample.json", "w") as f:
    json.dump(prices, f, indent=2)
print(f"Generated {len(prices)} price records")
```

Run it:

```bash
cd stocks && python -c "
import json, random
random.seed(42)
prices = []
base = 260.0
for i in range(100):
    base += random.gauss(0, 2)
    r = abs(random.gauss(0, 1.5))
    prices.append({'ticker':'OCP','date':f'2026-{(3 + i//31):02d}-{(i%28)+1:02d}','open':round(base-r/2,2),'high':round(base+r,2),'low':round(base-r,2),'close':round(base,2),'volume':random.randint(5000,30000)})
with open('tests/fixtures/prices_sample.json','w') as f:
    json.dump(prices, f, indent=2)
print('Generated', len(prices), 'records')
"
```
Expected: `Generated 100 records`

- [ ] **Step 2: Add failing tests to `stocks/tests/test_collectors.py`**

Append:

```python
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
```

- [ ] **Step 3: Run — confirm failure**

```bash
cd stocks && python -m pytest tests/test_collectors.py -k technical -v
```
Expected: FAIL

- [ ] **Step 4: Create `stocks/collectors/technical.py`**

```python
import logging
import pandas as pd
import pandas_ta as ta

from storage.db import get_price_history

logger = logging.getLogger(__name__)

MIN_HISTORY_DAYS = 20


def _compute_volume_trend(df: pd.DataFrame) -> str:
    if len(df) < 10:
        return "unknown"
    recent = df["volume"].tail(5).mean()
    older = df["volume"].tail(20).head(15).mean()
    if older == 0:
        return "unknown"
    ratio = recent / older
    if ratio > 1.2:
        return "increasing"
    if ratio < 0.8:
        return "decreasing"
    return "stable"


def _compute_fibonacci(df: pd.DataFrame, window: int = 60) -> dict:
    recent = df.tail(window)
    high = float(recent["high"].max()) if "high" in recent.columns else float(recent["close"].max())
    low = float(recent["low"].min()) if "low" in recent.columns else float(recent["close"].min())
    diff = high - low
    return {
        "0.0": round(low, 2),
        "0.236": round(low + diff * 0.236, 2),
        "0.382": round(low + diff * 0.382, 2),
        "0.5": round(low + diff * 0.5, 2),
        "0.618": round(low + diff * 0.618, 2),
        "1.0": round(high, 2),
    }


def _analyze_ticker(ticker: str) -> dict:
    history = get_price_history(ticker, days=200)
    if len(history) < MIN_HISTORY_DAYS:
        raise ValueError(f"Only {len(history)} days of history (need {MIN_HISTORY_DAYS}+)")

    df = pd.DataFrame(history)
    close = df["close"].astype(float)

    rsi_series = ta.rsi(close, length=14)
    macd_df = ta.macd(close)
    sma20 = ta.sma(close, length=20)
    sma50 = ta.sma(close, length=50) if len(df) >= 50 else None
    sma200 = ta.sma(close, length=200) if len(df) >= 200 else None
    bb = ta.bbands(close, length=20)

    def safe_float(series, idx=-1):
        if series is None or series.empty:
            return None
        val = series.iloc[idx]
        return round(float(val), 4) if pd.notna(val) else None

    return {
        "rsi": safe_float(rsi_series),
        "macd": {
            "macd": safe_float(macd_df["MACD_12_26_9"]) if macd_df is not None else None,
            "signal": safe_float(macd_df["MACDs_12_26_9"]) if macd_df is not None else None,
            "histogram": safe_float(macd_df["MACDh_12_26_9"]) if macd_df is not None else None,
        },
        "sma20": safe_float(sma20),
        "sma50": safe_float(sma50),
        "sma200": safe_float(sma200),
        "bollinger": {
            "upper": safe_float(bb["BBU_20_2.0"]) if bb is not None else None,
            "middle": safe_float(bb["BBM_20_2.0"]) if bb is not None else None,
            "lower": safe_float(bb["BBL_20_2.0"]) if bb is not None else None,
        },
        "current_price": round(float(close.iloc[-1]), 2),
        "volume_trend": _compute_volume_trend(df),
        "support": round(float(close.tail(20).min()), 2),
        "resistance": round(float(close.tail(20).max()), 2),
        "fibonacci": _compute_fibonacci(df),
    }


def collect(tickers: list[str]) -> dict:
    data = {}
    errors = []

    for ticker in tickers:
        try:
            data[ticker] = _analyze_ticker(ticker)
        except Exception as exc:
            logger.error(f"Technical: {ticker}: {exc}")
            errors.append(f"{ticker}: {exc}")

    return {
        "success": True,
        "data": data,
        "errors": errors,
    }
```

- [ ] **Step 5: Run — confirm all pass**

```bash
cd stocks && python -m pytest tests/test_collectors.py -k technical -v
```
Expected: 2 passed

- [ ] **Step 6: Run all collector tests together**

```bash
cd stocks && python -m pytest tests/ -v
```
Expected: All tests pass (storage + all collector tests)

- [ ] **Step 7: Commit**

```bash
cd stocks && git add collectors/technical.py tests/test_collectors.py tests/fixtures/prices_sample.json
git commit -m "feat: technical analysis collector (RSI, MACD, MAs, Bollinger, Fibonacci)"
```

---

### Task 7: AI Agent — Prompts

**Files:**
- Create: `stocks/agent/prompts.py`
- Create: `stocks/tests/test_agent.py`

**Interfaces:**
- Consumes: nothing (pure functions)
- Produces:
  - `agent.prompts.MORNING_BRIEFING_SYSTEM: str`
  - `agent.prompts.ALERT_SYSTEM: str`
  - `agent.prompts.build_morning_briefing_prompt(context: dict) → str` — returns prompt string containing JSON-serialized context
  - `agent.prompts.build_alert_prompt(alert_type: str, context: dict) → str`

- [ ] **Step 1: Write failing tests in `stocks/tests/test_agent.py`**

```python
def test_morning_briefing_prompt_contains_context():
    from agent.prompts import build_morning_briefing_prompt
    context = {"bvc": {"data": {"masi": {"value": 13245}}}, "date": "2026-06-24"}
    prompt = build_morning_briefing_prompt(context)
    assert "13245" in prompt
    assert "BUY" in prompt or "WATCH" in prompt or "label" in prompt.lower()
    assert "JSON" in prompt


def test_alert_prompt_contains_type_and_context():
    from agent.prompts import build_alert_prompt
    context = {"stock": {"ticker": "OCP", "change_pct": 4.2}}
    prompt = build_alert_prompt("price_move", context)
    assert "price_move" in prompt
    assert "OCP" in prompt
    assert "JSON" in prompt


def test_prompts_export_system_strings():
    from agent.prompts import MORNING_BRIEFING_SYSTEM, ALERT_SYSTEM
    assert len(MORNING_BRIEFING_SYSTEM) > 50
    assert len(ALERT_SYSTEM) > 50
    assert "BVC" in MORNING_BRIEFING_SYSTEM
    assert "JSON" in MORNING_BRIEFING_SYSTEM
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd stocks && python -m pytest tests/test_agent.py -v
```
Expected: FAIL

- [ ] **Step 3: Create `stocks/agent/prompts.py`**

```python
import json


MORNING_BRIEFING_SYSTEM = """You are an AI investment assistant specializing in the Casablanca Stock Exchange (BVC).
Your user is a beginner investor in Morocco learning as they invest. Explain reasoning in clear, educational terms — never use jargon without defining it.
Respond ONLY with valid JSON matching the exact schema provided. No markdown fences, no extra text."""


ALERT_SYSTEM = """You are a real-time investment alert assistant for a beginner investor on the Casablanca Stock Exchange (BVC).
Write clear, short, educational alerts. Explain what happened and why it matters in simple terms.
Respond ONLY with valid JSON matching the exact schema provided. No markdown fences, no extra text."""


def build_morning_briefing_prompt(context: dict) -> str:
    return f"""Analyze today's BVC market data and produce a morning briefing.

MARKET DATA:
{json.dumps(context, indent=2, ensure_ascii=False, default=str)}

Return a JSON object with this EXACT structure (no extra fields):
{{
  "market_pulse": {{
    "masi": {{"value": <float>, "change_pct": <float>, "comment": "<1 sentence>"}},
    "gold": {{"value": <float>, "change_pct": <float>, "comment": "<1 sentence>"}},
    "oil": {{"value": <float>, "change_pct": <float>, "comment": "<1 sentence>"}},
    "eur_mad": {{"value": <float>, "change_pct": <float>, "comment": "<1 sentence>"}},
    "cac40": {{"value": <float>, "change_pct": <float>, "comment": "<1 sentence>"}},
    "phosphate_proxy": {{"value": <float>, "change_pct": <float>, "comment": "<1 sentence>"}}
  }},
  "whats_happening": "<3-4 sentence summary of today's key events and their BVC relevance, in plain language>",
  "ai_picks": [
    {{
      "ticker": "<BVC ticker>",
      "name": "<company name>",
      "label": "<BUY|WATCH|AVOID>",
      "strategy": "<1-2 sentence tactical recommendation>",
      "explanation": "<3-4 sentence educational explanation for a beginner, including what technical signal supports this>"
    }}
  ],
  "this_week": ["<forward-looking event 1>", "<event 2>", "<event 3>"]
}}

Rules:
- Select 3-5 stocks for ai_picks; base decisions on technical signals in the data, not company fame
- Each explanation must define at least one technical term used (e.g. RSI, MACD, support level)
- Use null for any market_pulse value not present in the data"""


def build_alert_prompt(alert_type: str, context: dict) -> str:
    return f"""Generate a real-time BVC investment alert.

ALERT TYPE: {alert_type}
CONTEXT:
{json.dumps(context, indent=2, ensure_ascii=False, default=str)}

Return a JSON object with this EXACT structure:
{{
  "alert_type": "{alert_type}",
  "ticker": "<affected BVC ticker or null>",
  "headline": "<10-15 word headline summarizing the event>",
  "what_happened": "<2-3 sentences describing what occurred>",
  "what_it_means": "<2-3 sentences explaining portfolio impact for a beginner investor>",
  "educational_lesson": "<1-2 sentences: one investing concept this event illustrates>"
}}"""
```

- [ ] **Step 4: Run — confirm all pass**

```bash
cd stocks && python -m pytest tests/test_agent.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd stocks && git add agent/prompts.py tests/test_agent.py
git commit -m "feat: centralized AI prompts for morning briefing and alerts"
```

---

### Task 8: AI Agent — Analyst

**Files:**
- Create: `stocks/agent/analyst.py`
- Modify: `stocks/tests/test_agent.py` (add analyst tests)

**Interfaces:**
- Consumes: `agent.prompts.MORNING_BRIEFING_SYSTEM`, `agent.prompts.ALERT_SYSTEM`, `agent.prompts.build_morning_briefing_prompt`, `agent.prompts.build_alert_prompt`; `config.MORNING_BRIEFING_MODEL`, `config.ALERT_MODEL`, `config.ANTHROPIC_API_KEY`
- Produces:
  - `agent.analyst.run_morning_analysis(context: dict) → dict` — returns parsed JSON from Claude; on double failure returns `{"error": "AI analysis unavailable", "raw_context": context}`
  - `agent.analyst.run_alert_analysis(alert_type: str, context: dict) → dict` — returns parsed JSON from Claude; on double failure returns `{"error": "AI analysis unavailable", "context": context}`

- [ ] **Step 1: Add failing tests to `stocks/tests/test_agent.py`**

Append:

```python
import json
from unittest.mock import patch, MagicMock


MORNING_RESPONSE = {
    "market_pulse": {
        "masi": {"value": 13245.5, "change_pct": 0.3, "comment": "Slight uptick."},
        "gold": {"value": 2340.0, "change_pct": -0.5, "comment": "Minor pullback."},
        "oil": {"value": 78.5, "change_pct": 1.2, "comment": "Rising."},
        "eur_mad": {"value": 10.85, "change_pct": 0.1, "comment": "Stable."},
        "cac40": {"value": 7850.0, "change_pct": -0.2, "comment": "Slight loss."},
        "phosphate_proxy": {"value": 15.3, "change_pct": 2.1, "comment": "Positive signal for OCP."}
    },
    "whats_happening": "Markets are calm today.",
    "ai_picks": [{"ticker": "OCP", "name": "OCP Group", "label": "BUY",
                  "strategy": "Buy on RSI dip.", "explanation": "RSI is below 40."}],
    "this_week": ["AMMC filing deadline", "Fed rate decision"]
}

ALERT_RESPONSE = {
    "alert_type": "price_move",
    "ticker": "OCP",
    "headline": "OCP surges 4% on new export contract",
    "what_happened": "OCP jumped sharply.",
    "what_it_means": "Portfolio impact positive.",
    "educational_lesson": "Large moves often follow news catalysts."
}


def _make_mock_client(response_json: dict):
    mock_content = MagicMock()
    mock_content.text = json.dumps(response_json)
    mock_message = MagicMock()
    mock_message.content = [mock_content]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message
    return mock_client


def test_run_morning_analysis_returns_parsed_dict():
    from agent.analyst import run_morning_analysis
    with patch("agent.analyst.client", _make_mock_client(MORNING_RESPONSE)):
        result = run_morning_analysis({"date": "2026-06-24"})
    assert result["market_pulse"]["masi"]["value"] == 13245.5
    assert result["ai_picks"][0]["ticker"] == "OCP"


def test_run_morning_analysis_retries_and_returns_fallback():
    from agent.analyst import run_morning_analysis
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("API error")
    with patch("agent.analyst.client", mock_client):
        result = run_morning_analysis({"date": "2026-06-24"})
    assert "error" in result
    assert mock_client.messages.create.call_count == 2


def test_run_alert_analysis_returns_parsed_dict():
    from agent.analyst import run_alert_analysis
    with patch("agent.analyst.client", _make_mock_client(ALERT_RESPONSE)):
        result = run_alert_analysis("price_move", {"stock": {"ticker": "OCP"}})
    assert result["ticker"] == "OCP"
    assert result["alert_type"] == "price_move"
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd stocks && python -m pytest tests/test_agent.py -k analyst -v
```
Expected: FAIL

- [ ] **Step 3: Create `stocks/agent/analyst.py`**

```python
import json
import logging
import anthropic

from config import ANTHROPIC_API_KEY, MORNING_BRIEFING_MODEL, ALERT_MODEL
from agent.prompts import (
    MORNING_BRIEFING_SYSTEM, ALERT_SYSTEM,
    build_morning_briefing_prompt, build_alert_prompt,
)

logger = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def run_morning_analysis(context: dict) -> dict:
    prompt = build_morning_briefing_prompt(context)
    for attempt in range(2):
        try:
            message = client.messages.create(
                model=MORNING_BRIEFING_MODEL,
                max_tokens=4096,
                system=MORNING_BRIEFING_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            return json.loads(message.content[0].text)
        except Exception as exc:
            logger.error(f"Morning analysis attempt {attempt + 1} failed: {exc}", exc_info=True)
    return {"error": "AI analysis unavailable", "raw_context": context}


def run_alert_analysis(alert_type: str, context: dict) -> dict:
    prompt = build_alert_prompt(alert_type, context)
    for attempt in range(2):
        try:
            message = client.messages.create(
                model=ALERT_MODEL,
                max_tokens=1024,
                system=ALERT_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            return json.loads(message.content[0].text)
        except Exception as exc:
            logger.error(f"Alert analysis attempt {attempt + 1} failed: {exc}", exc_info=True)
    return {"error": "AI analysis unavailable", "context": context}
```

- [ ] **Step 4: Run all agent tests**

```bash
cd stocks && python -m pytest tests/test_agent.py -v
```
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd stocks && git add agent/analyst.py tests/test_agent.py
git commit -m "feat: Claude API analyst with 2-attempt retry and fallback response"
```

---

### Task 9: Email Formatter and HTML Templates

**Files:**
- Create: `stocks/agent/formatter.py`
- Create: `stocks/delivery/templates/morning_briefing.html`
- Create: `stocks/delivery/templates/alert.html`
- Create: `stocks/tests/test_delivery.py`

**Interfaces:**
- Consumes: `agent.analyst.run_morning_analysis` output dict; `agent.analyst.run_alert_analysis` output dict
- Produces:
  - `agent.formatter.format_morning_briefing(analysis: dict, date: str) → str` — returns HTML string
  - `agent.formatter.format_alert(analysis: dict) → str` — returns HTML string

- [ ] **Step 1: Create `stocks/delivery/templates/morning_briefing.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BVC Morning Briefing — {{ date }}</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 680px; margin: 0 auto; padding: 20px; color: #222; background: #f5f5f5; }
    .card { background: white; border-radius: 8px; padding: 24px; margin-bottom: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
    .header { background: #1a5f3f; color: white; border-radius: 8px; padding: 20px 24px; margin-bottom: 20px; }
    .header h1 { margin: 0 0 4px; font-size: 22px; }
    .header p { margin: 0; opacity: .8; font-size: 14px; }
    .pulse-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
    .pulse-card { border: 1px solid #e8e8e8; border-radius: 6px; padding: 12px; text-align: center; }
    .pulse-label { font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: .5px; }
    .pulse-value { font-size: 18px; font-weight: bold; margin: 4px 0; }
    .pulse-comment { font-size: 11px; color: #555; margin-top: 4px; }
    .up { color: #1a8c4e; }
    .down { color: #c0392b; }
    .section-title { font-size: 16px; font-weight: bold; color: #1a5f3f; border-bottom: 2px solid #1a5f3f; padding-bottom: 6px; margin-bottom: 16px; }
    .pick { border-left: 4px solid #1a5f3f; padding: 12px 16px; margin-bottom: 12px; background: #f8f9fa; border-radius: 0 6px 6px 0; }
    .pick-header { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
    .pick-name { font-weight: bold; font-size: 15px; }
    .label { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; text-transform: uppercase; }
    .label-buy { background: #1a8c4e; color: white; }
    .label-watch { background: #e67e22; color: white; }
    .label-avoid { background: #c0392b; color: white; }
    .strategy { font-style: italic; color: #444; margin-bottom: 6px; font-size: 14px; }
    .explanation { font-size: 14px; color: #333; }
    .week-list { padding-left: 20px; }
    .week-list li { margin-bottom: 6px; font-size: 14px; }
    .footer { text-align: center; color: #aaa; font-size: 11px; margin-top: 20px; }
  </style>
</head>
<body>
  <div class="header">
    <h1>BVC Morning Briefing</h1>
    <p>{{ date }}</p>
  </div>

  <div class="card">
    <div class="section-title">Market Pulse</div>
    <div class="pulse-grid">
      {% for key, item in market_pulse.items() %}
      <div class="pulse-card">
        <div class="pulse-label">{{ key | replace("_", " ") }}</div>
        <div class="pulse-value">{{ item.value if item.value is not none else "N/A" }}</div>
        {% if item.change_pct is not none %}
        <div class="{{ 'up' if item.change_pct >= 0 else 'down' }}">
          {{ '+' if item.change_pct >= 0 else '' }}{{ item.change_pct }}%
        </div>
        {% endif %}
        <div class="pulse-comment">{{ item.comment }}</div>
      </div>
      {% endfor %}
    </div>
  </div>

  <div class="card">
    <div class="section-title">What's Happening</div>
    <p>{{ whats_happening }}</p>
  </div>

  <div class="card">
    <div class="section-title">AI Picks</div>
    {% for pick in ai_picks %}
    <div class="pick">
      <div class="pick-header">
        <span class="pick-name">{{ pick.name }} ({{ pick.ticker }})</span>
        <span class="label label-{{ pick.label | lower }}">{{ pick.label }}</span>
      </div>
      <div class="strategy">{{ pick.strategy }}</div>
      <div class="explanation">{{ pick.explanation }}</div>
    </div>
    {% endfor %}
  </div>

  <div class="card">
    <div class="section-title">This Week</div>
    <ul class="week-list">
      {% for event in this_week %}
      <li>{{ event }}</li>
      {% endfor %}
    </ul>
  </div>

  <div class="footer">
    Mizan BVC AI Assistant &mdash; for educational purposes only, not financial advice
  </div>
</body>
</html>
```

- [ ] **Step 2: Create `stocks/delivery/templates/alert.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>BVC Alert{% if ticker %}: {{ ticker }}{% endif %}</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 680px; margin: 0 auto; padding: 20px; background: #f5f5f5; color: #222; }
    .alert-header { background: #c0392b; color: white; border-radius: 8px; padding: 20px 24px; margin-bottom: 16px; }
    .alert-header h2 { margin: 0 0 4px; font-size: 20px; }
    .alert-header p { margin: 0; opacity: .9; font-size: 15px; font-weight: bold; }
    .card { background: white; border-radius: 8px; padding: 20px 24px; margin-bottom: 14px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
    .section-title { font-weight: bold; color: #444; font-size: 12px; text-transform: uppercase; letter-spacing: .5px; margin-bottom: 8px; }
    .lesson { background: #eaf4fb; border-left: 4px solid #2980b9; border-radius: 0 6px 6px 0; padding: 16px; margin-top: 4px; }
    .lesson .section-title { color: #2980b9; }
    .footer { text-align: center; color: #aaa; font-size: 11px; margin-top: 16px; }
  </style>
</head>
<body>
  <div class="alert-header">
    <h2>BVC Alert{% if ticker %}: {{ ticker }}{% endif %}</h2>
    <p>{{ headline }}</p>
  </div>

  <div class="card">
    <div class="section-title">What Happened</div>
    <p>{{ what_happened }}</p>
  </div>

  <div class="card">
    <div class="section-title">What It Means for Your Portfolio</div>
    <p>{{ what_it_means }}</p>
  </div>

  <div class="lesson">
    <div class="section-title">Today's Lesson</div>
    <p>{{ educational_lesson }}</p>
  </div>

  <div class="footer">Mizan BVC AI Assistant</div>
</body>
</html>
```

- [ ] **Step 3: Write failing tests in `stocks/tests/test_delivery.py`**

```python
from tests.test_agent import MORNING_RESPONSE, ALERT_RESPONSE


def test_format_morning_briefing_returns_html():
    from agent.formatter import format_morning_briefing
    html = format_morning_briefing(MORNING_RESPONSE, "Tuesday, June 24, 2026")
    assert "<html" in html
    assert "OCP" in html
    assert "BUY" in html
    assert "13245.5" in html
    assert "What's Happening" in html or "whats_happening" not in html


def test_format_morning_briefing_handles_null_values():
    from agent.formatter import format_morning_briefing
    analysis = dict(MORNING_RESPONSE)
    analysis["market_pulse"] = dict(MORNING_RESPONSE["market_pulse"])
    analysis["market_pulse"]["gold"] = {"value": None, "change_pct": None, "comment": "Unavailable"}
    html = format_morning_briefing(analysis, "2026-06-24")
    assert "N/A" in html


def test_format_alert_returns_html():
    from agent.formatter import format_alert
    html = format_alert(ALERT_RESPONSE)
    assert "<html" in html
    assert "OCP" in html
    assert "Today's Lesson" in html
    assert "OCP surges" in html
```

- [ ] **Step 4: Run — confirm failure**

```bash
cd stocks && python -m pytest tests/test_delivery.py -v
```
Expected: FAIL

- [ ] **Step 5: Create `stocks/agent/formatter.py`**

```python
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

_TEMPLATES_DIR = Path(__file__).parent.parent / "delivery" / "templates"
_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)))


def format_morning_briefing(analysis: dict, date: str) -> str:
    template = _env.get_template("morning_briefing.html")
    return template.render(date=date, **analysis)


def format_alert(analysis: dict) -> str:
    template = _env.get_template("alert.html")
    return template.render(**analysis)
```

- [ ] **Step 6: Run — confirm all pass**

```bash
cd stocks && python -m pytest tests/test_delivery.py -v
```
Expected: 3 passed

- [ ] **Step 7: Commit**

```bash
cd stocks && git add agent/formatter.py delivery/templates/ tests/test_delivery.py
git commit -m "feat: Jinja2 HTML formatter and email templates for briefing and alerts"
```

---

### Task 10: Email Delivery

**Files:**
- Create: `stocks/delivery/email.py`
- Modify: `stocks/tests/test_delivery.py` (add email tests)

**Interfaces:**
- Consumes: `config.GMAIL_USER`, `config.GMAIL_APP_PASSWORD`, `config.RECIPIENT_EMAIL`
- Produces:
  - `delivery.email.send_morning_briefing(html_body: str) → None` — sends via Gmail SMTP; raises on failure
  - `delivery.email.send_alert(html_body: str, ticker: str | None, alert_type: str) → None`

- [ ] **Step 1: Add failing tests to `stocks/tests/test_delivery.py`**

Append:

```python
from unittest.mock import patch, MagicMock


def test_send_morning_briefing_calls_smtp():
    from delivery.email import send_morning_briefing
    mock_smtp = MagicMock()
    with patch("delivery.email.smtplib.SMTP_SSL", return_value=mock_smtp.__enter__.return_value):
        mock_smtp.__enter__.return_value.login.return_value = None
        mock_smtp.__enter__.return_value.sendmail.return_value = None
        with patch("delivery.email.smtplib.SMTP_SSL") as mock_ssl:
            mock_ssl.return_value.__enter__.return_value = MagicMock()
            send_morning_briefing("<html>test</html>")
            mock_ssl.assert_called_once_with("smtp.gmail.com", 465)


def test_send_alert_includes_ticker_in_subject():
    from delivery.email import send_alert, _create_message
    msg = _create_message("⚡ BVC Alert [OCP]: price_move", "<html>alert</html>")
    assert "OCP" in msg["Subject"]
    assert "price_move" in msg["Subject"]
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd stocks && python -m pytest tests/test_delivery.py -k email -v
```
Expected: FAIL

- [ ] **Step 3: Create `stocks/delivery/email.py`**

```python
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

from config import GMAIL_USER, GMAIL_APP_PASSWORD, RECIPIENT_EMAIL

logger = logging.getLogger(__name__)


def _create_message(subject: str, html_body: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["From"] = GMAIL_USER
    msg["To"] = RECIPIENT_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


def send_email(subject: str, html_body: str) -> None:
    msg = _create_message(subject, html_body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, RECIPIENT_EMAIL, msg.as_string())
    logger.info(f"Email sent: {subject}")


def send_morning_briefing(html_body: str) -> None:
    date_str = datetime.now().strftime("%A, %B %d, %Y")
    send_email(f"BVC Morning Briefing — {date_str}", html_body)


def send_alert(html_body: str, ticker: str | None, alert_type: str) -> None:
    ticker_str = f" [{ticker}]" if ticker else ""
    send_email(f"BVC Alert{ticker_str}: {alert_type}", html_body)
```

- [ ] **Step 4: Run all delivery tests**

```bash
cd stocks && python -m pytest tests/test_delivery.py -v
```
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
cd stocks && git add delivery/email.py tests/test_delivery.py
git commit -m "feat: Gmail SMTP email delivery for briefing and alerts"
```

---

### Task 11: Scheduler, Main Entry Point, and Dry-Run Mode

**Files:**
- Create: `stocks/scheduler/jobs.py`
- Create: `stocks/main.py`

**Interfaces:**
- Consumes: all collectors, analyst, formatter, email, storage modules
- Produces:
  - `main.py --dry-run` — runs full pipeline once, prints HTML to stdout, skips email
  - `main.py` — starts APScheduler blocking loop (never returns)

- [ ] **Step 1: Create `stocks/scheduler/jobs.py`**

```python
import json
import logging
from datetime import datetime
from pathlib import Path

import pytz

from config import (
    COLLECT_HOUR, COLLECT_MINUTE, BRIEFING_HOUR, BRIEFING_MINUTE,
    ALERT_INTERVAL_MINUTES, MARKET_OPEN_HOUR, MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE,
    PRICE_MOVE_THRESHOLD_PCT, WATCHLIST_PATH, LOG_PATH,
)

logger = logging.getLogger(__name__)
MOROCCO_TZ = pytz.timezone("Africa/Casablanca")


def _load_watchlist() -> list[dict]:
    if WATCHLIST_PATH.exists():
        return json.loads(WATCHLIST_PATH.read_text())
    return []


def collect_and_persist() -> dict:
    from collectors.bvc import collect as collect_bvc
    from collectors.commodities import collect as collect_commodities
    from collectors.macro import collect as collect_macro
    from collectors.news import collect as collect_news
    from collectors.technical import collect as collect_technical
    from storage.db import upsert_price, init_db

    init_db()

    bvc = collect_bvc()
    today = datetime.now(MOROCCO_TZ).date().isoformat()

    if bvc["success"]:
        for stock in bvc["data"].get("stocks", []):
            if stock.get("ticker"):
                upsert_price(stock["ticker"], today, {
                    "open": stock.get("open"),
                    "high": stock.get("high"),
                    "low": stock.get("low"),
                    "close": stock.get("close"),
                    "volume": stock.get("volume"),
                })

    tickers = [s["ticker"] for s in bvc["data"].get("stocks", []) if s.get("ticker")]

    return {
        "date": today,
        "bvc": bvc,
        "commodities": collect_commodities(),
        "macro": collect_macro(),
        "news": collect_news(),
        "technical": collect_technical(tickers),
        "watchlist": _load_watchlist(),
    }


def run_morning_briefing(dry_run: bool = False) -> None:
    from agent.analyst import run_morning_analysis
    from agent.formatter import format_morning_briefing
    from delivery.email import send_morning_briefing
    from storage.db import save_briefing

    logger.info("Running morning briefing")
    context = collect_and_persist()
    analysis = run_morning_analysis(context)
    html = format_morning_briefing(analysis, context["date"])
    save_briefing(context["date"], html, context)

    if dry_run:
        print("\n" + "=" * 60)
        print("MORNING BRIEFING (DRY RUN — email not sent)")
        print("=" * 60)
        print(html[:2000])
        print("..." if len(html) > 2000 else "")
    else:
        try:
            send_morning_briefing(html)
        except Exception as exc:
            logger.error(f"Email delivery failed: {exc}", exc_info=True)


def run_alert_check(dry_run: bool = False) -> None:
    from collectors.bvc import collect as collect_bvc
    from collectors.news import collect as collect_news
    from agent.analyst import run_alert_analysis
    from agent.formatter import format_alert
    from delivery.email import send_alert
    from storage.db import log_alert

    now = datetime.now(MOROCCO_TZ)
    market_open = now.replace(hour=MARKET_OPEN_HOUR, minute=0, second=0, microsecond=0)
    market_close = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0)

    if not (market_open <= now <= market_close):
        logger.debug("Outside market hours — skipping alert check")
        return

    bvc = collect_bvc()
    news = collect_news()
    watchlist = _load_watchlist()
    watchlist_map = {w["ticker"]: w for w in watchlist}

    if not bvc["success"]:
        logger.warning("BVC data unavailable for alert check")
        return

    for stock in bvc["data"].get("stocks", []):
        ticker = stock.get("ticker")
        change_pct = stock.get("change_pct") or 0.0

        if abs(change_pct) >= PRICE_MOVE_THRESHOLD_PCT:
            context = {
                "stock": stock,
                "recent_news": news["data"].get("articles", [])[:5],
                "threshold_pct": PRICE_MOVE_THRESHOLD_PCT,
            }
            analysis = run_alert_analysis("price_move", context)
            html = format_alert(analysis)

            if dry_run:
                print(f"\n[ALERT DRY RUN] {ticker}: {change_pct:+.1f}%")
                print(html[:500])
            else:
                try:
                    send_alert(html, ticker, "price_move")
                    log_alert(ticker, f"price_move_{abs(change_pct):.1f}pct", html)
                except Exception as exc:
                    logger.error(f"Alert delivery failed for {ticker}: {exc}")

        w = watchlist_map.get(ticker)
        if w and w.get("note_price") and stock.get("close"):
            note = w["note_price"]
            close = stock["close"]
            if abs(close - note) / note < 0.005:
                context = {"stock": stock, "watchlist_entry": w}
                analysis = run_alert_analysis("watchlist_trigger", context)
                html = format_alert(analysis)
                if not dry_run:
                    try:
                        send_alert(html, ticker, "watchlist_trigger")
                        log_alert(ticker, "watchlist_trigger", html)
                    except Exception as exc:
                        logger.error(f"Watchlist alert failed for {ticker}: {exc}")
```

- [ ] **Step 2: Create `stocks/main.py`**

```python
import argparse
import logging
import sys
from pathlib import Path

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config import (
    COLLECT_HOUR, COLLECT_MINUTE, BRIEFING_HOUR, BRIEFING_MINUTE,
    ALERT_INTERVAL_MINUTES, MARKET_OPEN_HOUR, MARKET_CLOSE_HOUR, LOG_PATH,
)
from storage.db import init_db
from scheduler.jobs import collect_and_persist, run_morning_briefing, run_alert_check

MOROCCO_TZ = pytz.timezone("Africa/Casablanca")


def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH),
            logging.StreamHandler(sys.stdout),
        ],
    )


def run_dry_run() -> None:
    print("Running full pipeline in dry-run mode (no emails sent)...")
    run_morning_briefing(dry_run=True)
    run_alert_check(dry_run=True)
    print("\nDry run complete.")


def run_scheduler() -> None:
    scheduler = BlockingScheduler(timezone=MOROCCO_TZ)

    scheduler.add_job(
        collect_and_persist,
        CronTrigger(hour=COLLECT_HOUR, minute=COLLECT_MINUTE, timezone=MOROCCO_TZ),
        id="collect",
        name="Collect all market data",
    )
    scheduler.add_job(
        run_morning_briefing,
        CronTrigger(hour=BRIEFING_HOUR, minute=BRIEFING_MINUTE, timezone=MOROCCO_TZ),
        id="briefing",
        name="Morning briefing email",
    )
    scheduler.add_job(
        run_alert_check,
        CronTrigger(
            hour=f"{MARKET_OPEN_HOUR}-{MARKET_CLOSE_HOUR}",
            minute=f"*/{ALERT_INTERVAL_MINUTES}",
            timezone=MOROCCO_TZ,
        ),
        id="alerts",
        name="Intraday alert check",
    )

    logging.getLogger(__name__).info("Scheduler started. Press Ctrl+C to exit.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mizan BVC AI Assistant")
    parser.add_argument("--dry-run", action="store_true", help="Run pipeline once without sending emails")
    args = parser.parse_args()

    setup_logging()
    init_db()

    if args.dry_run:
        run_dry_run()
    else:
        run_scheduler()
```

- [ ] **Step 3: Verify dry-run mode works end-to-end (requires `.env` with real API key)**

```bash
cd stocks && cp .env.example .env
# Fill in your actual ANTHROPIC_API_KEY, GMAIL credentials in .env
python main.py --dry-run
```
Expected: Pipeline runs, prints HTML morning briefing to stdout, prints alert check results, exits cleanly. No emails sent.

- [ ] **Step 4: Commit**

```bash
cd stocks && git add scheduler/jobs.py main.py
git commit -m "feat: APScheduler pipeline with Morocco timezone and dry-run mode"
```

---

### Task 12: Docker Containerization

**Files:**
- Create: `stocks/Dockerfile`
- Create: `stocks/docker-compose.yml`
- Create: `stocks/.dockerignore`

**Interfaces:**
- Consumes: `stocks/requirements.txt`, `stocks/.env`
- Produces: `docker compose up -d` starts the container; SQLite DB and logs persist via volume mount

- [ ] **Step 1: Create `stocks/.dockerignore`**

```
.env
*.pyc
__pycache__/
.pytest_cache/
tests/
*.db
logs/
*.egg-info/
.git/
```

- [ ] **Step 2: Create `stocks/Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/storage /app/logs

CMD ["python", "main.py"]
```

- [ ] **Step 3: Create `stocks/docker-compose.yml`**

```yaml
services:
  bvc-agent:
    build: .
    restart: always
    env_file:
      - .env
    volumes:
      - ./storage:/app/storage
      - ./logs:/app/logs
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

- [ ] **Step 4: Build the Docker image**

```bash
cd stocks && docker compose build
```
Expected: Build succeeds with no errors. Final line: `Successfully built ...` or `bvc-agent Built`

- [ ] **Step 5: Verify container dry-run**

```bash
cd stocks && docker compose run --rm bvc-agent python main.py --dry-run
```
Expected: Full pipeline output printed to terminal, container exits cleanly

- [ ] **Step 6: Start in detached mode**

```bash
cd stocks && docker compose up -d
```
Expected: Container starts. Verify with:
```bash
docker compose logs -f bvc-agent
```
Expected log output: `Scheduler started. Press Ctrl+C to exit.`

- [ ] **Step 7: Final full test suite**

```bash
cd stocks && python -m pytest tests/ -v
```
Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
cd stocks && git add Dockerfile docker-compose.yml .dockerignore
git commit -m "feat: Docker containerization with volume-mounted SQLite and logs"
```

---

## Self-Review

### Spec Coverage Check

| Spec Requirement | Covered By |
|---|---|
| BVC prices (all 76 stocks) | Task 2: `collectors/bvc.py` |
| MASI / MADEX index levels | Task 2: `_parse_html` |
| Morocco macro (HCP, BAM) | Task 4: `collectors/macro.py` + news RSS |
| Commodities: oil, gold, gas, silver, copper, wheat, corn | Task 3: `collectors/commodities.py` |
| Phosphate price | Task 3: MOS proxy in `COMMODITY_TICKERS` |
| Forex: USD/MAD, EUR/MAD, DXY, EUR/USD | Task 4: `collectors/macro.py` |
| Global markets: S&P500, CAC40, MSCI EM/FM, VIX, US10Y | Task 4: `GLOBAL_INDEX_TICKERS` |
| Geopolitical + Morocco sector news (RSS) | Task 5: `collectors/news.py` |
| Climate/agriculture (Météo Maroc, HCP) | Task 5: add `https://www.meteomaroc.com/rss.xml` to `RSS_FEEDS` in config.py ⚠️ |
| Technical analysis: RSI, MACD, MAs, Bollinger, support/resistance, Fibonacci | Task 6: `collectors/technical.py` |
| Morning briefing at 8 AM | Task 11: APScheduler cron |
| Market Pulse + What's Happening + AI Picks + This Week | Task 7: prompts, Task 8: analyst |
| BUY/WATCH/AVOID labels with educational explanations | Task 7: prompt schema |
| Real-time alerts every 30 min 10:00–15:30 | Task 11: APScheduler |
| Price move alert >3% | Task 11: `run_alert_check` |
| Watchlist price target alert | Task 11: `watchlist_map` logic |
| Breaking news / commodity shock alert | ⚠️ Not yet — alert check only fires on price move; see gap below |
| Watchlist JSON management | Task 1: `watchlist.json` |
| SQLite: prices, briefings, alerts tables | Task 1: `storage/db.py` |
| Persist daily prices for historical analysis | Task 11: `collect_and_persist` |
| Claude API retry (2 attempts) + fallback | Task 8: `agent/analyst.py` |
| Email retry on failure | ⚠️ Partial — logs error, does not retry at next cycle; see gap below |
| yfinance exponential backoff (3 attempts) | Task 3 + Task 4: `_fetch_ticker` / `_fetch_yf` |
| BVC scraper down → use cached prices | ⚠️ Not implemented — see gap below |
| Dry-run mode | Task 11: `main.py --dry-run` |
| Docker with `docker compose up -d` | Task 12 |
| Unit tests with fixtures / mocked AI | Tasks 1–10: `tests/` |

### Gaps Found — Add These Steps

**Gap 1: Météo Maroc RSS** — Add to `config.py` `RSS_FEEDS`:
```python
{"name": "Météo Maroc", "url": "https://www.meteomaroc.com/rss.xml"},
{"name": "HCP", "url": "https://www.hcp.ma/rss.aspx"},
```
(Do this in Task 1 Step 5; verified live URLs may differ — check before deploying.)

**Gap 2: News / commodity shock alerts** — `run_alert_check` currently only checks price moves. Add after the price-move loop in `scheduler/jobs.py`:

```python
# Commodity shock check — alert if oil or gold moves >3% (same threshold)
commodities = collect_commodities()
for commodity_name in ("brent_crude", "gold", "phosphate_proxy"):
    item = commodities["data"].get(commodity_name, {})
    if abs(item.get("change_pct") or 0) >= PRICE_MOVE_THRESHOLD_PCT:
        context = {"commodity": commodity_name, "data": item,
                   "recent_news": news["data"].get("articles", [])[:5]}
        analysis = run_alert_analysis("commodity_shock", context)
        html = format_alert(analysis)
        if not dry_run:
            send_alert(html, None, f"commodity_shock_{commodity_name}")
            log_alert(None, f"commodity_shock_{commodity_name}", html)
```

**Gap 3: Email retry at next cycle** — Wrap `send_morning_briefing` in `run_morning_briefing` with retry logic:

```python
for attempt in range(2):
    try:
        send_morning_briefing(html)
        break
    except Exception as exc:
        logger.error(f"Email delivery attempt {attempt+1} failed: {exc}")
        if attempt == 1:
            logger.error("Email delivery failed after 2 attempts — will retry at next scheduler cycle")
```

**Gap 4: BVC scraper down → use cached prices** — In `collect_and_persist`, after `bvc = collect_bvc()`:

```python
if not bvc["success"]:
    logger.warning("BVC scraper failed — loading yesterday's prices from DB")
    from storage.db import get_connection
    with get_connection() as conn:
        tickers_with_recent = conn.execute(
            "SELECT DISTINCT ticker FROM prices ORDER BY date DESC LIMIT 76"
        ).fetchall()
    # Reconstruct minimal bvc data from DB for technical analysis
    tickers = [r["ticker"] for r in tickers_with_recent]
    bvc["data"]["stocks"] = [{"ticker": t} for t in tickers]
    bvc["data"]["_cached"] = True
```

Add `"_cached": True` check to the prompt context so the AI mentions the data gap in the briefing.

### Placeholder Scan

No TBD or TODO placeholders found in plan code blocks.

### Type Consistency Check

- `collect() → dict` with `success/data/errors` keys: consistent across all 5 collectors ✓
- `run_morning_analysis(context: dict) → dict`: consumed by `format_morning_briefing(analysis, date)` ✓
- `format_morning_briefing(analysis: dict, date: str) → str`: matches template `{{ date }}` and `{% for key, item in market_pulse.items() %}` ✓
- `format_alert(analysis: dict) → str`: uses `ticker, headline, what_happened, what_it_means, educational_lesson` — matches `build_alert_prompt` JSON schema ✓
- `collect_and_persist() → dict` with keys `date, bvc, commodities, macro, news, technical, watchlist`: passed as `context` to `run_morning_analysis` ✓
- `collectors.technical.collect(tickers: list[str]) → dict`: called as `collect_technical(tickers)` in `jobs.py` ✓
