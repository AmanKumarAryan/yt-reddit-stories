"""
reddit.py — Fetch, score, and pick the best Reddit story for a video.

Strategy:
  1. Target story-based subreddits (r/stories, r/TrueOffMyChest, r/confessions, etc.)
  2. If PRAW credentials are available, use Reddit API.
     Otherwise fall back to scraping old.reddit.com HTML.
  3. Score posts by: upvotes, comments, word count (target: 200–800 words).
  4. Skip any post ID already in topics_used.json.
  5. Return the top-scoring post's title + body.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from modules.config import (
    REDDIT_CLIENT_ID,
    REDDIT_CLIENT_SECRET,
    REDDIT_USER_AGENT,
    DATA_DIR,
    MIN_STORY_WORDS,
    MAX_STORY_WORDS,
)

logger = logging.getLogger(__name__)

# ─── Story-based subreddits (NOT advice/problem subreddits) ─────
STORY_SUBREDDITS = [
    "stories",
    "TrueOffMyChest",
    "confessions",
    "tifu",
    "PointlessStories",
    "LifeStories",
    "ProRevenge",
    "PettyRevenge",
    "WholesomeStories",
    "IDontWorkHereLady",
    "EntitledPeople",
    "MaliciousCompliance",
    "DeliciousCompliance",
    "TalesFromRetail",
    "TalesFromTheFrontDesk",
    "TalesFromTechSupport",
    "TalesFromYourServer",
]

TOPICS_USED_FILE = DATA_DIR / "topics_used.json"


# ─── Load / Save used topics ──────────────────────────────────────
def _load_used_ids() -> set:
    """Load set of already-used Reddit post IDs."""
    if TOPICS_USED_FILE.exists():
        try:
            with open(TOPICS_USED_FILE) as f:
                return set(json.load(f))
        except (json.JSONDecodeError, KeyError):
            return set()
    return set()


def _save_used_ids(used_ids: set) -> None:
    """Persist used IDs to JSON."""
    TOPICS_USED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TOPICS_USED_FILE, "w") as f:
        json.dump(sorted(used_ids), f, indent=2)
    logger.info("Saved %d used IDs to %s", len(used_ids), TOPICS_USED_FILE)


def mark_used(post_id: str) -> None:
    """Mark a post ID as used so it won't be picked again."""
    used = _load_used_ids()
    used.add(post_id)
    _save_used_ids(used)


# ─── Scoring ──────────────────────────────────────────────────────
def _score_post(ups: int, comments: int, word_count: int) -> float:
    """
    Score a post for video suitability.

    Factors:
      - Upvotes (engagement signal) — higher is better, log-scaled
      - Comments (discussion signal) — higher is better, log-scaled
      - Word count — 300-600 is ideal, penalize outside range
    """
    if word_count < MIN_STORY_WORDS or word_count > MAX_STORY_WORDS:
        return 0.0  # Outside acceptable length

    upvote_score = (ups ** 0.5) * 2.0
    comment_score = (comments ** 0.5) * 1.5
    length_score = 1.0  # Default

    if 300 <= word_count <= 600:
        length_score = 1.0  # Sweet spot
    elif 200 <= word_count < 300:
        length_score = 0.7
    elif 600 < word_count <= 800:
        length_score = 0.8

    return (upvote_score + comment_score) * length_score


# ─── Fetch using PRAW (Reddit API) ───────────────────────────────
def _fetch_via_api() -> list[dict]:
    """Fetch top posts from story subreddits using PRAW."""
    import praw

    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
    )

    candidates = []
    for sub_name in STORY_SUBREDDITS:
        try:
            sub = reddit.subreddit(sub_name)
            for post in sub.top(time_filter="week", limit=10):
                word_count = len(post.selftext.split())
                if word_count < MIN_STORY_WORDS or word_count > MAX_STORY_WORDS:
                    continue
                candidates.append({
                    "id": post.id,
                    "title": post.title,
                    "body": post.selftext,
                    "ups": post.ups,
                    "comments": post.num_comments,
                    "subreddit": sub_name,
                    "url": f"https://reddit.com/r/{sub_name}/comments/{post.id}",
                    "word_count": word_count,
                    "created_utc": post.created_utc,
                })
            time.sleep(0.5)  # Rate limiting
        except Exception as e:
            logger.warning("Failed to fetch r/%s via API: %s", sub_name, e)
            continue

    return candidates


