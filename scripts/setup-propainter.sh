#!/bin/sh
# ProPainter (object removal in video, ICCV 2023) for Visual Quality: the repo at a known commit and an environment of its
# own beside the data (PyTorch on the Apple GPU through MPS), so NEXORA itself needs no PyTorch.
# Run once: sh scripts/setup-propainter.sh [data dir]. About 1 GB of packages and 390 MB of weights.
set -e
DATA="${1:-data}"
DEST="$DATA/tools/propainter"
COMMIT="e870e79321c31b733e2031af5aa2fb1fe3ac7eec"
mkdir -p "$DEST"
if [ ! -d "$DEST/repo/.git" ]; then
  git clone --quiet https://github.com/sczhou/ProPainter.git "$DEST/repo"
fi
git -C "$DEST/repo" fetch --quiet origin
git -C "$DEST/repo" checkout --quiet "$COMMIT"
uv venv --python 3.12 "$DEST/env"
uv pip install --python "$DEST/env/bin/python" "torch>=2.6" "torchvision>=0.21" opencv-python-headless av einops scipy scikit-image imageio-ffmpeg pyyaml requests timm addict future matplotlib
mkdir -p "$DEST/repo/weights"
for W in ProPainter.pth raft-things.pth recurrent_flow_completion.pth; do
  [ -s "$DEST/repo/weights/$W" ] || curl -fsSL -o "$DEST/repo/weights/$W" "https://github.com/sczhou/ProPainter/releases/download/v0.1.0/$W"
done
# The files that were checked (src/nexora/adapters/pinned.py); anything else is refused.
printf "12c070c4b48f374c91d8a2a17851140b85c159621080989f9e191bbc18bd6591  $DEST/repo/weights/ProPainter.pth\nfcfa4125d6418f4de95d84aec20a3c5f4e205101715a79f193243c186ac9a7e1  $DEST/repo/weights/raft-things.pth\n22939a1a7900da878dbe1ccd011d646b1bfb30b8290039d8ff0e0c2fefbfd283  $DEST/repo/weights/recurrent_flow_completion.pth\n" | shasum -a 256 -c -
"$DEST/env/bin/python" -I -c "import torch; print('ready', torch.__version__, 'mps' if torch.backends.mps.is_available() else 'cpu')"
