"""Pieces of a recording taken out to be used elsewhere (design 2026-10-15, section 9 F): a clip, its best still and its sound,
each beside a card of what is known about it, so that an editor or another project picks it up without analysing it again.

Taken from the original, at its size and depth. A stretch is cut as asked; "the usable beats" are the beats whose picture was
measured good (`core.usability`). What a piece shows, its grades and where it came from are read from the canonical model.
Each request is bounded (`MAX_SECONDS` of footage) so that it is done while the operator waits.
"""
import json
import re
import time
from pathlib import Path

from nexora.core.adapter import AdapterRegistry, Request
from nexora.core.assets import AssetStore
from nexora.core.intelligence import VideoIntelligence
from nexora.core.usability import picture_grade, sound_grade

KINDS = ("clip", "still", "audio")
MAX_SECONDS = 120.0
SUFFIX = {"clip": ".mp4", "still": ".jpg", "audio": ".wav"}


def _slug(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]+", "-", text).strip("-")[:60] or "doan"


class Extractor:
    def __init__(self, assets: AssetStore, adapters: AdapterRegistry, vi: VideoIntelligence, out_dir: str | Path, *, vq=None):
        self._assets, self._adapters, self._vi, self._out = assets, adapters, vi, Path(out_dir)
        self._vq = vq                                 # Visual Quality's reader: a piece is taken out with its approved recipe

    def card(self, asset_id: str, t_in: float, t_out: float) -> dict:
        """What is known about a stretch, from the canonical model: what it shows, how it was graded, where it comes from."""
        values = self._vi.values(asset_id, (t_in, t_out))
        v = lambda f: values[f].value if f in values else None
        picture, picture_why = picture_grade(values)
        sound, sound_why = sound_grade(values)
        original = self._assets.original(asset_id)
        tech = (self._vi.recording(asset_id) or {}).get("technical") or {}
        return {"source": {"asset_id": asset_id, "file": Path(original.relative_path).name, "checksum": original.checksum, "t_in": t_in, "t_out": t_out},
                "description": v("description") or "", "things": v("things") or [], "place": v("place"), "shot_size": v("shot_size"),
                "camera": v("camera"), "people": v("people"), "picture": {"grade": picture, "why": picture_why}, "sound": {"grade": sound, "why": sound_why},
                "format": {k: tech.get(k) for k in ("display_width", "display_height", "frame_rate", "codec", "bit_depth", "color_transfer", "hdr")},
                "log": bool((((self._vi.recording(asset_id) or {}).get("summary") or {}).get("profile") or {}).get("log_profile")),
                "made_at": round(time.time())}

    def extract(self, asset_id: str, t_in: float, t_out: float, *, kinds=KINDS, name: str | None = None) -> dict:
        """Take one stretch out: the pieces asked for, and the card beside them."""
        original = self._assets.original(asset_id)
        path = self._assets.path_of(original)
        if not path.is_file():
            raise FileNotFoundError("the original is not at hand")
        probe = original.metadata.get("probe", {})
        duration = float(probe.get("duration") or 0.0)
        t_in, t_out = max(0.0, float(t_in)), min(float(t_out), duration) if duration else float(t_out)
        if t_out - t_in < 0.1 or t_out - t_in > MAX_SECONDS:
            raise ValueError("bad_span")
        label = name or f"{Path(original.relative_path).stem}_{int(round(t_in * 10)):05d}-{int(round(t_out * 10)):05d}"      # tenths of a second
        folder = self._out / asset_id / _slug(label)
        folder.mkdir(parents=True, exist_ok=True)
        card = self.card(asset_id, t_in, t_out)
        source, offset, vq_filters = path, 0.0, []
        if self._vq is not None:
            found = self._vq.filters_for(asset_id, t_in, t_out)
            recipe = self._vq.recipe(asset_id, status="approved")
            if found is None:
                prepared = self._vq.prepared_for(asset_id, t_in, t_out)
                if prepared is not None:
                    source, offset = Path(prepared[0]), prepared[1] - t_in
            else:
                vq_filters = found
            if recipe is not None and (vq_filters or source != path):
                card["visual_quality"] = {"recipe_id": recipe.recipe_id, "version": recipe.version, "colour": recipe.data.get("output", {}).get("colour")}
        files = {}
        for kind in kinds:
            if kind not in KINDS or (kind == "audio" and not probe.get("has_audio")):
                continue
            out = folder / f"{kind}{SUFFIX[kind]}"
            colour = (card.get("visual_quality") or {}).get("colour") or {k: probe.get(k) for k in ("color_transfer", "color_primaries", "color_space")}
            params = {"kind": kind, "out": str(out), "t_in": t_in + offset, "t_out": t_out + offset, "bit_depth": probe.get("bit_depth"),
                      "color_range": probe.get("color_range"), **colour, "filters": vq_filters}
            if kind == "still":
                best = self._vi.value(asset_id, (t_in, t_out), "best_frame")
                at = best.value if best is not None and t_in <= float(best.value) < t_out else (t_in + t_out) / 2
                params["at"] = at
                card["still_at"] = at
            if kind == "still":
                params["at"] = params["at"] + offset
            self._adapters.submit("ffmpeg", Request("extract", inputs={"path": str(source)}, params=params))
            files[kind] = str(out)
        card["files"] = {k: Path(p).name for k, p in files.items()}
        (folder / "card.json").write_text(json.dumps(card, ensure_ascii=False, indent=2))
        return {"folder": str(folder), "name": folder.name, "files": files, "card": card}

    def extract_usable(self, asset_id: str, *, kinds=KINDS) -> list[dict]:
        """Every beat whose picture was measured good, taken out one by one, up to `MAX_SECONDS` in all."""
        made, spent = [], 0.0
        for beat in self._vi.segments(asset_id, "beat"):
            if picture_grade(self._vi.values(asset_id, (beat.t_start, beat.t_end)))[0] != "dùng được":
                continue
            if spent + (beat.t_end - beat.t_start) > MAX_SECONDS:
                break
            made.append(self.extract(asset_id, beat.t_start, beat.t_end, kinds=kinds))
            spent += beat.t_end - beat.t_start
        return made

    def taken(self, asset_id: str) -> list[dict]:
        """What has been taken out of a recording, newest first."""
        root = self._out / asset_id
        if not root.is_dir():
            return []
        out = []
        for card in sorted(root.glob("*/card.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            data = json.loads(card.read_text())
            out.append({"name": card.parent.name, "card": data, "files": data.get("files", {})})
        return out
