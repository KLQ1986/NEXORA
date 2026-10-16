#!/bin/sh
# Real-ESRGAN, its ncnn build for macOS (Vulkan through MoltenVK on the Apple GPU), beside the data, for Visual Quality.
# Run once: sh scripts/setup-realesrgan.sh [data dir]. About 50 MB with its models.
set -e
DATA="${1:-data}"
DEST="$DATA/tools/realesrgan"
URL="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-macos.zip"
TMP="$(mktemp -d)"
curl -fsSL -o "$TMP/r.zip" "$URL"
mkdir -p "$DEST"
unzip -q -o "$TMP/r.zip" -d "$DEST"
rm -rf "$TMP"
chmod +x "$DEST/realesrgan-ncnn-vulkan"
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
"$DEST/realesrgan-ncnn-vulkan" -i "$DEST/input.jpg" -o "$DEST/check.png" -n realesrgan-x4plus -m "$DEST/models" >/dev/null 2>&1
rm -f "$DEST/check.png"
echo "ready $DEST"
