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


# ─── Seed story for offline/local testing ─────────────────────────
SEED_STORY = {
    "id": "seed_story_001",
    "title": "I spent 5 years pretending to be happy. Here's what broke me.",
    "body": (
        "I was 22 when I realized I had been living my life for everyone else. "
        "My parents wanted me to be a doctor, so I studied medicine. "
        "I hated every second of it. The blood, the hours, the pressure. "
        "But I smiled through it all. I smiled at graduation. "
        "I smiled at my first job. I smiled when my father said he was proud of me. "
        "But inside, I was dying. Every morning I would stare at the ceiling "
        "and pray I wouldn't have to get up. "
        "The breaking point came on a Tuesday. I was in the middle of a 36-hour shift. "
        "A patient coded. We lost him. His wife was crying in the hallway. "
        "And I felt nothing. Absolutely nothing. "
        "That's when I knew something was wrong. I went to the bathroom, "
        "locked the door, and sat on the floor for 20 minutes. "
        "I couldn't feel joy, sadness, anger, or fear. I was empty. "
        "I quit medical residency the next week. My parents haven't spoken to me since. "
        "That was three years ago. Today I run a small bookshop in a town "
        "where nobody knows me. I make barely enough to survive. "
        "But for the first time in my life, I feel something. "
        "It's not happiness yet. But it's real. And that's enough for now."
    ),
    "ups": 15200,
    "comments": 843,
    "subreddit": "TrueOffMyChest",
    "url": "https://reddit.com/r/TrueOffMyChest/comments/seed_story",
    "word_count": 220,
    "score": 0.0,
}


def _fetch_via_scrape() -> list[dict]:
    """
    Fallback: load a seed story for testing when no Reddit API credentials are available.
    
    For production, set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env
    to fetch real Reddit stories via PRAW.
    """
    used_ids = _load_used_ids()
    candidates = []

    if SEED_STORY["id"] not in used_ids:
        logger.info("No Reddit API credentials — using seed story for testing")
        logger.info("Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env for live Reddit stories")
        candidates.append(dict(SEED_STORY))
    else:
        logger.warning(
            "Seed story already used and no Reddit API credentials configured. "
            "Add REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET to .env "
            "or delete data/topics_used.json to reset."
        )

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
