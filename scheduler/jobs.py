import json
import logging
import traceback
from datetime import datetime, timedelta, timezone
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


def _write_debug_snapshot(
    run_id: str,
    date: str,
    failed_at: str,
    exc: Exception,
    context: dict,
    health: "RunHealthCollector",
) -> None:
    debug_dir = LOG_PATH.parent / "debug"
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = debug_dir / f"{date}-{run_id}.json"

        _PRUNE = {"sector_map", "past_performance", "reddit_discussions"}
        pruned = {k: v for k, v in context.items() if k not in _PRUNE}
        if "bvc" in pruned:
            stocks = pruned["bvc"].get("data", {}).get("stocks", [])
            clean_stocks = [{k: v for k, v in s.items() if k != "profile"} for s in stocks]
            pruned = {
                **pruned,
                "bvc": {
                    **pruned["bvc"],
                    "data": {**pruned["bvc"].get("data", {}), "stocks": clean_stocks},
                },
            }

        snapshot = {
            "run_id": run_id,
            "date": date,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "failed_at": failed_at,
            "exception": str(exc),
            "traceback": traceback.format_exc(),
            "health": {
                "stocks_collected": health.stocks_collected,
                "bvc_cached": health.bvc_cached,
                "news_articles": health.news_articles,
                "enrichers_ok": health.enrichers_ok,
                "enrichers_total": health.enrichers_total,
                "ai_ok": health.ai_ok,
                "email_sent": health.email_sent,
                "warnings": health.warnings,
            },
            "context_snapshot": pruned,
        }

        with open(snapshot_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, default=str)
        logger.info(f"Debug snapshot written: {snapshot_path}")
    except Exception as snap_exc:
        logger.warning(f"Failed to write debug snapshot: {snap_exc}")


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
        masi = bvc["data"].get("masi", {})
        if masi.get("value"):
            try:
                from storage.db import insert_masi_daily
                insert_masi_daily(today, masi["value"], masi.get("change_pct"))
            except Exception as exc:
                logger.warning(f"Failed to write MASI daily: {exc}")
        tickers = [s["ticker"] for s in bvc["data"].get("stocks", []) if s.get("ticker")]
    else:
        logger.warning("BVC collect failed — loading yesterday's tickers from DB as fallback")
        yesterday = (datetime.now(MOROCCO_TZ).date() - timedelta(days=1)).isoformat()
        cached_stocks = []
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
    from storage.db import save_briefing, get_masi_history
    from enrichment import enrich
    from enrichment.outcome_tracker import record_picks
    from observability.run_context import new_run_id, set_run_id
    from observability.health import RunHealthCollector

    rid = new_run_id()
    set_run_id(rid)
    date_str = datetime.now(MOROCCO_TZ).date().isoformat()
    health = RunHealthCollector(run_id=rid, date=date_str)
    logger.info("Running morning briefing")

    context = collect_and_persist()
    stocks = context["bvc"]["data"].get("stocks", [])
    health.stocks_collected = len(stocks)
    health.stocks_total = len(stocks)
    health.bvc_cached = any(s.get("_cached") for s in stocks)
    health.news_articles = len(context["news"]["data"].get("articles", []))

    try:
        context, enrich_stats = enrich(context)
        health.enrichers_ok = enrich_stats["ok"]
        health.enrichers_total = enrich_stats["total"]
        health.reddit_ok = bool(context.get("reddit_discussions"))
        health.masi_rows = len(get_masi_history(days=252))
        for name in enrich_stats.get("failed", []):
            health.add_warning(f"{name} enricher failed")
    except Exception as exc:
        logger.warning(f"Enrichment pipeline failed: {exc}")
        health.add_warning(f"enrichment pipeline: {exc}")

    try:
        from storage.db import get_paper_trades
        from paper_trading.portfolio import compute_positions
        trades = get_paper_trades()
        if trades:
            stocks = context["bvc"]["data"].get("stocks", [])
            current_prices = {s["ticker"]: s["close"] for s in stocks if s.get("close")}
            context["paper_portfolio"] = compute_positions(trades, current_prices)
    except Exception as exc:
        logger.warning(f"Paper portfolio enrichment failed: {exc}")

    analysis = run_morning_analysis(context)
    health.ai_ok = "error" not in analysis

    if "error" in analysis:
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
        _write_debug_snapshot(
            rid, date_str, "ai_analysis", Exception(analysis["error"]), context, health
        )
        if dry_run:
            print("\n" + "=" * 60)
            print("FALLBACK BRIEFING (AI unavailable — DRY RUN)")
            print("=" * 60)
            print(html[:500])
        else:
            try:
                send_morning_briefing(html)
            except Exception as exc:
                logger.error(
                    f"Fallback briefing email delivery failed: {exc}", exc_info=True
                )
        logger.info(health.to_log_line())
        return

    html = format_morning_briefing(analysis, date_str, portfolio=context.get("paper_portfolio", []))
    save_briefing(date_str, html, context)

    try:
        record_picks(analysis, context)
    except Exception as exc:
        logger.warning(f"Failed to record picks: {exc}")
        health.add_warning(f"record_picks: {exc}")

    if dry_run:
        print("\n" + "=" * 60)
        print("MORNING BRIEFING (DRY RUN — email not sent)")
        print("=" * 60)
        print(html[:2000])
        print("..." if len(html) > 2000 else "")
        print("\n" + health.to_log_line())
    else:
        last_exc = None
        for attempt in range(2):
            try:
                health.email_sent = True
                send_morning_briefing(html, health_html=health.to_html_footer())
                last_exc = None
                break
            except Exception as exc:
                health.email_sent = False
                last_exc = exc
                logger.warning(
                    f"Morning briefing email attempt {attempt + 1} failed: {exc}"
                )
        if last_exc is not None:
            _write_debug_snapshot(
                rid, date_str, "email_delivery", last_exc, context, health
            )
            logger.error(
                f"Morning briefing email delivery failed after 2 attempts: {last_exc}",
                exc_info=True,
            )

    logger.info(health.to_log_line())


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
