"""
video.py — Provide Minecraft parkour background video.

Strategy:
  1. Check assets/ folder for pre-downloaded high-quality clips
  2. If found, concatenate multiple clips (random segments) to reach target duration
  3. If not found, download from YouTube (fallback)
  4. Credit the source (requires attribution in video description)
"""

import logging
import random
import subprocess
import tempfile
import shutil
from pathlib import Path

from modules.config import MINECRAFT_VIDEO_URL, MINECRAFT_CREDITS, OUTPUT_DIR

logger = logging.getLogger(__name__)


def _find_assets_videos() -> list[Path]:
    """Find pre-downloaded Minecraft parkour videos in assets/ folder."""
    assets_dir = Path(__file__).resolve().parent.parent / "assets"
    if not assets_dir.exists():
        return []
    videos = sorted(assets_dir.glob("*.mp4"))
    return videos


def _concat_assets_clips(assets_videos: list[Path], target_duration_sec: float, output_path: Path) -> Path:
    """
    Concatenate multiple asset clips to reach target_duration_sec.

    Picks random segments from random clips, loops if needed.
    Uses stream copy (no re-encode) for speed.
    """
    # Get durations of all assets
    video_durations = {}
    for v in assets_videos:
        try:
            video_durations[v] = _get_video_duration(v)
        except Exception as e:
            logger.warning("Could not get duration for %s: %s", v.name, e)

    if not video_durations:
        raise RuntimeError("No valid assets found with readable durations")

    total_available = sum(video_durations.values())
    logger.info("Assets: %d files, %.0f sec total available", len(video_durations), total_available)

    # How many times we need to loop through all clips
    times_through = max(1, int(target_duration_sec / total_available) + 1)

    # Build list of segments to extract
    segments = []  # list of (video_path, segment_length)
    remaining = target_duration_sec

    for _ in range(times_through):
        if remaining <= 0:
            break
        # Randomize order each pass
        shuffled = list(video_durations.keys())
        random.shuffle(shuffled)

        for video in shuffled:
            if remaining <= 0:
                break
            dur = video_durations[video]
            seg_len = min(remaining, dur)
            segments.append((video, seg_len))
            remaining -= seg_len

    logger.info("Target: %.0f sec → %d segments to concatenate", target_duration_sec, len(segments))

    # Trim each segment with stream copy
    tmp_dir = Path(tempfile.mkdtemp(prefix="bg_concat_"))
    segment_files = []

    try:
        for i, (video, seg_len) in enumerate(segments):
            seg_path = tmp_dir / f"seg_{i:04d}.mp4"
            dur = video_durations[video]
            max_start = max(0, dur - seg_len - 2)
            start_offset = random.uniform(5, max_start) if max_start > 5 else 0

            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start_offset),
                "-i", str(video),
                "-t", str(seg_len),
                "-c", "copy",
                "-avoid_negative_ts", "1",
                str(seg_path),
            ]
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)
            segment_files.append(seg_path)

        # Create concat file list
        concat_list = tmp_dir / "concat.txt"
        with open(concat_list, "w") as f:
            for seg in segment_files:
                f.write(f"file '{seg}'\n")

        # Concatenate all segments (stream copy, no re-encode)
        cmd_concat = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ]
        subprocess.run(cmd_concat, check=True, capture_output=True, text=True, timeout=300)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    final_duration = _get_video_duration(output_path)
    logger.info("Background video ready: %s (%.1f sec, %d segments)", output_path, final_duration, len(segments))
    return output_path


def download_background_video(
    target_duration_sec: float,
    output_path: Path | None = None,
    video_url: str | None = None,
) -> Path:
    """
    Provide a Minecraft parkour background video trimmed to target duration.

    Priority:
      1. Concatenate random segments from assets/*.mp4 (pre-downloaded high-quality)
         to reach target_duration_sec. Loops clips if total duration < target.
      2. Download from YouTube via yt-dlp (fallback).
    """
    from modules.config import MINECRAFT_VIDEO_URL as DEFAULT_URL

    if output_path is None:
        output_path = OUTPUT_DIR / "background_video.mp4"
    if video_url is None:
        video_url = DEFAULT_URL

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ─── Priority 1: Use assets/ folder (multi-clip concat) ─
    assets_videos = _find_assets_videos()
    if assets_videos:
        return _concat_assets_clips(assets_videos, target_duration_sec, output_path)

    # ─── Priority 2: Download from YouTube ───────────────────
    logger.warning("No assets found in assets/ folder — downloading from YouTube (quality may be lower)")
    logger.info("To improve quality, pre-download videos into assets/ folder")
    logger.info("Target duration: %.0f seconds", target_duration_sec)

    raw_path = output_path.with_suffix(".raw.mp4")
    download_duration = min(target_duration_sec + 60, 300)

    download_success = False

    cmd_dl = [
        "yt-dlp",
        "-o", str(raw_path),
        "--format", "bestvideo[height<=1080][vcodec^=avc1]+bestaudio[ext=m4a]/best[height<=1080]",
        "--merge-output-format", "mp4",
        "--download-sections", f"*0-{min(download_duration, 180)}",
        "--force-keyframes-at-cuts",
        "--no-playlist",
        "--no-check-certificates",
        "--retries", "10",
        "--fragment-retries", "10",
        "--retry-sleep", "5",
        "--socket-timeout", "30",
        attempt_url,
    ]

    try:
        result = subprocess.run(cmd_dl, check=True, capture_output=True, text=True, timeout=600)
        logger.debug("yt-dlp stdout: %s", result.stdout[:500])
        if raw_path.exists() and raw_path.stat().st_size > 100000:
            download_success = True
    except subprocess.TimeoutExpired:
        logger.warning("yt-dlp timed out — checking partial output")
        if raw_path.exists() and raw_path.stat().st_size > 100000:
            download_success = True
    except subprocess.CalledProcessError as e:
        logger.error("yt-dlp failed (exit %d): %s", e.returncode, e.stderr[:1000])
        if raw_path.exists() and raw_path.stat().st_size > 100000:
            logger.info("Partial download exists despite error — using it")
            download_success = True

    if not download_success:
        raise RuntimeError("Failed to download video from all sources")

    raw_duration = _get_video_duration(raw_path)
    start_offset = min(30, max(0, raw_duration - target_duration_sec - 10))

    cmd_trim = [
        "ffmpeg", "-y",
        "-ss", str(start_offset),
        "-i", str(raw_path),
        "-t", str(target_duration_sec),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]
    subprocess.run(cmd_trim, check=True, capture_output=True, text=True, timeout=60)

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
