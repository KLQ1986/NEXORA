#!/bin/sh
# The picture-and-words model (SigLIP 2) in an environment of its own, beside the data, so NEXORA itself needs no PyTorch.
# Run once: sh scripts/setup-pictures.sh [data dir] [model]. About 1 GB of packages and 0.4 GB of model.
set -e
DATA="${1:-data}"
MODEL="${2:-google/siglip2-base-patch16-256}"
ENV="$DATA/tools/siglip"
uv venv --python 3.12 "$ENV"
uv pip install --python "$ENV/bin/python" "torch>=2.6" "transformers>=4.56" pillow sentencepiece protobuf
# Fetch the model now, so the first search does not wait for it.
"$ENV/bin/python" -I -c "import sys; from transformers import AutoModel, AutoProcessor; AutoModel.from_pretrained(sys.argv[1]); AutoProcessor.from_pretrained(sys.argv[1]); print('ready', sys.argv[1])" "$MODEL"
