import time
from observability.health import RunHealthCollector


def test_to_log_line_contains_key_fields():
    h = RunHealthCollector(run_id="run-0830", date="2026-06-26")
    h.stocks_collected = 37
    h.stocks_total = 37
    h.news_articles = 43
    h.enrichers_ok = 5
    h.enrichers_total = 5
    h.ai_ok = True
    h.email_sent = True
    line = h.to_log_line()
    assert "stocks:37/37" in line
    assert "news:43" in line
    assert "enrichers:5/5" in line
    assert "ai:✓" in line
    assert "sent:✓" in line


def test_to_html_footer_contains_run_id_and_date():
    h = RunHealthCollector(run_id="run-0830", date="2026-06-26")
    html = h.to_html_footer()
    assert "run-0830" in html
    assert "2026-06-26" in html
    assert "Stocks collected" in html
    assert "Email delivered" in html


def test_add_warning_appears_in_footer():
    h = RunHealthCollector(run_id="run-0830", date="2026-06-26")
    h.enrichers_ok = 4
    h.enrichers_total = 5
    h.add_warning("reddit enricher failed")
    html = h.to_html_footer()
    assert "reddit enricher failed" in html
    assert "⚠" in html


def test_duration_s_increases():
    h = RunHealthCollector(run_id="run-0830", date="2026-06-26")
    d1 = h.duration_s
    time.sleep(0.12)
    d2 = h.duration_s
    assert d2 >= d1
