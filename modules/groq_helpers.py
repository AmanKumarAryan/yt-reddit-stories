"""
groq_helpers.py — Generate YouTube Title, Description, and Thumbnail Prompt
using Groq API (Mixtral / LLaMA).

Requires GROQ_API_KEY in .env.
"""

import json
import logging
from typing import Optional

from modules.config import GROQ_API_KEY

logger = logging.getLogger(__name__)


def _call_groq(prompt: str, model: str = "llama-3.3-70b-versatile", max_tokens: int = 500) -> Optional[str]:
    """
    Call the Groq API with a prompt and return the response text.
    Falls back to local rule-based generation if API key is missing.
    """
    if not GROQ_API_KEY:
        logger.warning("No GROQ_API_KEY set — using fallback generation")
        return None

    try:
        import groq

        client = groq.Client(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a creative YouTube content strategist specializing "
                        "in storytelling, self-improvement, and psychology content. "
                        "Write engaging, clickable content that drives views."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("Groq API call failed: %s", e)
        return None


def generate_title(story_title: str, story_body: str) -> str:
    """
    Generate a clickable YouTube title from a Reddit story.
    """
    prompt = f"""
You are writing a YouTube title for a narrated Reddit story video with Minecraft gameplay background.

The video is a first-person narration of a personal story. The title should:
- Be clickable but not misleading
- Spark curiosity or emotional resonance
- Use proven patterns: "I...", "The moment I...", "What happened when..."
- Be under 70 characters
- NO clickbait like "You won't believe..."
- Make viewers want to hear the full story

Story Title: {story_title}
Story Summary: {story_body[:300]}...

Generate exactly ONE title. No quotes, no extra text.
"""
    result = _call_groq(prompt)
    if result:
        return result[:100].strip('"\' \n')

    # Fallback: use the original Reddit title with a narrative prefix
    if len(story_title) > 70:
        return story_title[:67] + "..."
    return story_title


def generate_description(story_body: str, credits: str = "") -> str:
    """
    Generate a YouTube description from the story.
    Includes narrative hook, credits, and engagement prompts.
    """
    # Get first ~200 chars as hook
    hook = story_body[:200].strip()
    if len(story_body) > 200:
        hook += "..."

    prompt = f"""
Write a YouTube video description for a narrated Reddit story video.
Style: Emotional, engaging, authentic.

Story text: {story_body[:1000]}...

The description should include:
1. A compelling 2-3 sentence hook that summarizes the story
2. A "Story Source" section linking to the original Reddit post
3. Video credits
4. Engagement prompts (subscribe, comment, like)

Keep it under 500 words. Make it natural, not salesy.
"""
    result = _call_groq(prompt)

    if result:
        desc = result.strip()
    else:
        # Fallback generation
        desc = (
            f"{hook}\\n\\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\\n"
            f"📖 Story Source: Reddit\\n\\n"
            f"This is a narrated version of a personal story shared on Reddit. "
            f"Names and details may be changed for privacy.\\n\\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\\n"
            f"🎮 Background: Minecraft parkour gameplay\\n\\n"
            f"▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\\n"
            f"💬 What did you think? Share your story in the comments.\\n"
            f"👍 Like if you enjoyed\\n"
            f"🔔 Subscribe for more Reddit stories\\n"
        )

    if credits:
        desc += f"\\n\\nCredits:\\n{credits}"

    return desc


def expand_story_for_youtube(original_title: str, original_body: str, target_minutes: int = 10) -> str:
    """
    Use Groq to expand a short Reddit story into a long, engaging YouTube narration.
    Target: ~150 words per minute * target_minutes
    """
    target_words = target_minutes * 150  # 150 words/min at speaking pace
    
    prompt = f"""
You are a master storyteller writing a narrated story for YouTube. 
Take the following short Reddit post and EXPAND it into a much longer, more detailed, emotionally rich story.

Your job:
- Write in FIRST PERSON ("I" not "he/she")
- Keep the original plot and events but ADD scenes, descriptions, internal monologue, and emotional depth
- Add vivid sensory details (sights, sounds, textures, smells)
- Expand each moment into a full scene
- Include pacing: build tension, have emotional peaks, and a satisfying resolution
- The final length should be approximately {target_words} words (for a {target_minutes}-minute video at 150 words/min)

ORIGINAL STORY:
Title: {original_title}
{original_body}

Write ONLY the expanded narration text. No headers, no timestamps, no instructions.
Just pure first-person storytelling. Make it gripping and emotional.
"""
    
    result = _call_groq(prompt, model="llama-3.3-70b-versatile", max_tokens=4000)
    
    if result:
        expanded = result.strip()
        word_count = len(expanded.split())
        logger.info("Story expanded: %d words (%d min estimated)", word_count, int(word_count / 150))
        return expanded
    
    logger.warning("Story expansion failed — returning original")
    return original_body


def generate_thumbnail_prompt(story_title: str, story_body: str) -> str:
    """
    Generate a prompt for Cloudflare Flux to create a thumbnail image.
    The thumbnail should be visually striking, simple, and symbolic.
    """
    # Extract key emotional elements
    prompt = f"""
Create a detailed prompt for an AI image generator (Flux) to make a YouTube thumbnail.

The video is a first-person Reddit story narrated over Minecraft parkour gameplay.
The thumbnail should NOT include Minecraft elements. Instead, create a symbolic,
emotionally resonant image that represents the story's theme.

Target aspect ratio: 16:9 (YouTube thumbnail)
Style: Simple, bold, dramatic, high contrast
NO text in the image (title text will be added by YouTube)

Story: {story_title}
Context: {story_body[:500]}...

Generate a single paragraph describing the exact image to create.
Focus on: composition, colors, lighting, mood, and symbolic elements.
Make it visually striking and clickable.
"""
    result = _call_groq(prompt)

    if result:
        return result.strip()

    # Fallback
    return (
        f"A dramatic cinematic scene symbolizing: {story_title[:100]}. "
        f"High contrast lighting, deep shadows, emotional atmosphere, "
        f"professional photography style, 4K, 16:9 aspect ratio."
    )


# ─── Main entry point (for testing) ──────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    test_story = {
        "title": "I spent 5 years pretending to be happy. Here's what broke me.",
        "body": (
            "I was 22 when I realized I had been living my life for everyone else. "
            "My parents wanted me to be a doctor, so I studied medicine. "
            "I hated every second of it. The blood, the hours, the pressure. "
            "But I smiled through it all. I smiled at graduation. "
            "I smiled at my first job. I smiled when my father said he was proud of me. "
            "But inside, I was dying. Every morning I would stare at the ceiling "
            "and pray I wouldn't have to get up."
        ),
    }

    print("Title:", generate_title(test_story["title"], test_story["body"]))
    print("\nThumbnail Prompt:", generate_thumbnail_prompt(test_story["title"], test_story["body"]))
    print("\nDescription Preview:", generate_description(test_story["body"])[:300])
