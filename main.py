#!/usr/bin/env python3
"""
main.py — YouTube Reddit Stories Pipeline Orchestrator.

Full pipeline: Reddit Story → Script → Voiceover → Background Video → 
              Thumbnail → Merge → Upload

Usage:
    python main.py                            # Full pipeline (10 min)
    python main.py --dry-run                  # Fetch story only, don't upload
    python main.py --skip-upload              # Generate video but don't upload
    python main.py --target-minutes 5         # Make a 5-minute video
    python main.py --story-id XYZ             # Re-use a specific story ID
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from datetime import datetime

# Ensure modules are importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from modules.config import (
    OUTPUT_DIR,
    SCRIPTS_DIR,
    TARGET_DURATION_MINUTES,
    MINECRAFT_CREDITS,
)
from modules.reddit import (
    fetch_top_stories,
    pick_best_story,
    format_story_script,
    mark_used,
)
from modules.voice import generate_voiceover
from modules.video import download_background_video, get_credits_text
from modules.groq_helpers import (
    generate_title,
    generate_description,
    generate_thumbnail_prompt,
)
from modules.thumbnail_gen import generate_thumbnail
from modules.merger import merge
from modules.uploader import upload_video

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    """Configure logging with timestamps."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def run_pipeline(
    dry_run: bool = False,
    skip_upload: bool = False,
    story_id: str | None = None,
    target_minutes: int = 10,
) -> bool:
    """
    Execute the full pipeline.

    Returns True on success, False on failure.
    """
    # ─── Step 0: Output directory ────────────────────────────────
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    logger.info("=" * 60)
    logger.info("Pipeline Run: %s", run_id)
    logger.info("=" * 60)

    # ─── Step 1: Fetch Story from Reddit ─────────────────────────
    logger.info("")
    logger.info("─" * 40)
    logger.info("Step 1/6: Fetch story from Reddit")
    logger.info("─" * 40)

    candidates = fetch_top_stories()
    if not candidates:
        logger.error("No story candidates found from Reddit")
        return False

    story = pick_best_story(candidates)
    if not story:
        logger.error("No suitable un-used story found")
        return False

    logger.info("Selected story: %s", story["title"])
    logger.info("  Subreddit: r/%s", story.get("subreddit", "?"))
    logger.info("  Score: %.1f", story.get("score", 0))
    logger.info("  Words: %d", story.get("word_count", 0))

    # ─── Step 2: Generate Script ─────────────────────────────────
    logger.info("")
    logger.info("─" * 40)
    logger.info("Step 2/6: Generate narration script")
    logger.info("─" * 40)

    script = format_story_script(story)
    script_path = run_dir / "script.txt"
    script_path.write_text(script, encoding="utf-8")
    logger.info("Script saved: %s (%d lines)", script_path, len(script.splitlines()))

    # ─── Step 3: Generate Voiceover ──────────────────────────────
    logger.info("")
    logger.info("─" * 40)
    logger.info("Step 3/6: Generate voiceover (TTS)")
    logger.info("─" * 40)

    voiceover_path = run_dir / "voiceover.mp3"
    try:
        voiceover_path = generate_voiceover(script_path, voiceover_path)
    except Exception as e:
        logger.error("Voiceover generation failed: %s", e)
        return False

    if dry_run:
        logger.info("DRY RUN: Stopping after voiceover generation.")
        logger.info("Script: %s", script_path)
        logger.info("Voice: %s", voiceover_path)
        return True

    # ─── Step 4: Download Background Video ───────────────────────
    logger.info("")
    logger.info("─" * 40)
    logger.info("Step 4/6: Download Minecraft background video")
    logger.info("─" * 40)

    # Estimate duration from voiceover
    import json as _json
    timing_path = voiceover_path.with_suffix(".timing.json")
    if timing_path.exists():
        with open(timing_path) as f:
            timing = _json.load(f)
        target_duration = timing.get("total_duration_sec", target_minutes * 60)
    else:
        target_duration = target_minutes * 60

    logger.info("Target video duration: %.0f seconds", target_duration)

    bg_video_path = run_dir / "background.mp4"
    try:
        bg_video_path = download_background_video(
            target_duration_sec=target_duration + 10,  # Add buffer
            output_path=bg_video_path,
        )
    except Exception as e:
        logger.error("Background video download failed: %s", e)
        return False

    # ─── Step 5: Generate Thumbnail ──────────────────────────────
    logger.info("")
    logger.info("─" * 40)
    logger.info("Step 5/6: Generate thumbnail, title, description")
    logger.info("─" * 40)

    # Generate title
    title = generate_title(story["title"], story["body"])
    logger.info("Title: %s", title)

    # Generate description
    credits = get_credits_text()
    description = generate_description(
        story["body"],
        credits=credits,
    )
    logger.info("Description: %d chars", len(description))

    # Generate thumbnail prompt + image
    thumb_prompt = generate_thumbnail_prompt(story["title"], story["body"])
    logger.info("Thumbnail prompt: %s", thumb_prompt[:100])

    thumbnail_path = None
    try:
        thumbnail_path = generate_thumbnail(
            prompt=thumb_prompt,
            output_path=run_dir / "thumbnail.png",
        )
    except Exception as e:
        logger.warning("Thumbnail generation failed (non-critical): %s", e)

    # ─── Step 6: Merge Video ─────────────────────────────────────
    logger.info("")
    logger.info("─" * 40)
    logger.info("Step 6/6: Merge video + voice + thumbnail")
    logger.info("─" * 40)

    final_video_path = run_dir / "final_video.mp4"
    try:
        final_video_path = merge(
            background_video=bg_video_path,
            voiceover=voiceover_path,
            thumbnail=thumbnail_path,
            output_path=final_video_path,
        )
    except Exception as e:
        logger.error("Video merging failed: %s", e)
        return False

    # Save metadata for later use
    metadata = {
        "run_id": run_id,
        "story": {
            "title": story["title"],
            "url": story.get("url", ""),
            "subreddit": story.get("subreddit", ""),
            "word_count": story.get("word_count", 0),
        },
        "video": {
            "path": str(final_video_path),
            "duration_sec": target_duration,
        },
        "youtube": {
            "title": title,
            "description_chars": len(description),
            "thumbnail": str(thumbnail_path) if thumbnail_path else None,
        },
    }
    meta_path = run_dir / "metadata.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
    logger.info("Metadata saved: %s", meta_path)

    logger.info("")
    logger.info("=" * 60)
    logger.info("Pipeline complete!")
    logger.info("  Video: %s", final_video_path)
    logger.info("  Duration: %.0f sec", target_duration)
    logger.info("=" * 60)

    # ─── Step 8: Upload to YouTube ──────────────────────────────
    if skip_upload:
        logger.info("SKIP UPLOAD: --skip-upload flag set.")
        # Still mark as used so we don't re-pick it
        mark_used(story["id"])
        return True

    logger.info("")
    logger.info("─" * 40)
    logger.info("Step 7: Upload to YouTube")
    logger.info("─" * 40)

    upload_success = upload_video(
        video_path=final_video_path,
        title=title,
        description=description,
        thumbnail_path=thumbnail_path,
        privacy_status="public",
    )

    if upload_success:
        logger.info("Upload successful! Marking story as used.")
        mark_used(story["id"])
        return True
    else:
        logger.warning("Upload failed. Story NOT marked as used (can retry).")
        return False


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="YouTube Reddit Stories Pipeline — automate Reddit-to-YouTube video creation.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch story and generate voiceover only (don't download video or upload).",
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="Run full pipeline but skip the YouTube upload step.",
    )
    parser.add_argument(
        "--story-id",
        type=str,
        default=None,
        help="Re-process a specific story ID (must be in topics_used.json).",
    )
    parser.add_argument(
        "--target-minutes",
        type=int,
        default=10,
        help="Target video length in minutes (default: 10).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    success = run_pipeline(
        dry_run=args.dry_run,
        skip_upload=args.skip_upload,
        story_id=args.story_id,
        target_minutes=args.target_minutes,
    )

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
