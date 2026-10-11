"""Edit: turn approved selections into a finished video (design v4.0, sections 12 and 19).

Narration is made first because its length decides how long each clip must be. Each shot is rendered
as its own segment and cached, so changing one shot re-renders one segment.
"""
import hashlib
import json
from pathlib import Path

from nexora.core.adapter import AdapterRegistry, Request
from nexora.core.assets import AssetStore
from nexora.core.orchestrator import Orchestrator
from nexora.core.pipeline import PipelineDefinition, PipelineRegistry, StageDef
from nexora.core.projects import ProjectStore

RENDER = PipelineDefinition("edit.render", "1", [
    StageDef("narration"),
    StageDef("segments", depends_on=("narration",)),
    StageDef("assemble", depends_on=("segments",), gate=True),
])
FORMATS = {
    "landscape": {"width": 1280, "height": 720, "fps": 30},     # 16:9
    "portrait": {"width": 720, "height": 1280, "fps": 30},      # 9:16, for short-form
    "square": {"width": 720, "height": 720, "fps": 30},
}
FORMAT = FORMATS["landscape"]
PAD_SECONDS = 0.4
WORDS_PER_SECOND = 2.6


def _key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]


class Edit:
    def __init__(self, orch: Orchestrator, projects: ProjectStore, assets: AssetStore, adapters: AdapterRegistry, media_dir: str | Path,
                 *, voice: bool = False, voice_name: str = "Linh", reviewer=None):
        self._orch, self._projects, self._assets, self._adapters = orch, projects, assets, adapters
        self._media, self._voice, self._voice_name = Path(media_dir), voice, voice_name
        self._reviewer = reviewer                    # the whole-cut review of the Quality module, injected by the composition root
        for sub in ("narration", "captions", "segments", "renders"):
            (self._media / sub).mkdir(parents=True, exist_ok=True)

    def register(self, registry: PipelineRegistry) -> None:
        registry.register(RENDER, {"narration": self._narration, "segments": self._segments, "assemble": self._assemble})

    def start_render(self, script_id: str) -> str:
        script = self._projects.script(script_id)
        if not script["match_approved"]:
            raise ValueError("the selections of this script have not been approved yet")
        return self._orch.submit_run(RENDER, subject_ref=script_id)

    def _narration(self, ctx):
        """One audio file per line; without a voice, the length is estimated and the line is silent."""
        lines = []
        script = self._projects.script(ctx.subject_ref)
        recorded = self._projects.project(script["project_id"]).get("narration_dir")
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
            out = self._media / "narration" / f"{_key(shot.text, self._voice_name)}.wav"
            if out.is_file():
                import wave
                with wave.open(str(out)) as w:
                    duration = w.getnframes() / w.getframerate()
            else:
                duration = self._adapters.submit("voice", Request("speak", inputs={"text": shot.text}, params={"out": str(out), "voice": self._voice_name},
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

    def _segments(self, ctx):
        script = self._projects.script(ctx.subject_ref)
        project = self._projects.project(script["project_id"])
        FORMAT = FORMATS.get(project["format"], FORMATS["landscape"])
        fill = "fit" if project["format"] == "landscape" else "cover"
        durations = {l["shot_id"]: l for l in ctx.inputs["narration"]["lines"]}
        out = []
        for shot in script["shots"]:
            line, sel = durations[shot.shot_id], self._projects.selection(shot.shot_id)
            duration = round(line["duration"] + PAD_SECONDS, 2)
            caption = self._media / "captions" / f"{_key(shot.text, FORMAT)}.png"
            if not caption.is_file():
                self._adapters.submit("graphics", Request("caption", inputs={"text": shot.text}, params={"out": str(caption), **FORMAT}))
            has_picture = sel is not None and sel.status != "gap" and sel.asset_id
            if has_picture:
                path, checksum, t_in = self._source(sel.asset_id, sel.t_in, duration)
                key = _key(checksum, t_in, duration, shot.text, line["audio"], FORMAT, fill)
            else:
                path, t_in, key = None, 0.0, _key("gap", duration, shot.text, line["audio"], FORMAT)
            segment = self._media / "segments" / f"{key}.mp4"
            if not segment.is_file():                                   # unchanged shots are reused, not rendered again
                self._adapters.submit("ffmpeg", Request("segment", inputs={"path": path}, attempt_id=ctx.claim.attempt_id,
                                                       params={"out": str(segment), "t_in": t_in, "duration": duration, "overlay": str(caption),
                                                               "audio": line["audio"], "fill": fill, **FORMAT}))
            out.append({"shot_id": shot.shot_id, "file": str(segment), "duration": duration, "gap": not has_picture, "text": shot.text,
                        "asset_id": sel.asset_id if has_picture else None, "t_in": t_in, "chosen_in": sel.t_in if has_picture else None,
                        "own_voice": bool(line.get("own_voice"))})
            ctx.heartbeat()
        return {"segments": out}

    def _assemble(self, ctx):
        script = self._projects.script(ctx.subject_ref)
        project = self._projects.project(script["project_id"])
        FORMAT = FORMATS.get(project["format"], FORMATS["landscape"])
        music = project["music_path"] if project["music_path"] and Path(project["music_path"]).is_file() else None
        segments = ctx.inputs["segments"]["segments"]
        out = self._media / "renders" / f"{ctx.subject_ref}_{ctx.claim.attempt_id}.mp4"
        self._adapters.submit("ffmpeg", Request("concat", inputs={"paths": [s["file"] for s in segments]}, params={"out": str(out), "music": music},
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
              "format": project["format"], "music": bool(music), "mean_db": loud["mean_db"], "max_db": loud["max_db"],
              "findings": self._reviewer(segments) if self._reviewer else [],
              "shots": [{"text": s["text"], "duration": s["duration"], "gap": s["gap"], "asset_id": s.get("asset_id"), "t_in": s.get("chosen_in"),
                         "own_voice": s.get("own_voice", False)} for s in segments]}
        render_id = self._projects.add_render(script["project_id"], ctx.subject_ref, str(out), qc)
        return {"render_id": render_id, "qc_passed": qc["passed"]}