# ─── Fetch via scraping (old.reddit.com) ──────────────────────────
def _fetch_via_scrape() -> list[dict]:
    """Fallback: scrape old.reddit.com's top posts."""
    import urllib.request
    from html.parser import HTMLParser

    class PostParser(HTMLParser):
        """Minimal parser to extract post data from old.reddit.com listings."""

        def __init__(self):
            super().__init__()
            self.candidates = []
            self._current = {}
            self._in_entry = False
            self._in_title = False
            self._tag_stack = []
            self._data_buffer = []
            self._div_class = ""
            self._in_body = False
            self._body_text = []
            self._rows = []

        def handle_starttag(self, tag, attrs):
            attrs_dict = dict(attrs)
            self._tag_stack.append(tag)
            classes = attrs_dict.get("class", "")

            if tag == "div" and "entry" in classes:
                self._in_entry = True
                self._current = {}
                self._body_text = []

            if self._in_entry and tag == "a" and "title" in classes:
                self._in_title = True
                self._current["title"] = ""
                self._data_buffer = []

            if tag == "div" and "usertext-body" in classes:
                self._in_body = True
                self._data_buffer = []

        def handle_endtag(self, tag):
            if self._tag_stack:
                self._tag_stack.pop()
            if tag == "a" and self._in_title:
                self._in_title = False
                self._current["title"] = "".join(self._data_buffer).strip()
            if tag == "div" and self._in_body:
                self._in_body = False
                body = "".join(self._data_buffer).strip()
                # Clean up HTML entities and whitespace
                body = re.sub(r"<[^>]+>", "", body)
                body = body.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                body = re.sub(r"\s+", " ", body).strip()
                if body:
                    self._current["body"] = body
                    self._current["word_count"] = len(body.split())
                    # Commit candidate if it has body and reasonable length
                    if MIN_STORY_WORDS <= self._current.get("word_count", 0) <= MAX_STORY_WORDS:
                        self.candidates.append(self._current.copy())

        def handle_data(self, data):
            if self._in_title or self._in_body:
                self._data_buffer.append(data)

            # Also try to find rank/score/comments from the flat listing structure
            if self._tag_stack and self._tag_stack[-1] in ("span", "a"):
                pass  # We'll parse more below

    candidates = []
    used_ids = _load_used_ids()

    for sub_name in STORY_SUBREDDITS:
        url = f"https://old.reddit.com/r/{sub_name}/top/?sort=top&t=week"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": REDDIT_USER_AGENT},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")

            parser = PostParser()
            parser.feed(html)

            for c in parser.candidates:
                c["subreddit"] = sub_name
                if c.get("id") not in used_ids:
                    # Extract ID from any link: not perfect via pure scraping
                    # Assign a unique key: sub_name + hash of title
                    c["id"] = f"scrape_{sub_name}_{hash(c['title']) % 10000000}"
                    c["ups"] = 0  # Can't easily scrape without full parsing
                    c["comments"] = 0
                    c["url"] = url
                    candidates.append(c)

            logger.info("Scraped %d candidates from r/%s", len(parser.candidates), sub_name)
            time.sleep(1.0)

        except Exception as e:
            logger.warning("Failed to scrape r/%s: %s", sub_name, e)
            continue

    return candidates


