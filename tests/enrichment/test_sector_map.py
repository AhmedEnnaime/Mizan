import json
import pytest
from unittest.mock import patch
from pathlib import Path

SAMPLE_SECTOR_MAP = {
    "Banking": {
        "stocks": ["ATW", "BCP"],
        "sensitive_to": ["Bank Al-Maghrib rate"],
        "rate_hike_impact": "negative"
    }
}


def test_sector_map_injected_into_context(tmp_path):
    sector_file = tmp_path / "sector_map.json"
    sector_file.write_text(json.dumps(SAMPLE_SECTOR_MAP))

    import enrichment.sector_map as sm
    sm._sector_map = None
    with patch("enrichment.sector_map._SECTOR_MAP_PATH", sector_file):
        result = sm.enrich({})

    assert "sector_map" in result
    assert "Banking" in result["sector_map"]
    assert result["sector_map"]["Banking"]["rate_hike_impact"] == "negative"


def test_sector_map_returns_context_unchanged_on_missing_file():
    import enrichment.sector_map as sm
    sm._sector_map = None
    with patch("enrichment.sector_map._SECTOR_MAP_PATH", Path("/nonexistent.json")):
        context = {"foo": "bar"}
        result = sm.enrich(context)
    assert result == {"foo": "bar"}
