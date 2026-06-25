import time
import logging
import yfinance as yf

from config import COMMODITY_TICKERS

logger = logging.getLogger(__name__)


def _fetch_ticker(ticker_symbol: str) -> dict:
    ticker = yf.Ticker(ticker_symbol)
    for attempt in range(3):
        try:
            hist = ticker.history(period="2d")
            if hist.empty:
                return {}
            latest_close = float(hist["Close"].iloc[-1])
            prev_close = float(hist["Close"].iloc[-2]) if len(hist) > 1 else latest_close
            change_pct = round((latest_close - prev_close) / prev_close * 100, 2) if prev_close else 0.0
            return {"price": round(latest_close, 4), "change_pct": change_pct}
        except Exception as exc:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    return {}


def collect() -> dict:
    data = {}
    errors = []

    for name, symbol in COMMODITY_TICKERS.items():
        try:
            data[name] = _fetch_ticker(symbol)
        except Exception as exc:
            logger.error(f"Commodities: failed to fetch {name} ({symbol}): {exc}")
            errors.append(f"{name}: {exc}")
            data[name] = {}

    return {
        "success": len(data) > len(errors),
        "data": data,
        "errors": errors,
    }
