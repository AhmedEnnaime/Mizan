import json
import logging
import requests
from datetime import datetime, timezone

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from config import BVC_API_URL, BVC_OVERVIEW_URL

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BVC-Monitor/1.0)",
    "Accept": "application/json",
}
HTML_HEADERS = {**HEADERS, "Accept": "text/html,application/xhtml+xml"}


def _get(url: str, params: dict | None = None) -> dict:
    r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _parse_price(val) -> float | None:
    if val is None or val == "-":
        return None
    try:
        return round(float(str(val)), 4)
    except (ValueError, TypeError):
        return None


def _last_traded(attrs: dict) -> float | None:
    for txn in (attrs.get("lastTransactions") or []):
        price = _parse_price(txn.get("executedPrice"))
        if price:
            return price
    return None


def _fetch_masi() -> dict:
    try:
        html = requests.get(BVC_OVERVIEW_URL, headers=HTML_HEADERS, timeout=20).text
        tag_start = html.find('<script id="__NEXT_DATA__"')
        tag_end = html.find("</script>", tag_start)
        build_id = json.loads(html[tag_start:tag_end][html[tag_start:tag_end].find(">") + 1:])["buildId"]

        data_url = f"https://www.casablanca-bourse.com/_next/data/{build_id}/fr/live-market/overview.json"
        page = requests.get(data_url, headers=HTML_HEADERS, timeout=20).json()

        paragraphs = page.get("pageProps", {}).get("node", {}).get("field_vactory_paragraphs", [])
        for p in paragraphs:
            wid = p.get("field_vactory_component", {}).get("widget_id", "")
            if "overview" in wid:
                wd = json.loads(p["field_vactory_component"]["widget_data"])
                records = wd.get("components", [{}])[0].get("collection", {}).get("data", {}).get("data", [])
                if records:
                    sorted_records = sorted(records, key=lambda r: r["attributes"]["transactTime"], reverse=True)
                    latest = _parse_price(sorted_records[0]["attributes"].get("indexValue"))
                    if latest:
                        return {"value": latest, "change_pct": None}
    except Exception as exc:
        logger.warning(f"MASI fetch failed: {exc}")
    return {}


def _parse_response(data: dict) -> dict:
    records = data.get("data", [])
    included = {i["id"]: i for i in data.get("included", [])}
    errors = []
    stocks = []

    for r in records:
        try:
            sym_rel = (r.get("relationships") or {}).get("symbol", {}).get("data") or {}
            sym = included.get(sym_rel.get("id"), {})
            sym_attr = sym.get("attributes", {})

            url = sym_attr.get("instrument_url", "")
            ticker = url.split("/")[-1] if url else None
            if not ticker:
                continue

            attr = r["attributes"]
            close = _parse_price(attr.get("coursCourant")) or _last_traded(attr)

            stocks.append({
                "ticker": ticker,
                "name": sym_attr.get("libelleEN", ticker),
                "open": _parse_price(attr.get("openingPrice")),
                "high": _parse_price(attr.get("highPrice")),
                "low": _parse_price(attr.get("lowPrice")),
                "close": close,
                "change_pct": _parse_price(attr.get("varVeille")),
                "volume": int(float(attr.get("cumulTitresEchanges") or 0)),
            })
        except Exception as exc:
            errors.append(f"Failed to parse record: {exc}")

    return {
        "success": len(stocks) > 0,
        "data": {
            "date": datetime.now(timezone.utc).date().isoformat(),
            "masi": {},
            "madex": {},
            "stocks": stocks,
        },
        "errors": errors,
    }


def collect() -> dict:
    try:
        data = _get(BVC_API_URL, params={"include": "symbol", "page[limit]": "200"})
        result = _parse_response(data)
        result["data"]["masi"] = _fetch_masi()
        return result
    except Exception as exc:
        logger.error(f"BVC collector failed: {exc}", exc_info=True)
        return {
            "success": False,
            "data": {"stocks": [], "masi": {}, "madex": {}},
            "errors": [str(exc)],
        }
