"""The files the local frame tools run, pinned by SHA-256, and the environment their helpers run in.

Each was checked before it was pinned (2026-10-17): the Real-ESRGAN build is byte for byte its author's release; the
ProPainter weights hold only tensors (their pickles name nothing but `OrderedDict`, `_rebuild_tensor_v2` and storages, and
PyTorch 2.14 loads them `weights_only`); the ONNX and safetensors models carry no custom code. A tool whose file is missing or
differs is refused, never fetched again on its own: ProPainter, left to itself, downloads a missing weight from its release
page and loads it, and a file swapped there would then run here.

Helpers run with Hugging Face offline and its telemetry off, so a library inside them never reaches the network.
"""
import hashlib
import os
from pathlib import Path

from nexora.core.adapter import AdapterError, ErrorCode

PINS = {
    "ProPainter.pth": "12c070c4b48f374c91d8a2a17851140b85c159621080989f9e191bbc18bd6591",
    "raft-things.pth": "fcfa4125d6418f4de95d84aec20a3c5f4e205101715a79f193243c186ac9a7e1",
    "recurrent_flow_completion.pth": "22939a1a7900da878dbe1ccd011d646b1bfb30b8290039d8ff0e0c2fefbfd283",
    "codeformer.onnx": "21710e7ab61c82683576c428e9c1b6fe1ed419586b7b39e394c3449c294b550f",
    "gopro_width64.safetensors": "53d808d8f74bac6817055b01361bf2a13f73506391a84940bac7238aa400387e",
    "realesrgan-ncnn-vulkan": "c1c35d92079085de96b9d547fd7e4464bc8a2e9ccf28d7b8c712d72ade91b7cc",
    "realesrgan-x4plus.bin": "713ee713b0353afaa27976f0563a64a5043bd70b9bd8936c2e26e25ebcdbcddf",
    "realesrgan-x4plus.param": "35330ececcea33b6c397a72548e788d5d53becee4734c50b7fada36e89f10a86",
    "realesrgan-x4plus-anime.bin": "fe01c269cfd10cdef8e018ab66ebe750cf79c7af4d1f9c16c737e1295229bacc",
    "realesrgan-x4plus-anime.param": "2b8fb6e0ae4d2d85704ca08c119a2f5ea40add4f2ecd512eb7f4cd44b6127ed4",
    "realesr-animevideov3-x4.bin": "548a36f9c3f4ab8da56cd3b13badf23968bee207b396dad14d04b830e5f2ab2d",
    "realesr-animevideov3-x4.param": "850a248e7c14c27e5bd8cf7265113a9441036a7db63963bb8aa5169d788a435e",
    # FilmCraft 0.8.0's web build (2026-10-17): the release's SHA256SUMS and GitHub's digest agree on its zip; the page names
    # no address it fetches by itself (help links and model downloads are on the operator's click only).
    "filmcraft_web_bg.wasm": "eb7882f9e8c17a5d28be4d287265a8f2029d4f1fe860eb3bcb3cf1664281399e",
    "filmcraft_web.js": "8892fadd3f0a25f414259781316e95b6bb788b587afb9dbb645c0fb3648f38ce",
    "audio-worklet.js": "e3d3272a30eafe34505e5676eb3543d7248870835a5569f314f388c89b807524",
}
FILMCRAFT_VERSION = "0.8.0"
FILMCRAFT_INDEX = "bd87b647b9a99a5dc19c843d809f088b161238a122854af2698a24ba03515799"

_checked: dict[str, tuple[int, int]] = {}


def verify(path: str | Path, *, fix: str) -> Path:
    """`path` if it is the file pinned under its name; otherwise refused, saying how to set it up again. Hashed once, and
    again only when its size or modification time changes."""
    path = Path(path)
    want = PINS.get(path.name)
    if want is None:
        raise AdapterError(ErrorCode.INVALID_REQUEST, f"{path.name} is not a pinned file", retryable=False)
    try:
        st = path.stat()
    except FileNotFoundError:
        raise AdapterError(ErrorCode.UNAVAILABLE, f"{path.name} is missing ({fix})", retryable=False) from None
    stamp = (st.st_size, st.st_mtime_ns)
    if _checked.get(str(path)) == stamp:
        return path
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    if digest.hexdigest() != want:
        raise AdapterError(ErrorCode.UNAVAILABLE, f"{path.name} is not the file that was checked (SHA-256 differs); it is not run ({fix})", retryable=False)
    _checked[str(path)] = stamp
    return path


def offline_env() -> dict[str, str]:
    """The environment a helper runs in: as this process's, with Hugging Face kept off the network."""
    return {**os.environ, "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
            "DO_NOT_TRACK": "1"}
