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

REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "Mizan/1.0")
REDDIT_KEYWORDS = [
    "OCP", "ATW", "BCP", "BOA", "IAM", "MNG", "TQM", "ADH", "LBV", "CIH",
    "bourse", "MASI", "maroc", "marché", "investissement", "action", "dividende",
    "phosphate", "dirham", "Casablanca", "Morocco stock", "invest maroc",
]

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

BVC_API_URL = "https://api.casablanca-bourse.com/fr/api/bourse_data/market_watch"
BVC_OVERVIEW_URL = "https://www.casablanca-bourse.com/fr/live-market/overview"

RSS_FEEDS = [
    {"name": "Google News Maroc", "url": "https://news.google.com/rss/search?q=bourse+maroc&hl=fr&gl=MA&ceid=MA:fr"},
    {"name": "Google News OCP", "url": "https://news.google.com/rss/search?q=OCP+Maroc&hl=fr&gl=MA&ceid=MA:fr"},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"name": "Medias24", "url": "https://medias24.com/feed"},
    {"name": "MAP", "url": "https://www.mapnews.ma/en/rss.xml"},
    {"name": "L'Économiste", "url": "https://www.leconomiste.com/rss.xml"},
    {"name": "TelQuel", "url": "https://telquel.ma/feed"},
    {"name": "Hespress Économie", "url": "https://fr.hespress.com/category/economie/feed"},
]

COMMODITY_TICKERS = {
    "brent_crude": "BZ=F",
    "natural_gas": "NG=F",
    "gold": "GC=F",
    "silver": "SI=F",
    "copper": "HG=F",
    "wheat": "ZW=F",
    "corn": "ZC=F",
    "phosphate_proxy": "MOS",
}

GLOBAL_INDEX_TICKERS = {
    "sp500": "^GSPC",
    "cac40": "^FCHI",
    "msci_em": "EEM",
    "vix": "^VIX",
    "us_10y": "^TNX",
}

FOREX_TICKERS = {
    "eurusd": "EURUSD=X",
    "dxy": "DX-Y.NYB",
}
