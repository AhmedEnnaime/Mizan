from pathlib import Path
from unittest.mock import patch, MagicMock

FIXTURES = Path(__file__).parent / "fixtures"


# --- BVC ---

def test_bvc_collect_parses_stocks():
    from collectors.bvc import collect, _parse_html
    html = (FIXTURES / "bvc_sample.html").read_text()
    result = _parse_html(html)
    assert result["success"] is True
    stocks = result["data"]["stocks"]
    assert len(stocks) == 2
    ocp = next(s for s in stocks if s["ticker"] == "OCP")
    assert ocp["close"] == 261.5
    assert ocp["change_pct"] == 0.19
    assert ocp["volume"] == 15342


def test_bvc_collect_parses_indices():
    from collectors.bvc import _parse_html
    html = (FIXTURES / "bvc_sample.html").read_text()
    result = _parse_html(html)
    assert result["data"]["masi"]["value"] == 13245.5
    assert result["data"]["masi"]["change_pct"] == 0.3


def test_bvc_collect_returns_failure_on_error():
    from collectors.bvc import collect
    with patch("collectors.bvc.requests.get", side_effect=Exception("timeout")):
        result = collect()
    assert result["success"] is False
    assert len(result["errors"]) > 0
