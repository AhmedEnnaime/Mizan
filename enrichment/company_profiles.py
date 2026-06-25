import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_PROFILES_PATH = Path(__file__).parent.parent / "knowledge" / "company_profiles.json"
_profiles: dict | None = None


def _load() -> dict:
    global _profiles
    if _profiles is None:
        _profiles = json.loads(_PROFILES_PATH.read_text())
    return _profiles


def enrich(context: dict) -> dict:
    try:
        profiles = _load()
    except Exception as exc:
        logger.warning(f"company_profiles: failed to load profiles: {exc}")
        return context

    stocks = context.get("bvc", {}).get("data", {}).get("stocks", [])
    for stock in stocks:
        ticker = stock.get("ticker")
        if ticker and ticker in profiles:
            stock["profile"] = profiles[ticker]
    return context
