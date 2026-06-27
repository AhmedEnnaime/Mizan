import logging
import urllib.parse
import feedparser

from config import MARKET_KEYWORDS

logger = logging.getLogger(__name__)

_GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
_MAX_ARTICLES = 12
_MAX_PER_QUERY = 4


def _rss_url(query: str) -> str:
    params = urllib.parse.urlencode({"q": query, "hl": "fr", "gl": "MA", "ceid": "MA:fr"})
    return f"{_GOOGLE_NEWS_RSS}?{params}"


def enrich(context: dict) -> dict:
    articles: list[dict] = []
    seen_titles: set[str] = set()

    stocks = context.get("bvc", {}).get("data", {}).get("stocks", [])
    top_movers = sorted(
        [s for s in stocks if s.get("change_pct") is not None],
        key=lambda s: abs(s.get("change_pct", 0)),
        reverse=True,
    )[:4]

    queries: list[tuple[str, str | None]] = [("bourse casablanca MASI", None)]
    for s in top_movers:
        name = s.get("name", "") or s.get("ticker", "")
        queries.append((f"{name} bourse maroc", s.get("ticker")))

    for query, ticker in queries:
        if len(articles) >= _MAX_ARTICLES:
            break
        try:
            feed = feedparser.parse(_rss_url(query))
            count = 0
            for entry in feed.entries:
                if len(articles) >= _MAX_ARTICLES or count >= _MAX_PER_QUERY:
                    break
                title = entry.get("title", "")
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                articles.append({
                    "source": entry.get("source", {}).get("title", "Google News"),
                    "ticker": ticker,
                    "title": title,
                    "url": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "summary": (entry.get("summary", "") or "")[:300],
                })
                count += 1
        except Exception as exc:
            logger.warning(f"google news fetch failed for '{query}': {exc}")

    context["reddit_discussions"] = articles
    return context
