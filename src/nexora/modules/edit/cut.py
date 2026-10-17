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

import json
import re
from pathlib import Path

from nexora.core.adapter import AdapterRegistry, Request
from nexora.core.assets import AssetStore
from nexora.core.cuts import CutStore, media_of
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
                 adapters: AdapterRegistry, media_dir: str | Path, source=None):
        self._orch, self._projects, self._assets, self._board, self._cuts = orch, projects, assets, storyboard, cuts
        self._adapters, self._media = adapters, Path(media_dir)
        self._source = source or (lambda asset_id: None)        # asset id -> the file a final cut reads (the edit module's choice)

    def register(self, registry: PipelineRegistry) -> None:
        registry.register(EXPORT, {"export": self._export})

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
        at, lines = 0.0, []
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
                commands.append({"id": "timeline.place", "params": {"item": f"$item:{version.version_id}", "track": "V1", "seconds": round(at, 4),
                                                                  "sourceIn": ticks(float(a.get("t_in") or 0.0)), "duration": ticks(length)}})
                speed = float((a.get("treat") or {}).get("speed") or 1.0)
                if abs(speed - 1.0) > 1e-6:
                    commands.append({"id": "clip.speedDuration", "params": {"clips": ["$clip"], "speed": round(speed * 100, 2), "ripple": True}})
                    length /= speed
            lines.append((at, length, line))
            at += length
        commands.append({"id": "captions.newTrack", "params": {"format": "Subtitle", "name": "Lời dẫn", "language": "vi"}})
        frame = 1 / FPS
        for start, length, line in lines:
            if line and length > 3 * frame:
                # Two captions that touch are refused: each is held one frame clear of the next.
                commands.append({"id": "captions.add", "params": {"track": "C1", "text": line, "time": ticks(start + (frame if start else 0.0)),
                                                                "durationSeconds": round(length - 2 * frame, 4)}})
        commands.append({"id": "captions.setTrack", "params": {"track": "C1", "syncLock": True}})
        return {"media": list(media.values()), "commands": commands, "missing": missing, "seconds": round(at, 2),
                "size": [width, height], "shots": len(shots)}

    # ---------------------------------------------------------------------------------------------- the final render
    def relinked(self, document: str) -> tuple[str, list[str]]:
        """The cut with every medium it names pointed at the file a final render reads; the versions none was found for."""
        unread = []
        for version_id in media_of(document):
            version = self._assets.version(version_id)
            path = self._source(version.asset_id) if version else None
            if not path:
                unread.append(version_id)
                continue
            document = re.sub(rf'"/files/{re.escape(version_id)}\.[A-Za-z0-9]+"', json.dumps(str(path)), document)
        return document, unread

    def start_export(self, cut_id: str) -> str:
        cut = self._cuts.get(cut_id)
        if cut is None:
            raise LookupError(cut_id)
        self._orch.supersede(EXPORT.pipeline_id, cut_id)
        return self._orch.submit_run(EXPORT, project_id=cut["project_id"], subject_ref=cut_id)

    def _export(self, ctx):
        cut = self._cuts.get(ctx.subject_ref)
        document, unread = self.relinked(self._cuts.document(ctx.subject_ref))
        if unread:
            raise ValueError(f"the cut names media that cannot be read here: {', '.join(unread)}")
        project = self._projects.project(cut["project_id"])
        width, height = SIZES.get(project["format"], SIZES["landscape"])
        out = self._media / "renders" / f"{cut['cut_id']}_{ctx.claim.attempt_id}.mp4"
        made = self._adapters.submit("filmcraft", Request("export", inputs={"document": document}, params={"out": str(out), "format": "h264"},
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
