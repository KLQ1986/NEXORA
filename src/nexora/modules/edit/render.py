"""Edit: turn approved selections into a finished video (design v4.0, sections 12 and 19).

Narration is made first because its length decides how long each clip must be. Each shot is rendered
as its own segment and cached, so changing one shot re-renders one segment.

A preview is the same cut made quickly to be judged, not published: half size, the fastest encoding, footage read from
the proxies, and no new narration recorded (lines already spoken are heard, the rest are silent at their estimated
length). It has no approval gate and is never packaged.
"""
import functools
import hashlib
import json
from pathlib import Path

from nexora.core.adapter import AdapterError, AdapterRegistry, Request
from nexora.core.assets import AssetStore
from nexora.core.orchestrator import Orchestrator
from nexora.core.pipeline import PipelineDefinition, PipelineRegistry, StageDef
from nexora.core.projects import ProjectStore

RENDER = PipelineDefinition("edit.render", "1", [
    StageDef("narration", requires=("voice",)),
    StageDef("segments", depends_on=("narration",), requires=("ffmpeg", "graphics")),
    StageDef("assemble", depends_on=("segments",), gate=True, requires=("ffmpeg", "ffprobe")),
])
FORMATS = {
    "landscape": {"width": 1280, "height": 720, "fps": 30},     # 16:9
    "portrait": {"width": 720, "height": 1280, "fps": 30},      # 9:16, for short-form
    "square": {"width": 720, "height": 720, "fps": 30},
}
FORMAT = FORMATS["landscape"]
# The same three steps without a voice requirement and without a gate: nothing here is a decision.
PREVIEW = PipelineDefinition("edit.preview", "1", [
    StageDef("narration"),
    StageDef("segments", depends_on=("narration",), requires=("ffmpeg", "graphics")),
    StageDef("assemble", depends_on=("segments",), requires=("ffmpeg", "ffprobe")),
])
SPEEDS = (0.5, 0.75, 1.0, 1.5, 2.0)
PAD_SECONDS = 0.4
WORDS_PER_SECOND = 2.6


# Asked for a number, the local model answers "50" for every picture. Asked to name the subject and choose one of
# three parts, it answers correctly (measured on pictures with a known answer), so the question is put that way.
FOCUS_PROMPT = (
    "Chia hình này thành ba phần theo chiều ngang: trái, giữa, phải. Trước hết nói ngắn gọn chủ thể chính là gì, rồi cho biết nó nằm chủ yếu ở phần nào. "
    "Chỉ trả về JSON với khoá chu_the (vài từ) và phan (một trong: trai, giua, phai)."
)
FOCUS_PARTS = {"trai": 0.2, "giua": 0.5, "phai": 0.8}
FOCUS_VERSION = "thirds-1"
MIN_BEFORE_INSERT, MIN_INSERT = 0.4, 0.8          # seconds: a cut closer than this to either end of a shot reads as a glitch


def spoken_by(text: str, bible: list[dict]) -> tuple[dict | None, str]:
    """A line written as "Name: words" is dialogue when the name is a character of the project. Returns the character and the words alone."""
    name, sep, words = text.partition(":")
    if sep and words.strip() and len(name) <= 30:
        who = next((e for e in bible if e.get("kind") == "character" and e["name"].strip().lower() == name.strip().lower()), None)
        if who:
            return who, words.strip()
    return None, text


def _key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]


