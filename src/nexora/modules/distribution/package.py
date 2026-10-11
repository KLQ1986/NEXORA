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


class Distribution:
    def __init__(self, projects: ProjectStore, assets: AssetStore, adapters: AdapterRegistry, export_dir: str | Path):
        self._projects, self._assets, self._adapters, self._exports = projects, assets, adapters, Path(export_dir)

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
