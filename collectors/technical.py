import logging
import pandas as pd
import pandas_ta as ta

from storage.db import get_price_history

logger = logging.getLogger(__name__)

MIN_HISTORY_DAYS = 20


def _compute_volume_trend(df: pd.DataFrame) -> str:
    if len(df) < 10:
        return "unknown"
    recent = df["volume"].tail(5).mean()
    older = df["volume"].tail(20).head(15).mean()
    if older == 0:
        return "unknown"
    ratio = recent / older
    if ratio > 1.2:
        return "increasing"
    if ratio < 0.8:
        return "decreasing"
    return "stable"


def _compute_fibonacci(df: pd.DataFrame, window: int = 60) -> dict:
    recent = df.tail(window)
    high = float(recent["high"].max()) if "high" in recent.columns else float(recent["close"].max())
    low = float(recent["low"].min()) if "low" in recent.columns else float(recent["close"].min())
    diff = high - low
    return {
        "0.0": round(low, 2),
        "0.236": round(low + diff * 0.236, 2),
        "0.382": round(low + diff * 0.382, 2),
        "0.5": round(low + diff * 0.5, 2),
        "0.618": round(low + diff * 0.618, 2),
        "1.0": round(high, 2),
    }


def _analyze_ticker(ticker: str) -> dict:
    history = get_price_history(ticker, days=200)
    if len(history) < MIN_HISTORY_DAYS:
        raise ValueError(f"Only {len(history)} days of history (need {MIN_HISTORY_DAYS}+)")

    df = pd.DataFrame(history)
    close = df["close"].astype(float)

    rsi_series = ta.rsi(close, length=14)
    macd_df = ta.macd(close)
    sma20 = ta.sma(close, length=20)
    sma50 = ta.sma(close, length=50) if len(df) >= 50 else None
    sma200 = ta.sma(close, length=200) if len(df) >= 200 else None
    bb = ta.bbands(close, length=20)

    def safe_float(series, idx=-1):
        if series is None or (hasattr(series, "empty") and series.empty):
            return None
        val = series.iloc[idx]
        return round(float(val), 4) if pd.notna(val) else None

    bbu = bbm = bbl = None
    if bb is not None:
        for col in bb.columns:
            if col.startswith("BBU"):
                bbu = bb[col]
            elif col.startswith("BBM"):
                bbm = bb[col]
            elif col.startswith("BBL"):
                bbl = bb[col]

    macd_val = macd_sig = macd_hist = None
    if macd_df is not None:
        for col in macd_df.columns:
            if col.startswith("MACD_"):
                macd_val = macd_df[col]
            elif col.startswith("MACDs_"):
                macd_sig = macd_df[col]
            elif col.startswith("MACDh_"):
                macd_hist = macd_df[col]

    return {
        "rsi": safe_float(rsi_series),
        "macd": {
            "macd": safe_float(macd_val),
            "signal": safe_float(macd_sig),
            "histogram": safe_float(macd_hist),
        },
        "sma20": safe_float(sma20),
        "sma50": safe_float(sma50),
        "sma200": safe_float(sma200),
        "bollinger": {
            "upper": safe_float(bbu),
            "middle": safe_float(bbm),
            "lower": safe_float(bbl),
        },
        "current_price": round(float(close.iloc[-1]), 2),
        "volume_trend": _compute_volume_trend(df),
        "support": round(float(close.tail(20).min()), 2),
        "resistance": round(float(close.tail(20).max()), 2),
        "fibonacci": _compute_fibonacci(df),
    }


def collect(tickers: list[str]) -> dict:
    data = {}
    errors = []

    for ticker in tickers:
        try:
            data[ticker] = _analyze_ticker(ticker)
        except Exception as exc:
            logger.error(f"Technical: {ticker}: {exc}")
            errors.append(f"{ticker}: {exc}")

    return {
        "success": True,
        "data": data,
        "errors": errors,
    }
