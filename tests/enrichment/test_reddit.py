from unittest.mock import patch, MagicMock
import enrichment.reddit as reddit_mod


def _make_feed(entries):
    feed = MagicMock()
    feed.entries = entries
    return feed


def _make_entry(title, source="Medias24", link="https://example.com", published="Fri, 27 Jun 2026"):
    entry = MagicMock()
    entry.get = lambda k, default=None: {
        "title": title,
        "source": {"title": source},
        "link": link,
        "published": published,
        "summary": f"Summary of {title}",
    }.get(k, default)
    return entry


def test_returns_articles_from_feed():
    entry = _make_entry("OCP résultats financiers en hausse")
    with patch("enrichment.reddit.feedparser.parse", return_value=_make_feed([entry])):
        result = reddit_mod.enrich({})
    assert "reddit_discussions" in result
    assert len(result["reddit_discussions"]) >= 1
    assert result["reddit_discussions"][0]["title"] == "OCP résultats financiers en hausse"


def test_deduplicates_by_title():
    entry = _make_entry("MASI en hausse aujourd'hui")
    with patch("enrichment.reddit.feedparser.parse", return_value=_make_feed([entry, entry])):
        result = reddit_mod.enrich({})
    titles = [a["title"] for a in result["reddit_discussions"]]
    assert titles.count("MASI en hausse aujourd'hui") == 1


def test_caps_at_max_articles():
    entries = [_make_entry(f"Article {i}", link=f"https://example.com/{i}") for i in range(20)]
    with patch("enrichment.reddit.feedparser.parse", return_value=_make_feed(entries)):
        result = reddit_mod.enrich({})
    assert len(result["reddit_discussions"]) <= 12


def test_single_query_failure_does_not_break_others():
    call_count = 0

    def side_effect(url):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("network error")
        return _make_feed([_make_entry("Attijariwafa résultats")])

    with patch("enrichment.reddit.feedparser.parse", side_effect=side_effect):
        context = {"bvc": {"data": {"stocks": [{"ticker": "ATW", "name": "Attijariwafa", "change_pct": 2.5}]}}}
        result = reddit_mod.enrich(context)

    assert "reddit_discussions" in result


def test_returns_empty_list_on_full_failure():
    with patch("enrichment.reddit.feedparser.parse", side_effect=Exception("DNS failure")):
        result = reddit_mod.enrich({"existing": "data"})

    assert result["reddit_discussions"] == []
    assert result["existing"] == "data"


def test_ticker_tagged_for_mover_queries():
    def side_effect(url):
        if "OCP" in url:
            return _make_feed([_make_entry("OCP annonce dividende", link="https://medias24.com/ocp")])
        return _make_feed([_make_entry("MASI en progression", link="https://medias24.com/masi")])

    with patch("enrichment.reddit.feedparser.parse", side_effect=side_effect):
        context = {"bvc": {"data": {"stocks": [{"ticker": "OCP", "name": "OCP SA", "change_pct": 4.1}]}}}
        result = reddit_mod.enrich(context)

    assert any(a.get("ticker") == "OCP" for a in result["reddit_discussions"])
