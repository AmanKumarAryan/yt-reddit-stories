"""
merger.py — Merge voiceover + background video + thumbnail into final video.

Steps:
  1. Overlay voiceover audio onto Minecraft background video
  2. Optionally add intro card with the thumbnail image
  3. Export final MP4 with proper YouTube encoding settings
"""

import logging
import subprocess
from pathlib import Path
from typing import Optional

from modules.config import OUTPUT_DIR

logger = logging.getLogger(__name__)


def merge(
    background_video: Path,
    voiceover: Path,
    thumbnail: Optional[Path] = None,
    output_path: Optional[Path] = None,
    intro_duration: float = 2.0,
) -> Path:
    """
    Merge background video + voiceover + optional thumbnail intro card.

    Args:
        background_video: Path to the Minecraft background MP4.
        voiceover: Path to the TTS voiceover MP3.
        thumbnail: Optional path to thumbnail PNG for intro card.
        output_path: Where to save the final MP4.
        intro_duration: How long (seconds) to show the thumbnail at start.

    Returns:
        Path to the final merged video.
    """
    if output_path is None:
        output_path = OUTPUT_DIR / "final_video.mp4"

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ─── Step 1: Normalize audio on voiceover ────────────────────
    normalized_audio = voiceover.with_suffix(".normalized.m4a")
    try:
        _normalize_audio(voiceover, normalized_audio)
        audio_to_use = normalized_audio if normalized_audio.exists() else voiceover
        logger.info("Audio normalized successfully")
    except Exception as e:
        logger.warning("Audio normalization failed (%s) — using original voiceover", e)
        audio_to_use = voiceover

    # ─── Step 2: Get durations ───────────────────────────────────
    bg_duration = _get_media_duration(background_video)
    try:
        audio_duration = _get_media_duration(audio_to_use)
    except Exception:
        audio_duration = _get_media_duration(voiceover)
        audio_to_use = voiceover
    logger.info("BG video: %.1f sec | Voiceover: %.1f sec", bg_duration, audio_duration)

    # ─── Step 3: Build the video ──────────────────────────────────
    if thumbnail and thumbnail.exists() and intro_duration > 0:
        # Create intro card with thumbnail
        intro_path = output_path.with_suffix(".intro.mp4")
        _create_intro_card(thumbnail, audio_to_use, intro_path, intro_duration)
        # Then merge intro + background
        _merge_intro_with_bg(intro_path, background_video, output_path, intro_duration, audio_duration)
        # Clean up
        if intro_path.exists():
            intro_path.unlink()
    else:
        # Simple overlay: voiceover on background
        _overlay_audio_on_video(background_video, audio_to_use, output_path)

    # ─── Step 4: Clean up ────────────────────────────────────────
    if normalized_audio.exists() and normalized_audio != voiceover:
        normalized_audio.unlink()
    # Also clean up old-style .normalized.mp3 if it exists
    legacy_norm = voiceover.with_suffix(".normalized.mp3")
    if legacy_norm.exists():
        legacy_norm.unlink()

    logger.info("Final video ready: %s", output_path)
    return output_path


def _normalize_audio(input_path: Path, output_path: Path) -> None:
    """Normalize audio volume using ffmpeg loudnorm (simple pass-through with volume boost)."""
    # First try loudnorm, fall back to simple volume boost
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=summary",
        "-c:a", "aac",
        "-b:a", "192k",
        "-f", "null",
        "-",
    ]
    # First pass: measure loudness (may fail on some files)
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
    except Exception:
        pass  # First pass is optional

    # Second pass: apply normalization (use M4A container for AAC codec)
    output_path = output_path.with_suffix(".m4a")
    cmd2 = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-af", "volume=2.0",  # Simple 2x volume boost
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_path),
    ]
    subprocess.run(cmd2, check=True, capture_output=True, text=True, timeout=60)


def _get_media_duration(media_path: Path) -> float:
    """Get duration of any media file using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    return float(result.stdout.strip())


def _create_intro_card(
    thumbnail: Path,
    audio: Path,
    output_path: Path,
    duration: float,
) -> None:
    """Create an intro video segment with the thumbnail image and first part of audio."""
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(thumbnail),
        "-i", str(audio),
        "-c:v", "libx264",
        "-preset", "fast",
        "-t", str(duration),
        "-pix_fmt", "yuv420p",
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)


def _overlay_audio_on_video(
    video: Path,
    audio: Path,
    output_path: Path,
) -> None:
    """Overlay voiceover audio onto background video. Video continues if audio ends."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-i", str(audio),
        "-c:v", "libx264",
        "-preset", "fast",
        "-c:a", "aac",
        "-b:a", "192k",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        "-shortest",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)


def _merge_intro_with_bg(
    intro: Path,
    background: Path,
    output_path: Path,
    intro_duration: float,
    total_audio_duration: float,
) -> None:
    """Concatenate intro card with background video, overlay audio."""
    # Trim background to length: total audio duration minus intro
    remaining = max(10, total_audio_duration - intro_duration)
    bg_trimmed = background.with_suffix(".trimmed.mp4")

    cmd_trim = [
        "ffmpeg", "-y",
        "-ss", str(intro_duration),  # Start from where intro ends
        "-i", str(background),
        "-t", str(remaining),
        "-c", "copy",
        str(bg_trimmed),
    ]
    subprocess.run(cmd_trim, check=True, capture_output=True, text=True, timeout=120)

    # Concatenate intro + trimmed background
    concat_file = output_path.with_suffix(".concat.txt")
    concat_file.write_text(
        f"file '{intro.resolve()}'\n"
        f"file '{bg_trimmed.resolve()}'\n"
    )

    cmd_concat = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c:v", "libx264",
        "-preset", "fast",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    subprocess.run(cmd_concat, check=True, capture_output=True, text=True, timeout=300)

    # Cleanup
    for f in [bg_trimmed, concat_file]:
        if f.exists():
            f.unlink()


# ─── Main entry point (for testing) ──────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test with dummy files
    test_bg = OUTPUT_DIR / "background_video.mp4"
    test_voice = OUTPUT_DIR / "voiceover.mp3"
    test_thumb = OUTPUT_DIR / "thumbnail.png"

    if not test_bg.exists() or not test_voice.exists():
        print("Run video.py and voice.py first to generate test files!")
        print(f"Need: {test_bg}")
        print(f"Need: {test_voice}")
    else:
        final = merge(
            background_video=test_bg,
            voiceover=test_voice,
            thumbnail=test_thumb if test_thumb.exists() else None,
        )
        print(f"Final video: {final}")
