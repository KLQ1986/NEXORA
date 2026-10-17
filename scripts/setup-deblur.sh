#!/bin/sh
# Deblurring for Visual Quality: NAFNet (GoPro, width64) in its MLX port, on the Apple GPU, in an environment of its own beside
# the data, so NEXORA itself needs no MLX. Run once: sh scripts/setup-deblur.sh [data dir]. About 60 MB of packages, 270 MB of model.
set -e
DATA="${1:-data}"
ENV="$DATA/tools/nafnet"
uv venv --python 3.12 "$ENV"
uv pip install --python "$ENV/bin/python" "git+https://github.com/xocialize/nafnet-mlx@9a03831949ea95d2f0d03e3606b34504f3ba76b8"
mkdir -p "$ENV/models"
[ -s "$ENV/models/gopro_width64.safetensors" ] || curl -fsSL -o "$ENV/models/gopro_width64.safetensors" https://huggingface.co/mlx-community/NAFNet-GoPro-width64/resolve/main/model.safetensors
"$ENV/bin/python" -I -c "import mlx.core as mx; print('ready', mx.default_device())"
