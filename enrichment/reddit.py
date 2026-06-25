import logging
import praw

from config import REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT, REDDIT_KEYWORDS

logger = logging.getLogger(__name__)

_SUBREDDITS = ["Maroc", "Morocco", "investing"]
_MAX_POSTS = 8
_MAX_TOP_COMMENTS = 3
_MAX_NOTABLE_REPLIES = 3
_MIN_REPLY_SCORE = 3
_MIN_REPLY_LENGTH = 40


def _matches_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in REDDIT_KEYWORDS)


def enrich(context: dict) -> dict:
    discussions = []
    try:
        reddit = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            user_agent=REDDIT_USER_AGENT,
            read_only=True,
        )
        for subreddit_name in _SUBREDDITS:
            if len(discussions) >= _MAX_POSTS:
                break
            try:
                subreddit = reddit.subreddit(subreddit_name)
                for submission in subreddit.new(limit=50):
                    if len(discussions) >= _MAX_POSTS:
                        break
                    text = submission.title + " " + (submission.selftext or "")
                    if not _matches_keywords(text):
                        continue
                    submission.comments.replace_more(limit=0)
                    top_comments = []
                    for comment in list(submission.comments)[:_MAX_TOP_COMMENTS]:
                        notable_replies = []
                        for reply in list(getattr(comment, "replies", []))[:10]:
                            body = getattr(reply, "body", "")
                            score = getattr(reply, "score", 0)
                            if score >= _MIN_REPLY_SCORE and len(body) >= _MIN_REPLY_LENGTH:
                                notable_replies.append({"text": body[:500], "score": score})
                                if len(notable_replies) >= _MAX_NOTABLE_REPLIES:
                                    break
                        top_comments.append({
                            "text": getattr(comment, "body", "")[:500],
                            "score": getattr(comment, "score", 0),
                            "notable_replies": notable_replies,
                        })
                    discussions.append({
                        "subreddit": subreddit_name,
                        "title": submission.title,
                        "score": submission.score,
                        "url": submission.url,
                        "top_comments": top_comments,
                    })
            except Exception as exc:
                logger.warning(f"reddit: failed to fetch r/{subreddit_name}: {exc}")
    except Exception as exc:
        logger.warning(f"reddit enricher failed: {exc}")

    context["reddit_discussions"] = discussions
    return context
