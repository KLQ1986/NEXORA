"""The stages of `library.profile` (design 2026-10-14): look at every frame twice a second, listen to the sound, then join
both with the shots, beats and words already known into the profile of each beat and of the file. No language model is used;
the recognisers of the `vision` and `sound` adapters are used when present, and their fields are left out when not."""
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Callable

import numpy as np

from nexora.core.adapter import AdapterError, AdapterRegistry, ErrorCode, Request
from nexora.core.assets import AssetStore
from nexora.core.index import MomentIndex
from nexora.core.pipeline import PipelineDefinition, StageDef
from nexora.core.timebase import to_seconds
from nexora.modules.intelligence import profile as P

PROFILE = PipelineDefinition("library.profile", P.VERSION, [
    StageDef("probe"),
    StageDef("look", depends_on=("probe",), timeout_seconds=6 * 3600, lane="background", requires=("ffmpeg",)),
    StageDef("listen", depends_on=("probe",), timeout_seconds=6 * 3600, lane="background", requires=("ffmpeg",)),
    StageDef("profile", depends_on=("look", "listen"), lane="background"),
])
BATCH = 120                       # pictures handed to the recogniser at once
ANALYZER = f"profile:{P.VERSION}"


class Profiler:
    def __init__(self, assets: AssetStore, index: MomentIndex, adapters: AdapterRegistry, media_dir: str | Path, *,
                 structure_of: Callable[[str], dict | None], signals_of: Callable = lambda asset_id: None,
                 words: Callable[[str], list[dict]] = lambda asset_id: []):
        self._assets, self._index, self._adapters, self._media = assets, index, adapters, Path(media_dir)
        self._structure_of, self._signals_of, self._words = structure_of, signals_of, words

    def handlers(self) -> dict:
        return {"probe": self._probe, "look": self._look, "listen": self._listen, "profile": self._profile}

    def _has(self, name: str) -> bool:
        return any(c.name == name for c in self._adapters.describe())

    def _path(self, asset_id: str, suffix: str) -> Path:
        original = self._assets.original(asset_id)
        return self._media / original.checksum[:2] / f"{original.checksum}{suffix}"

    def _source(self, asset_id: str) -> Path | None:
        versions = {v.role: v for v in self._assets.versions(asset_id)}
        return next((p for p in (self._assets.path_of(versions[r]) for r in ("proxy", "original") if r in versions) if p.is_file()), None)

    def profile(self, asset_id: str) -> dict | None:
        """The profile last worked out for an asset: its beats, text, sound and the file as a whole."""
        original = self._assets.original(asset_id)
        if not original.checksum:
            return None
        try:
            return json.loads(self._path(asset_id, "_profile.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def beat_fields(self, asset_id: str) -> dict[tuple[float, float], dict]:
        made = self.profile(asset_id) or {}
        return {(b["start"], b["end"]): b["profile"] for b in made.get("beats", [])}

    def beat_prints(self, asset_id: str) -> dict[tuple[float, float], np.ndarray]:
        """One feature print a beat, by (start, end)."""
        prints, made = self.prints(asset_id), self.profile(asset_id)
        if prints is None or not made:
            return {}
        out = {}
        for b in made["beats"]:
            v = P.beat_print(prints, 1 / P.LOOK_FPS, b["start"], b["end"])
            if v is not None:
                out[(b["start"], b["end"])] = v
        return out

    def alike(self, asset_id: str, t_start: float, t_end: float, *, among: list[str], limit: int = 8) -> list[tuple[float, str, float, float]]:
        """Beats anywhere in `among` whose pictures look most like this one: (likeness 0-1, asset, start, end), best first."""
        mine = self.beat_prints(asset_id).get((round(t_start, 2), round(t_end, 2)))
        if mine is None:
            return []
        found = []
        for other in among:
            for (a, b), v in self.beat_prints(other).items():
                if other == asset_id and abs(a - t_start) < 0.01:
                    continue
                found.append((round(float(mine @ v), 4), other, a, b))
        return sorted(found, reverse=True)[:limit]

    def scenes(self, asset_ids: list[str]) -> list[dict]:
        """The scenes of a shoot: the beats of its recordings in the order they were filmed, grouped (design group 03)."""
        from datetime import datetime
        dated = []
        for asset_id in asset_ids:
            meta = self._assets.original(asset_id).metadata
            made = self.profile(asset_id)
            created = (meta.get("probe") or {}).get("created")
            if not made or not created:
                continue
            try:
                at = datetime.fromisoformat(str(created).replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            dated.append((at, asset_id, made))
        dated.sort()
        if not dated:
            return []
        origin = dated[0][0]
        beats = []
        for at, asset_id, made in dated:
            prints = self.beat_prints(asset_id)
            for b in made["beats"]:
                p = b["profile"]
                beats.append({"asset_id": asset_id, "start": b["start"], "end": b["end"], "at": at - origin + b["start"], "end_at": at - origin + b["end"],
                              "print": prints.get((b["start"], b["end"])), "place": (p.get("place") or {}).get("value"), "tags": (p.get("scene_tags") or {}).get("value")})
        made = P.scenes_of(beats)
        for k, scene in enumerate(made, 1):
            scene["number"] = k
            scene["beats"] = [{key: b[key] for key in ("asset_id", "start", "end")} for b in scene["beats"]]
        return made

    def publish_scenes(self, asset_ids: list[str]) -> list[dict]:
        """Keep the scenes of a shoot where search finds them: one line a scene in each recording it passes through."""
        made = self.scenes(asset_ids)
        for asset_id in asset_ids:
            self._index.remove(asset_id, "scene")
        for scene in made:
            for asset_id in scene["assets"]:
                mine = [b for b in scene["beats"] if b["asset_id"] == asset_id]
                self._index.upsert(asset_id, "scene", mine[0]["start"], mine[-1]["end"], f"Phân cảnh {scene['number']}: {scene['name']}.",
                                   data={"scene": scene["number"], "why": scene["why"], "assets": scene["assets"], "files": len(scene["assets"]), "measured": True},
                                   analyzer=ANALYZER)
        return made

    # ------------------------------------------------------------------------------------------------ people (group 06)
    def _faces(self, asset_id: str):
        try:
            with np.load(self._path(asset_id, "_faces.npz")) as data:
                return data["prints"].astype(np.float32), data["where"], data["boxes"]
        except (OSError, ValueError, KeyError):
            return None

    def people(self, asset_ids: list[str]) -> list[dict]:
        """The people of the library: faces from every recording grouped by how alike they look, each group one person, with
        where they appear and the name the operator gave (design group 06). Names are kept in `people.json` by a face that
        belongs to the group, so a name follows its person through every later grouping."""
        rows, prints = [], []
        for asset_id in asset_ids:
            got = self._faces(asset_id)
            if got is None:
                continue
            p, where, boxes = got
            for v, (k, j), box in zip(p, where, boxes):
                n = float(np.linalg.norm(v))
                if n > 0:
                    rows.append({"asset_id": asset_id, "t": round(int(k) / P.LOOK_FPS, 2), "face": int(j), "box": [round(float(x), 3) for x in box]})
                    prints.append(v / n)
        groups = P.group_faces(np.array(prints)) if prints else []
        names = self._names()
        out = []
        for g in groups:
            members = [rows[i] for i in g]
            keys = {f"{m['asset_id']}@{m['t']}#{m['face']}" for m in members}
            named = next((n for key, n in names.items() if key in keys), None)
            out.append({"key": sorted(keys)[0], "name": named, "faces": len(members), "assets": sorted({m["asset_id"] for m in members}),
                        "appearances": members[:50], "source": "measured", "confidence": "low" if len(members) < 3 else "medium"})
        return sorted(out, key=lambda x: -x["faces"])

    def places(self, asset_ids: list[str], *, same: float = 0.85) -> list[dict]:
        """Places of the library: beats whose pictures look alike (feature prints), from any recording, grouped (design group 06).
        Each place lists where it appears and the words the recogniser and the operator's notes give it."""
        rows, prints = [], []
        for asset_id in asset_ids:
            made = self.profile(asset_id) or {}
            tags = {(b["start"], b["end"]): ((b["profile"].get("scene_tags") or {}).get("value") or []) for b in made.get("beats", [])}
            for (a, b), v in self.beat_prints(asset_id).items():
                rows.append({"asset_id": asset_id, "start": a, "end": b, "tags": tags.get((a, b), [])})
                prints.append(v)
        groups = P.group_faces(np.array(prints), same=same) if prints else []
        out = []
        for g in groups:
            members = [rows[i] for i in g]
            counts: dict[str, int] = {}
            for m in members:
                for t in m["tags"][:6]:
                    counts[t] = counts.get(t, 0) + 1
            words = [t for t, _ in sorted(counts.items(), key=lambda kv: -kv[1]) if t not in ("ngoài trời", "trong nhà", "bầu trời", "trời xanh")][:4]
            out.append({"name": ", ".join(words) or "nơi chưa rõ", "beats": len(members), "assets": sorted({m["asset_id"] for m in members}),
                        "appearances": members[:40], "source": "recognized", "confidence": "medium" if len(members) >= 3 else "low"})
        return sorted(out, key=lambda x: (-len(x["assets"]), -x["beats"]))

    def _names(self) -> dict:
        try:
            return json.loads((self._media / "people.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def name_person(self, key: str, name: str) -> None:
        names = self._names()
        if name.strip():
            names[key] = name.strip()
        else:
            names.pop(key, None)
        _write_json(self._media / "people.json", names)

    def prints(self, asset_id: str) -> np.ndarray | None:
        """The feature print of every looked-at frame, one row a frame, for finding pictures that look alike."""
        try:
            with np.load(self._path(asset_id, "_prints.npz")) as data:
                return data["prints"]
        except (OSError, ValueError, KeyError):
            return None

    # ---------------------------------------------------------------------------------------------------------- stages
    def _skip(self, asset_id: str) -> str | None:
        meta = self._assets.original(asset_id).metadata
        probe = meta.get("probe", {})
        if "duplicate_of" in meta:
            return "duplicate"
        if probe.get("still") or probe.get("audio_only") or not probe.get("duration"):
            return "not a recording"
        return None

    def _probe(self, ctx):
        """Read the file's technical description again: footage taken in before every field was read gets the rest."""
        if self._skip(ctx.subject_ref):
            return {"skipped": self._skip(ctx.subject_ref)}
        original = self._assets.original(ctx.subject_ref)
        path = self._assets.path_of(original)
        if not path.is_file():
            return {"skipped": "the original is not available; the description read at ingest stays"}
        info = self._adapters.submit("ffprobe", Request("probe", inputs={"path": str(path)}, attempt_id=ctx.claim.attempt_id)).outputs
        info["content_credentials"] = P.has_content_credentials(path)
        # The camera's own record of its angle and turning, frame by frame, where it kept one (DJI).
        from nexora.modules.intelligence import telemetry
        try:
            packets = self._adapters.submit("ffmpeg", Request("telemetry", inputs={"path": str(path)}, attempt_id=ctx.claim.attempt_id,
                                                             params={"out": str(self._path(ctx.subject_ref, f"_meta.{ctx.claim.attempt_id or 'x'}.bin"))})).outputs["packets"]
        except AdapterError:
            packets = []
        records = telemetry.frames([bytes.fromhex(p) for p in packets])
        target = self._path(ctx.subject_ref, "_telemetry.json")
        if records:
            _write_json(target, {"fps": info.get("frame_rate") or 30.0, "frames": records})
            info["telemetry"] = {"frames": len(records), "kind": "dji"}
        else:
            target.unlink(missing_ok=True)
        kept = original.metadata.get("probe", {})
        self._assets.update_metadata(original.version_id, probe={**kept, **info, "still": kept.get("still"), "audio_only": kept.get("audio_only")})
        return {"fields": len(info)}

    def _look(self, ctx):
        if self._skip(ctx.subject_ref):
            return {"skipped": self._skip(ctx.subject_ref)}
        # Frames are drawn from the original where it is at hand: the proxy is compressed hard enough that the text on a phone held
        # in the frame cannot be read from it (measured on 0073: "Anh Cần" read from the original, nothing from the proxy).
        original = self._assets.path_of(self._assets.original(ctx.subject_ref))
        source = original if original.is_file() else self._source(ctx.subject_ref)
        if source is None:
            raise AdapterError(ErrorCode.MISSING_INPUT, "neither the footage nor its proxy is available")
        on_proxy = source.name.endswith("_proxy.mp4")
        probe = self._assets.original(ctx.subject_ref).metadata.get("probe", {})
        drawn = self._path(ctx.subject_ref, f"_look.{ctx.claim.attempt_id or 'draw'}")
        try:
            frames = self._adapters.submit("ffmpeg", Request("frames", inputs={"path": str(source)}, attempt_id=ctx.claim.attempt_id, params={
                "out_dir": str(drawn), "fps": P.LOOK_FPS, "width": P.LOOK_WIDTH, "color_transfer": None if on_proxy else probe.get("color_transfer")})).outputs["frames"]
            pictures: list[dict] = [{} for _ in frames]
            looked = False
            if self._has("vision"):
                try:
                    for start in range(0, len(frames), BATCH):
                        if ctx.should_stop():
                            break
                        got = self._adapters.submit("vision", Request("look", inputs={"images": frames[start:start + BATCH]}, attempt_id=ctx.claim.attempt_id)).outputs["pictures"]
                        pictures[start:start + len(got)] = got
                        ctx.heartbeat()
                    looked = True
                except AdapterError as err:
                    if err.code is not ErrorCode.UNAVAILABLE:
                        raise
            if looked:
                self._read_closer(ctx, source, on_proxy, probe, pictures)
            prints = [p.pop("print", None) for p in pictures]
            faces = [(k, j, f.get("box"), f.pop("print")) for k, p in enumerate(pictures) for j, f in enumerate(p.get("faces") or []) if f.get("print")]
            from PIL import Image
            measures, stack = [], []
            for k, frame in enumerate(frames):
                with Image.open(frame) as im:
                    rgb = np.asarray(im.convert("RGB"))
                measures.append(asdict(P.measure_frame(rgb, pictures[k].get("salient"))))
                stack.append(np.asarray(Image.fromarray(rgb).convert("L").resize((160, 90)), np.float32) / 255)
                for key in ("path",):
                    pictures[k].pop(key, None)
            sample = np.array(stack[:: max(1, len(stack) // 120)]) if stack else np.zeros((0, 90, 160))
            marks = P.static_marks(sample)
        finally:
            shutil.rmtree(drawn, ignore_errors=True)
        target = self._path(ctx.subject_ref, "_look.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_json(target, {"version": P.VERSION, "step": 1 / P.LOOK_FPS, "looked": looked, "pictures": pictures, "measures": measures, "marks": marks})
        if looked and any(p is not None for p in prints):
            width = len(next(p for p in prints if p is not None))
            matrix = np.array([p if p is not None and len(p) == width else [0.0] * width for p in prints], np.float16)
            with open(self._path(ctx.subject_ref, "_prints.npz"), "wb") as out:
                np.savez_compressed(out, prints=matrix, step=1 / P.LOOK_FPS)
        faces_file = self._path(ctx.subject_ref, "_faces.npz")
        faces_file.unlink(missing_ok=True)
        if faces:
            with open(faces_file, "wb") as out:
                np.savez_compressed(out, prints=np.array([f[3] for f in faces], np.float16), where=np.array([[f[0], f[1]] for f in faces], np.int32),
                                    boxes=np.array([f[2] for f in faces], np.float32))
        return {"frames": len(frames), "recognised": looked, "faces": len(faces)}

    def _read_closer(self, ctx, source: Path, on_proxy: bool, probe: dict, pictures: list[dict]) -> int:
        """Read text again, at the footage's own resolution, in the frames where small text is likely: hands holding something, a
        phone, a screen, a page. Measured on the seven beats of 0073 whose phone screen was missed: read again at 4K, six gave
        their text back; at 1920 wide, two. Returns how many frames gained text."""
        likely = [k for k, p in enumerate(pictures) if p.get("hands") or {c for c, conf in p.get("classes") or [] if conf >= 0.3} & P.TEXTY]
        if not likely or (probe.get("width") or 0) < 1600:
            return 0
        drawn = self._path(ctx.subject_ref, f"_read.{ctx.claim.attempt_id or 'draw'}")
        gained = 0
        try:
            frames = self._adapters.submit("ffmpeg", Request("frames", inputs={"path": str(source)}, attempt_id=ctx.claim.attempt_id, params={
                "out_dir": str(drawn), "fps": P.LOOK_FPS, "width": int(probe.get("display_width") or probe.get("width")), "color_transfer": None if on_proxy else probe.get("color_transfer")})).outputs["frames"]
            wanted = [k for k in likely if k < len(frames)]
            for start in range(0, len(wanted), BATCH):
                part = wanted[start:start + BATCH]
                got = self._adapters.submit("vision", Request("read", inputs={"images": [frames[k] for k in part]}, attempt_id=ctx.claim.attempt_id)).outputs["pictures"]
                for k, read in zip(part, got):
                    better = [t for t in read.get("text") or [] if len(t.get("text", "").strip()) >= 2]
                    if sum(len(t["text"]) for t in better) > sum(len(t.get("text", "")) for t in pictures[k].get("text") or []):
                        pictures[k]["text"] = better
                        gained += 1
                ctx.heartbeat()
        except AdapterError as err:
            if err.code is not ErrorCode.UNAVAILABLE:
                raise
        finally:
            shutil.rmtree(drawn, ignore_errors=True)
        return gained

    def _listen(self, ctx):
        if self._skip(ctx.subject_ref):
            return {"skipped": self._skip(ctx.subject_ref)}
        probe = self._assets.original(ctx.subject_ref).metadata.get("probe", {})
        target = self._path(ctx.subject_ref, "_listen.json")
        if not probe.get("has_audio"):
            _write_json(target, {"version": P.VERSION, "silent_file": True})
            return {"skipped": "no sound"}
        source = self._source(ctx.subject_ref)
        if source is None:
            raise AdapterError(ErrorCode.MISSING_INPUT, "neither the footage nor its proxy is available")
        out: dict = {"version": P.VERSION}
        if self._has("sound"):
            try:
                heard = self._adapters.submit("sound", Request("listen", inputs={"path": str(source)}, params={"window": 1.0, "hop": 0.5},
                                                              attempt_id=ctx.claim.attempt_id)).outputs
                out["windows"], out["hop"] = heard["windows"], heard["hop"]
            except AdapterError as err:
                if err.code is not ErrorCode.UNAVAILABLE:
                    raise
        r128 = self._adapters.submit("ffmpeg", Request("r128", inputs={"path": str(source)}, attempt_id=ctx.claim.attempt_id)).outputs
        out["momentary"], out["integrated"] = r128["momentary"], {k: r128[k] for k in ("integrated", "range", "true_peak")}
        raw = self._path(ctx.subject_ref, f"_pcm.{ctx.claim.attempt_id or 'x'}.raw")
        try:
            got = self._adapters.submit("ffmpeg", Request("pcm", inputs={"path": str(source)}, params={"out": str(raw), "rate": 16000}, attempt_id=ctx.claim.attempt_id)).outputs
            samples = np.memmap(raw, dtype=np.float32, mode="r") if raw.stat().st_size else np.zeros(0, np.float32)
            out["levels"] = P.levels(np.asarray(samples), got["rate"])
            del samples
        finally:
            raw.unlink(missing_ok=True)
        _write_json(target, out)
        return {"windows": len(out.get("windows", [])), "integrated": out["integrated"]["integrated"]}

    def _profile(self, ctx):
        if self._skip(ctx.subject_ref):
            return {"skipped": self._skip(ctx.subject_ref)}
        made = self.build(ctx.subject_ref)
        if made is None:
            return {"skipped": "nothing measured yet"}
        scenes = self.publish_scenes(self.shoot_of(ctx.subject_ref))
        return {"beats": len(made["beats"]), "text": len(made["text_spans"]), "sound": len(made["sound_events"]), "scenes_in_shoot": len(scenes)}

    def shoot_of(self, asset_id: str) -> list[str]:
        """The recordings of the same shoot: the same session named by the operator, else the same folder."""
        def key(a: dict) -> tuple:
            return ("session", a["session"]) if a.get("session") else ("folder", str(self._assets.path_of(self._assets.original(a["asset_id"])).parent))
        mine = self._assets.asset(asset_id)
        if mine is None:
            return []
        wanted = key(mine)
        return [a["asset_id"] for a in self._assets.assets() if a["kind"] == "video" and key(a) == wanted]

    # ------------------------------------------------------------------------------------------------------- joining
    def build(self, asset_id: str) -> dict | None:
        """Join what was looked at, heard and measured into the profile, keep it, and put it where the rest of the system reads it."""
        structure = self._structure_of(asset_id)
        if not structure or not structure.get("beats"):
            return None
        original = self._assets.original(asset_id)
        probe = dict(original.metadata.get("probe", {}))
        look = _read_json(self._path(asset_id, "_look.json")) or {}
        listen = _read_json(self._path(asset_id, "_listen.json")) or {}
        step = float(look.get("step", 1 / P.LOOK_FPS))
        pictures, measures = look.get("pictures", []), [P.FrameMeasure(**m) for m in look.get("measures", [])]
        words = self._words(asset_id)
        duration = float(probe.get("duration") or to_seconds(structure["beats"][-1]["end"], 2))
        beats = [{"start": to_seconds(b["start"], 2), "end": to_seconds(b["end"], 2), "labels": b.get("labels", {}), "shot": b.get("shot")} for b in structure["beats"]]

        def camera_at(t: float) -> str | None:
            beat = next((b for b in beats if b["start"] <= t < b["end"]), None)
            return ((beat or {}).get("labels", {}).get("camera") or {}).get("value")

        spans = P.text_spans(pictures, step=step, duration=duration, camera_moving=lambda t: camera_at(t) not in (None, "static"), words=words)
        for box in look.get("marks", []):
            if not any(s["kind"] == "watermark" and P._iou(s["box"], box) > 0.2 for s in spans):
                spans.append({"text": "", "start": 0.0, "end": round(duration, 2), "box": box, "kind": "watermark", "confidence": "medium",
                              "source": "measured", "frames": 0, "size": box[3]})
        events = P.sound_events(listen.get("windows", []), hop=float(listen.get("hop", 0.5)), duration=duration) if listen.get("windows") else []
        log_profile = P.detect_log(probe, measures)
        for beat in beats:
            k0, k1 = int(np.ceil(beat["start"] / step - 1e-6)), int(np.floor((beat["end"] - 1e-6) / step))
            inside = range(max(k0, 0), min(k1 + 1, max(len(pictures), len(measures))))
            beat["profile"] = P.profile_beat(beat["start"], beat["end"], [pictures[k] for k in inside if k < len(pictures) and pictures[k]],
                                             [measures[k] for k in inside if k < len(measures)], words=words, events=events,
                                             momentary=listen.get("momentary", []), audio=listen.get("levels", {}),
                                             camera=(beat["labels"].get("camera") or {}).get("value"), spans=spans, log_profile=log_profile)
        sensed = _read_json(self._path(asset_id, "_telemetry.json"))
        if sensed:
            from nexora.modules.intelligence import telemetry
            for beat in beats:
                got = telemetry.beat_fields(sensed["frames"], float(sensed["fps"]), beat["start"], beat["end"])
                beat["profile"].update(got)
                if got.get("tilt"):                      # the camera's sensor knows its roll better than a horizon found in the picture
                    beat["profile"]["horizon"] = {**got["tilt"], "value": got["tilt"]["value"]}
        probe["log_profile"] = log_profile
        shots = [{"start": to_seconds(s["start"], 2), "end": to_seconds(s["end"], 2), "transition_in": s.get("transition_in")} for s in structure.get("shots", [])]
        found = self._signals_of(asset_id)
        whole = P.asset_profile(probe=probe, shots=shots, beats=beats, words=words, spans=spans, events=events, integrated=listen.get("integrated"),
                                signals_diff=getattr(found, "diff", None), fps=getattr(found, "fps", None),
                                language=original.metadata.get("speech", {}).get("language"))
        tracks = P.tracks_of(pictures, step=step, shots=shots) if look.get("looked") else []
        made = {"version": P.VERSION, "beats": [{"start": b["start"], "end": b["end"], "profile": b["profile"]} for b in beats],
                "text_spans": spans, "sound_events": events, "tracks": tracks, "asset": whole, "recognised": bool(look.get("looked"))}
        _write_json(self._path(asset_id, "_profile.json"), made)
        self._assets.update_metadata(original.version_id, probe={**original.metadata.get("probe", {}), "log_profile": log_profile},
                                     profile={k: whole[k] for k in ("orientation", "language", "log_profile", "pacing", "hook", "platforms", "quality", "loudness", "calls_to_action")})
        self._publish(asset_id, made)
        return made

    def _publish(self, asset_id: str, made: dict) -> None:
        """Beats that have been described get their profile beside their description; text seen and sounds heard become
        moments of their own, so that a search finds them."""
        if self._assets.asset(asset_id) is None:
            return                                   # deleted while it was being measured
        fields = {(b["start"], b["end"]): b["profile"] for b in made["beats"]}
        for moment in self._index.moments(asset_id, level="segment"):
            got = fields.get((round(moment.t_start, 2), round(moment.t_end, 2)))
            if got is not None and moment.data.get("profile") != got:
                self._index.merge_data(moment.moment_id, profile=got)
        self._index.remove(asset_id, "text")
        for span in made["text_spans"]:
            if span["text"]:
                kind = span["kind"]
                self._index.upsert(asset_id, "text", span["start"], span["end"], f"Chữ trên hình ({kind}): {span['text']}",
                                   data={"span": span, "measured": True}, analyzer=ANALYZER)
        self._index.remove(asset_id, "sound")
        for event in made["sound_events"]:
            if event["kind"] in ("lời nói", "im lặng"):
                continue                                   # speech has its own words; silence is not something to search for
            self._index.upsert(asset_id, "sound", event["start"], event["end"], f"Âm thanh: {event['kind']}",
                               data={"event": event, "measured": True}, analyzer=ANALYZER)


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    partial.replace(path)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
