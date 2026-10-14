"""Understanding: describe footage as time-coded text and index it (design v4.0, section 17.2).

Works from the picture alone; no stage depends on speech. Descriptions are cached per segment and
analyzer, and a text corrected by the operator is never overwritten.
"""
import hashlib
from pathlib import Path

from nexora.core.adapter import AdapterError, AdapterRegistry, ErrorCode, Request
from nexora.core.assets import AssetStore
from nexora.core.index import MomentIndex
from nexora.core.pipeline import PipelineDefinition, StageDef
from nexora.core.timebase import to_seconds

UNDERSTAND = PipelineDefinition("library.understand", "1", [
    StageDef("segments", requires=("ffmpeg",)),
    StageDef("describe", depends_on=("segments",), timeout_seconds=6 * 3600, lane="background", requires=("model",)),
    StageDef("summarise", depends_on=("describe",), lane="background", requires=("model",)),
    StageDef("index", depends_on=("summarise",), lane="background", requires=("model",)),
])

PROMPT_VERSION = "v1"
FRAME_FPS = 0.5
BEAT_FRAME_FPS = 2.0             # frames are drawn at this rate for footage that has been divided into beats; each beat keeps the few it chose
DESCRIBE_PROMPT = (
    "Đây là {n} khung hình liên tiếp, cách nhau {gap:g} giây, của cùng một đoạn video không có lời thoại. "
    "Hãy mô tả đúng những gì nhìn thấy, bằng tiếng Việt, gọi tên cụ thể đồ vật, món ăn, con vật, địa điểm, hành động của tay và người. "
    "Không suy đoán điều không thấy. Chỉ trả về JSON với các khoá: "
    "mo_ta (1 đến 2 câu ngắn, cụ thể: ai hoặc cái gì đang làm gì, ở đâu), chu_the (danh sách các vật thể và người thấy rõ), "
    "hanh_dong (danh sách hành động), boi_canh (một cụm từ về nơi chốn), chu_tren_hinh (chữ đọc được trên hình, hoặc chuỗi rỗng), "
    "co_canh (toàn, trung hoặc cận)."
)
CONTEXT_NOTE = (
    "\n\nNgười quay cho biết thêm về đoạn video này:\n{context}\n"
    "Dùng thông tin này để gọi đúng tên người, nơi chốn và sự việc khi chúng xuất hiện trong hình. Không tả điều không thấy trong hình."
)
FRAME_PROMPT = (
    "Đây là một khung hình của một video. Hãy mô tả thật kỹ đúng khung hình này bằng tiếng Việt: từng vật thể, người, tư thế, vị trí trong khung, màu sắc, ánh sáng. "
    "Không suy đoán điều không thấy. Chỉ trả về JSON với các khoá: mo_ta (2 đến 3 câu), chu_the (danh sách vật thể và người), chu_tren_hinh (chữ đọc được, hoặc chuỗi rỗng)."
)
MAX_DEEP_FRAMES = 8
SUMMARY_PROMPT = (
    "Dưới đây là mô tả từng đoạn của một video, theo thứ tự thời gian. Hãy tóm tắt cả video bằng tiếng Việt. "
    "Chỉ trả về JSON với các khoá: tieu_de (một tiêu đề ngắn), tom_tat (2 đến 3 câu), chu_de (danh sách chủ đề chính).\n\n{lines}"
)


