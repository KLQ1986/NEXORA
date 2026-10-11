"""Distribution: the publishing package of an approved render (design v4.0, section 21.1).

Everything a manual upload needs, exported to one folder: the video, a thumbnail, captions as a
sidecar file, a title and description, credits and the synthetic-content disclosure.
"""
import json
import shutil
from pathlib import Path

from nexora.core.adapter import AdapterRegistry, Request
from nexora.core.assets import AssetStore
from nexora.core.projects import ProjectStore


def _stamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def srt(shots: list[dict]) -> str:
    out, t = [], 0.0
    for i, shot in enumerate(shots, 1):
        out.append(f"{i}\n{_stamp(t)} --> {_stamp(t + shot['duration'])}\n{shot['text']}\n")
        t += shot["duration"]
    return "\n".join(out)


def _tc(seconds: float, fps: int) -> str:
    frames = int(round(seconds * fps))
    return f"{frames // (3600 * fps):02d}:{frames // (60 * fps) % 60:02d}:{frames // fps % 60:02d}:{frames % fps:02d}"


def edl(title: str, shots: list[dict], *, fps: int = 30) -> str:
    """The cut as a CMX 3600 edit decision list, which DaVinci Resolve and other editors import: one event per shot, pointing at
    the original footage and the range used, so that finishing starts from the camera files and not from NEXORA's render."""
    lines, at = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""], 0.0
    for n, shot in enumerate(shots, 1):
        d = shot["duration"]
        if shot.get("path"):
            src = shot.get("t_in") or 0.0
            lines.append(f"{n:03d}  AX       V     C        {_tc(src, fps)} {_tc(src + d, fps)} {_tc(at, fps)} {_tc(at + d, fps)}")
            lines.append(f"* FROM CLIP NAME: {Path(shot['path']).name}")
            lines.append(f"* SOURCE FILE: {shot['path']}")
        else:
            lines.append(f"{n:03d}  BL       V     C        {_tc(0, fps)} {_tc(d, fps)} {_tc(at, fps)} {_tc(at + d, fps)}")
        lines.append(f"* COMMENT: {shot['text']}")
        at += d
    return "\n".join(lines) + "\n"


class Distribution:
    def __init__(self, projects: ProjectStore, assets: AssetStore, adapters: AdapterRegistry, export_dir: str | Path):
        self._projects, self._assets, self._adapters, self._exports = projects, assets, adapters, Path(export_dir)

    def export_edl(self, render_id: str) -> Path:
        render = self._projects.render(render_id)
        project = self._projects.project(render["project_id"])
        shots = []
        for shot in render["qc"].get("shots", []):
            path = str(self._assets.path_of(self._assets.original(shot["asset_id"]))) if shot.get("asset_id") else None
            shots.append({**shot, "path": path})
        folder = self._exports / render_id
        folder.mkdir(parents=True, exist_ok=True)
        out = folder / "cut.edl"
        out.write_text(edl(project["title"], shots), encoding="utf-8")
        return out

    def build_package(self, render_id: str, *, title: str | None = None, description: str | None = None) -> dict:
        render = self._projects.render(render_id)
        project = self._projects.project(render["project_id"])
        script = self._projects.script(render["script_id"])
        folder = self._exports / render_id
        folder.mkdir(parents=True, exist_ok=True)
        video = folder / "video.mp4"
        shutil.copyfile(render["path"], video)
        shots = render["qc"].get("shots") or [{"text": s.text, "duration": d} for s, d in zip(script["shots"], render["qc"]["shot_durations"])]
        (folder / "captions.srt").write_text(srt(shots), encoding="utf-8")
        thumbnails = []
        for i, share in enumerate((0.12, 0.45, 0.78), 1):                 # three candidates; the operator picks one
            out = folder / f"thumbnail_{i}.jpg"
            self._adapters.submit("ffmpeg", Request("thumbnail", inputs={"path": str(video)}, params={"out": str(out), "at": round(render["qc"]["duration"] * share, 2)}))
            thumbnails.append(out.name)
        origins = set()
        for sel in self._projects.selections(render["script_id"]):
            if sel.asset_id:
                origins.add(next(a["origin"] for a in self._assets.assets() if a["asset_id"] == sel.asset_id))
        package = {
            "render_id": render_id,
            "title": (title or project["title"]).strip(),
            "description": (description or " ".join(s["text"] for s in shots)).strip(),
            "video": video.name, "captions": "captions.srt", "thumbnails": thumbnails, "thumbnail": thumbnails[0],
            "duration": render["qc"]["duration"], "format": render["qc"].get("format", "landscape"),
            "synthetic_content": "generated" in origins,
            "credits": sorted(o for o in origins if o == "licensed"),
            "folder": str(folder),
        }
        (folder / "package.json").write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        return package

    def package(self, render_id: str) -> dict | None:
        path = self._exports / render_id / "package.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def choose_thumbnail(self, render_id: str, name: str) -> dict:
        package = self.package(render_id)
        if name not in package["thumbnails"]:
            raise ValueError("not a thumbnail of this package")
        package["thumbnail"] = name
        (self._exports / render_id / "package.json").write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        return package
