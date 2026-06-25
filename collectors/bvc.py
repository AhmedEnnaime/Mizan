import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

from config import BVC_URL

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BVC-Monitor/1.0)",
    "Accept-Language": "fr-MA,fr;q=0.9",
}


def _parse_french_number(s: str) -> float | None:
    if not s:
        return None
    try:
        return float(
            s.strip()
            .replace("\xa0", "")
            .replace(" ", "")
            .replace(",", ".")
            .replace("%", "")
            .replace("+", "")
        )
    except ValueError:
        return None


def _parse_html(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    errors = []

    # Parse indices
    masi_val = soup.select_one(".masi-value")
    masi_var = soup.select_one(".masi-var")
    madex_val = soup.select_one(".madex-value")
    madex_var = soup.select_one(".madex-var")

    masi = {
        "value": _parse_french_number(masi_val.text) if masi_val else None,
        "change_pct": _parse_french_number(masi_var.text) if masi_var else None,
    }
    madex = {
        "value": _parse_french_number(madex_val.text) if madex_val else None,
        "change_pct": _parse_french_number(madex_var.text) if madex_var else None,
    }

    if masi["value"] is None:
        errors.append("Could not parse MASI index value")

    # Parse stocks table
    table = soup.select_one("#cours-table")
    stocks = []
    if table:
        for row in table.select("tbody tr"):
            cells = row.find_all("td")
            if len(cells) < 8:
                continue
            stocks.append({
                "name": cells[0].text.strip(),
                "ticker": cells[1].text.strip(),
                "open": _parse_french_number(cells[2].text),
                "high": _parse_french_number(cells[3].text),
                "low": _parse_french_number(cells[4].text),
                "close": _parse_french_number(cells[5].text),
                "change_pct": _parse_french_number(cells[6].text),
                "volume": int(_parse_french_number(cells[7].text) or 0),
            })
    else:
        errors.append("Stock table #cours-table not found — page structure may have changed")

    return {
        "success": len(stocks) > 0,
        "data": {
            "date": datetime.now(timezone.utc).date().isoformat(),
            "masi": masi,
            "madex": madex,
            "stocks": stocks,
        },
        "errors": errors,
    }


def collect() -> dict:
    try:
        resp = requests.get(BVC_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return _parse_html(resp.text)
    except Exception as exc:
        logger.error(f"BVC collector failed: {exc}", exc_info=True)
        return {
            "success": False,
            "data": {"stocks": [], "masi": {}, "madex": {}},
            "errors": [str(exc)],
        }
