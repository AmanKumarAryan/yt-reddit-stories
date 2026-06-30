"""
Configuration — loads all secrets from environment variables.
Never hardcode API keys here.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


# ─── Reddit ──────────────────────────────────────────────────────
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "yt-pipeline/1.0")

# ─── Groq ─────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# ─── Cloudflare Flux ──────────────────────────────────────────────
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID", "")
CF_FLUX_API_TOKEN = os.getenv("CF_FLUX_API_TOKEN", "")

# ─── YouTube Upload ──────────────────────────────────────────────
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CLIENT_SECRETS_FILE = os.getenv("GOOGLE_CLIENT_SECRETS_FILE", "")
YOUTUBE_CHANNEL_NAME = os.getenv("YOUTUBE_CHANNEL_NAME", "")

# ─── Minecraft Video ──────────────────────────────────────────────
MINECRAFT_VIDEO_URL = os.getenv(
    "MINECRAFT_VIDEO_URL",
    "https://www.youtube.com/watch?v=eBExtYRpuqI",
)
MINECRAFT_CREDITS = os.getenv("MINECRAFT_CREDITS", "perpexior")

# ─── Pipeline Config ──────────────────────────────────────────────
TTS_VOICE = os.getenv("TTS_VOICE", "en-US-BrianNeural")
TARGET_DURATION_MINUTES = int(os.getenv("TARGET_VIDEO_DURATION_MINUTES", "3"))
MAX_STORY_WORDS = int(os.getenv("MAX_STORY_WORDS", "800"))
MIN_STORY_WORDS = int(os.getenv("MIN_STORY_WORDS", "200"))

# ─── Paths ────────────────────────────────────────────────────────
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

# Ensure directories exist
for d in [DATA_DIR, OUTPUT_DIR, SCRIPTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)
