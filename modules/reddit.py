"""
reddit.py - Fetch, score, and pick the best Reddit story for a video.

Strategy:
  1. Target story-based subreddits (r/stories, r/TrueOffMyChest, r/confessions, etc.)
  2. Use Reddit's PUBLIC JSON API (no API keys needed)
     https://www.reddit.com/r/<subreddit>/top.json?t=week&limit=10
  3. Score posts by: upvotes, comments, word count (target: 1000-3000 words)
     — only pick LONG posts (no AI expansion), skip posts under 1000 words
  4. Skip any post ID already in topics_used.json
  5. Return the top-scoring post's title + body
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional
import urllib.request

from modules.config import (
    MIN_STORY_WORDS,
    MAX_STORY_WORDS,
    DATA_DIR,
)

logger = logging.getLogger(__name__)

# Story-based subreddits (NOT advice/problem subreddits)
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
    "TalesFromRetail",
    "TalesFromTheFrontDesk",
    "TalesFromTechSupport",
    "TalesFromYourServer",
    "IDontWorkHereLady",
    "NoStupidQuestions",
    "offmychest",
    "TwoSentenceHorror",
]

TOPICS_USED_FILE = DATA_DIR / "topics_used.json"

SEED_STORY = {
    "id": "seed_001",
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
        "It's not happiness yet. But it's real. And that's enough for now. "
        "I want to tell you more about that journey because it wasn't just one moment. "
        "It was a slow unraveling that started years before that Tuesday. "
        "Growing up, I was the golden child. My parents were immigrants who sacrificed "
        "everything to give me a better life. My father worked double shifts at a factory. "
        "My mother cleaned houses on weekends. They never complained. They just kept saying, "
        "Study hard, get a good job, make us proud. So I studied. I studied until my eyes "
        "burned and my back ached from hunching over textbooks. I got straight As. "
        "I got into medical school. I got engaged to a girl my parents approved of. "
        "On paper, my life was perfect. But perfection is a cage they build for you, "
        "not a garden you grow for yourself. "
        "During my third year of medical school, I started having panic attacks. "
        "They would hit me in the middle of lectures, in the library, once during "
        "a cadaver dissection. My heart would race, my vision would tunnel, "
        "and I would feel like I was drowning in plain sight. I never told anyone. "
        "I was too ashamed. What would they say? Here is this kid who has everything, "
        "and he is falling apart? So I hid it. I became a master of masks. "
        "I learned to smile so convincingly that even I believed it sometimes. "
        "I would go to parties and laugh, go on dates and charm, go to family dinners "
        "and play the grateful son. But at night, alone in my apartment, "
        "I would sit in the dark and feel nothing but a cold, hollow emptiness. "
        "The engagement fell apart six months before the wedding. She told me "
        "I was distant, that she felt like she was dating a ghost. She was right. "
        "I had been a ghost for years, going through the motions, saying the right things, "
        "but never truly present. When she left, I felt relief before I felt sadness. "
        "That should have told me everything. "
        "The Tuesday that broke me was not exceptional by any standard. "
        "It was just another day of pretending. But something snapped. "
        "Maybe it was the accumulation of a thousand small compromises. "
        "Maybe it was the patient we lost, a young father with two kids. "
        "Maybe it was just exhaustion. Whatever it was, I stopped pretending. "
        "I walked out of the hospital that evening and never went back. "
        "I didn't go home. I drove west for three days without telling anyone. "
        "I slept in my car at rest stops. I ate gas station food. I called no one. "
        "On the third day, I ended up in a small coastal town called Morrow Bay. "
        "I had never heard of it. I just ran out of road. "
        "I found the bookshop by accident. It was a tiny, dusty place with "
        "a hand-painted sign that said The Last Chapter. The owner was an old woman "
        "named Margaret who had been running it for forty years. She hired me "
        "on the spot when I told her I needed a job and knew nothing about books. "
        "She said that was perfect because I would learn as I go. "
        "That was three years ago. Margaret passed away last spring and left me "
        "the shop. I live in the apartment above it now. I wake up to the sound "
        "of seagulls instead of sirens. I spend my days surrounded by stories "
        "instead of sick people. I make enough to pay the bills and save a little. "
        "My parents still do not speak to me. My father calls once a year "
        "on my birthday and we exchange awkward pleasantries for three minutes. "
        "I have three friends here, real friends who know my whole story. "
        "Last month, I adopted a stray cat who showed up at the back door. "
        "I named him Tuesday. "
        "I am not happy. I do not know if I will ever be happy in the way "
        "people mean when they say that word. But I am awake. I am present. "
        "I feel the wind on my face and the rain on my roof and the weight "
        "of a good book in my hands. And for now, that is enough. "
        "That is more than enough. "
        "There is something I have not told anyone yet. Last week, my father called. "
        "Not the annual birthday call. A real call. He said my mother had been asking "
        "about me. He said she had been crying. He said maybe it was time to come home "
        "for a visit. I did not know what to say. I stood in the back room of the bookshop "
        "with the phone pressed to my ear and the sound of the ocean in the distance. "
        "I told him I would think about it. "
        "I have been thinking about it every minute since. Going back means facing "
        "everyone I disappointed. It means walking into rooms where people will whisper. "
        "It means seeing my ex-fiancee, who is now married to a cardiologist. "
        "But it also means seeing my mother. She is seventy-two now. She has diabetes. "
        "She is not getting younger. And every day I stay away is a day I am choosing "
        "my own comfort over her happiness. "
        "I do not know what I will do. But I am learning that the answer is not "
        "always either-or. Maybe I can visit for a week and come back. "
        "Maybe I can have both lives. Maybe I can be both the son they wanted "
        "and the person I am becoming. "
        "The bookshop is quiet tonight. Tuesday is curled up on a stack of used novels. "
        "The rain is falling softly on the roof. I am sitting at Margarets old desk, "
        "writing this, trying to make sense of a life that does not fit neatly "
        "into any story I was ever told. But maybe that is the point. "
        "Maybe a life that does not fit is a life that is finally, truly yours. "
        "I have been thinking a lot about masks lately. About the faces we wear "
        "for different people. The professional mask for colleagues. The dutiful mask "
        "for family. The charming mask for dates. The strong mask for friends. "
        "I wore so many masks that I forgot which one was my real face. "
        "Maybe none of them were. Maybe the real me was the one sitting alone "
        "in the dark at 2 AM, staring at the ceiling, wondering if anyone "
        "would notice if I just disappeared for a while. "
        "I remember a specific moment from high school that I think about often. "
        "I was seventeen, and I had just won a regional science fair. My father "
        "was so proud. He took me out for dinner, just the two of us. "
        "He told me I was going to be somebody. He told me all his sacrifice "
        "was worth it because of moments like this. I smiled and nodded. "
        "But inside, I was thinking about how I had only entered the science fair "
        "because my guidance counselor suggested it. I did not care about science. "
        "I cared about making my father happy. And that worked for a long time. "
        "It worked until the gap between who I was and who I was pretending to be "
        "became so wide that I could no longer bridge it. "
        "The bookshop taught me something important. Margaret never asked me "
        "to be anyone other than who I was. She did not care about my grades "
        "or my career or what my parents thought. She cared about whether "
        "I could recommend a good mystery novel to a customer, whether I would "
        "remember to water the plants, whether I would show up on time. "
        "She accepted me so completely that I started to believe I was acceptable. "
        "That is a powerful thing, to be seen exactly as you are and not turned away. "
        "I do not know if I will ever go back to medicine. I do not know "
        "if I will visit my parents next month or next year or ever. "
        "I do not know if I will ever fall in love or have children or own a house. "
        "But I know that I am done pretending. I would rather be a nobody "
        "who is real than a somebody who is empty. And I think, somewhere deep down, "
        "that is what we all want. Not to be successful. Not to be admired. "
        "Just to be known and accepted anyway."
    ),
    "ups": 15200,
    "comments": 843,
    "subreddit": "TrueOffMyChest",
    "url": "https://reddit.com/r/TrueOffMyChest/comments/seed_001",
    "word_count": 1611,
}


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


# Fetch via public JSON API (no auth needed)

def _fetch_json_posts(subreddit: str) -> list[dict]:
    """Fetch top posts from a subreddit using Reddit's public JSON API."""
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t=week&limit=15"
    
    # Rotate user agents to avoid rate limiting
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]
    
    for ua in user_agents:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": ua,
                    "Accept": "application/json",
                }
            )
            
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            
            posts = []
            for child in data.get("data", {}).get("children", []):
                post_data = child.get("data", {})
                
                title = post_data.get("title", "")
                body = post_data.get("selftext", "")
                word_count = len(body.split()) if body else 0
                
                if word_count < MIN_STORY_WORDS or word_count > MAX_STORY_WORDS:
                    continue
                
                posts.append({
                    "id": post_data.get("id", ""),
                    "title": title,
                    "body": body,
                    "ups": post_data.get("ups", 0),
                    "comments": post_data.get("num_comments", 0),
                    "subreddit": subreddit,
                    "url": f"https://reddit.com{post_data.get('permalink', '')}",
                    "word_count": word_count,
                    "created_utc": post_data.get("created_utc", 0),
                })
            
            logger.info("Fetched %d story candidates from r/%s", len(posts), subreddit)
            return posts
            
        except urllib.error.HTTPError as e:
            if e.code == 429:  # Rate limited
                time.sleep(2)
                continue
            logger.warning("HTTP Error %d for r/%s", e.code, subreddit)
            return []
        except Exception as e:
            logger.warning("Failed to fetch r/%s: %s", subreddit, str(e))
            return []
    
    return []


# Public API

def fetch_top_stories() -> list[dict]:
    """Fetch story candidates from all target subreddits.
    Falls back to a seed story if Reddit API is unavailable (403, etc).
    """
    candidates = []
    consecutive_errors = 0
    
    for sub_name in STORY_SUBREDDITS:
        posts = _fetch_json_posts(sub_name)
        if not posts:
            consecutive_errors += 1
        else:
            consecutive_errors = 0
            candidates.extend(posts)
        
        # If 5 subreddits in a row fail with 403, Reddit API is blocked
        if consecutive_errors >= 5 and not candidates:
            logger.warning("Reddit API returning 403 for 5+ subreddits — skipping remaining")
            break
        
        time.sleep(0.3)
    
    logger.info("Fetched %d total story candidates", len(candidates))
    
    if not candidates:
        used_ids = _load_used_ids()
        if SEED_STORY["id"] not in used_ids:
            logger.info("Reddit API unavailable — using seed story for testing")
            candidates.append(dict(SEED_STORY))
        else:
            logger.warning("Seed story already used — no stories available!")
    
    return candidates


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
