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


def vtt(shots: list[dict]) -> str:
    out, t = ["WEBVTT", ""], 0.0
    for shot in shots:
        out.append(f"{_stamp(t).replace(',', '.')} --> {_stamp(t + shot['duration']).replace(',', '.')}\n{shot['text']}\n")
        t += shot["duration"]
    return "\n".join(out)


LANGUAGES = {"en": "tiếng Anh", "zh": "tiếng Trung", "ja": "tiếng Nhật", "ko": "tiếng Hàn", "fr": "tiếng Pháp", "es": "tiếng Tây Ban Nha", "th": "tiếng Thái", "vi": "tiếng Việt"}
TRANSLATE_PROMPT = (
    "Dịch các dòng phụ đề sau sang {language}. Giữ nguyên số dòng và thứ tự, mỗi dòng dịch gọn để đọc kịp trên màn hình, không thêm bớt ý.\n{lines}\n\n"
    "Chỉ trả về JSON với khoá dong: danh sách đúng {n} chuỗi, theo thứ tự."
)


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
        if shot.get("sound_cue"):
            lines.append(f"* SOUND: {shot['sound_cue']}")
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

    def annotate_package(self, render_id: str, **values) -> dict:
        """Add to a package's record what other parts of the system found about it: its rights report, its checks."""
        package = {**self.package(render_id), **values}
        (self._exports / render_id / "package.json").write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        return package

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
        (folder / "captions.vtt").write_text(vtt(shots), encoding="utf-8")
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
            "video": video.name, "captions": "captions.srt", "captions_vtt": "captions.vtt", "translations": (self.package(render_id) or {}).get("translations", {}), "thumbnails": thumbnails, "thumbnail": thumbnails[0],
            "duration": render["qc"]["duration"], "format": render["qc"].get("format", "landscape"),
            "synthetic_content": "generated" in origins,
            "credits": sorted(o for o in origins if o == "licensed"),
            "folder": str(folder),
        }
        (folder / "package.json").write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        return package

    def translate_captions(self, render_id: str, language: str) -> dict:
        """The captions in another language, as sidecar files with the same timing. A translation with a different number of
        lines cannot be timed, so it is refused rather than guessed at."""
        from nexora.core.adapter import AdapterError, ErrorCode
        package = self.package(render_id)
        if package is None or language not in LANGUAGES:
            raise ValueError("no package for this render, or a language that is not offered")
        shots = self._projects.render(render_id)["qc"].get("shots") or []
        if not shots:
            raise ValueError("this render has no captions to translate")
        lines = "\n".join(f"{i}. {s['text']}" for i, s in enumerate(shots, 1))
        out = self._adapters.submit("model", Request("chat", params={"prompt": TRANSLATE_PROMPT.format(language=LANGUAGES[language], lines=lines, n=len(shots)),
                                                                    "json": True, "max_tokens": 60 * len(shots) + 100, "task": "translate"})).outputs["json"]
        translated = [str(t).strip() for t in out.get("dong") or []]
        if len(translated) != len(shots) or not all(translated):
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "the translation does not have one line for every caption")
        folder, timed = self._exports / render_id, [{**s, "text": t} for s, t in zip(shots, translated)]
        (folder / f"captions.{language}.srt").write_text(srt(timed), encoding="utf-8")
        (folder / f"captions.{language}.vtt").write_text(vtt(timed), encoding="utf-8")
        package["translations"] = {**package.get("translations", {}), language: f"captions.{language}.srt"}
        (folder / "package.json").write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        return package

    def handoff(self, render_id: str) -> dict:
        """Everything another editor (CapCut, for one) needs to rebuild this cut by hand: each shot as a clean clip without
        captions, the narration of each line as its own sound file, the captions, the music, and a sheet saying what goes where."""
        render = self._projects.render(render_id)
        project = self._projects.project(render["project_id"])
        script = self._projects.script(render["script_id"])
        folder = self._exports / render_id / "handoff"
        folder.mkdir(parents=True, exist_ok=True)
        size = {"landscape": (1280, 720), "portrait": (720, 1280), "square": (720, 720)}.get(render["qc"].get("format"), (1280, 720))
        sheet, files = [f"# {project['title']}: gói bàn giao để dựng tay", "", "Đặt các clip theo thứ tự số. Mỗi clip đã dài đúng bằng lời dẫn của nó.", ""], []
        for n, (shot, cut) in enumerate(zip(script["shots"], render["qc"].get("shots", [])), 1):
            clip, sel = folder / f"{n:02d}.mp4", self._projects.selection(shot.shot_id)
            source = None
            if cut.get("asset_id"):
                path = self._assets.path_of(self._assets.original(cut["asset_id"]))
                source = str(path) if path.is_file() else None
            # The same cut without anything drawn on it; a line spoken on camera keeps its sound, the rest are silent picture.
            self._adapters.submit("ffmpeg", Request("segment", inputs={"path": source}, params={
                "out": str(clip), "t_in": cut.get("t_in") or 0.0, "duration": cut["duration"], "width": size[0], "height": size[1], "fps": 30,
                "fill": "fit" if render["qc"].get("format") == "landscape" else "cover", "focus_x": cut.get("focus_x") or 0.5, "speed": cut.get("speed") or 1.0,
                "live_sound": bool(cut.get("live_sound")), "audio": None, "overlay": None}))
            files.append(clip.name)
            sheet.append(f"{n:02d}.mp4  {cut['duration']:.1f} giây  “{shot.text}”" + ("  (không có hình, cần thay)" if not source else "") + (f"  Âm thanh: {shot.sound_cue}" if shot.sound_cue else ""))
        (folder / "captions.srt").write_text(srt(render["qc"].get("shots", [])), encoding="utf-8")
        files.append("captions.srt")
        if project.get("music_path") and Path(project["music_path"]).is_file():
            music = folder / ("music" + Path(project["music_path"]).suffix)
            shutil.copyfile(project["music_path"], music)
            files.append(music.name)
            sheet += ["", f"Nhạc nền: {music.name}, đặt dưới toàn bộ video và giảm khi có lời dẫn."]
        sheet += ["", "Lời dẫn: file video.mp4 trong gói xuất bản có sẵn lời dẫn đã trộn. Phụ đề: captions.srt, nhập vào phần mềm dựng.",
                  "Dựng xong, nhập bản hoàn thiện lại vào dự án ở mục Bản dựng."]
        (folder / "README.md").write_text("\n".join(sheet) + "\n", encoding="utf-8")
        return {"folder": str(folder), "files": files + ["README.md"]}

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
