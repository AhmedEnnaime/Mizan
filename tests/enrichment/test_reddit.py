import pytest
from unittest.mock import MagicMock, patch


def _make_comment(body, score, replies=None):
    comment = MagicMock()
    comment.body = body
    comment.score = score
    comment.replies = replies or []
    return comment


def _make_submission(title, score, comments):
    sub = MagicMock()
    sub.title = title
    sub.score = score
    sub.selftext = ""
    sub.url = "https://reddit.com/r/Maroc/test"
    sub.comments = MagicMock()
    sub.comments.__getitem__ = lambda self, s: comments[s]
    sub.comments.replace_more = MagicMock()
    sub.comments.__iter__ = lambda self: iter(comments)
    return sub


def test_filters_replies_below_score_threshold():
    import enrichment.reddit as reddit_mod

    low_score_reply = _make_comment("short", 1)
    high_score_reply = _make_comment("This is a long enough reply that adds real value here", 5)
    comment = _make_comment("Top comment about bourse maroc OCP", 20, [low_score_reply, high_score_reply])
    submission = _make_submission("OCP bourse maroc annonce", 100, [comment])

    mock_reddit = MagicMock()
    mock_subreddit = MagicMock()
    mock_subreddit.new.return_value = [submission]
    mock_reddit.subreddit.return_value = mock_subreddit

    with patch("enrichment.reddit.praw.Reddit", return_value=mock_reddit):
        result = reddit_mod.enrich({})

    assert "reddit_discussions" in result
    assert result["reddit_discussions"], "Expected at least one matching post"
    post = result["reddit_discussions"][0]
    comment_data = post["top_comments"][0]
    for reply in comment_data["notable_replies"]:
        assert reply["score"] >= 3
        assert len(reply["text"]) >= 40


def test_caps_at_max_posts():
    import enrichment.reddit as reddit_mod

    submissions = []
    for i in range(20):
        sub = _make_submission(f"bourse maroc OCP news {i}", 50, [])
        sub.comments.__getitem__ = lambda self, s: [][s]
        sub.comments.replace_more = MagicMock()
        sub.comments.__iter__ = lambda self: iter([])
        submissions.append(sub)

    mock_reddit = MagicMock()
    mock_subreddit = MagicMock()
    mock_subreddit.new.return_value = submissions
    mock_reddit.subreddit.return_value = mock_subreddit

    with patch("enrichment.reddit.praw.Reddit", return_value=mock_reddit):
        result = reddit_mod.enrich({})

    assert len(result.get("reddit_discussions", [])) == 8


def test_single_subreddit_failure_does_not_break_others():
    import enrichment.reddit as reddit_mod

    def side_effect(name):
        if name == "Maroc":
            raise Exception("Subreddit unavailable")
        mock_sub = MagicMock()
        mock_sub.new.return_value = []
        return mock_sub

    mock_reddit = MagicMock()
    mock_reddit.subreddit.side_effect = side_effect

    with patch("enrichment.reddit.praw.Reddit", return_value=mock_reddit):
        result = reddit_mod.enrich({})

    assert "reddit_discussions" in result


def test_returns_empty_list_on_full_failure():
    import enrichment.reddit as reddit_mod

    with patch("enrichment.reddit.praw.Reddit", side_effect=Exception("No credentials")):
        result = reddit_mod.enrich({"existing": "data"})

    assert result["reddit_discussions"] == []
    assert result["existing"] == "data"
