from agent.formatter import format_morning_briefing

_ANALYSIS = {
    "market_pulse": {
        "masi": {"value": 13245.5, "change_pct": 0.3, "comment": "Stable."},
    },
    "whats_happening": "Quiet day.",
    "ai_picks": [],
    "this_week": [],
}


def test_portfolio_section_appears_when_positions_given():
    positions = [
        {
            "ticker": "OCP",
            "shares": 10,
            "avg_cost_mad": 261.0,
            "current_price": 275.0,
            "pnl_mad": 140.0,
            "pnl_pct": 5.36,
        }
    ]
    html = format_morning_briefing(_ANALYSIS, "2026-07-03", portfolio=positions)
    assert "Paper Portfolio" in html
    assert "OCP" in html
    assert "261.00" in html


def test_portfolio_section_absent_when_empty():
    html = format_morning_briefing(_ANALYSIS, "2026-07-03", portfolio=[])
    assert "Paper Portfolio" not in html


def test_portfolio_section_absent_when_omitted():
    html = format_morning_briefing(_ANALYSIS, "2026-07-03")
    assert "Paper Portfolio" not in html


def test_pnl_na_when_no_current_price():
    positions = [
        {
            "ticker": "ATW",
            "shares": 5,
            "avg_cost_mad": 540.0,
            "current_price": None,
            "pnl_mad": None,
            "pnl_pct": None,
        }
    ]
    html = format_morning_briefing(_ANALYSIS, "2026-07-03", portfolio=positions)
    assert "ATW" in html
    assert "N/A" in html
