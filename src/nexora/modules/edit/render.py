"""Edit: turn approved selections into a finished video (design v4.0, sections 12 and 19).

Narration is made first because its length decides how long each clip must be. Each shot is rendered
as its own segment and cached, so changing one shot re-renders one segment.
"""
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


def _key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]


class Edit:
    def __init__(self, orch: Orchestrator, projects: ProjectStore, assets: AssetStore, adapters: AdapterRegistry, media_dir: str | Path,
                 *, voice: bool = False, voice_name: str = "Linh", reviewer=None, model: bool = False):
        self._orch, self._projects, self._assets, self._adapters = orch, projects, assets, adapters
        self._media, self._voice, self._voice_name = Path(media_dir), voice, voice_name
        self._reviewer = reviewer                    # the whole-cut review of the Quality module, injected by the composition root
        self._model = model                          # a vision model is available to find the subject when a frame must be cropped
        for sub in ("narration", "captions", "segments", "renders", "focus"):
            (self._media / sub).mkdir(parents=True, exist_ok=True)

    def register(self, registry: PipelineRegistry) -> None:
        registry.register(RENDER, {"narration": self._narration, "segments": self._segments, "assemble": self._assemble})

    def start_render(self, script_id: str) -> str:
        script = self._projects.script(script_id)
        if not script["match_approved"]:
            raise ValueError("the selections of this script have not been approved yet")
        self._orch.supersede(RENDER.pipeline_id, script_id)
        return self._orch.submit_run(RENDER, subject_ref=script_id)

    def _narration(self, ctx):
        """One audio file per line; without a voice, the length is estimated and the line is silent."""
        lines = []
        script = self._projects.script(ctx.subject_ref)
        project = self._projects.project(script["project_id"])
        recorded = project.get("narration_dir")
        voice = project.get("voice") or self._orch.setting("voice", self._voice_name)      # the project's voice, else the installation's
        for shot in script["shots"]:
            # The operator's own recording for this line, if one exists, takes the place of the synthetic voice.
            own = next((p for ext in ("wav", "m4a", "mp3", "aiff") for p in [Path(recorded or "/nonexistent") / f"{shot.position + 1}.{ext}"] if p.is_file()), None)
            if own:
                duration = self._adapters.submit("ffprobe", Request("duration", inputs={"path": str(own)})).outputs["duration"]
                lines.append({"shot_id": shot.shot_id, "audio": str(own), "duration": round(float(duration), 2), "own_voice": True})
                continue
            if not self._voice:
                lines.append({"shot_id": shot.shot_id, "audio": None, "duration": round(max(2.0, len(shot.text.split()) / WORDS_PER_SECOND), 2)})
                continue
            spoken = shot.text
            for written, said in (json.loads(project.get("profile") or "{}").get("pronounce") or {}).items():
                spoken = spoken.replace(written, said)             # the brand's pronunciation dictionary: written form, spoken form
            out = self._media / "narration" / f"{_key(spoken, voice)}.wav"
            if out.is_file():
                import wave
                with wave.open(str(out)) as w:
                    duration = w.getnframes() / w.getframerate()
            else:
                duration = self._adapters.submit("voice", Request("speak", inputs={"text": spoken}, params={"out": str(out), "voice": voice},
                                                                 attempt_id=ctx.claim.attempt_id)).outputs["duration"]
            lines.append({"shot_id": shot.shot_id, "audio": str(out), "duration": round(float(duration), 2)})
        return {"lines": lines}

    def _source(self, asset_id: str, t_in: float, need: float) -> tuple[str, str, float]:
        """The file to cut from (the original when its volume is online, else the proxy) and a start that leaves room for `need` seconds."""
        versions = {v.role: v for v in self._assets.versions(asset_id)}
        original = versions["original"]
        path = self._assets.path_of(original)
        if not path.is_file() and "proxy" in versions:
            path = self._assets.path_of(versions["proxy"])
        if original.metadata.get("probe", {}).get("still"):
            return str(path), original.checksum, 0.0
        usable = original.metadata.get("usable_ranges") or [[0.0, original.metadata.get("probe", {}).get("duration", t_in + need)]]
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

    def _segments(self, ctx):
        script = self._projects.script(ctx.subject_ref)
        project = self._projects.project(script["project_id"])
        FORMAT = FORMATS.get(project["format"], FORMATS["landscape"])
        fill = "fit" if project["format"] == "landscape" else "cover"
        profile = json.loads(project.get("profile") or "{}")
        look = {"scale": float(profile.get("caption_scale") or 1.0), "position": profile.get("caption_position") or "bottom", "colour": profile.get("caption_colour"),
                "typeface": profile.get("typeface") or "sans", "logo": profile.get("logo_path")}
        durations = {l["shot_id"]: l for l in ctx.inputs["narration"]["lines"]}
        out, draft = [], False
        for shot in script["shots"]:
            line, sel = durations[shot.shot_id], self._projects.selection(shot.shot_id)
            duration = round(max(line["duration"] + PAD_SECONDS, shot.target_seconds or 0.0), 2)      # never shorter than the narration, longer if the script asks
            words = shot.screen_text or shot.text
            caption = self._media / "captions" / f"{_key(words, FORMAT, look)}.png"
            if not caption.is_file():
                self._adapters.submit("graphics", Request("caption", inputs={"text": words}, params={"out": str(caption), **FORMAT, **look}))
            has_picture = sel is not None and sel.status != "gap" and sel.asset_id
            inserts, focus = [], 0.5
            if has_picture:
                path, checksum, t_in = self._source(sel.asset_id, sel.t_in, duration)
                draft = draft or not self._assets.path_of(self._assets.original(sel.asset_id)).is_file()      # cut from the proxy: good to judge, not to publish
                focus = self._focus(sel, path, checksum, t_in, duration) if fill == "cover" else 0.5
                for ins in sel.extras.get("inserts", []):
                    at = round(ins["at"] * line["duration"], 2)
                    if at < MIN_BEFORE_INSERT or duration - at < MIN_INSERT:
                        continue
                    ipath, isum, iin = self._source(ins["asset_id"], ins["t_in"], duration - at)
                    inserts.append({"path": ipath, "t_in": iin, "at": at, "checksum": isum, "keyword": ins["keyword"]})
                key = _key(checksum, t_in, duration, words, look, line["audio"], FORMAT, fill, focus, [(i["checksum"], i["t_in"], i["at"]) for i in inserts])
            else:
                path, t_in, key = None, 0.0, _key("gap", duration, words, look, line["audio"], FORMAT)
            segment = self._media / "segments" / f"{key}.mp4"
            if not segment.is_file():                                   # unchanged shots are reused, not rendered again
                self._adapters.submit("ffmpeg", Request("segment", inputs={"path": path}, attempt_id=ctx.claim.attempt_id,
                                                       params={"out": str(segment), "t_in": t_in, "duration": duration, "overlay": str(caption),
                                                               "audio": line["audio"], "fill": fill, "focus_x": focus, "inserts": inserts, **FORMAT}))
            out.append({"shot_id": shot.shot_id, "file": str(segment), "duration": duration, "gap": not has_picture, "text": shot.text,
                        "asset_id": sel.asset_id if has_picture else None, "t_in": t_in, "chosen_in": sel.t_in if has_picture else None,
                        "is_fact": shot.is_fact, "source": shot.source, "fact_check": shot.fact_check, "sound_cue": shot.sound_cue,
                        "own_voice": bool(line.get("own_voice")), "focus_x": focus if fill == "cover" else None,
                        "inserts": [{"keyword": i["keyword"], "at": i["at"]} for i in inserts]})
            ctx.heartbeat()
        return {"segments": out, "draft": draft}

    def _assemble(self, ctx):
        script = self._projects.script(ctx.subject_ref)
        project = self._projects.project(script["project_id"])
        FORMAT = FORMATS.get(project["format"], FORMATS["landscape"])
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
        qc = {"passed": all(checks.values()), "checks": checks, "width": probe["width"], "height": probe["height"], "duration": probe["duration"],
              "has_audio": probe["has_audio"], "shot_durations": [s["duration"] for s in segments], "gaps": sum(1 for s in segments if s["gap"]),
              "format": project["format"], "music": bool(music), "draft": bool(ctx.inputs["segments"].get("draft")), "mean_db": loud["mean_db"], "max_db": loud["max_db"],
              "findings": self._reviewer(segments) if self._reviewer else [],
              "shots": [{"text": s["text"], "duration": s["duration"], "gap": s["gap"], "asset_id": s.get("asset_id"), "t_in": s.get("chosen_in"),
                         "is_fact": s.get("is_fact", False), "source": s.get("source"), "fact_check": s.get("fact_check"), "sound_cue": s.get("sound_cue"), "own_voice": s.get("own_voice", False), "focus_x": s.get("focus_x"), "inserts": s.get("inserts", [])} for s in segments]}
        render_id = self._projects.add_render(script["project_id"], ctx.subject_ref, str(out), qc)
        return {"render_id": render_id, "qc_passed": qc["passed"]}
