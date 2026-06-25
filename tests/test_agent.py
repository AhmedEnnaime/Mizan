def test_morning_briefing_prompt_contains_context():
    from agent.prompts import build_morning_briefing_prompt
    context = {"bvc": {"data": {"masi": {"value": 13245}}}, "date": "2026-06-24"}
    prompt = build_morning_briefing_prompt(context)
    assert "13245" in prompt
    assert "BUY" in prompt or "WATCH" in prompt or "label" in prompt.lower()
    assert "JSON" in prompt


def test_alert_prompt_contains_type_and_context():
    from agent.prompts import build_alert_prompt
    context = {"stock": {"ticker": "OCP", "change_pct": 4.2}}
    prompt = build_alert_prompt("price_move", context)
    assert "price_move" in prompt
    assert "OCP" in prompt
    assert "JSON" in prompt


def test_prompts_export_system_strings():
    from agent.prompts import MORNING_BRIEFING_SYSTEM, ALERT_SYSTEM
    assert len(MORNING_BRIEFING_SYSTEM) > 50
    assert len(ALERT_SYSTEM) > 50
    assert "BVC" in MORNING_BRIEFING_SYSTEM
    assert "JSON" in MORNING_BRIEFING_SYSTEM


import json
from unittest.mock import patch, MagicMock


MORNING_RESPONSE = {
    "market_pulse": {
        "masi": {"value": 13245.5, "change_pct": 0.3, "comment": "Slight uptick."},
        "gold": {"value": 2340.0, "change_pct": -0.5, "comment": "Minor pullback."},
        "oil": {"value": 78.5, "change_pct": 1.2, "comment": "Rising."},
        "eur_mad": {"value": 10.85, "change_pct": 0.1, "comment": "Stable."},
        "cac40": {"value": 7850.0, "change_pct": -0.2, "comment": "Slight loss."},
        "phosphate_proxy": {"value": 15.3, "change_pct": 2.1, "comment": "Positive signal for OCP."}
    },
    "whats_happening": "Markets are calm today.",
    "ai_picks": [{"ticker": "OCP", "name": "OCP Group", "label": "BUY",
                  "strategy": "Buy on RSI dip.", "explanation": "RSI is below 40."}],
    "this_week": ["AMMC filing deadline", "Fed rate decision"]
}

ALERT_RESPONSE = {
    "alert_type": "price_move",
    "ticker": "OCP",
    "headline": "OCP surges 4% on new export contract",
    "what_happened": "OCP jumped sharply.",
    "what_it_means": "Portfolio impact positive.",
    "educational_lesson": "Large moves often follow news catalysts."
}


def _make_mock_client(response_json: dict):
    mock_content = MagicMock()
    mock_content.text = json.dumps(response_json)
    mock_message = MagicMock()
    mock_message.content = [mock_content]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message
    return mock_client


def test_run_morning_analysis_returns_parsed_dict():
    from agent.analyst import run_morning_analysis
    with patch("agent.analyst.client", _make_mock_client(MORNING_RESPONSE)):
        result = run_morning_analysis({"date": "2026-06-24"})
    assert result["market_pulse"]["masi"]["value"] == 13245.5
    assert result["ai_picks"][0]["ticker"] == "OCP"


def test_run_morning_analysis_retries_and_returns_fallback():
    from agent.analyst import run_morning_analysis
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("API error")
    with patch("agent.analyst.client", mock_client):
        result = run_morning_analysis({"date": "2026-06-24"})
    assert "error" in result
    assert mock_client.messages.create.call_count == 2


def test_run_alert_analysis_returns_parsed_dict():
    from agent.analyst import run_alert_analysis
    with patch("agent.analyst.client", _make_mock_client(ALERT_RESPONSE)):
        result = run_alert_analysis("price_move", {"stock": {"ticker": "OCP"}})
    assert result["ticker"] == "OCP"
    assert result["alert_type"] == "price_move"
