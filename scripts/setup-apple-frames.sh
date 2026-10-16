#!/bin/sh
# Apple's frame processors (VideoToolbox VTFrameProcessor) for Visual Quality: builds the helper beside the data.
# Run once: sh scripts/setup-apple-frames.sh [data dir]. Needs macOS 15.4 or later (super resolution: 26) and the Swift compiler.
set -e
DATA="${1:-data}"
OUT="$DATA/tools/apple_frames"
mkdir -p "$OUT"
WORK=$(mktemp -d)
cp "$(dirname "$0")/../src/nexora/adapters/apple_frames.swift" "$WORK/main.swift"
swiftc -O "$WORK/main.swift" -o "$OUT/apple_frames"
rm -rf "$WORK"
"$OUT/apple_frames" probe
