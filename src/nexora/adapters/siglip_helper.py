"""The picture-and-words model, SigLIP 2, in an environment of its own (`scripts/setup-pictures.sh`), so that NEXORA itself
needs neither PyTorch nor transformers. Not imported by NEXORA: `adapters/siglip.py` starts it and talks to it, one JSON
request a line on stdin, one JSON answer a line on stdout, keeping the model loaded between requests.

    {"op": "images", "paths": [...]}  ->  {"vectors": [[...], ...]}     one unit vector a picture
    {"op": "texts", "texts": [...]}   ->  {"vectors": [[...], ...]}     one unit vector a text, in the same space
"""
import json
import sys

import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor

BATCH = 32


def main() -> None:
    name = sys.argv[1]
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    dtype = torch.float16 if device == "mps" else torch.float32
    model = AutoModel.from_pretrained(name, dtype=dtype).to(device).eval()
    processor = AutoProcessor.from_pretrained(name)
    print(json.dumps({"ready": name, "device": device}), flush=True)

    def unit(features) -> list[list[float]]:
        features = getattr(features, "pooler_output", features)        # transformers 5 returns an output object
        return torch.nn.functional.normalize(features.float(), dim=-1).cpu().tolist()

    for line in sys.stdin:
        try:
            asked = json.loads(line)
            out: list[list[float]] = []
            with torch.no_grad():
                if asked["op"] == "images":
                    for start in range(0, len(asked["paths"]), BATCH):
                        pictures = [Image.open(p).convert("RGB") for p in asked["paths"][start:start + BATCH]]
                        x = processor(images=pictures, return_tensors="pt").to(device)
                        out += unit(model.get_image_features(pixel_values=x["pixel_values"].to(dtype)))
                elif asked["op"] == "texts":
                    # SigLIP 2 was trained with texts padded to 64 tokens; shorter padding changes the vectors.
                    x = processor(text=asked["texts"], padding="max_length", max_length=64, truncation=True, return_tensors="pt").to(device)
                    out = unit(model.get_text_features(**x))
                else:
                    raise ValueError(f"unknown op {asked['op']!r}")
            print(json.dumps({"vectors": out}), flush=True)
        except Exception as err:                                        # one bad request does not end the helper
            print(json.dumps({"error": f"{type(err).__name__}: {err}"}), flush=True)


if __name__ == "__main__":
    main()
