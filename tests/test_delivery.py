from tests.test_agent import MORNING_RESPONSE, ALERT_RESPONSE


def test_format_morning_briefing_returns_html():
    from agent.formatter import format_morning_briefing
    html = format_morning_briefing(MORNING_RESPONSE, "Tuesday, June 24, 2026")
    assert "<html" in html
    assert "OCP" in html
    assert "BUY" in html
    assert "13245.5" in html
    assert "What's Happening" in html or "whats_happening" not in html


def test_format_morning_briefing_handles_null_values():
    from agent.formatter import format_morning_briefing
    analysis = dict(MORNING_RESPONSE)
    analysis["market_pulse"] = dict(MORNING_RESPONSE["market_pulse"])
    analysis["market_pulse"]["gold"] = {"value": None, "change_pct": None, "comment": "Unavailable"}
    html = format_morning_briefing(analysis, "2026-06-24")
    assert "N/A" in html


def test_format_alert_returns_html():
    from agent.formatter import format_alert
    html = format_alert(ALERT_RESPONSE)
    assert "<html" in html
    assert "OCP" in html
    assert "Today's Lesson" in html
    assert "OCP surges" in html


from unittest.mock import patch, MagicMock


def test_send_morning_briefing_calls_smtp():
    from delivery.email import send_morning_briefing
    mock_smtp = MagicMock()
    with patch("delivery.email.smtplib.SMTP_SSL", return_value=mock_smtp.__enter__.return_value):
        mock_smtp.__enter__.return_value.login.return_value = None
        mock_smtp.__enter__.return_value.sendmail.return_value = None
        with patch("delivery.email.smtplib.SMTP_SSL") as mock_ssl:
            mock_ssl.return_value.__enter__.return_value = MagicMock()
            send_morning_briefing("<html>test</html>")
            mock_ssl.assert_called_once_with("smtp.gmail.com", 465)


def test_send_alert_includes_ticker_in_subject():
    from delivery.email import send_alert, _create_message
    msg = _create_message("⚡ BVC Alert [OCP]: price_move", "<html>alert</html>")
    assert "OCP" in msg["Subject"]
    assert "price_move" in msg["Subject"]
