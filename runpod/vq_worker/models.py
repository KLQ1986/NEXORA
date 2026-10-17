"""The models of the Visual Quality worker. Each task reads the frames of a span (in/000000.png …) and writes the same number of
frames under the same names (out/), so the handler and its client can count on frames in = frames out.

    deblur    VRT 006 (GoPro)            JingyunLiang/VRT, one clip of the span at a time, in tiles
    denoise   VRT 008 (DAVIS, non-blind)  given σ: the noise measured, raised by the lift the picture will get
    upscale   VRT 001 (REDS, ×4)          clean footage; the handler brings it to the height asked
    restore   RealBasicVSR (×4)           mmagic; real-world damage of old footage; the handler brings it to the height asked
    faces     CodeFormer                  sczhou/CodeFormer, frame by frame, faces only (the rest of the frame as it was)

Every weight is checked against its SHA-256 (pins.txt) where the image is built and again before it is loaded, and loaded
with weights_only: a checkpoint is data, never code. The code of VRT and CodeFormer is fixed at the commits in the Dockerfile.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

TASKS = ("deblur", "denoise", "upscale", "restore", "faces")
FAKE = os.environ.get("VQ_WORKER_FAKE") == "1"
ROOT = Path(os.environ.get("VQ_WORKER_ROOT", "/opt/vq"))
WEIGHTS = ROOT / "weights"
VRT, CODEFORMER = ROOT / "VRT", ROOT / "CodeFormer"
FILES = {
    "deblur": ["006_VRT_videodeblurring_GoPro.pth"],
    "denoise": ["008_VRT_videodenoising_DAVIS.pth"],
    "upscale": ["001_VRT_videosr_bi_REDS_6frames.pth"],
    "restore": ["realbasicvsr_c64b20_1x30x8_lr5e-5_150k_reds_20211104-52f77c2c.pth"],
    "faces": ["codeformer.pth", "detection_Resnet50_Final.pth", "parsing_parsenet.pth"],
}
HAS_NVENC = not FAKE and shutil.which("nvidia-smi") is not None and "hevc_nvenc" in subprocess.run(
    [os.environ.get("FFMPEG", "ffmpeg"), "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
_loaded: dict = {}


def _pins() -> dict[str, str]:
    pins = {}
    for line in (Path(__file__).with_name("pins.txt")).read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            digest, name = line.split()
            pins[name] = digest
    return pins


def _checked(name: str) -> Path:
    path = WEIGHTS / name
    want = _pins()[name]
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    if h.hexdigest() != want:
        raise RuntimeError(f"{name} is not the file that was checked (sha256 {h.hexdigest()[:12]}…, pinned {want[:12]}…)")
    return path


def available() -> list[str]:
    if FAKE:
        return list(TASKS)
    return [t for t in TASKS if all((WEIGHTS / f).is_file() for f in FILES[t])]


def run(task: str, frames_in: Path, frames_out: Path, given: dict) -> str:
    frames_out.mkdir(parents=True, exist_ok=True)
    if FAKE:
        return _fake(task, frames_in, frames_out)
    if task in ("deblur", "denoise", "upscale"):
        return _vrt(task, frames_in, frames_out, given)
    if task == "restore":
        return _realbasicvsr(frames_in, frames_out)
    return _codeformer(frames_in, frames_out, float(given.get("weight", 0.7)))


# ------------------------------------------------------------------------------------------------------------------ VRT
VRT_TASK = {"deblur": "006_VRT_videodeblurring_GoPro", "denoise": "008_VRT_videodenoising_DAVIS", "upscale": "001_VRT_videosr_bi_REDS_6frames"}


def _vrt_model(task: str):
    """VRT built as its own test script builds it for the task (main_test_vrt.prepare_model_dataset), its weights loaded here."""
    import torch
    if task in _loaded:
        return _loaded[task]
    sys.path.insert(0, str(VRT))
    from models.network_vrt import VRT as net
    if task == "upscale":
        model = net(upscale=4, img_size=[6, 64, 64], window_size=[6, 8, 8], depths=[8, 8, 8, 8, 8, 8, 8, 4, 4, 4, 4, 4, 4], indep_reconsts=[11, 12],
                    embed_dims=[120, 120, 120, 120, 120, 120, 120, 180, 180, 180, 180, 180, 180], num_heads=[6] * 13, pa_frames=2, deformable_groups=12)
    else:
        model = net(upscale=1, img_size=[6, 192, 192], window_size=[6, 8, 8], depths=[8, 8, 8, 8, 8, 8, 8, 4, 4, 4, 4], indep_reconsts=[9, 10],
                    embed_dims=[96, 96, 96, 96, 96, 96, 96, 120, 120, 120, 120], num_heads=[6] * 11, pa_frames=2, deformable_groups=16,
                    nonblind_denoising=task == "denoise")
    state = torch.load(_checked(VRT_TASK[task] + ".pth"), map_location="cpu", weights_only=True)
    model.load_state_dict(state.get("params", state), strict=True)
    model = model.eval().cuda()
    _loaded[task] = model
    return model


def _vrt(task: str, frames_in: Path, frames_out: Path, given: dict) -> str:
    import numpy as np
    import torch
    from PIL import Image
    sys.path.insert(0, str(VRT))
    from main_test_vrt import test_video
    model = _vrt_model(task)
    names = sorted(frames_in.glob("*.png"))
    lq = torch.from_numpy(np.stack([np.asarray(Image.open(n).convert("RGB"), np.float32) / 255.0 for n in names])).permute(0, 3, 1, 2)[None]
    if task == "denoise":
        # σ as the model was trained to be told it: the noise level (0..255) as a channel; the noise measured, raised by the lift
        # the picture will get after (what will be seen), within the 10–50 it learned.
        sigma = min(50.0, max(10.0, float(given.get("sigma", 10.0)) * float(given.get("lift", 1.0))))
        lq = torch.cat([lq, torch.full((1, lq.shape[1], 1, lq.shape[3], lq.shape[4]), sigma / 255.0)], 2)
    args = type("Args", (), {"tile": [12, 128, 128], "tile_overlap": [2, 20, 20], "scale": 4 if task == "upscale" else 1,
                             "window_size": [6, 8, 8], "nonblind_denoising": task == "denoise"})()
    with torch.no_grad():
        out = test_video(lq.cuda(), model, args)
    out = out[0].clamp(0, 1).permute(0, 2, 3, 1).cpu().numpy()
    for n, frame in zip(names, out):
        Image.fromarray((frame * 255.0).round().astype(np.uint8)).save(frames_out / n.name)
    return VRT_TASK[task]


# --------------------------------------------------------------------------------------------------------- RealBasicVSR
def _realbasicvsr(frames_in: Path, frames_out: Path) -> str:
    from mmagic.apis import MMagicInferencer
    if "restore" not in _loaded:
        _loaded["restore"] = MMagicInferencer("real_basicvsr", model_ckpt=str(_checked(FILES["restore"][0])))
    tmp = frames_out.parent / "rbvsr"
    _loaded["restore"].infer(video=str(frames_in), result_out_dir=str(tmp))
    made = sorted(tmp.rglob("*.png"))
    for src, name in zip(made, sorted(frames_in.glob("*.png"))):
        shutil.move(str(src), frames_out / name.name)
    return "RealBasicVSR"


# ----------------------------------------------------------------------------------------------------------- CodeFormer
def _codeformer(frames_in: Path, frames_out: Path, weight: float) -> str:
    for name in FILES["faces"]:
        _checked(name)
    tmp = frames_out.parent / "cf"
    subprocess.run([sys.executable, "inference_codeformer.py", "-w", f"{weight:.2f}", "--input_path", str(frames_in), "--output_path", str(tmp)],
                   cwd=CODEFORMER, check=True, capture_output=True)
    done = {p.stem: p for p in (tmp / "final_results").glob("*.png")}
    for name in sorted(frames_in.glob("*.png")):
        shutil.copy(done.get(name.stem, name), frames_out / name.name)          # a frame without a face comes back as it was
    return "CodeFormer"


# ----------------------------------------------------------------------------------------------------------------- fake
def _fake(task: str, frames_in: Path, frames_out: Path) -> str:
    """Stand-ins for running the protocol without a GPU: ×4 by resampling for the tasks that enlarge, a copy otherwise."""
    from PIL import Image
    for name in sorted(frames_in.glob("*.png")):
        with Image.open(name) as im:
            (im.resize((im.width * 4, im.height * 4), Image.BICUBIC) if task in ("upscale", "restore") else im.copy()).save(frames_out / name.name)
    return f"fake-{task}"
