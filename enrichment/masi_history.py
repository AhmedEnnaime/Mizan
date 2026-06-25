import logging

logger = logging.getLogger(__name__)


def enrich(context: dict) -> dict:
    from storage.db import get_masi_history

    current_value = context.get("bvc", {}).get("data", {}).get("masi", {}).get("value")
    if not current_value:
        return context

    rows = get_masi_history(days=252)
    if len(rows) < 5:
        return context

    values = [r["value"] for r in rows if r["value"]]
    if not values:
        return context

    change_30d = None
    if len(values) >= 30:
        change_30d = round((current_value - values[-30]) / values[-30] * 100, 2)

    change_90d = None
    if values:
        oldest = values[0] if len(values) < 90 else values[-90]
        change_90d = round((current_value - oldest) / oldest * 100, 2)

    trend = "flat"
    if change_30d is not None:
        if change_30d > 1.0:
            trend = "rising"
        elif change_30d < -1.0:
            trend = "declining"

    masi = context["bvc"]["data"]["masi"]
    masi.update({
        "change_30d_pct": change_30d,
        "change_90d_pct": change_90d,
        "week52_high": max(values),
        "week52_low": min(values),
        "trend": trend,
    })
    return context
