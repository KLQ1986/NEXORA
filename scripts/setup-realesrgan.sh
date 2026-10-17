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
# The files that were checked (src/nexora/adapters/pinned.py); anything else is refused.
printf "c1c35d92079085de96b9d547fd7e4464bc8a2e9ccf28d7b8c712d72ade91b7cc  $DEST/realesrgan-ncnn-vulkan\n713ee713b0353afaa27976f0563a64a5043bd70b9bd8936c2e26e25ebcdbcddf  $DEST/models/realesrgan-x4plus.bin\n35330ececcea33b6c397a72548e788d5d53becee4734c50b7fada36e89f10a86  $DEST/models/realesrgan-x4plus.param\n" | shasum -a 256 -c -
"$DEST/realesrgan-ncnn-vulkan" -i "$DEST/input.jpg" -o "$DEST/check.png" -n realesrgan-x4plus -m "$DEST/models" >/dev/null 2>&1
rm -f "$DEST/check.png"
echo "ready $DEST"
