"""Colour transforms by OpenColorIO, baked into 3D LUTs (design 2026-10-16, Visual Quality §3.1).

Every camera encoding Visual Quality can read is turned into the same thing, a `.cube` LUT, so that a cut, an extract and a
preview apply it alike, with FFmpeg's `lut3d`. Encodings OCIO knows (Apple Log, ARRI LogC, Canon Log, Panasonic V-Log, RED,
Sony S-Log3, BMD Film, DJI's older D-Log, HLG and PQ) are baked from its built-in studio config, to Rec.709 through the
ACES SDR view; a maker's own LUT (DJI D-Log M) is used as it is and does not come here.

Baked LUTs are kept by what they were baked from, so each is made once.
"""
import hashlib
from pathlib import Path

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result

CONFIG = "studio-config-latest"
DISPLAY, VIEW = "Rec.1886 Rec.709 - Display", "ACES 2.0 - SDR 100 nits (Rec.709)"


class ColorTransforms(Adapter):
    def __init__(self, lut_dir: str | Path):
        self._dir = Path(lut_dir)

    def describe(self) -> Capability:
        return Capability(name="color", operations=("bake", "colorspaces", "fetch"), runs="local")

    def available(self) -> bool:
        try:
            import PyOpenColorIO  # noqa: F401
            return True
        except ImportError:
            return False

    def environment(self) -> dict:
        if not self.available():
            return {"available": False}
        import PyOpenColorIO as OCIO
        return {"available": True, "ocio": OCIO.__version__, "config": CONFIG}

    def _config(self):
        import PyOpenColorIO as OCIO
        return OCIO.Config.CreateFromBuiltinConfig(CONFIG)

    def submit(self, request: Request) -> Result:
        if request.operation == "fetch":
            return self._fetch(request.params["url"], request.params["name"])
        if not self.available():
            raise AdapterError(ErrorCode.UNAVAILABLE, "OpenColorIO is not installed", retryable=False)
        import PyOpenColorIO as OCIO
        cfg = self._config()
        if request.operation == "colorspaces":
            return Result(outputs={"colorspaces": [cs.getName() for cs in cfg.getColorSpaces()], "displays": list(cfg.getDisplays())})
        if request.operation != "bake":
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"unknown operation {request.operation}")
        source = request.params["source"]
        display, view = request.params.get("display", DISPLAY), request.params.get("view", VIEW)
        size = int(request.params.get("size", 33))
        if source not in [cs.getName() for cs in cfg.getColorSpaces()]:
            raise AdapterError(ErrorCode.INVALID_REQUEST, f"OpenColorIO does not know the colour space {source!r}")
        key = hashlib.sha1(f"{OCIO.__version__}|{CONFIG}|{source}|{display}|{view}|{size}".encode()).hexdigest()[:12]
        out = self._dir / "ocio" / f"{source.replace(' ', '_').replace('/', '_')}__{key}.cube"
        if not out.is_file():
            out.parent.mkdir(parents=True, exist_ok=True)
            baker = OCIO.Baker()
            baker.setConfig(cfg)
            baker.setFormat("resolve_cube")
            baker.setInputSpace(source)
            baker.setDisplayView(display, view)
            baker.setCubeSize(size)
            partial = out.with_suffix(".partial")
            baker.bake(str(partial))
            partial.replace(out)
        return Result(outputs={"lut": str(out), "source": source, "display": display, "view": view, "size": size})

    def _fetch(self, url: str, name: str) -> Result:
        """A maker's LUT, downloaded once into the LUT folder (DJI publishes one per camera)."""
        import urllib.request
        out = self._dir / name
        if not out.is_file():
            out.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 NEXORA"})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = r.read()
            except OSError as err:
                raise AdapterError(ErrorCode.UNAVAILABLE, f"cannot fetch the LUT: {err}", retryable=True) from None
            if b"LUT_3D_SIZE" not in data[:4096]:
                raise AdapterError(ErrorCode.OUTPUT_INVALID, "what was fetched is not a 3D LUT", retryable=False)
            partial = out.with_suffix(".partial")
            partial.write_bytes(data)
            partial.replace(out)
        return Result(outputs={"lut": str(out)})
