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
"$DEST/env/bin/python" -I -c "import torch; print('ready', torch.__version__, 'mps' if torch.backends.mps.is_available() else 'cpu')"
