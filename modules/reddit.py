"""
reddit.py - Fetch, score, and pick the best Reddit story for a video.

Strategy:
  1. Ask Groq for 10 trending Reddit story post IDs from story subreddits
  2. Verify each via Reddit's public JSON API (individual post lookup)
  3. Filter out already-used IDs (topics_used.json)
  4. Score by: upvotes, comments, word count (target: 1000-3000 words)
  5. Retry up to 3 times with different suggestions if nothing found
  6. Return the top-scoring post's title + body
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional
import urllib.request

from modules.config import (
    GROQ_API_KEY,
    MIN_STORY_WORDS,
    MAX_STORY_WORDS,
    DATA_DIR,
)

logger = logging.getLogger(__name__)

TOPICS_USED_FILE = DATA_DIR / "topics_used.json"

# Story subreddits Groq will search for
STORY_SUBREDDITS = [
    "TrueOffMyChest", "confessions", "tifu", "stories",
    "LifeStories", "ProRevenge", "PettyRevenge",
    "WholesomeStories", "MaliciousCompliance", "offmychest",
]


# Load / Save used topics

def _load_used_ids() -> set:
    """Load set of already-used Reddit post IDs."""
    if TOPICS_USED_FILE.exists():
        try:
            return set(json.load(open(TOPICS_USED_FILE)))
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


# Scoring

def _score_post(ups: int, comments: int, word_count: int) -> float:
    """Score a post for video suitability."""
    if word_count < MIN_STORY_WORDS or word_count > MAX_STORY_WORDS:
        return 0.0

    upvote_score = (ups ** 0.5) * 2.0
    comment_score = (comments ** 0.5) * 1.5
    length_score = 1.0

    # Prefer longer stories (1000-3000 words = enough for 7-20 min video)
    if 1200 <= word_count <= 2500:
        length_score = 1.5  # Sweet spot: ~8-16 min video
    elif 1000 <= word_count < 1200:
        length_score = 1.2  # Good: ~7 min video
    elif 2500 < word_count <= 4000:
        length_score = 1.1  # Long but usable
    elif 800 <= word_count < 1000:
        length_score = 0.8  # Short but acceptable
    else:
        length_score = 0.5  # Too short or too long

    return (upvote_score + comment_score) * length_score


# ─── Groq story discovery ─────────────────────────────────────

def _groq_suggest_post_ids(exclude_ids: set[str] | None = None) -> list[str]:
    """Ask Groq for trending Reddit story post IDs, excluding already-tried ones."""
    if not GROQ_API_KEY:
        logger.warning("GROQ_API_KEY not set — cannot discover stories")
        return []

    exclude_clause = ""
    if exclude_ids:
        exclude_list = ", ".join(f'"{pid}"' for pid in list(exclude_ids)[:20])
        exclude_clause = f'\nEXCLUDE these IDs (already tried): [{exclude_list}]'

    prompt = (
        f"Find 10 engaging, high-quality text-based Reddit stories that are currently "
        f"trending or viral from subreddits like: {', '.join(STORY_SUBREDDITS)}.\n\n"
        f"For each story, provide ONLY the Reddit post ID "
        f"(the 6-7 character alphanumeric ID from the URL).\n"
        f"Format your response as a valid JSON array of strings, like:\n"
        f'["abc123", "def456", "ghi789"]\n\n'
        f"Requirements:\n"
        f"- Stories must be 1000-5000 words long (text posts, not links/images)\n"
        f"- High engagement (many upvotes and comments)\n"
        f"- Engaging, emotional, or powerful personal narratives\n"
        f"- NOT advice posts, NOT relationship advice, NOT AITA posts\n"
        f"- Must be real Reddit posts that actually exist and are accessible\n"
        f"- Prefer stories with 5000+ upvotes from this week or month\n"
        f"{exclude_clause}\n\n"
        f"Return ONLY the JSON array. No explanation, no markdown formatting."
    )

    try:
        import groq as groq_client
        client = groq_client.Client(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You are a Reddit content curator. You find high-quality, "
                               "engaging Reddit stories. You always respond with valid JSON only."
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=300,
        )
        text = response.choices[0].message.content.strip()

        # Try to extract JSON array from the response
        if "[" in text and "]" in text:
            json_str = text[text.index("["):text.rindex("]") + 1]
            ids = json.loads(json_str)
            if isinstance(ids, list):
                clean_ids = [pid.strip() for pid in ids if isinstance(pid, str) and len(pid.strip()) >= 4]
                logger.info("Groq suggested %d post IDs", len(clean_ids))
                return clean_ids

        logger.warning("Could not parse Groq response as ID list: %s", text[:200])
        return []
    except Exception as e:
        logger.error("Groq story suggestion failed: %s", e)
        return []


# ─── Individual Reddit post verification ─────────────────────

def _verify_reddit_post(post_id: str) -> Optional[dict]:
    """Verify a Reddit post exists via public JSON API and return its data."""
    url = f"https://www.reddit.com/comments/{post_id}.json"

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))

        # Response is a list: [post_data, comments_data]
        if not isinstance(data, list) or len(data) < 1:
            return None

        post_listing = data[0].get("data", {}).get("children", [])
        if not post_listing:
            return None

        post_data = post_listing[0].get("data", {})

        title = post_data.get("title", "")
        body = post_data.get("selftext", "")
        full_body = f"{title}\n\n{body}" if body else title
        word_count = len(body.split()) if body else 0

        if word_count < MIN_STORY_WORDS or word_count > MAX_STORY_WORDS:
            logger.debug("Post %s: %d words (outside range)", post_id, word_count)
            return None

        subreddit = post_data.get("subreddit", "")
        post_id_actual = post_data.get("id", post_id)

        story = {
            "id": post_id_actual,
            "title": title,
            "body": body,
            "ups": post_data.get("ups", 0),
            "comments": post_data.get("num_comments", 0),
            "subreddit": subreddit,
            "url": f"https://reddit.com/r/{subreddit}/comments/{post_id_actual}",
            "word_count": word_count,
            "created_utc": post_data.get("created_utc", 0),
        }

        logger.info("Verified post %s: %d ups, %d words, r/%s",
                     post_id, story["ups"], word_count, subreddit)
        return story

    except urllib.error.HTTPError as e:
        if e.code == 404:
            logger.debug("Post %s not found (404)", post_id)
        else:
            logger.debug("Post %s: HTTP %d", post_id, e.code)
        return None
    except Exception as e:
        logger.debug("Failed to verify post %s: %s", post_id, e)
        return None


# ─── Public API ─────────────────────────────────────────────

def fetch_top_stories() -> list[dict]:
    """
    Discover Reddit stories via Groq, verify via Reddit API, filter used ones.
    Retries up to 3 times with different suggestions. No seed fallback.
    """
    used_ids = _load_used_ids()
    all_attempted_ids = set(used_ids)
    candidates = []

    for attempt in range(1, 4):
        logger.info("Story discovery attempt %d/3", attempt)

        suggested_ids = _groq_suggest_post_ids(exclude_ids=all_attempted_ids)
        if not suggested_ids:
            logger.warning("Groq returned no suggestions on attempt %d", attempt)
            time.sleep(1)
            continue

        for pid in suggested_ids:
            if pid in all_attempted_ids:
                continue
            all_attempted_ids.add(pid)

            story = _verify_reddit_post(pid)
            if story is not None:
                candidates.append(story)

        if candidates:
            logger.info("Found %d valid stories across %d attempts", len(candidates), attempt)
            return candidates

        logger.warning("No valid stories found on attempt %d — retrying with different IDs", attempt)
        time.sleep(2)

    logger.error("No stories found after 3 attempts — aborting")
    return []


def pick_best_story(candidates: list[dict]) -> Optional[dict]:
    """Score and pick the best un-used story."""
    used_ids = _load_used_ids()
    logger.info("Already used %d stories", len(used_ids))

    scored = []
    for c in candidates:
        if c["id"] in used_ids:
            continue

        ups = c.get("ups", 50) or 50
        comments = c.get("comments", 20) or 20
        wc = c.get("word_count", 0)

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
        best["score"], best.get("ups", 0), best.get("comments", 0),
        best.get("word_count", 0), best.get("subreddit", "?"),
    )

    return best


def format_story_script(story: dict) -> str:
    """Convert a Reddit story into a narration script with timestamps."""
    title = story.get("title", "Untitled Story")
    body = story.get("body", "")

    import re
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()]
    
    total_words = sum(len(s.split()) for s in sentences)
    estimated_seconds = int(total_words / 2.5)
    
    script_lines = [
        f"[STYLE: minecraft]",
        f"# Story: {title}",
        f"# Source: {story.get('url', '')}",
        f"# Word count: {total_words} | Estimated duration: ~{estimated_seconds}s",
        "",
    ]

    # Group sentences into reasonable chunks (25-50 words each)
    word_target = max(20, min(50, total_words // 6))
    current_chunk = []
    current_words = 0
    time_sec = 0

    for sentence in sentences:
        current_chunk.append(sentence)
        current_words += len(sentence.split())
        if current_words >= word_target:
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


# Main entry point (for testing)
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Fetching top stories from Reddit (no API key needed)...")
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
