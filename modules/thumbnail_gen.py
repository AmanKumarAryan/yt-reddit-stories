"""
thumbnail_gen.py — Generate YouTube thumbnail using Cloudflare Flux.

Uses the Cloudflare Workers AI API with the flux-schnell model.
Requires CF_ACCOUNT_ID and CF_FLUX_API_TOKEN in .env.
"""

import base64
import json
import logging
from pathlib import Path
from typing import Optional
import urllib.request

from modules.config import CF_ACCOUNT_ID, CF_FLUX_API_TOKEN, OUTPUT_DIR

logger = logging.getLogger(__name__)


def generate_thumbnail(
    prompt: str,
    output_path: Optional[Path] = None,
) -> Optional[Path]:
    """
    Generate a YouTube thumbnail using Cloudflare Flux.

    Args:
        prompt: Text description for the image.
        output_path: Where to save the PNG thumbnail.

    Returns:
        Path to the generated thumbnail, or None if failed.
    """
    if not CF_ACCOUNT_ID or not CF_FLUX_API_TOKEN:
        logger.warning(
            "CF_ACCOUNT_ID or CF_FLUX_API_TOKEN not set — "
            "skipping thumbnail generation"
        )
        return None

    if output_path is None:
        output_path = OUTPUT_DIR / "thumbnail.png"

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Cloudflare Flux API endpoint (using flux-2-dev for better quality)
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}"
        f"/ai/run/@cf/black-forest-labs/flux-2-dev"
    )

    import uuid
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"

    # Build multipart form-data body for Flux 2 dev
    body_parts = []
    for key, value in [("prompt", prompt), ("steps", "25"), ("width", "1024"), ("height", "1024")]:
        part = f"--{boundary}\r\n"
        part += f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
        part += f"{value}\r\n"
        body_parts.append(part)
    body_parts.append(f"--{boundary}--\r\n")
    payload = "".join(body_parts).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {CF_FLUX_API_TOKEN}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }

    logger.info("Generating thumbnail via Cloudflare Flux 2 Dev...")
    logger.debug("Prompt: %s", prompt[:200])

    try:
        req = urllib.request.Request(url, data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())

        if not data.get("success"):
            logger.error("Cloudflare Flux API error: %s", data.get("errors"))
            return None

        result = data.get("result", {})
        image_b64 = result.get("image")

        if not image_b64:
            logger.error("No image in response: %s", result)
            return None

        # Decode and save
        image_bytes = base64.b64decode(image_b64)
        with open(output_path, "wb") as f:
            f.write(image_bytes)

        logger.info("Thumbnail saved: %s", output_path)
        return output_path

    except urllib.error.HTTPError as e:
        logger.error("HTTP Error %d: %s", e.code, e.read().decode()[:500])
        return None
    except Exception as e:
        logger.error("Failed to generate thumbnail: %s", e)
        return None


# ─── Main entry point (for testing) ──────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    test_prompt = (
        "A person sitting alone on a hospital bed, staring out a window at night, "
        "rain on the glass, dim blue lighting, emotional atmosphere, "
        "cinematic composition, high contrast, 16:9 YouTube thumbnail style"
    )

    thumb_path = generate_thumbnail(test_prompt)
    if thumb_path:
        print(f"Thumbnail generated: {thumb_path}")
    else:
        print("Thumbnail generation failed (check CF credentials in .env)")
