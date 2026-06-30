"""
uploader.py — Upload video to YouTube using YouTube Data API v3.

Requires Google OAuth credentials and a refresh token.
Uses the google-api-python-client library.
"""

import json
import logging
import os
import pickle
from pathlib import Path
from typing import Optional

from modules.config import (
    GOOGLE_CLIENT_SECRETS_FILE,
    GOOGLE_REFRESH_TOKEN,
    OUTPUT_DIR,
)

logger = logging.getLogger(__name__)


def upload_video(
    video_path: Path,
    title: str,
    description: str,
    thumbnail_path: Optional[Path] = None,
    privacy_status: str = "public",
    category_id: str = "22",  # "People & Blogs"
) -> bool:
    """
    Upload a video to YouTube.

    Args:
        video_path: Path to the final MP4 video.
        title: YouTube video title.
        description: YouTube video description.
        thumbnail_path: Optional path to thumbnail image.
        privacy_status: 'public', 'unlisted', or 'private'.
        category_id: YouTube category ID (22 = People & Blogs).

    Returns:
        True if upload succeeded, False otherwise.
    """
    if not video_path.exists():
        logger.error("Video file not found: %s", video_path)
        return False

    # Check credentials
    if not _check_credentials():
        logger.warning(
            "YouTube credentials not configured. "
            "Set GOOGLE_CLIENT_SECRETS_FILE and GOOGLE_REFRESH_TOKEN in .env"
        )
        return False

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        logger.error(
            "google-api-python-client not installed. "
            "Run: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        )
        return False

    try:
        # ─── Authenticate ────────────────────────────────────────
        credentials = _authenticate()

        # ─── Build YouTube client ────────────────────────────────
        youtube = build("youtube", "v3", credentials=credentials)

        # ─── Upload video ────────────────────────────────────────
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(
            str(video_path),
            chunksize=1024 * 1024 * 5,  # 5MB chunks
            resumable=True,
        )

        logger.info("Uploading video: %s", title)
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                logger.info("Upload progress: %d%%", progress)

        video_id = response.get("id", "?")
        logger.info("Video uploaded! ID: %s", video_id)

        # ─── Upload thumbnail (if provided) ──────────────────────
        if thumbnail_path and thumbnail_path.exists():
            _upload_thumbnail(youtube, video_id, thumbnail_path)

        logger.info(
            "Video live at: https://youtu.be/%s",
            video_id,
        )
        return True

    except Exception as e:
        logger.error("Upload failed: %s", e)
        return False


def _check_credentials() -> bool:
    """Check if YouTube upload credentials are available."""
    secrets_file = None
    if GOOGLE_CLIENT_SECRETS_FILE:
        secrets_file = Path(GOOGLE_CLIENT_SECRETS_FILE)
    if not secrets_file or not secrets_file.exists():
        secrets_file = Path("client_secrets.json")
    if not secrets_file.exists():
        return False
    return bool(GOOGLE_REFRESH_TOKEN)


def _authenticate():
    """Authenticate using refresh token and client secrets."""
    secrets_file = None
    if GOOGLE_CLIENT_SECRETS_FILE:
        secrets_file = Path(GOOGLE_CLIENT_SECRETS_FILE)
    if not secrets_file or not secrets_file.exists():
        secrets_file = Path("client_secrets.json")

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token_path = OUTPUT_DIR / "youtube_token.pickle"

    # Try loading saved token
    credentials = None
    if token_path.exists():
        with open(token_path, "rb") as f:
            credentials = pickle.load(f)

    # If no valid token, use refresh token
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            # Create from refresh token
            with open(secrets_file) as f:
                client_config = json.load(f)["installed"]

            credentials = Credentials(
                token=None,
                refresh_token=GOOGLE_REFRESH_TOKEN,
                token_uri=client_config["token_uri"],
                client_id=client_config["client_id"],
                client_secret=client_config["client_secret"],
                scopes=["https://www.googleapis.com/auth/youtube.upload"],
            )

        # Save token
        with open(token_path, "wb") as f:
            pickle.dump(credentials, f)

    return credentials


def _upload_thumbnail(youtube, video_id: str, thumbnail_path: Path) -> None:
    """Upload a thumbnail for the video."""
    try:
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=str(thumbnail_path),
        ).execute()
        logger.info("Thumbnail uploaded for video %s", video_id)
    except Exception as e:
        logger.warning("Thumbnail upload failed: %s", e)


# ─── Main entry point (for testing) ──────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    test_video = OUTPUT_DIR / "final_video.mp4"
    test_thumb = OUTPUT_DIR / "thumbnail.png"

    if not test_video.exists():
        print(f"Test video not found: {test_video}")
        print("Run merger.py first.")
    else:
        success = upload_video(
            video_path=test_video,
            title="Test Upload — I Was Living for Everyone Else",
            description="Test upload from pipeline. Ignore this video.",
            thumbnail_path=test_thumb if test_thumb.exists() else None,
            privacy_status="unlisted",
        )
        print(f"Upload {'succeeded' if success else 'failed'}")
