#!/bin/sh
# Face recovery for Visual Quality: CodeFormer (ONNX, from FaceFusion's model assets) run by onnxruntime in an environment of
# its own, beside the data, so NEXORA itself needs neither. Faces are found by Apple Vision (scripts/setup-apple-frames.sh).
# Run once: sh scripts/setup-faces.sh [data dir]. About 150 MB of packages and 380 MB of model.
set -e
DATA="${1:-data}"
ENV="$DATA/tools/faces"
uv venv --python 3.12 "$ENV"
uv pip install --python "$ENV/bin/python" "onnxruntime>=1.22" "opencv-python-headless>=4.11" numpy
mkdir -p "$ENV/models"
[ -s "$ENV/models/codeformer.onnx" ] || curl -fsSL -o "$ENV/models/codeformer.onnx" https://github.com/facefusion/facefusion-assets/releases/download/models-3.0.0/codeformer.onnx
# The files that were checked (src/nexora/adapters/pinned.py); anything else is refused.
printf "21710e7ab61c82683576c428e9c1b6fe1ed419586b7b39e394c3449c294b550f  $ENV/models/codeformer.onnx\n" | shasum -a 256 -c -
"$ENV/bin/python" -I -c "import sys, onnxruntime as ort; s = ort.InferenceSession(sys.argv[1], providers=['CPUExecutionProvider']); print('ready', [(i.name, i.shape) for i in s.get_inputs()])" "$ENV/models/codeformer.onnx"
