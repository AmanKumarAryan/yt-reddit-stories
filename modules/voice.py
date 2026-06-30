"""
voice.py — Text-to-Speech generation using edge-tts.

Parses a script file in the format:
  [MM:SS] | narration text | image prompt
And generates a single voiceover MP3 with word-level timing.
"""

import asyncio
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Optional

import edge_tts

from modules.config import TTS_VOICE, OUTPUT_DIR

logger = logging.getLogger(__name__)


def parse_script(filepath: Path) -> list[dict]:
    """
    Parse a pipeline script file into segments.
    Format: [MM:SS] | narration | image prompt
    Lines starting with # are comments, [STYLE: x] lines define style.
    Returns list of dicts: {start_sec, text, image_prompt}
    """
    segments = []
    with open(filepath, encoding="utf-8") as f:
        lines = f.readlines()

    current_style = "minecraft"

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Style declaration: [STYLE: x]
        style_match = re.match(r"^\[STYLE:\s*(\w+)\]", line, re.IGNORECASE)
        if style_match:
            current_style = style_match.group(1).lower()
            continue

        # Segment line: [MM:SS] | text | prompt
        seg_match = re.match(
            r"^\[(\d+):(\d+)\]\s*\|\s*(.*?)\s*\|\s*(.*)$", line
        )
        if seg_match:
            mins, secs = int(seg_match.group(1)), int(seg_match.group(2))
            narration = seg_match.group(3).strip()
            image_prompt = seg_match.group(4).strip()
            start_sec = mins * 60 + secs
            segments.append({
                "start_sec": start_sec,
                "text": narration,
                "image_prompt": image_prompt,
                "style": current_style,
            })

    return segments


async def _generate_tts_async(
    text: str,
    output_path: Path,
    voice: str,
) -> Path:
    """Generate TTS audio for a single text segment."""
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(output_path))
    return output_path


def generate_voiceover(
    script_path: Path,
    output_path: Optional[Path] = None,
) -> Path:
    """
    Generate a full voiceover MP3 from a script file.
    1. Parse script into segments
    2. Generate separate TTS per segment
    3. Concatenate into a single MP3
    4. Save timing metadata as JSON

    Returns path to the generated voiceover MP3.
    """
    segments = parse_script(script_path)
    if not segments:
        raise ValueError("No segments found in script!")

    if output_path is None:
        output_path = OUTPUT_DIR / "voiceover.mp3"

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Concatenate all text into a single block for edge-tts
    full_text = " ".join(seg["text"] for seg in segments)

    logger.info(
        "Generating TTS for %d segments (%d words) using voice: %s",
        len(segments),
        len(full_text.split()),
        voice,
    )

    # Run async TTS
    asyncio.run(_generate_tts_async(full_text, output_path, TTS_VOICE))

    # Calculate approximate segment timings based on word proportions
    # edge-tts doesn't give word timings, so we estimate:
    # Assume ~150 words/min (~2.5 words/sec)
    total_words = len(full_text.split())
    total_audio_sec = _get_audio_duration(output_path)

    word_start_times = []
    word_idx = 0
    for seg in segments:
        seg_words = len(seg["text"].split())
        if total_words > 0:
            seg_duration = total_audio_sec * (seg_words / total_words)
        else:
            seg_duration = 10.0
        word_start_times.append({
            "start": word_idx,
            "duration": seg_duration,
            "text": seg["text"],
        })
        word_idx += seg_words

    # Save timing metadata
    timing_path = output_path.with_suffix(".timing.json")
    with open(timing_path, "w") as f:
        json.dump(
            {
                "total_duration_sec": round(total_audio_sec, 2),
                "total_words": total_words,
                "segments": word_start_times,
            },
            f,
            indent=2,
        )

    logger.info(
        "Voiceover generated: %s (%.1f sec, %d words)",
        output_path,
        total_audio_sec,
        total_words,
    )
    return output_path


def _get_audio_duration(audio_path: Path) -> float:
    """Get audio duration in seconds using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return float(result.stdout.strip())


# ─── Main entry point (for testing) ──────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test with a sample script
    test_script = """[STYLE: minecraft]
[0:00] | I was 22 when I realized I had been living my life for everyone else. | Minecraft gameplay background, parkour scenery
[0:10] | My parents wanted me to be a doctor, so I studied medicine. | Minecraft gameplay background, parkour scenery
[0:20] | I hated every second of it. The blood, the hours, the pressure. | Minecraft gameplay background, parkour scenery
"""

    test_path = OUTPUT_DIR / "test_script.txt"
    test_path.write_text(test_script)
    mp3 = generate_voiceover(test_path)
    print(f"Voiceover saved: {mp3}")
