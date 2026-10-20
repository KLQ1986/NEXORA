"""Distribution: the publishing package of an approved render (design v4.0, section 21.1).

Everything a manual upload needs, exported to one folder: the video, a thumbnail, captions as a
sidecar file, a title and description, credits and the synthetic-content disclosure.
"""
import json
import shutil
from pathlib import Path

from nexora.core.adapter import AdapterRegistry, PrivacyClass, Request

TEXT_ONLY = PrivacyClass.CLOUD_ALLOWED       # a prompt of words alone: it may be served by a cloud model if the operator routes it there
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
TITLES_PROMPT = (
    "Đây là lời dẫn của một video ngắn:\n{script}\n\nViết {n} tiêu đề khác nhau cho video này bằng tiếng Việt. Mỗi tiêu đề dưới 60 ký tự, nói đúng nội dung, "
    "không giật gân, không hứa điều video không có. Mỗi tiêu đề kèm lý do riêng của nó: một câu vì sao người xem sẽ bấm.\n"
    'Chỉ trả về JSON: {{"tieu_de": [{{"ten": "...", "ly_do": "..."}}]}}'
)
GOOD_TITLE = (20, 60)        # characters: shorter says too little, longer is cut off in most lists
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


def otio(title: str, shots: list[dict], *, fps: int = 30) -> dict:
    """The cut as an OpenTimelineIO timeline (the .otio JSON form), which Resolve, Premiere and other editors open: one video
    track with a clip per shot pointing at the original footage and the range used, a gap where a line had no picture, and
    the line itself as the clip's name and a marker, so the script travels with the cut."""
    rate = float(fps)
    time = lambda seconds: {"OTIO_SCHEMA": "RationalTime.1", "rate": rate, "value": float(round(seconds * fps))}
    span = lambda start, duration: {"OTIO_SCHEMA": "TimeRange.1", "start_time": time(start), "duration": time(duration)}
    children = []
    for n, shot in enumerate(shots, 1):
        if not shot.get("path"):
            children.append({"OTIO_SCHEMA": "Gap.1", "name": f"{n:02d} {shot['text']}", "source_range": span(0, shot["duration"]), "effects": [], "markers": [], "metadata": {}})
            continue
        speed = float(shot.get("speed") or 1.0)
        children.append({"OTIO_SCHEMA": "Clip.2", "name": f"{n:02d} {shot['text']}", "source_range": span(shot.get("t_in") or 0.0, shot["duration"] * speed),
                         "effects": [] if speed == 1.0 else [{"OTIO_SCHEMA": "LinearTimeWarp.1", "name": "speed", "effect_name": "LinearTimeWarp", "time_scalar": speed, "metadata": {}}],
                         "markers": [{"OTIO_SCHEMA": "Marker.2", "name": shot["text"], "color": "PURPLE", "marked_range": span(shot.get("t_in") or 0.0, 0), "metadata": {}}],
                         "metadata": {"nexora": {k: shot.get(k) for k in ("asset_id", "sound_cue", "live_sound", "focus_x") if shot.get(k) is not None}},
                         "active_media_reference_key": "DEFAULT_MEDIA",
                         "media_references": {"DEFAULT_MEDIA": {"OTIO_SCHEMA": "ExternalReference.1", "name": Path(shot["path"]).name, "target_url": Path(shot["path"]).as_uri(),
                                                                "available_range": None, "available_image_bounds": None, "metadata": {}}}})
    track = {"OTIO_SCHEMA": "Track.1", "name": "Hình", "kind": "Video", "children": children, "source_range": None, "effects": [], "markers": [], "metadata": {}}
    return {"OTIO_SCHEMA": "Timeline.1", "name": title, "global_start_time": time(0), "metadata": {"nexora": {"fps": fps}},
            "tracks": {"OTIO_SCHEMA": "Stack.1", "name": "tracks", "children": [track], "source_range": None, "effects": [], "markers": [], "metadata": {}}}


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

    def export_otio(self, render_id: str) -> Path:
        render = self._projects.render(render_id)
        project = self._projects.project(render["project_id"])
        shots = [{**shot, "path": str(self._assets.path_of(self._assets.original(shot["asset_id"]))) if shot.get("asset_id") else None} for shot in render["qc"].get("shots", [])]
        folder = self._exports / render_id
        folder.mkdir(parents=True, exist_ok=True)
        out = folder / "cut.otio"
        out.write_text(json.dumps(otio(project["title"], shots), ensure_ascii=False, indent=2), encoding="utf-8")
        return out

    def lineage(self, render_id: str) -> dict:
        """Everything a cut was made from, traced back: the script version, and for each shot the footage, the stretch used, where
        that footage came from and how it was derived, and for generated pictures the prompt, seed and provider that made them."""
        render = self._projects.render(render_id)
        script = self._projects.script(render["script_id"])
        shots = []
        for n, (shot, cut) in enumerate(zip(script["shots"], render["qc"].get("shots", [])), 1):
            entry = {"line": n, "text": shot.text, "duration": cut["duration"], "source": None, "generated": None, "inserts": cut.get("inserts", []), "remote": cut.get("remote", [])}
            asset = self._assets.asset(cut.get("asset_id") or "")
            if asset:
                versions = self._assets.versions(asset["asset_id"])
                original = next(v for v in versions if v.role == "original")
                entry["source"] = {"asset_id": asset["asset_id"], "name": self._assets.path_of(original).name, "path": str(self._assets.path_of(original)), "origin": asset["origin"],
                                   "checksum": original.checksum, "t_in": cut.get("t_in"), "rights": original.metadata.get("rights"),
                                   "derived": [{"role": v.role, "from": v.parents, "made_by": v.created_by_attempt_id} for v in versions if v.role != "original"]}
            made = [g for g in self._projects.generations(shot.shot_id) if g["kind"] in ("keyframe", "clip")]
            if made:
                entry["generated"] = [{"kind": g["kind"], "prompt": g["prompt"], "seed": g["seed"], "provider": g["provider"], "model": g["model"], "compiler": g["compiler_version"], "quality": g["quality"]} for g in made]
            shots.append(entry)
        return {"render_id": render_id, "created_at": render["created_at"], "file": render["path"], "script": {"script_id": script["script_id"], "version": script["version"]},
                "review": render["review"], "external": bool(render["qc"].get("external")), "shots": shots}

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

    def suggest_titles(self, render_id: str, *, count: int = 5) -> list[dict]:
        """Title candidates from the model, each with what can be measured about it. A title that repeats words the video
        never says is marked, since a title must not promise what the video does not hold."""
        shots = self._projects.render(render_id)["qc"].get("shots") or []
        script = " ".join(s["text"] for s in shots)
        out = self._adapters.submit("model", Request("chat", privacy_class=TEXT_ONLY, params={"prompt": TITLES_PROMPT.format(script=script, n=count), "json": True, "max_tokens": 500, "task": "titles"})).outputs["json"]
        said = {w.strip(".,!?:;“”\"").lower() for w in script.split()}
        titles = []
        for raw in (out.get("tieu_de") or [])[:count]:
            name = str(raw.get("ten") if isinstance(raw, dict) else raw).strip()
            if not name or name in [t["title"] for t in titles]:
                continue
            words = [w.strip(".,!?:;“”\"").lower() for w in name.split() if len(w) > 3]
            outside = [w for w in words if w not in said]
            notes = []
            if not GOOD_TITLE[0] <= len(name) <= GOOD_TITLE[1]:
                notes.append("quá ngắn" if len(name) < GOOD_TITLE[0] else "quá dài, sẽ bị cắt")
            if words and len(outside) * 2 > len(words):
                notes.append("phần lớn từ không có trong lời dẫn")
            titles.append({"title": name, "why": str(raw.get("ly_do") or "").strip() if isinstance(raw, dict) else "", "chars": len(name), "notes": notes})
        return sorted(titles, key=lambda t: len(t["notes"]))

    def set_text(self, render_id: str, *, title: str | None = None, description: str | None = None) -> dict:
        package = self.package(render_id)
        if title and title.strip():
            package["title"] = title.strip()
        if description is not None and description.strip():
            package["description"] = description.strip()
        (self._exports / render_id / "package.json").write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
        return package

    def make_poster(self, render_id: str, base: str, text: str) -> dict:
        """A thumbnail candidate made from one of the frames with words on it."""
        package = self.package(render_id)
        if base not in package["thumbnails"] or not text.strip():
            raise ValueError("choose one of the package's thumbnails and give it words")
        folder = self._exports / render_id
        name = f"poster_{sum(1 for t in package['thumbnails'] if t.startswith('poster_')) + 1}.jpg"
        self._adapters.submit("graphics", Request("poster", inputs={"image": str(folder / base), "text": text.strip()}, params={"out": str(folder / name)}))
        package["thumbnails"] = package["thumbnails"] + [name]
        package["thumbnail"] = name
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
        out = self._adapters.submit("model", Request("chat", privacy_class=TEXT_ONLY, params={"prompt": TRANSLATE_PROMPT.format(language=LANGUAGES[language], lines=lines, n=len(shots)),
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
