"""
video.py — Download high-quality Minecraft parkour video from YouTube.

Strategy:
  1. Target CC BY / free-to-use Minecraft parkour channels
  2. Download the best available quality (up to 1080p)
  3. Trim to match voiceover duration
  4. Credit the source (requires attribution in video description)
"""

import logging
import subprocess
from pathlib import Path

from modules.config import MINECRAFT_VIDEO_URL, MINECRAFT_CREDITS, OUTPUT_DIR

logger = logging.getLogger(__name__)


def download_background_video(
    target_duration_sec: float,
    output_path: Path | None = None,
    video_url: str | None = None,
) -> Path:
    """
    Download a Minecraft parkour video from YouTube, trimmed to target duration.

    Args:
        target_duration_sec: Length of video needed (seconds).
        output_path: Where to save the final MP4.
        video_url: YouTube URL of the Minecraft video.
                   Defaults to MINECRAFT_VIDEO_URL from config.

    Returns:
        Path to the downloaded and trimmed MP4.

    Note:
        - Uses yt-dlp for downloading
        - Downloads best video (up to 1080p) + best audio
        - Selects a random-ish segment from the middle of the source video
    """
    from modules.config import MINECRAFT_VIDEO_URL as DEFAULT_URL

    if output_path is None:
        output_path = OUTPUT_DIR / "background_video.mp4"
    if video_url is None:
        video_url = DEFAULT_URL

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    raw_path = output_path.with_suffix(".raw.mp4")

    # Step 1: Download the video (first 5 minutes to have buffer)
    logger.info("Downloading Minecraft video from: %s", video_url)
    logger.info("Target duration: %.0f seconds", target_duration_sec)

    # Add a 30-second buffer on each side for trimming
    download_duration = min(target_duration_sec + 60, 300)  # Max 5 min

    cmd_dl = [
        "yt-dlp",
        "-o", str(raw_path),
        "--format", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
        "--download-sections", f"*0-{download_duration}",
        "--force-keyframes-at-cuts",
        "--no-playlist",
        video_url,
    ]

    try:
        subprocess.run(cmd_dl, check=True, capture_output=True, text=True, timeout=300)
    except subprocess.CalledProcessError as e:
        logger.warning("yt-dlp download failed: %s", e.stderr[-500:])

        # Fallback: try downloading a shorter clip from a different source
        fallback_url = "https://www.youtube.com/watch?v=0tx7sKsyuOg"
        logger.info("Trying fallback URL: %s", fallback_url)
        cmd_fb = [
            "yt-dlp",
            "-o", str(raw_path),
            "--format", "best[height<=720]",
            "--download-sections", f"*0-{download_duration}",
            "--force-keyframes-at-cuts",
            "--no-playlist",
            fallback_url,
        ]
        subprocess.run(cmd_fb, check=True, capture_output=True, text=True, timeout=300)

    if not raw_path.exists():
        raise RuntimeError("Failed to download video from all sources")

    # Step 2: Trim to exact target duration (from a random-ish offset)
    raw_duration = _get_video_duration(raw_path)
    logger.info("Downloaded video duration: %.1f sec", raw_duration)

    # Start from 30 seconds in (skip intros) or proportional
    start_offset = min(30, max(0, raw_duration - target_duration_sec - 10))

    cmd_trim = [
        "ffmpeg",
        "-y",
        "-ss", str(start_offset),
        "-i", str(raw_path),
        "-t", str(target_duration_sec),
        "-c:v", "libx264",
        "-preset", "fast",
        "-c:a", "aac",
        "-movflags", "+faststart",
        str(output_path),
    ]

    subprocess.run(cmd_trim, check=True, capture_output=True, text=True, timeout=120)

    # Clean up raw download
    if raw_path.exists():
        raw_path.unlink()

    final_duration = _get_video_duration(output_path)
    logger.info("Background video ready: %s (%.1f sec)", output_path, final_duration)

    return output_path


def get_credits_text() -> str:
    """Get attribution text for the Minecraft video creator."""
    return (
        f"Minecraft gameplay by {MINECRAFT_CREDITS}, "
        f"licensed under CC BY 4.0. "
        f"Source: {MINECRAFT_VIDEO_URL}"
    )


def _get_video_duration(video_path: Path) -> float:
    """Get video duration using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return float(result.stdout.strip())


# ─── Main entry point (for testing) ──────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    video_path = download_background_video(target_duration_sec=120)
    print(f"Background video: {video_path}")
    print(f"Credits: {get_credits_text()}")
