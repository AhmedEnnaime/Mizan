import logging
import requests
import feedparser
from bs4 import BeautifulSoup

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


def _scrape_ammc() -> list[dict]:
    try:
        url = "https://www.ammc.ma/fr/actualites/communiques-de-presse"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        articles = []
        for item in soup.select(".views-row")[:5]:
            title_el = item.select_one("h3 a, h2 a, a")
            date_el = item.select_one(".date, time, .field-date, span")
            if not title_el:
                continue
            href = title_el.get("href", "")
            link = ("https://www.ammc.ma" + href) if href.startswith("/") else href
            articles.append({
                "title": title_el.get_text(strip=True),
                "summary": "",
                "published": date_el.get_text(strip=True) if date_el else "",
                "link": link,
                "source": "AMMC",
            })
        return articles
    except Exception as exc:
        logger.warning(f"AMMC scraper failed: {exc}")
        return []


def _scrape_bam() -> list[dict]:
    try:
        url = "https://www.bkam.ma/Politique-monetaire/Decisions-du-conseil/Communiques"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        articles = []
        for item in (soup.select(".views-row") or soup.select("article"))[:5]:
            title_el = item.select_one("h3 a, h2 a, a")
            date_el = item.select_one(".date, time, .field-date, span")
            if not title_el:
                continue
            href = title_el.get("href", "")
            link = ("https://www.bkam.ma" + href) if href.startswith("/") else href
            articles.append({
                "title": title_el.get_text(strip=True),
                "summary": "",
                "published": date_el.get_text(strip=True) if date_el else "",
                "link": link,
                "source": "Bank Al-Maghrib",
            })
        return articles
    except Exception as exc:
        logger.warning(f"Bank Al-Maghrib scraper failed: {exc}")
        return []


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

    try:
        all_articles.extend(_scrape_ammc())
    except Exception as exc:
        logger.error(f"News: AMMC scraper raised unexpectedly: {exc}")

    try:
        all_articles.extend(_scrape_bam())
    except Exception as exc:
        logger.error(f"News: BAM scraper raised unexpectedly: {exc}")

    return {
        "success": len(all_articles) > 0,
        "data": {"articles": all_articles},
        "errors": errors,
    }
