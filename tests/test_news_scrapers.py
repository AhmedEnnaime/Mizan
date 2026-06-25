from unittest.mock import patch, MagicMock
import requests


AMMC_HTML = """
<html><body>
<div class="views-row">
  <h3><a href="/fr/actualites/1">OCP émet des obligations</a></h3>
  <span class="date">2026-06-24</span>
</div>
<div class="views-row">
  <h3><a href="/fr/actualites/2">Résultats semestriels ATW</a></h3>
  <span class="date">2026-06-23</span>
</div>
</body></html>
"""


def test_scrape_ammc_returns_normalized_articles():
    from collectors.news import _scrape_ammc
    mock_resp = MagicMock()
    mock_resp.text = AMMC_HTML
    mock_resp.raise_for_status = MagicMock()
    with patch("collectors.news.requests.get", return_value=mock_resp):
        articles = _scrape_ammc()
    assert len(articles) >= 1
    assert articles[0]["source"] == "AMMC"
    assert "title" in articles[0]
    assert "link" in articles[0]


def test_scrape_ammc_returns_empty_list_on_failure():
    from collectors.news import _scrape_ammc
    with patch("collectors.news.requests.get", side_effect=Exception("timeout")):
        articles = _scrape_ammc()
    assert articles == []


def test_scrape_bam_returns_empty_list_on_failure():
    from collectors.news import _scrape_bam
    with patch("collectors.news.requests.get", side_effect=Exception("timeout")):
        articles = _scrape_bam()
    assert articles == []


def test_collect_still_returns_articles_when_scrapers_fail():
    from collectors.news import collect
    mock_feed = MagicMock()
    mock_feed.bozo = False
    mock_feed.entries = [MagicMock(title="Test", summary="Test summary", published="", link="http://example.com")]
    with patch("collectors.news.feedparser.parse", return_value=mock_feed), \
         patch("collectors.news.requests.get", side_effect=Exception("network error")):
        result = collect()
    assert result["success"] is True
    assert any(a["source"] != "AMMC" and a["source"] != "Bank Al-Maghrib" for a in result["data"]["articles"])