class Edit:
    def __init__(self, orch: Orchestrator, projects: ProjectStore, assets: AssetStore, adapters: AdapterRegistry, media_dir: str | Path,
                 *, voice: bool = False, voice_name: str = "Linh", reviewer=None, model: bool = False, inspector=None):
        self._orch, self._projects, self._assets, self._adapters = orch, projects, assets, adapters
        self._media, self._voice, self._voice_name = Path(media_dir), voice, voice_name
        self._reviewer = reviewer                    # the whole-cut review of the Quality module, injected by the composition root
        self._inspector = inspector                  # the Quality module's measured checks on the finished file and its captions
        self._model = model                          # a vision model is available to find the subject when a frame must be cropped
        for sub in ("narration", "captions", "segments", "renders", "focus"):
            (self._media / sub).mkdir(parents=True, exist_ok=True)

    def register(self, registry: PipelineRegistry) -> None:
        registry.register(RENDER, {"narration": self._narration, "segments": self._segments, "assemble": self._assemble})
        registry.register(PREVIEW, {key: functools.partial(handler, preview=True) for key, handler in
                                    (("narration", self._narration), ("segments", self._segments), ("assemble", self._assemble))})

    def start_preview(self, script_id: str) -> str:
        """A quick look at the cut as it stands, gaps and all. Needs no approval of the clips, and starts over if asked again."""
        self._orch.supersede(PREVIEW.pipeline_id, script_id)
        return self._orch.submit_run(PREVIEW, subject_ref=script_id)

    def set_shot_options(self, shot_id: str, **options) -> None:
        """How one shot is treated in the cut: `speed`, `stabilise`, `live_sound` (keep the clip's own sound instead of narration),
        `sfx` (an audio asset played under the shot)."""
        clean = {}
        if "speed" in options:
            clean["speed"] = min(SPEEDS, key=lambda s: abs(s - float(options["speed"] or 1.0)))
        for flag in ("stabilise", "live_sound"):
            if flag in options:
                clean[flag] = bool(options[flag])
        if "sfx" in options:
            clean["sfx"] = options["sfx"] if options["sfx"] and self._assets.asset(str(options["sfx"])) else None
        if self._projects.selection(shot_id) is None:
            raise ValueError("this shot has no clip yet")
        self._projects.set_extras(shot_id, **clean)

    def start_render(self, script_id: str) -> str:
        script = self._projects.script(script_id)
        if not script["match_approved"]:
            raise ValueError("the selections of this script have not been approved yet")
        self._orch.supersede(RENDER.pipeline_id, script_id)
        return self._orch.submit_run(RENDER, subject_ref=script_id)

    def _narration(self, ctx, preview: bool = False):
        """One audio file per line; without a voice, the length is estimated and the line is silent."""
        lines = []
        script = self._projects.script(ctx.subject_ref)
        project = self._projects.project(script["project_id"])
        recorded = project.get("narration_dir")
        voice = project.get("voice") or self._orch.setting("voice", self._voice_name)      # the project's voice, else the installation's
        bible = json.loads(project.get("bible") or "[]")
        for shot in script["shots"]:
            sel = self._projects.selection(shot.shot_id)
            if sel and sel.status != "gap" and sel.extras.get("live_sound") and sel.t_out is not None:
                # The clip speaks for itself: its length on the timeline is the range chosen, at the speed chosen.
                lines.append({"shot_id": shot.shot_id, "audio": None, "live": True, "duration": round((sel.t_out - sel.t_in) / float(sel.extras.get("speed") or 1.0), 2)})
                continue
            # The operator's own recording for this line, if one exists, takes the place of the synthetic voice.
            own = next((p for ext in ("wav", "m4a", "mp3", "aiff") for p in [Path(recorded or "/nonexistent") / f"{shot.position + 1}.{ext}"] if p.is_file()), None)
            if own:
                duration = self._adapters.submit("ffprobe", Request("duration", inputs={"path": str(own)})).outputs["duration"]
                lines.append({"shot_id": shot.shot_id, "audio": str(own), "duration": round(float(duration), 2), "own_voice": True})
                continue
            if not self._voice:
                lines.append({"shot_id": shot.shot_id, "audio": None, "duration": round(max(2.0, len(shot.text.split()) / WORDS_PER_SECOND), 2)})
                continue
            who, spoken = spoken_by(shot.text, bible)
            line_voice = (who or {}).get("voice") or voice           # a character with a voice of its own speaks in it
            for written, said in (json.loads(project.get("profile") or "{}").get("pronounce") or {}).items():
                spoken = spoken.replace(written, said)             # the brand's pronunciation dictionary: written form, spoken form
            out = self._media / "narration" / f"{_key(spoken, line_voice)}.wav"
            if preview and not out.is_file():        # a preview records nothing new
                lines.append({"shot_id": shot.shot_id, "audio": None, "duration": round(max(2.0, len(shot.text.split()) / WORDS_PER_SECOND), 2)})
                continue
            if out.is_file():
                import wave
                with wave.open(str(out)) as w:
                    duration = w.getnframes() / w.getframerate()
            else:
                duration = self._adapters.submit("voice", Request("speak", inputs={"text": spoken}, params={"out": str(out), "voice": line_voice},
                                                                 attempt_id=ctx.claim.attempt_id)).outputs["duration"]
            lines.append({"shot_id": shot.shot_id, "audio": str(out), "duration": round(float(duration), 2)})
        return {"lines": lines}

    def import_finished(self, project_id: str, path: str | Path) -> str:
        """Bring back a cut finished in another editor as the project's newest render. It is measured like any render, and it
        counts as approved: the operator made it."""
        path = Path(path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(path)
        script = self._projects.current_script(project_id)
        project = self._projects.project(project_id)
        probe = self._adapters.submit("ffprobe", Request("probe", inputs={"path": str(path)})).outputs
        loud = self._adapters.submit("ffmpeg", Request("loudness", inputs={"path": str(path)})).outputs if probe.get("has_audio") else {"mean_db": -120.0, "max_db": -120.0}
        kept = self._media / "renders" / f"{script['script_id']}_external_{_key(str(path), path.stat().st_mtime)}{path.suffix.lower()}"
        import shutil
        shutil.copyfile(path, kept)                                   # the project keeps its own copy: the file outside may move
        wanted = FORMATS.get(project["format"], FORMATS["landscape"])
        checks = {"Có hình": bool(probe.get("width")), "Có âm thanh": bool(probe.get("has_audio")), "Âm thanh không bị vỡ": loud["max_db"] <= -0.5,
                  "Đúng tỷ lệ khung của dự án": abs(probe["width"] / probe["height"] - wanted["width"] / wanted["height"]) < 0.02 if probe.get("height") else False}
        qc = {"passed": all(checks.values()), "checks": checks, "width": probe.get("width"), "height": probe.get("height"), "duration": probe["duration"], "has_audio": probe.get("has_audio"),
              "shot_durations": [], "gaps": 0, "format": project["format"], "music": False, "draft": False, "external": True, "source_file": str(path),
              "mean_db": loud["mean_db"], "max_db": loud["max_db"], "findings": [], "shots": []}
        render_id = self._projects.add_render(project_id, script["script_id"], str(kept), qc)
        self._projects.set_render_review(render_id, approved=True, comment="Bản hoàn thiện ở phần mềm khác, do bạn nhập vào.")
        return render_id

    def _source(self, asset_id: str, t_in: float, need: float, *, proxy: bool = False, exact: bool = False) -> tuple[str, str, float]:
        """The file to cut from (the original when its volume is online, else the proxy) and a start that leaves room for `need` seconds.
        `proxy` asks for the small copy outright; `exact` keeps the start as given, for a range chosen to the word."""
        versions = {v.role: v for v in self._assets.versions(asset_id)}
        original = versions["original"]
        path = self._assets.path_of(original)
        if (proxy or not path.is_file()) and "proxy" in versions and self._assets.path_of(versions["proxy"]).is_file():
            path = self._assets.path_of(versions["proxy"])
        if original.metadata.get("probe", {}).get("still"):
            return str(path), original.checksum, 0.0
        enhanced = [v for v in self._assets.versions(asset_id) if v.role == "enhanced" and self._assets.path_of(v).is_file()]
        if enhanced and not proxy and self._assets.path_of(original).is_file():
            # The operator had a larger or smoother copy made: the final cut is taken from it. Its times are those of the original.
            path = self._assets.path_of(enhanced[-1])
            usable = original.metadata.get("usable_ranges") or [[0.0, original.metadata.get("probe", {}).get("duration", t_in + need)]]
            start, end = next(((a, b) for a, b in usable if a <= t_in < b), usable[0])
            return str(path), f"{original.checksum}:{enhanced[-1].version_id}", round(t_in if exact else max(start, min(t_in, end - need)), 2)
        usable = original.metadata.get("usable_ranges") or [[0.0, original.metadata.get("probe", {}).get("duration", t_in + need)]]
        if exact:
            return str(path), original.checksum, round(t_in, 2)
        start, end = next(((a, b) for a, b in usable if a <= t_in < b), usable[0])
        return str(path), original.checksum, round(max(start, min(t_in, end - need)), 2)

    def _focus(self, sel, path: str, checksum: str, t_in: float, duration: float) -> float:
        """Where to centre the crop when the output is narrower than the footage: the operator's word first, then the model's eye, then the middle."""
        own = sel.extras.get("focus") or {}
        if own.get("asset_id") == sel.asset_id:
            return float(own["x"])
        if not self._model:
            return 0.5
        cache = self._media / "focus" / f"{_key(FOCUS_VERSION, checksum, t_in, duration)}.json"
        if cache.is_file():
            return json.loads(cache.read_text())["x"]
        try:
            frame = path
            if Path(path).suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
                frame = str(cache.with_suffix(".jpg"))
                self._adapters.submit("ffmpeg", Request("thumbnail", inputs={"path": path}, params={"out": frame, "at": round(t_in + duration / 2, 2)}))
            out = self._adapters.submit("model", Request("describe", inputs={"images": [frame]}, params={"task": "focus", "prompt": FOCUS_PROMPT, "max_tokens": 80})).outputs["json"]
            x = FOCUS_PARTS.get(str(out.get("phan", "")).strip().lower(), 0.5)
        except (AdapterError, ValueError, TypeError):
            return 0.5                               # no answer is not a reason to fail a render
        cache.write_text(json.dumps({"x": x}))
        return x

    def _segments(self, ctx, preview: bool = False):
        script = self._projects.script(ctx.subject_ref)
        project = self._projects.project(script["project_id"])
        FORMAT = FORMATS.get(project["format"], FORMATS["landscape"])
        if preview:
            FORMAT = {"width": FORMAT["width"] // 2, "height": FORMAT["height"] // 2, "fps": 15}
        options = json.loads(project.get("options") or "{}")
        bible = json.loads(project.get("bible") or "[]")
        fill = "fit" if project["format"] == "landscape" else "cover"
        profile = json.loads(project.get("profile") or "{}")
        look = {"scale": float(profile.get("caption_scale") or 1.0), "position": profile.get("caption_position") or "bottom", "colour": profile.get("caption_colour"),
                "typeface": profile.get("typeface") or "sans", "logo": profile.get("logo_path")}
        durations = {l["shot_id"]: l for l in ctx.inputs["narration"]["lines"]}
        out, draft = [], False
        for shot in script["shots"]:
            line, sel = durations[shot.shot_id], self._projects.selection(shot.shot_id)
            live = bool(line.get("live"))
            duration = line["duration"] if live else round(max(line["duration"] + PAD_SECONDS, shot.target_seconds or 0.0), 2)      # never shorter than the narration, longer if the script asks
            extras = sel.extras if sel else {}
            speed = float(extras.get("speed") or 1.0)
            sfx = None
            if extras.get("sfx") and self._assets.asset(extras["sfx"]):
                sfx_path = self._assets.path_of(self._assets.original(extras["sfx"]))
                sfx = str(sfx_path) if sfx_path.is_file() else None
            treat = {"speed": speed, "stabilise": bool(extras.get("stabilise")), "normalise": bool(options.get("match_colour")), "live_sound": live,
                     "clean_audio": bool(options.get("clean_audio")), "own_voice": bool(line.get("own_voice")) or live, "sfx": sfx, "quality": "preview" if preview else "final"}
            words = shot.screen_text or spoken_by(shot.text, bible)[1]       # a caption shows what is said, not who says it
            caption = self._media / "captions" / f"{_key(words, FORMAT, look)}.png"
            if not caption.is_file():
                self._adapters.submit("graphics", Request("caption", inputs={"text": words}, params={"out": str(caption), **FORMAT, **look}))
            has_picture = sel is not None and sel.status != "gap" and sel.asset_id
            inserts, focus = [], 0.5
            if has_picture:
                path, checksum, t_in = self._source(sel.asset_id, sel.t_in, duration * speed, proxy=preview, exact=live)
                source_original = self._assets.original(sel.asset_id)
                draft = draft or not self._assets.path_of(source_original).is_file()      # cut from the proxy: good to judge, not to publish
                # Only the camera file can still be HDR: the proxy and an enhanced copy were brought to SDR when they were made.
                treat["color_transfer"] = source_original.metadata.get("probe", {}).get("color_transfer") if path == str(self._assets.path_of(source_original)) else None
                focus = self._focus(sel, path, checksum, t_in, duration) if fill == "cover" else 0.5
                for ins in sel.extras.get("inserts", []):
                    at = round(ins["at"] * line["duration"], 2)
                    if at < MIN_BEFORE_INSERT or duration - at < MIN_INSERT:
                        continue
                    ipath, isum, iin = self._source(ins["asset_id"], ins["t_in"], duration - at, proxy=preview)
                    inserts.append({"path": ipath, "t_in": iin, "at": at, "checksum": isum, "keyword": ins["keyword"]})
                key = _key(checksum, t_in, duration, words, look, line["audio"], FORMAT, fill, focus, [(i["checksum"], i["t_in"], i["at"]) for i in inserts], treat)
            else:
                path, t_in, key = None, 0.0, _key("gap", duration, words, look, line["audio"], FORMAT, treat)
            segment = self._media / "segments" / f"{key}.mp4"
            if not segment.is_file():                                   # unchanged shots are reused, not rendered again
                self._adapters.submit("ffmpeg", Request("segment", inputs={"path": path}, attempt_id=ctx.claim.attempt_id,
                                                       params={"out": str(segment), "t_in": t_in, "duration": duration, "overlay": str(caption),
                                                               "audio": line["audio"], "fill": fill, "focus_x": focus, "inserts": inserts, **FORMAT, **treat}))
            out.append({"shot_id": shot.shot_id, "file": str(segment), "duration": duration, "gap": not has_picture, "text": shot.text,
                        "asset_id": sel.asset_id if has_picture else None, "t_in": t_in, "chosen_in": sel.t_in if has_picture else None,
                        "is_fact": shot.is_fact, "source": shot.source, "fact_check": shot.fact_check, "sound_cue": shot.sound_cue,
                        "own_voice": bool(line.get("own_voice")), "live_sound": live, "speed": speed, "focus_x": focus if fill == "cover" else None,
                        "inserts": [{"keyword": i["keyword"], "at": i["at"]} for i in inserts]})
            ctx.heartbeat()
        return {"segments": out, "draft": draft}

    def _assemble(self, ctx, preview: bool = False):
        script = self._projects.script(ctx.subject_ref)
        project = self._projects.project(script["project_id"])
        FORMAT = FORMATS.get(project["format"], FORMATS["landscape"])
        if preview:
            FORMAT = {"width": FORMAT["width"] // 2, "height": FORMAT["height"] // 2, "fps": 15}
        music = project["music_path"] if project["music_path"] and Path(project["music_path"]).is_file() else None
        segments = ctx.inputs["segments"]["segments"]
        out = self._media / "renders" / f"{ctx.subject_ref}_{ctx.claim.attempt_id}.mp4"
        self._adapters.submit("ffmpeg", Request("concat", inputs={"paths": [s["file"] for s in segments]}, params={"out": str(out), "music": music, "music_gain": project.get("music_gain") or 0.35},
                                               attempt_id=ctx.claim.attempt_id))
        probe = self._adapters.submit("ffprobe", Request("probe", inputs={"path": str(out)})).outputs
        expected = sum(s["duration"] for s in segments)
        loud = self._adapters.submit("ffmpeg", Request("loudness", inputs={"path": str(out)})).outputs
        checks = {
            "Có hình và đúng kích thước": (probe["width"], probe["height"]) == (FORMAT["width"], FORMAT["height"]),
            "Có âm thanh": bool(probe["has_audio"]),
            "Độ dài khớp với kịch bản": abs(probe["duration"] - expected) < 1.0,
            "Âm thanh không bị vỡ": loud["max_db"] <= -0.5,
        }
        findings = self._reviewer(segments) if self._reviewer else []
        if self._inspector and not preview:
            black = self._adapters.submit("ffmpeg", Request("blackdetect", inputs={"path": str(out)})).outputs["black_ranges"]
            silent = [[a, probe["duration"] if b is None else b] for a, b in self._adapters.submit("ffmpeg", Request("silencedetect", inputs={"path": str(out)})).outputs["silent_ranges"]]
            gap_ranges, at = [], 0.0
            for s in segments:
                if s["gap"]:
                    gap_ranges.append([at, at + s["duration"]])
                at += s["duration"]
            measured = self._inspector["file"](black, silent, probe["duration"], gap_ranges=gap_ranges)
            checks.update(measured["checks"])
            findings = findings + self._inspector["captions"]([{"text": s["text"], "duration": s["duration"]} for s in segments])
        qc = {"passed": all(checks.values()), "checks": checks, "width": probe["width"], "height": probe["height"], "duration": probe["duration"],
              "has_audio": probe["has_audio"], "shot_durations": [s["duration"] for s in segments], "gaps": sum(1 for s in segments if s["gap"]),
              "format": project["format"], "music": bool(music), "draft": bool(ctx.inputs["segments"].get("draft")) and not preview, "preview": preview, "mean_db": loud["mean_db"], "max_db": loud["max_db"],
              "findings": findings,
              "shots": [{"text": s["text"], "duration": s["duration"], "gap": s["gap"], "asset_id": s.get("asset_id"), "t_in": s.get("chosen_in"),
                         "is_fact": s.get("is_fact", False), "source": s.get("source"), "fact_check": s.get("fact_check"), "sound_cue": s.get("sound_cue"), "own_voice": s.get("own_voice", False), "live_sound": s.get("live_sound", False), "speed": s.get("speed", 1.0), "focus_x": s.get("focus_x"), "inserts": s.get("inserts", [])} for s in segments]}
        render_id = self._projects.add_render(script["project_id"], ctx.subject_ref, str(out), qc)
        return {"render_id": render_id, "qc_passed": qc["passed"]}
