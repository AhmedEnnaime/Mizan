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