def clock(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def split_segments(usable: list[list[float]], seconds: float) -> list[tuple[float, float]]:
    out = []
    for start, end in usable:
        start, end = round(start, 1), round(end, 1)
        t = start
        while end - t >= 0.5:
            out.append((round(t, 1), round(min(t + seconds, end), 1)))
            t += seconds
    return out


class Understanding:
    def __init__(self, assets: AssetStore, index: MomentIndex, adapters: AdapterRegistry, media_dir: str | Path, *, segment_seconds: float = 12.0,
                 structure_of=None):
        self._assets, self._index, self._adapters, self._media = assets, index, adapters, Path(media_dir)
        self._seconds = segment_seconds
        self._structure_of = structure_of or (lambda asset_id: None)      # the shots and beats of an asset, once it has been measured

    def handlers(self) -> dict:
        return {"segments": self._segments, "describe": self._describe, "summarise": self._summarise, "index": self._index_stage}

    @property
    def analyzer(self) -> str:
        return f"{PROMPT_VERSION}:{self._seconds:g}s"

    def context(self, asset_id: str) -> str:
        """What is known about a recording apart from its picture: where the file sat (the shoot it came from), when it was made,
        and what the operator wrote about it. For silent footage this is the only way a name or a place can reach the description."""
        original, asset = self._assets.original(asset_id), self._assets.asset(asset_id) or {}
        path, probe = self._assets.path_of(original), original.metadata.get("probe", {})
        lines = [f"Tên file: {path.name}", f"Thư mục (buổi quay): {path.parent.name}"]
        if probe.get("created"):
            lines.append(f"Ngày quay: {str(probe['created'])[:10]}")
        if asset.get("note"):
            lines.append(f"Ghi chú của người quay: {asset['note']}")
        return "\n".join(lines)

    def _analyzer_for(self, asset_id: str) -> str:
        """A changed note is a changed question, so descriptions made before it are no longer the cached answer."""
        import hashlib
        note = (self._assets.asset(asset_id) or {}).get("note")
        return self.analyzer + (":" + hashlib.sha1(note.encode()).hexdigest()[:8] if note else "")

    def deepen(self, moment_id: str) -> list[str]:
        """Look at one stretch frame by frame. Segment descriptions say what happens; these say what each frame holds,
        for when the operator needs an exact instant. Bounded, because every frame is one more look by the model."""
        segment = self._index.by_id(moment_id)
        if segment is None or segment.level != "segment":
            raise ValueError("no such segment")
        frames, made = segment.data.get("frames") or [], []
        span = max(segment.t_end - segment.t_start, 0.1) / max(len(frames), 1)
        for k, frame in enumerate(frames[:MAX_DEEP_FRAMES]):
            out = self._adapters.submit("model", Request("describe", inputs={"images": [frame]}, params={"prompt": FRAME_PROMPT, "task": "frame", "index": k, "max_tokens": 400})).outputs["json"]
            parts = [str(out.get("mo_ta", "")).strip()]
            if isinstance(out.get("chu_the"), list) and out["chu_the"]:
                parts.append(f"Thấy: {', '.join(str(v) for v in out['chu_the'])}.")
            if out.get("chu_tren_hinh"):
                parts.append(f"Chữ trên hình: {out['chu_tren_hinh']}.")
            t = round(segment.t_start + k * span, 1)
            made.append(self._index.upsert(segment.asset_id, "frame", t, round(min(t + span, segment.t_end), 1), " ".join(p for p in parts if p),
                                           data={"frame": frame, "frames": [frame], "detail": out}, analyzer=self.analyzer))
        self.embed_pending(segment.asset_id)
        return made

    def embed_pending(self, asset_id: str) -> int:
        pending = self._index.without_vectors(asset_id)
        for start in range(0, len(pending), 32):
            batch = pending[start:start + 32]
            vectors = self._adapters.submit("model", Request("embed", inputs={"texts": [m.text for m in batch]})).outputs["vectors"]
            for moment, vector in zip(batch, vectors):
                self._index.set_vector(moment.moment_id, vector)
        return len(pending)

    def _segments(self, ctx):
        versions = {v.role: v for v in self._assets.versions(ctx.subject_ref)}
        original = versions["original"]
        if original.metadata.get("probe", {}).get("still"):          # a photograph is one moment and its own frame
            return {"segments": [{"t_start": 0.0, "t_end": 0.0, "frames": [str(self._assets.path_of(original))]}]}
        source = self._assets.path_of(versions.get("proxy", original))
        structure = self._structure_of(ctx.subject_ref)
        if structure and structure.get("beats"):
            return {"segments": self._beats(ctx, original, source, structure), "structured": True}
        out_dir = self._media / original.checksum[:2] / f"{original.checksum}_frames"
        frames = self._adapters.submit("ffmpeg", Request("frames", inputs={"path": str(source)}, params={"out_dir": str(out_dir), "fps": FRAME_FPS},
                                                        attempt_id=ctx.claim.attempt_id)).outputs["frames"]
        segments = []
        for a, b in split_segments(original.metadata.get("usable_ranges", []), self._seconds):
            picks = [f for k, f in enumerate(frames) if a <= k / FRAME_FPS < b] or frames[int(a * FRAME_FPS):int(a * FRAME_FPS) + 1]
            segments.append({"t_start": a, "t_end": b, "frames": picks[:6]})
        return {"segments": segments}

    def _beats(self, ctx, original, source: Path, structure: dict) -> list[dict]:
        """The beats of measured footage as the segments to describe, each with the frames it chose to be looked at. Segments
        left over from an earlier division go: one the operator corrected is kept as a note on the same stretch."""
        out_dir = self._media / original.checksum[:2] / f"{original.checksum}_beats"
        frames = self._adapters.submit("ffmpeg", Request("frames", inputs={"path": str(source)}, params={"out_dir": str(out_dir), "fps": BEAT_FRAME_FPS},
                                                        attempt_id=ctx.claim.attempt_id)).outputs["frames"]
        segments, wanted = [], set()
        for beat in structure["beats"]:
            picks = list(dict.fromkeys(frames[min(len(frames) - 1, max(0, round(t * BEAT_FRAME_FPS)))] for t in beat["frames"])) if frames else []
            wanted.update(picks)
            segments.append({"t_start": to_seconds(beat["start"], 2), "t_end": to_seconds(beat["end"], 2), "frames": picks, "labels": beat["labels"],
                             "shot": beat["shot"], "start_tick": beat["start"], "end_tick": beat["end"]})
        for path in frames:
            if path not in wanted:
                Path(path).unlink(missing_ok=True)
        ranges = {(s["t_start"], s["t_end"]) for s in segments}
        for old in self._index.moments(ctx.subject_ref, level="segment"):
            if (old.t_start, old.t_end) in ranges:
                continue
            if old.source == "human":
                self._index.relevel(old.moment_id, "note", kept=True)        # the operator's words outlive the division they were written on
            else:
                self._index.remove(ctx.subject_ref, "segment", only=lambda m, gone=old.moment_id: m.moment_id == gone)
        return segments

    def _describe(self, ctx):
        done = unreadable = 0
        whole, context = self._analyzer_for(ctx.subject_ref), self.context(ctx.subject_ref)
        for i, seg in enumerate(ctx.inputs["segments"]["segments"]):
            if ctx.should_stop():
                break
            measured = {k: seg[k] for k in ("labels", "shot", "start_tick", "end_tick") if k in seg}
            # A beat's description answers one question: these frames, with this note. The rule that divided the footage is not
            # part of it, so a beat whose bounds and frames a new division leaves alone keeps what was said about it.
            analyzer = whole if not measured else ":".join([PROMPT_VERSION, "beat", hashlib.sha1("|".join(Path(f).name for f in seg["frames"]).encode()).hexdigest()[:8],
                                                             *whole.split(":")[2:]])
            existing = self._index.get(ctx.subject_ref, "segment", seg["t_start"], seg["t_end"])
            if existing and (existing.source == "human" or existing.analyzer == analyzer):
                if measured and any(existing.data.get(k) != v for k, v in measured.items()):
                    self._index.merge_data(existing.moment_id, **measured)   # what was measured may have changed; what was said has not
                continue                                                    # cached: no model call
            if not seg["frames"]:
                continue
            out = None
            # A small model shown many frames at once sometimes answers with something that is not JSON. It is then shown fewer:
            # the first, the middle and the last say most of what the stretch holds; failing that, the middle one alone.
            middle = seg["frames"][len(seg["frames"]) // 2]
            for shown in (seg["frames"], [seg["frames"][0], middle, seg["frames"][-1]] if len(seg["frames"]) > 3 else None, [middle] if len(seg["frames"]) > 1 else None):
                if shown is None:
                    continue
                gap = (seg["t_end"] - seg["t_start"]) / max(len(shown) - 1, 1) if measured else 1 / FRAME_FPS
                prompt = DESCRIBE_PROMPT.format(n=len(shown), gap=round(gap, 1)) + CONTEXT_NOTE.format(context=context)
                try:
                    out = self._adapters.submit("model", Request("describe", inputs={"images": shown},
                                                                params={"prompt": prompt, "index": i, "max_tokens": 700},
                                                                attempt_id=ctx.claim.attempt_id)).outputs["json"]
                    break
                except AdapterError as err:
                    if err.code is not ErrorCode.OUTPUT_INVALID:
                        raise
            if out is None:
                unreadable += 1                      # one bad answer must not cost the whole video; the segment stays undescribed
                continue
            parts = [str(out.get("mo_ta", "")).strip()]
            for key, label in (("chu_the", "Thấy"), ("hanh_dong", "Hành động")):
                values = out.get(key) or []
                if isinstance(values, list) and values:
                    parts.append(f"{label}: {', '.join(str(v) for v in values)}.")
            if out.get("boi_canh"):
                parts.append(f"Nơi: {out['boi_canh']}.")
            if out.get("chu_tren_hinh"):
                parts.append(f"Chữ trên hình: {out['chu_tren_hinh']}.")
            frame = seg["frames"][len(seg["frames"]) // 2]
            self._index.upsert(ctx.subject_ref, "segment", seg["t_start"], seg["t_end"], " ".join(p for p in parts if p),
                               data={"frame": frame, "frames": seg["frames"], "detail": out, **measured}, analyzer=analyzer)
            done += 1
            ctx.heartbeat()
        return {"described": done, "unreadable": unreadable}

    def _summarise(self, ctx):
        segments = self._index.moments(ctx.subject_ref, level="segment")
        if not segments:
            return {"skipped": "nothing to summarise"}
        lines = self.context(ctx.subject_ref) + "\n\n" + "\n".join(f"[{clock(m.t_start)}] {m.text}" for m in segments)[:12000]
        out = self._adapters.submit("model", Request("chat", params={"prompt": SUMMARY_PROMPT.format(lines=lines), "json": True, "max_tokens": 400},
                                                    attempt_id=ctx.claim.attempt_id)).outputs["json"]
        duration = self._assets.original(ctx.subject_ref).metadata.get("probe", {}).get("duration", segments[-1].t_end)
        self._index.upsert(ctx.subject_ref, "video", 0.0, round(float(duration), 1), str(out.get("tom_tat", "")).strip(),
                           data={"detail": out}, analyzer=self.analyzer)
        return {"title": out.get("tieu_de")}

    def _index_stage(self, ctx):
        pending = self._index.without_vectors(ctx.subject_ref)
        for start in range(0, len(pending), 32):
            batch = pending[start:start + 32]
            vectors = self._adapters.submit("model", Request("embed", inputs={"texts": [m.text for m in batch]},
                                                            attempt_id=ctx.claim.attempt_id)).outputs["vectors"]
            for moment, vector in zip(batch, vectors):
                self._index.set_vector(moment.moment_id, vector)
        return {"embedded": len(pending)}
