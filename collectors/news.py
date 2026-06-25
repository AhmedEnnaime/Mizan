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
