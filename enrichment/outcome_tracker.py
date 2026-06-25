import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def enrich(context: dict) -> dict:
    from storage.db import get_recent_ai_picks

    picks = get_recent_ai_picks(days=30)
    if len(picks) < 3:
        context["past_performance"] = None
        return context

    stocks_by_ticker = {
        s["ticker"]: s
        for s in context.get("bvc", {}).get("data", {}).get("stocks", [])
    }

    evaluated = []
    for pick in picks:
        ticker = pick["ticker"]
        current = (stocks_by_ticker.get(ticker) or {}).get("close")
        price_at = pick["price_at_pick"]
        change_pct = None
        outcome = "unknown"
        if current and price_at:
            change_pct = round((current - price_at) / price_at * 100, 2)
            if pick["pick"] == "BUY":
                outcome = "correct" if change_pct > 0 else "incorrect"
            elif pick["pick"] == "AVOID":
                outcome = "correct" if change_pct < 0 else "incorrect"
            else:
                outcome = "neutral"
        evaluated.append({
            "ticker": ticker,
            "date": pick["date"],
            "pick": pick["pick"],
            "price_at_pick": price_at,
            "current_price": current,
            "change_pct": change_pct,
            "outcome": outcome,
        })

    buy_correct = sum(1 for p in evaluated if p["pick"] == "BUY" and p["outcome"] == "correct")
    buy_incorrect = sum(1 for p in evaluated if p["pick"] == "BUY" and p["outcome"] == "incorrect")
    avoid_correct = sum(1 for p in evaluated if p["pick"] == "AVOID" and p["outcome"] == "correct")
    avoid_incorrect = sum(1 for p in evaluated if p["pick"] == "AVOID" and p["outcome"] == "incorrect")

    context["past_performance"] = {
        "window_days": 30,
        "picks": evaluated,
        "accuracy_summary": f"BUY: {buy_correct} correct / {buy_incorrect} incorrect. AVOID: {avoid_correct} correct / {avoid_incorrect} incorrect.",
    }
    return context


def record_picks(analysis: dict, context: dict) -> None:
    from storage.db import insert_ai_pick

    today = datetime.now(timezone.utc).date().isoformat()
    stocks_by_ticker = {
        s["ticker"]: s
        for s in context.get("bvc", {}).get("data", {}).get("stocks", [])
    }
    for pick in analysis.get("ai_picks", []):
        ticker = pick.get("ticker")
        if not ticker:
            continue
        current_price = (stocks_by_ticker.get(ticker) or {}).get("close")
        try:
            insert_ai_pick(
                date=today,
                ticker=ticker,
                pick=pick.get("label", "WATCH"),
                price_at_pick=current_price,
                reasoning=pick.get("explanation", ""),
            )
        except Exception as exc:
            logger.warning(f"outcome_tracker: failed to record pick for {ticker}: {exc}")
