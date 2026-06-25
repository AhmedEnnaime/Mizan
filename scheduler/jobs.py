import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytz

BREAKING_NEWS_KEYWORDS = [
    "rate decision", "interest rate", "bank al-maghrib", "bam decision",
    "earnings", "résultats", "dividende", "dividend",
    "opa", "takeover", "acquisition", "fusion", "merger",
    "profit warning", "avertissement", "ammc", "regulatory filing",
    "sovereign rating", "credit rating", "fitch", "moody", "s&p",
]

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
    from storage.db import upsert_price, init_db, get_price_history

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
    else:
        # BVC failed: load yesterday's tickers from DB and reconstruct a minimal stock list
        logger.warning("BVC collect failed — loading yesterday's tickers from DB as fallback")
        yesterday = (datetime.now(MOROCCO_TZ).date() - timedelta(days=1)).isoformat()
        cached_stocks = []
        # Retrieve known tickers from watchlist as a starting set, then pull their last price
        watchlist = _load_watchlist()
        known_tickers = [w["ticker"] for w in watchlist if w.get("ticker")]
        for ticker in known_tickers:
            history = get_price_history(ticker, days=5)
            if history:
                latest = history[-1]
                cached_stocks.append({
                    "ticker": ticker,
                    "name": ticker,
                    "open": latest.get("open"),
                    "high": latest.get("high"),
                    "low": latest.get("low"),
                    "close": latest.get("close"),
                    "volume": latest.get("volume"),
                    "change_pct": None,
                    "_cached": True,
                })
        bvc = {
            "success": len(cached_stocks) > 0,
            "data": {
                "date": yesterday,
                "stocks": cached_stocks,
                "masi": {},
                "madex": {},
            },
            "errors": bvc.get("errors", []) + ["BVC collect failed; using cached prices"],
        }
        tickers = [s["ticker"] for s in cached_stocks]

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
    date_str = context["date"]
    analysis = run_morning_analysis(context)

    if "error" in analysis:
        # AI unavailable — send simplified briefing with raw data only (spec requirement)
        logger.warning("AI analysis unavailable; sending fallback briefing with raw data")
        raw_bvc = context.get("bvc", {}).get("data", {})
        raw_json = json.dumps(raw_bvc, indent=2, default=str)[:3000]
        html = (
            f"<html><body>"
            f"<h2>BVC Briefing — {date_str} (AI Unavailable)</h2>"
            f"<p>AI analysis could not be generated today. Raw market data below.</p>"
            f"<pre>{raw_json}</pre>"
            f"</body></html>"
        )
        save_briefing(date_str, html, context)
        if dry_run:
            print("\n" + "=" * 60)
            print("FALLBACK BRIEFING (AI unavailable — DRY RUN)")
            print("=" * 60)
            print(html[:500])
        else:
            try:
                send_morning_briefing(html)
            except Exception as exc:
                logger.error(f"Fallback briefing email delivery failed: {exc}", exc_info=True)
        return

    html = format_morning_briefing(analysis, date_str)
    save_briefing(date_str, html, context)

    if dry_run:
        print("\n" + "=" * 60)
        print("MORNING BRIEFING (DRY RUN — email not sent)")
        print("=" * 60)
        print(html[:2000])
        print("..." if len(html) > 2000 else "")
    else:
        # 2-attempt retry for email delivery
        last_exc = None
        for attempt in range(2):
            try:
                send_morning_briefing(html)
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    f"Morning briefing email attempt {attempt + 1} failed: {exc}"
                )
        if last_exc is not None:
            logger.error(
                f"Morning briefing email delivery failed after 2 attempts: {last_exc}",
                exc_info=True,
            )


def run_alert_check(dry_run: bool = False) -> None:
    from collectors.bvc import collect as collect_bvc
    from collectors.commodities import collect as collect_commodities
    from collectors.news import collect as collect_news
    from agent.analyst import run_alert_analysis
    from agent.formatter import format_alert
    from delivery.email import send_alert
    from storage.db import log_alert

    now = datetime.now(MOROCCO_TZ)
    market_open = now.replace(hour=MARKET_OPEN_HOUR, minute=0, second=0, microsecond=0)
    market_close = now.replace(
        hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0
    )

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

    # --- Price-move alerts for BVC stocks ---
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

    # --- Commodity shock alerts ---
    COMMODITY_SHOCK_NAMES = ("brent_crude", "gold", "phosphate_proxy")
    commodities = collect_commodities()
    for name in COMMODITY_SHOCK_NAMES:
        entry = commodities["data"].get(name, {})
        change_pct = entry.get("change_pct") or 0.0
        if abs(change_pct) >= PRICE_MOVE_THRESHOLD_PCT:
            context = {
                "commodity": name,
                "price": entry.get("price"),
                "change_pct": change_pct,
                "recent_news": news["data"].get("articles", [])[:5],
                "threshold_pct": PRICE_MOVE_THRESHOLD_PCT,
            }
            analysis = run_alert_analysis("price_move", context)
            html = format_alert(analysis)

            if dry_run:
                print(f"\n[COMMODITY ALERT DRY RUN] {name}: {change_pct:+.1f}%")
                print(html[:500])
            else:
                try:
                    send_alert(html, name, "commodity_shock")
                    log_alert(name, f"commodity_shock_{abs(change_pct):.1f}pct", html)
                except Exception as exc:
                    logger.error(f"Commodity shock alert failed for {name}: {exc}")

    # --- Breaking news alerts ---
    articles = news["data"].get("articles", [])
    for article in articles[:20]:
        title = article.get("title", "").lower()
        summary = article.get("summary", "").lower()
        text = title + " " + summary
        if any(kw in text for kw in BREAKING_NEWS_KEYWORDS):
            logger.info(f"Breaking news detected: {article.get('title', '')!r}")
            context = {"article": article, "recent_news": articles[:5]}
            analysis = run_alert_analysis("breaking_news", context)
            html = format_alert(analysis)
            if dry_run:
                print(f"\n[BREAKING NEWS DRY RUN] {article.get('title', '')}")
                print(html[:500])
            else:
                try:
                    send_alert(html, None, "breaking_news")
                    log_alert(None, "breaking_news", html)
                except Exception as exc:
                    logger.error(f"Breaking news alert delivery failed: {exc}")
            break  # Only one breaking news alert per cycle