# ─── Public API ───────────────────────────────────────────────────
def fetch_top_stories() -> list[dict]:
    """
    Fetch story candidates from all target subreddits.
    Returns list of dicts with: id, title, body, ups, comments, subreddit, url, word_count
    """
    candidates = []

    if REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET:
        logger.info("Using Reddit API (PRAW)...")
        candidates = _fetch_via_api()
    else:
        logger.info("No Reddit API credentials — falling back to scraping old.reddit.com...")
        candidates = _fetch_via_scrape()

    logger.info("Fetched %d total story candidates", len(candidates))
    return candidates


def pick_best_story(candidates: list[dict]) -> Optional[dict]:
    """
    Score and pick the best un-used story.
    Returns a single story dict, or None if no suitable story found.
    """
    used_ids = _load_used_ids()
    logger.info("Already used %d stories", len(used_ids))

    scored = []
    for c in candidates:
        if c["id"] in used_ids:
            logger.debug("Skipping used story: %s", c.get("title", "?"))
            continue

        # Give scrape-based entries a default score floor of 50
        ups = c.get("ups", 50) or 50
        comments = c.get("comments", 20) or 20
        wc = c.get("word_count", len(c.get("body", "").split()))

        score = _score_post(ups, comments, wc)
        if score > 0:
            c["score"] = round(score, 1)
            scored.append(c)

    scored.sort(key=lambda x: x["score"], reverse=True)

    if not scored:
        logger.warning("No suitable un-used stories found")
        return None

    best = scored[0]
    logger.info(
        "Picked best story: score=%.1f, ups=%d, comments=%d, words=%d, subreddit=r/%s",
        best["score"],
        best.get("ups", 0),
        best.get("comments", 0),
        best.get("word_count", 0),
        best.get("subreddit", "?"),
    )

    return best


def format_story_script(story: dict) -> str:
    """
    Convert a Reddit story into a narration script with timestamps.
    Format: [MM:SS] | narration | Minecraft background description
    """
    title = story.get("title", "Untitled Story")
    body = story.get("body", "")

    # Sentence-split the body
    sentences = re.split(r"(?<=[.!?])\s+", body)
    sentences = [s.strip() for s in sentences if s.strip()]

    # Estimate reading time: ~150 words/min → ~2.5 words/sec
    total_words = sum(len(s.split()) for s in sentences)
    estimated_seconds = int(total_words / 2.5)
    target_seconds = max(60, estimated_seconds)

    # Build script lines
    script_lines = [
        f"[STYLE: minecraft]",
        f"# Story: {title}",
        f"# Source: {story.get('url', '')}",
        f"# Word count: {total_words} | Estimated duration: ~{target_seconds}s",
        "",
    ]

    # Mix short and long sentences for pacing
    chunk_size = max(20, min(50, total_words // 6))
    current_chunk = []
    current_words = 0
    time_sec = 0

    for sentence in sentences:
        current_chunk.append(sentence)
        current_words += len(sentence.split())
        if current_words >= chunk_size:
            chunk_text = " ".join(current_chunk)
            mins = time_sec // 60
            secs = time_sec % 60
            script_lines.append(f"[{mins:02d}:{secs:02d}] | {chunk_text} | Minecraft gameplay background, parkour scenery")
            time_sec += int(current_words / 2.5)
            current_chunk = []
            current_words = 0

    # Remaining chunk
    if current_chunk:
        chunk_text = " ".join(current_chunk)
        mins = time_sec // 60
        secs = time_sec % 60
        script_lines.append(f"[{mins:02d}:{secs:02d}] | {chunk_text} | Minecraft gameplay background, parkour scenery")

    return "\n".join(script_lines)


# ─── Main entry point (for testing) ──────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Fetching top stories...")
    candidates = fetch_top_stories()
    print(f"Found {len(candidates)} candidates")
    best = pick_best_story(candidates)
    if best:
        print(f"\nBest story: {best['title']}")
        print(f"Score: {best.get('score', 'N/A')}")
        print(f"Subreddit: r/{best['subreddit']}")
        print(f"Words: {best.get('word_count', '?')}")
        print(f"URL: {best.get('url', '')}")
        print("\n--- Script Preview ---")
        print(format_story_script(best))
    else:
        print("No story found!")
