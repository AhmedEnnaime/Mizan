import pytest
from unittest.mock import patch
from pathlib import Path
import json


SAMPLE_PROFILES = {
    "OCP": {
        "sector": "Mining / Fertilizers",
        "description": "Phosphate exporter.",
        "key_drivers": ["phosphate price"],
        "risks": ["commodity cycles"],
        "macro_sensitivity": {"dirham_weakness": "positive"}
    }
}


@pytest.fixture
def context_with_stocks():
    return {
        "bvc": {
            "data": {
                "stocks": [
                    {"ticker": "OCP", "close": 261.5},
                    {"ticker": "ATW", "close": 685.0},
                ]
            }
        }
    }


def test_profile_attached_to_matching_stock(context_with_stocks, tmp_path):
    profiles_file = tmp_path / "company_profiles.json"
    profiles_file.write_text(json.dumps(SAMPLE_PROFILES))

    with patch("enrichment.company_profiles._PROFILES_PATH", profiles_file):
        import enrichment.company_profiles as cp
        cp._profiles = None  # reset cache
        result = cp.enrich(context_with_stocks)

    ocp = next(s for s in result["bvc"]["data"]["stocks"] if s["ticker"] == "OCP")
    assert ocp["profile"]["sector"] == "Mining / Fertilizers"
    assert ocp["profile"]["key_drivers"] == ["phosphate price"]


def test_missing_ticker_leaves_stock_unchanged(context_with_stocks, tmp_path):
    profiles_file = tmp_path / "company_profiles.json"
    profiles_file.write_text(json.dumps(SAMPLE_PROFILES))

    with patch("enrichment.company_profiles._PROFILES_PATH", profiles_file):
        import enrichment.company_profiles as cp
        cp._profiles = None
        result = cp.enrich(context_with_stocks)

    atw = next(s for s in result["bvc"]["data"]["stocks"] if s["ticker"] == "ATW")
    assert "profile" not in atw


def test_enrich_returns_context_unchanged_on_missing_file():
    from enrichment import company_profiles as cp
    cp._profiles = None
    with patch("enrichment.company_profiles._PROFILES_PATH", Path("/nonexistent/path.json")):
        context = {"bvc": {"data": {"stocks": [{"ticker": "OCP", "close": 261.5}]}}}
        result = cp.enrich(context)
    assert result == context
