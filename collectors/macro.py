import logging
import time
import requests
import yfinance as yf

from config import GLOBAL_INDEX_TICKERS, FOREX_TICKERS, EXCHANGE_RATE_API_KEY

logger = logging.getLogger(__name__)

EXCHANGE_RATE_URL = "https://open.exchangerate-api.com/v6/latest/USD"


def _fetch_mad_rates() -> dict:
    url = (
        f"https://v6.exchangerate-api.com/v6/{EXCHANGE_RATE_API_KEY}/latest/USD"
        if EXCHANGE_RATE_API_KEY
        else EXCHANGE_RATE_URL
    )
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json().get("conversion_rates", resp.json().get("rates", {}))


def _fetch_yf(symbol: str) -> dict:
    for attempt in range(3):
        try:
            hist = yf.Ticker(symbol).history(period="2d")
            if hist.empty:
                return {"price": None, "change_pct": None}
            latest = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else latest
            return {
                "price": round(latest, 4),
                "change_pct": round((latest - prev) / prev * 100, 2) if prev else 0.0,
            }
        except Exception as exc:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    return {}


def collect() -> dict:
    errors = []
    indices = {}
    forex = {}

    for name, symbol in GLOBAL_INDEX_TICKERS.items():
        try:
            indices[name] = _fetch_yf(symbol)
        except Exception as exc:
            logger.error(f"Macro index {name}: {exc}")
            errors.append(f"{name}: {exc}")
            indices[name] = {"price": None, "change_pct": None}

    for name, symbol in FOREX_TICKERS.items():
        try:
            forex[name] = _fetch_yf(symbol)
        except Exception as exc:
            logger.error(f"Macro forex {name}: {exc}")
            errors.append(f"{name}: {exc}")
            forex[name] = {"price": None, "change_pct": None}

    try:
        rates = _fetch_mad_rates()
        usd_mad = rates.get("MAD")
        eur_rate = rates.get("EUR")
        eur_mad = round(usd_mad / eur_rate, 4) if usd_mad and eur_rate else None
        try:
            usd_mad_yf = _fetch_yf("USDMAD=X")
            if usd_mad_yf.get("price"):
                forex["usd_mad"] = {
                    "price": usd_mad or usd_mad_yf["price"],
                    "change_pct": usd_mad_yf.get("change_pct"),
                }
            else:
                forex["usd_mad"] = {"price": usd_mad, "change_pct": None}
            eur_mad_yf = _fetch_yf("EURMAD=X")
            if eur_mad_yf.get("price"):
                forex["eur_mad"] = {
                    "price": eur_mad or eur_mad_yf["price"],
                    "change_pct": eur_mad_yf.get("change_pct"),
                }
            else:
                forex["eur_mad"] = {"price": eur_mad, "change_pct": None}
        except Exception as yf_exc:
            logger.warning(f"yfinance MAD change_pct unavailable: {yf_exc}")
            forex["usd_mad"] = {"price": usd_mad, "change_pct": None}
            forex["eur_mad"] = {"price": eur_mad, "change_pct": None}
    except Exception as exc:
        logger.error(f"Macro MAD rates: {exc}")
        errors.append(f"MAD rates: {exc}")
        forex["usd_mad"] = {"price": None, "change_pct": None}
        forex["eur_mad"] = {"price": None, "change_pct": None}

    return {
        "success": bool(indices),
        "data": {"indices": indices, "forex": forex},
        "errors": errors,
    }
