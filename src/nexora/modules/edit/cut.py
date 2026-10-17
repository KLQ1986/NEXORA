"""The Edit step on FilmCraft (design 2026-10-17): the storyboard made into a sequence, and the cut rendered on this Mac.

The plan is a list of FilmCraft commands the project page runs in the editor: a sequence of the project's size, each shot's
picture on V1 at its in and out (frame-exact; FilmCraft counts 254 016 000 000 ticks a second), a marker per shot with its
code and line, the lines as captions kept in step with the picture (the caption track is sync-locked, so a ripple moves
them too). Media go in as NEXORA's proxies, named by their version id, so the saved cut names them as
`/files/<version>.<ext>`. Rendering points those names at the files a final cut reads (the enhanced copy that stands for a
recording, else its original) and runs FilmCraft's command-line engine; the result is a render like any other, with its
checks, waiting for the operator's review.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from nexora.core.adapter import AdapterRegistry, Request
from nexora.core.assets import AssetStore
from nexora.core.cuts import CutStore, files_of
from nexora.core.orchestrator import Orchestrator
from nexora.core.pipeline import PipelineDefinition, PipelineRegistry, StageDef
from nexora.core.projects import ProjectStore
from nexora.core.storyboard import Storyboard

TICKS = 254_016_000_000
FPS = 30000 / 1001
SIZES = {"landscape": (1920, 1080), "portrait": (1080, 1920), "square": (1080, 1080)}
EXPORT = PipelineDefinition("edit.cut", "1", [StageDef("export", gate=True, requires=("filmcraft", "ffprobe", "ffmpeg"))])


def ticks(seconds: float) -> int:
    return round(seconds * TICKS)


class Cut:
    def __init__(self, orch: Orchestrator, projects: ProjectStore, assets: AssetStore, storyboard: Storyboard, cuts: CutStore,
                 adapters: AdapterRegistry, media_dir: str | Path, source=None, narrate=None):
        self._orch, self._projects, self._assets, self._board, self._cuts = orch, projects, assets, storyboard, cuts
        self._adapters, self._media = adapters, Path(media_dir)
        self._source = source or (lambda asset_id: None)        # asset id -> the file a final cut reads (the edit module's choice)
        # (project, text, position) -> {"audio", "duration", "own_voice"?}: a line said the way the render says it
        self._narrate = narrate or (lambda project, text, position: {"audio": None, "duration": 0.0})

    def register(self, registry: PipelineRegistry) -> None:
        registry.register(EXPORT, {"export": self._export})

    # ---------------------------------------------------------------------------------------------------- sound files
    def music_name(self, project: dict) -> str | None:
        path = project.get("music_path")
        if not path or not Path(path).is_file():
            return None
        return f"music_{hashlib.sha256(str(path).encode()).hexdigest()[:12]}{Path(path).suffix.lower() or '.mp3'}"

    def sound_file(self, project_id: str, name: str) -> Path | None:
        """A file a cut names that is not one of NEXORA's versions: a narration line (kept by its words and voice) or the
        project's music. Nothing else is handed out under these names."""
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            return None
        if name.startswith("music_"):
            project = self._projects.project(project_id)
            return Path(project["music_path"]) if project and self.music_name(project) == name else None
        path = self._media / "narration" / name
        return path if path.is_file() else None

    # -------------------------------------------------------------------------------------------- storyboard → sequence
    def _proxy(self, asset_id: str):
        """The copy the browser edits on: the newest proxy, else (a still, a generated picture) the original."""
        versions = [v for v in self._assets.versions(asset_id) if self._assets.path_of(v).is_file()]
        proxies = [v for v in versions if v.role == "proxy"]
        if proxies:
            return proxies[-1]
        return next((v for v in versions if v.role == "original"), None)

    def plan(self, project_id: str) -> dict:
        """The commands that build the project's storyboard as a sequence, the media they need, and what was left out."""
        project = self._projects.project(project_id)
        shots = self._board.shots(project_id)
        if not shots:
            raise ValueError("the project has no storyboard yet")
        width, height = SIZES.get(project["format"], SIZES["landscape"])
        media, commands, missing = {}, [], []
        commands.append({"id": "file.newSequence", "params": {"name": f"{project['title']} · từ Storyboard", "width": width, "height": height,
                                                           "fps": round(FPS, 3), "video": 3, "audio": 4}})
        at, lines, said, sfx, notes = 0.0, [], [], [], []
        for k, s in enumerate(shots, 1):
            code, line = f"SC{k}", s.spec["line"] or s.spec["intent"]
            a = s.assignment or {}
            length = float(a["t_out"]) - float(a["t_in"]) if a.get("asset_id") and a.get("t_out") is not None else float(s.spec["duration"]["target"])
            version = self._proxy(a["asset_id"]) if a.get("asset_id") else None
            commands.append({"id": "markers.add", "params": {"target": "program", "time": ticks(at), "name": code, "comment": line}})
            if version is None:
                missing.append({"code": code, "reason": "chưa có hình" if not a.get("asset_id") else "không đọc được file"})
            else:
                name = f"{version.version_id}{Path(self._assets.path_of(version)).suffix.lower() or '.mp4'}"
                media[version.version_id] = {"version": version.version_id, "name": name, "url": f"/media/{version.version_id}"}
                treat = a.get("treat") or {}
                # The clip's own sound only where the shot asks for it (an interview, a sound worth hearing); elsewhere the line speaks.
                commands.append({"id": "timeline.place", "params": {"item": f"$item:{version.version_id}", "track": "V1", "seconds": round(at, 4),
                                                                  "sourceIn": ticks(float(a.get("t_in") or 0.0)), "duration": ticks(length),
                                                                  "audio": bool(treat.get("live_sound"))}})
                if treat.get("sfx"):
                    sfx.append((code, at, treat["sfx"]))
                speed = float(treat.get("speed") or 1.0)
                if abs(speed - 1.0) > 1e-6:
                    commands.append({"id": "clip.speedDuration", "params": {"clips": ["$clip"], "speed": round(speed * 100, 2), "ripple": True}})
                    length /= speed
            lines.append((at, length, line))
            if line and not (a.get("treat") or {}).get("live_sound"):
                said.append((code, at, length, line, k - 1))
            at += length
        # A1, the narration: each line from the start of its shot, never over the line before; one too long for its shot is said.
        voice_end = 0.0
        for code, start, length, line, position in said:
            got = self._narrate(project, line, position)
            if not got.get("audio"):
                notes.append(f"{code}: chưa có giọng đọc cho câu này")
                continue
            name = Path(got["audio"]).name
            media[name] = {"version": None, "name": name, "url": f"/api/v1/projects/{project_id}/cut/sound/{name}"}
            begin = max(start, voice_end + 0.1 if voice_end else start)
            commands.append({"id": "timeline.place", "params": {"item": f"$item:{name}", "track": "A1", "seconds": round(begin, 4)}, "tag": "voice"})
            voice_end = begin + float(got["duration"])
            if voice_end > start + length + 0.3:
                notes.append(f"{code}: lời dài hơn hình {voice_end - start - length:.1f}s")
        # A2, the project's music under the whole cut, as loud as the project has it, held down while a line is said.
        music = self.music_name(project)
        if music and at > 0:
            media[music] = {"version": None, "name": music, "url": f"/api/v1/projects/{project_id}/cut/sound/{music}"}
            commands.append({"id": "timeline.place", "params": {"item": f"$item:{music}", "track": "A2", "seconds": 0, "duration": ticks(at)}, "tag": "music"})
            gain = float(project.get("music_gain") or 0.35)
            commands.append({"id": "clip.audioGain", "params": {"clips": "$tag:music", "mode": "set", "db": round(20 * math.log10(max(gain, 0.01)), 2)}})
        # A3, each shot's sound effect from the start of the shot.
        for code, start, asset_id in sfx:
            version = self._proxy(asset_id) if self._assets.asset(asset_id) else None
            if version is None:
                notes.append(f"{code}: không đọc được tiếng động")
                continue
            name = f"{version.version_id}{Path(self._assets.path_of(version)).suffix.lower() or '.wav'}"
            media[version.version_id] = {"version": version.version_id, "name": name, "url": f"/media/{version.version_id}"}
            commands.append({"id": "timeline.place", "params": {"item": f"$item:{version.version_id}", "track": "A3", "seconds": round(start, 4)}, "tag": "sfx"})
            commands.append({"id": "clip.audioGain", "params": {"clips": "$clip", "mode": "set", "db": round(20 * math.log10(0.6), 2)}})
        if said and any(c.get("tag") == "voice" for c in commands):
            commands.append({"id": "essentialSound.setType", "params": {"clips": "$tag:voice", "type": "dialogue"}})
        if music and at > 0:
            commands.append({"id": "essentialSound.setType", "params": {"clips": "$tag:music", "type": "music"}})
            if any(c.get("tag") == "voice" for c in commands):
                commands.append({"id": "essentialSound.generateDucking", "params": {"clips": "$tag:music"}})
        commands.append({"id": "captions.newTrack", "params": {"format": "Subtitle", "name": "Lời dẫn", "language": "vi"}})
        frame = 1 / FPS
        for start, length, line in lines:
            if line and length > 3 * frame:
                # Two captions that touch are refused: each is held one frame clear of the next.
                commands.append({"id": "captions.add", "params": {"track": "C1", "text": line, "time": ticks(start + (frame if start else 0.0)),
                                                                "durationSeconds": round(length - 2 * frame, 4)}})
        commands.append({"id": "captions.setTrack", "params": {"track": "C1", "syncLock": True}})
        return {"media": list(media.values()), "commands": commands, "missing": missing, "notes": notes, "seconds": round(at, 2),
                "size": [width, height], "shots": len(shots), "sound": {"voice": sum(c.get("tag") == "voice" for c in commands), "music": bool(music and at > 0),
                                                                        "sfx": sum(c.get("tag") == "sfx" for c in commands)}}

    # ---------------------------------------------------------------------------------------------- the final render
    def relinked(self, document: str, project_id: str) -> tuple[str, list[str]]:
        """The cut with every file it names pointed at the one a final render reads (a recording's approved VQ copy, else its
        original; a narration line; the project's music); the names nothing was found for."""
        unread = []
        for name in files_of(document):
            if name.startswith("ver_"):
                version = self._assets.version(re.match(r"ver_[0-9A-Za-z]+", name).group(0))
                path = self._source(version.asset_id) if version else None
            else:
                path = self.sound_file(project_id, name)
            if not path:
                unread.append(name)
                continue
            document = document.replace(json.dumps(f"/files/{name}"), json.dumps(str(path)))
        return document, unread

    def start_export(self, cut_id: str) -> str:
        cut = self._cuts.get(cut_id)
        if cut is None:
            raise LookupError(cut_id)
        self._orch.supersede(EXPORT.pipeline_id, cut_id)
        return self._orch.submit_run(EXPORT, project_id=cut["project_id"], subject_ref=cut_id)

    def _export(self, ctx):
        cut = self._cuts.get(ctx.subject_ref)
        document, unread = self.relinked(self._cuts.document(ctx.subject_ref), cut["project_id"])
        if unread:
            raise ValueError(f"the cut names media that cannot be read here: {', '.join(unread)}")
        project = self._projects.project(cut["project_id"])
        width, height = SIZES.get(project["format"], SIZES["landscape"])
        out = self._media / "renders" / f"{cut['cut_id']}_{ctx.claim.attempt_id}.mp4"
        # FilmCraft 0.8.0 can wait forever drawing the slate of a file it cannot read; nothing is sent that it cannot read, and
        # a render that outlives this is stopped rather than left holding the queue.
        made = self._adapters.submit("filmcraft", Request("export", inputs={"document": document}, params={"out": str(out), "format": "h264", "timeout": 900},
                                                         attempt_id=ctx.claim.attempt_id)).outputs["result"]
        ctx.heartbeat()
        probe = self._adapters.submit("ffprobe", Request("probe", inputs={"path": str(out)})).outputs
        loud = self._adapters.submit("ffmpeg", Request("loudness", inputs={"path": str(out)})).outputs
        checks = {
            "Có hình và đúng kích thước": (probe["width"], probe["height"]) == (width, height),
            "Có âm thanh": bool(probe["has_audio"]),
            "Đủ số khung đã dựng": int(made.get("frames") or 0) > 0,
            "Âm thanh không bị vỡ": loud["max_db"] <= -0.5,
        }
        script = self._projects.current_script(cut["project_id"])
        qc = {"passed": all(checks.values()), "checks": checks, "width": probe["width"], "height": probe["height"], "duration": probe["duration"],
              "has_audio": probe["has_audio"], "shot_durations": [], "gaps": 0, "format": project["format"], "music": False, "draft": False,
              "preview": False, "mean_db": loud["mean_db"], "max_db": loud["max_db"], "findings": [], "shots": [],
              "source": "filmcraft", "cut_id": cut["cut_id"], "cut_version": cut["version"], "render_seconds": made.get("seconds"),
              "render_fps": made.get("render_fps")}
        render_id = self._projects.add_render(cut["project_id"], script["script_id"] if script else cut["cut_id"], str(out), qc)
        return {"render_id": render_id, "qc_passed": qc["passed"]}
