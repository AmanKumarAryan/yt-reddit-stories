#!/usr/bin/env bash
# ──────────────────────────────────────────────────────
# download_assets.sh — Download Minecraft parkour clips
# from the "Minecraft Parkour Gameplay NO COPYRIGHT"
# playlist into assets/ for the pipeline.
#
# For each video, downloads the first 3 minutes at 1080p
# (H.264, fast, good quality). The pipeline concatenates
# random segments from all downloaded clips to match the
# target video length.
#
# Run at pipeline start (or manually once).
# Videos are ~20-50 MB each.
#
# Usage:
#   bash download_assets.sh [count]
#     count: how many videos to download (default: 5)
#
# Examples:
#   bash download_assets.sh          # Download 5 clips
#   bash download_assets.sh 10       # Download 10 clips
#   bash download_assets.sh 0        # Just show available
# ──────────────────────────────────────────────────────

set -euo pipefail

COUNT="${1:-5}"
ASSETS_DIR="$(cd "$(dirname "$0")" && pwd)/assets"
mkdir -p "$ASSETS_DIR"

PLAYLIST_URL="https://youtube.com/playlist?list=PLmSs-0cFIbfVWhkZx0i4UMiZdr2C0Z8w7"
CLIP_DURATION_SEC=180  # 3 minutes per clip (~30-50 MB)

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Downloading ${COUNT} Minecraft parkour clips"
echo "  Source: The Game Archive (CC BY)"
echo "  Playlist: $PLAYLIST_URL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Step 1: Extract video IDs from playlist
echo ""
echo "Fetching playlist..."
VIDEO_IDS=$(yt-dlp --flat-playlist --print "%(id)s" "$PLAYLIST_URL" 2>/dev/null | head -n "$COUNT")

if [ -z "$VIDEO_IDS" ]; then
    echo "❌ Failed to fetch playlist. Check URL."
    exit 1
fi

TOTAL_IDS=$(echo "$VIDEO_IDS" | wc -l)
echo "Found $TOTAL_IDS videos. Downloading..."

# Step 2: Download each video (first 3 min, 1080p H.264 for fast stream copy)
DOWNLOADED=0
echo "$VIDEO_IDS" | while read -r vid; do
    [ -z "$vid" ] && continue
    
    output="$ASSETS_DIR/${vid}.mp4"
    
    if [ -f "$output" ] && [ -s "$output" ]; then
        echo "  ✅ Already exists: ${vid}.mp4 ($(du -h "$output" | cut -f1))"
        DOWNLOADED=$((DOWNLOADED + 1))
        continue
    fi
    
    echo "  ⬇️  Downloading ${vid}..."
    
    yt-dlp \
        -f "bestvideo[height<=1080][vcodec^=avc1]+bestaudio[ext=m4a]/best[height<=1080]" \
        --merge-output-format mp4 \
        --download-sections "*0-${CLIP_DURATION_SEC}" \
        --force-keyframes-at-cuts \
        --no-playlist \
        --no-check-certificates \
        -o "$output" \
        "https://www.youtube.com/watch?v=${vid}" 2>&1 | tail -2
    
    if [ -f "$output" ] && [ -s "$output" ]; then
        echo "  ✅ Saved: ${vid}.mp4 ($(du -h "$output" | cut -f1))"
    else
        echo "  ⚠️  Failed: ${vid}"
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Done!"
ls -lh "$ASSETS_DIR"/*.mp4 2>/dev/null | awk '{print "  " $NF " (" $5 ")"}' || echo "  (no videos)"
echo ""
echo "Pipeline will pick random segments from all clips above."
echo "More clips = more variety in final video."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
