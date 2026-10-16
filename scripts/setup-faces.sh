#!/bin/sh
# The ONNX restoration models of Visual Quality: CodeFormer for faces (from FaceFusion's model assets) and NAFNet for blur (from
# OpenCV's model zoo), run by onnxruntime in an environment of its own, beside the data, so NEXORA itself needs neither. Faces are found by Apple Vision (scripts/setup-apple-frames.sh).
# Run once: sh scripts/setup-faces.sh [data dir]. About 150 MB of packages and 470 MB of models.
set -e
DATA="${1:-data}"
ENV="$DATA/tools/faces"
uv venv --python 3.12 "$ENV"
uv pip install --python "$ENV/bin/python" "onnxruntime>=1.22" "opencv-python-headless>=4.11" numpy
mkdir -p "$ENV/models"
[ -s "$ENV/models/codeformer.onnx" ] || curl -fsSL -o "$ENV/models/codeformer.onnx" https://github.com/facefusion/facefusion-assets/releases/download/models-3.0.0/codeformer.onnx
[ -s "$ENV/models/nafnet_deblur.onnx" ] || curl -fsSL -o "$ENV/models/nafnet_deblur.onnx" https://huggingface.co/opencv/deblurring_nafnet/resolve/main/deblurring_nafnet_2025may.onnx
"$ENV/bin/python" -I -c "import sys, onnxruntime as ort; s = ort.InferenceSession(sys.argv[1], providers=['CPUExecutionProvider']); print('ready', [(i.name, i.shape) for i in s.get_inputs()])" "$ENV/models/codeformer.onnx"
