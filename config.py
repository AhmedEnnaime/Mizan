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
