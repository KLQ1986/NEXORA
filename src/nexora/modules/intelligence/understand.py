"""Understanding: describe footage as time-coded text and index it (design v4.0, section 17.2).

Works from the picture alone; no stage depends on speech. Descriptions are cached per segment and
analyzer, and a text corrected by the operator is never overwritten.
"""
import hashlib
import os
import shutil
from pathlib import Path

from nexora.core.adapter import AdapterError, AdapterRegistry, ErrorCode, Request
from nexora.core.assets import AssetStore
from nexora.core.index import MomentIndex
from nexora.core.pipeline import PipelineDefinition, StageDef
from nexora.core.timebase import to_seconds
from nexora.modules.intelligence import vocab
from nexora.modules.intelligence.profile import cross_checks

UNDERSTAND = PipelineDefinition("library.understand", "1", [
    StageDef("segments", requires=("ffmpeg",)),
    StageDef("describe", depends_on=("segments",), timeout_seconds=6 * 3600, lane="background", requires=("model",)),
    StageDef("summarise", depends_on=("describe",), lane="background", requires=("model",)),
    StageDef("index", depends_on=("summarise",), lane="background", requires=("model",)),
])

PROMPT_VERSION = "v1"
BEAT_PROMPT_VERSION = "v4"       # beats of measured footage are described with what was measured about their picture
FRAME_FPS = 0.5
BEAT_FRAME_FPS = 2.0             # frames are drawn at this rate for footage that has been divided into beats; each beat keeps the few it chose
# Beat frames are drawn from the original, 1280 wide. Ollama brings every picture to about one megapixel before qwen3-vl sees it
# (a 448 and a 960 wide frame cost the same tokens), so a small frame from the proxy was only enlarged: measured on 0038, the
# boats out at sea, a purple flower and the beach morning glory were seen at 960 from the original and not at 448 from the
# proxy. 1280 named as many things as 960 for about 4% more tokens; it was settled on to keep more of the original's detail.
BEAT_WIDTH = 1280
DESCRIBE_PROMPT = (
    "Đây là {n} khung hình liên tiếp, cách nhau {gap:g} giây, của cùng một đoạn video không có lời thoại. "
    "Hãy mô tả đúng những gì nhìn thấy, bằng tiếng Việt, gọi tên cụ thể đồ vật, món ăn, con vật, địa điểm, hành động của tay và người. "
    "Không suy đoán điều không thấy. Chỉ trả về JSON với các khoá: "
    "mo_ta (1 đến 2 câu ngắn, cụ thể: ai hoặc cái gì đang làm gì, ở đâu), chu_the (danh sách các vật thể và người thấy rõ), "
    "hanh_dong (danh sách hành động), boi_canh (một cụm từ về nơi chốn), chu_tren_hinh (chữ đọc được trên hình, hoặc chuỗi rỗng), "
    "co_canh (toàn, trung hoặc cận)."
)
# Version 4 (2026-10-15). Version 3, read beside the frames of 0050 and 0038: descriptions of neighbouring beats said the same
# thing ("a path surrounded by thatched houses and green trees"), things plainly in the picture went unnamed (coconut palms,
# a purple flower, basket boats called "small boats"), half the sentences began "the picture shows" or said what was not
# there, and labels were confused (a shot size given as the place; "close" for a wide beach). So: no shot size or angle from
# the model (the measures and the camera's sensor do better: 92% against 14 of 25); the picture asked for layer by layer,
# subject and where it sits, near and far; local names offered for what is plainly seen; no opening formula, no negations.
BEAT_PROMPT = (
    "Đây là {n} khung hình liên tiếp, cách nhau {gap:g} giây, của cùng một đoạn video. Hãy tả đúng những gì nhìn thấy, bằng tiếng Việt, không dùng từ tiếng Anh.\n"
    "- Viết thẳng vào sự vật; không mở đầu bằng \"Hình ảnh cho thấy\", \"Các khung hình\", \"Đoạn video\".\n"
    "- Chỉ nói điều có trong hình; không viết điều không có (không viết \"không có người\", \"không có chữ\").\n"
    "- Không viết về cảm giác (yên tĩnh, thư giãn, đẹp, mờ ảo, thơ mộng).\n"
    "- Gọi tên cụ thể nhất mà chắc chắn, kèm màu, chất liệu, số lượng. Những tên hay gặp, chỉ dùng khi thấy rõ: {names}.\n"
    "- Nói cả những vật nhỏ ở xa nếu thấy rõ.\n{facts}"
    "Chỉ trả về JSON với các khoá: mo_ta (1 đến 2 câu: cái gì hoặc ai, đang làm gì, ở đâu, và điều riêng của đoạn này), "
    "chu_the_chinh (chủ thể chính và vị trí trong khung: trái, giữa, phải, trên, dưới), "
    "tien_canh (những gì ở sát máy, chuỗi rỗng nếu không có), trung_canh (ở khoảng giữa), hau_canh (ở xa, phía sau), "
    "chu_the (danh sách 3 đến 10 vật thể hoặc người thấy rõ, mỗi mục một cụm từ ngắn, không lặp), hanh_dong (danh sách cụm từ ngắn, rỗng nếu không ai làm gì), "
    "boi_canh (một cụm từ về nơi chốn, ví dụ: bãi biển, lối đi trong khu nghỉ dưỡng, gian bếp), chu_tren_hinh (chữ in trên hình đọc được, hoặc chuỗi rỗng), "
    "so_nguoi (một trong: không, một, hai, nhóm, đám đông), noi_chon (một trong: {places})."
)
MODEL_LABELS = {"noi_chon": vocab.PLACES, "thoi_diem": vocab.TIMES, "so_nguoi": ("không", "một", "hai", "nhóm", "đám đông"), "co_canh": vocab.SHOT_SIZES,
                "goc_may": vocab.ANGLES, "goc_nhin": vocab.VIEWPOINTS, "loai_noi_dung": vocab.CONTENT_KINDS, "huong_sang": vocab.LIGHT_DIRECTIONS,
                "cam_xuc": vocab.EMOTIONS}
CAMERA_WORDS = {"static": "máy đứng yên", "pan": "máy lia ngang", "tilt": "máy lia dọc", "push_in": "máy đẩy vào", "pull_out": "máy kéo ra", "handheld": "máy cầm tay rung"}


def facts_of(profile: dict, labels: dict, words: str = "") -> str:
    """What the machine measured and recognised in a beat's picture, said plainly, only where it is sure. The spoken words are
    not said: shown them, a small model copied them into the text it read on screen."""
    lines = []
    people = profile.get("people")
    if people and people.get("confidence") == "high":
        lines.append("không có người nào trong hình" if people.get("count", 0) == 0 else f"có {people['count']} người trong hình")
    size = profile.get("shot_size")
    if size and size.get("by") == "người":
        lines.append(f"cỡ cảnh: {size['value']}")
    camera = (labels.get("camera") or {}).get("value")
    if camera in CAMERA_WORDS:
        lines.append(CAMERA_WORDS[camera])
    text = profile.get("text")
    lines.append("chữ in trên hình: " + "; ".join(text["value"][:4]) if text and text.get("value") else "không có chữ in trên hình")
    return "Máy đã đo được (đúng, không được nói ngược lại): " + "; ".join(lines) + ".\n"


def model_labels(out: dict, profile: dict) -> dict:
    """The labels a model chose, each kept only when it is one of its list, with a confidence that says whether something the
    machine measured agrees (design 10-13, section 6): agreed is high, nothing to check against is medium, contradicted is low."""
    made = {}
    for key, allowed in MODEL_LABELS.items():
        value = vocab.canonical(str(out.get(key) or ""))
        if value not in allowed:
            continue
        confidence = "medium"
        if key == "co_canh" and profile.get("shot_size"):
            from nexora.modules.intelligence.profile import SIZE_RANK
            gap = abs(SIZE_RANK[value] - SIZE_RANK[profile["shot_size"]["value"]])
            confidence = "high" if gap == 0 else ("medium" if gap == 1 else "low")
        elif key == "noi_chon" and profile.get("place"):
            confidence = "high" if value == profile["place"]["value"] else "low"
        elif key == "so_nguoi" and profile.get("people"):
            confidence = "high" if value == profile["people"]["value"] else "low"
        made[key] = {"value": value, "source": "model", "confidence": confidence}
    return made


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
    "Dưới đây là mô tả từng đoạn của một video, theo thứ tự thời gian, và lời nói nghe được. Hãy tóm tắt cả video bằng tiếng Việt. "
    "Chỉ trả về JSON với các khoá: tieu_de (một tiêu đề ngắn), tom_tat (2 đến 3 câu), chu_de (danh sách chủ đề chính, mỗi chủ đề là một cụm từ có trong mô tả), "
    "the_loai (một trong: {genres}), muc_dich (giới thiệu, hướng dẫn, kể chuyện, quảng cáo, ghi lại hoặc giải trí), khan_gia (một cụm từ), "
    "thong_diep (một câu, hoặc chuỗi rỗng nếu không có), cau_truc (danh sách các phần, mỗi phần là {{\"phan\": một trong mở đầu, phát triển, cao trào, kết, "
    "\"tu\": mốc phút:giây lấy từ các dòng bên dưới, \"vi\": lý do ngắn}}), cam_xuc (danh sách {{\"tu\": mốc phút:giây, \"cam_xuc\": một trong {emotions}}}).\n\n{lines}"
)
SECTIONS = ("mở đầu", "phát triển", "cao trào", "kết")


def grounded(out: dict, texts: list[str], marks: set[str]) -> dict:
    """Keep only what the summary can show for itself (design 2026-10-14, group 02): a topic whose words appear in a described
    beat or in what was said, a section or a change of feeling at a time that is one of the beats' own. What it guesses about
    purpose, audience and message is kept, marked as inferred."""
    said = " ".join(texts).lower()
    keep = lambda topic: any(len(w) >= 3 and w in said for w in vocab.norm(str(topic)).split())
    out = dict(out)
    out["chu_de"] = [t for t in out.get("chu_de") or [] if keep(t)]
    genre = vocab.canonical(str(out.get("the_loai") or ""))
    out["the_loai"] = genre if genre in vocab.GENRES else ""
    out["cau_truc"] = [x for x in out.get("cau_truc") or [] if isinstance(x, dict) and vocab.canonical(str(x.get("phan"))) in SECTIONS and str(x.get("tu")) in marks]
    out["cam_xuc"] = [x for x in out.get("cam_xuc") or [] if isinstance(x, dict) and vocab.canonical(str(x.get("cam_xuc"))) in vocab.EMOTIONS and str(x.get("tu")) in marks]
    out["inferred"] = ["muc_dich", "khan_gia", "thong_diep", "cau_truc", "cam_xuc"]
    return out


STATE_PROMPT = (
    "Khung thứ nhất là lúc một việc bắt đầu, khung thứ hai là lúc nó kết thúc. Việc đó là: {what}. "
    "Chỉ trả về JSON với các khoá truoc (một câu: tình trạng lúc đầu) và sau (một câu: tình trạng lúc cuối), chỉ nói điều thấy trong hình."
)
MAX_STATES = 20          # events a recording gets before-and-after states for; each is one look by the model


UNKNOWN = frozenset({"", "không rõ", "không có", "không", "không có người", "không có hành động", "không có vật", "none", "null", "n/a"})


# A clause about how a place feels says nothing a search can use, and makes every beat of a place read the same.
FEELING = __import__("re").compile(r",?\s*(tạo nên|tạo ra|mang lại|mang đến|gợi lên)[^.]*(yên tĩnh|thư giãn|yên bình|thanh bình|dễ chịu|ấm cúng|sống động|tươi mát|mờ ảo)[^.]*", __import__("re").IGNORECASE)
FEELING_THING = __import__("re").compile(r"không gian|bầu không khí|cảm giác")
# "The picture shows ...": a formula that says nothing and makes every beat begin alike, so that their vectors draw together.
OPENING = __import__("re").compile(r"^\s*(các |những )?(hình ảnh|khung hình|đoạn video|video|cảnh)( liên tiếp| này)*\s+(cho thấy|ghi lại|thể hiện|mô tả|là)\s+", __import__("re").IGNORECASE)
# A sentence about what is not in the picture: a search for "người" would find the beats that say there is no one.
ABSENT = __import__("re").compile(r"\b(không có|không thấy|không xuất hiện|chẳng có)\b", __import__("re").IGNORECASE)
# How the camera moves is measured; said by the model, it took the place of the subject ("Chủ thể: máy quay di chuyển").
CAMERA_TALK = __import__("re").compile(r"\bmáy quay\b|\bcamera\b", __import__("re").IGNORECASE)
LAYERS = (("chu_the_chinh", "Chủ thể"), ("tien_canh", "Gần máy"), ("trung_canh", "Giữa"), ("hau_canh", "Xa"))


def plain(text: str) -> str:
    """A description without its opening formula, its sentences about what is not there and its clauses about feelings."""
    kept = []
    for sentence in __import__("re").split(r"(?<=[.!?])\s+", text.strip()):
        sentence = FEELING.sub("", OPENING.sub("", sentence)).strip()
        if sentence and not ABSENT.search(sentence) and not CAMERA_TALK.search(sentence):
            kept.append(sentence[0].upper() + sentence[1:])
    return " ".join(s if s.endswith((".", "!", "?")) else s + "." for s in kept)


def tidy(out: dict) -> dict:
    """A model's answer brought to the controlled vocabulary: English words turned Vietnamese, things named one way."""
    out = dict(out)
    for key in ("mo_ta", "khac_truoc", "boi_canh"):
        if isinstance(out.get(key), str):
            out[key] = vocab.mend(out[key]).strip()
    if isinstance(out.get("mo_ta"), str):
        out["mo_ta"] = plain(out["mo_ta"])
    for key, _ in LAYERS:
        if isinstance(out.get(key), str):
            value = FEELING.sub("", vocab.mend(out[key])).strip().rstrip(".")
            out[key] = "" if vocab.norm(value) in UNKNOWN or ABSENT.search(value) or CAMERA_TALK.search(value) else value
    if isinstance(out.get("chu_the"), list):
        things = []
        for v in out["chu_the"]:
            if isinstance(v, dict):                       # a small model sometimes answers a thing as a record: keep its words
                v = " ".join(str(x) for x in v.values() if x and vocab.norm(str(x)) not in UNKNOWN)
            v = vocab.mend(str(v)).strip()
            low = vocab.norm(v)
            if v and low not in UNKNOWN and not low.startswith("không ") and not FEELING_THING.search(low) and low not in (vocab.norm(t) for t in things):
                things.append(v)
        out["chu_the"] = things
    for key in ("chu_tren_hinh", "boi_canh"):
        if vocab.norm(str(out.get(key) or "")) in UNKNOWN:
            out[key] = ""
    actions = []
    for a in out.get("hanh_dong") or []:
        if isinstance(a, dict):
            actions.append({k: vocab.mend(str(a.get(k) or "")).strip() for k in ("ai", "lam_gi", "voi") if vocab.norm(str(a.get(k) or "")) not in UNKNOWN})
        elif str(a).strip() and vocab.norm(str(a)) not in UNKNOWN:
            actions.append({"ai": "", "lam_gi": vocab.mend(str(a)).strip(), "voi": ""})
    out["hanh_dong"] = [{"ai": a.get("ai", ""), "lam_gi": a.get("lam_gi", ""), "voi": a.get("voi", "")} for a in actions if a.get("lam_gi")]
    relations = []
    for r in out.get("quan_he") or []:
        if isinstance(r, (list, tuple)) and len(r) == 3 and vocab.canonical(str(r[1])) in vocab.RELATIONS:
            relations.append([vocab.canonical(str(r[0])), vocab.canonical(str(r[1])), vocab.canonical(str(r[2]))])
    out["quan_he"] = relations
    return out


def text_of(out: dict, profile: dict, labels: dict) -> str:
    """The text a beat is found by: what the model saw, what is new in it, and what the machine measured, in plain words."""
    parts = [str(out.get("mo_ta", "")).strip()]
    parts += [f"{name}: {out[key]}." for key, name in LAYERS if isinstance(out.get(key), str) and out[key]]
    new = str(out.get("khac_truoc") or "").strip()
    things = out.get("chu_the") or []
    # What is new, when it is not everything: the things of two beats are often named differently, and every one then looks new.
    everything = {vocab.norm(str(t)) for t in things} if isinstance(things, list) else set()
    if new and vocab.norm(new) not in ("tiếp diễn", "không", "không có gì khác") and {vocab.norm(x) for x in new.split(", ")} != everything:
        parts.append(f"Điểm mới: {new}.")
    if isinstance(things, list) and things:
        parts.append(f"Thấy: {', '.join(str(v) for v in things)}.")
    actions = out.get("hanh_dong") or []
    if actions:
        said = [" ".join(x for x in (a.get("ai"), a.get("lam_gi"), a.get("voi")) if x) if isinstance(a, dict) else str(a) for a in actions]
        parts.append(f"Hành động: {', '.join(said)}.")
    if out.get("boi_canh"):
        parts.append(f"Nơi: {out['boi_canh']}.")
    measured = []
    size = (profile.get("shot_size") or {}).get("value") or vocab.canonical(str(out.get("co_canh") or ""))
    if size in vocab.SHOT_SIZES:
        measured.append(f"cảnh {size}")
    camera = (labels.get("camera") or {}).get("value")
    if camera in CAMERA_WORDS:
        measured.append(CAMERA_WORDS[camera])
    if measured:
        parts.append(("Hình: " + "; ".join(measured)).rstrip(".") + ".")
    text = (profile.get("text") or {}).get("value") or ([out["chu_tren_hinh"]] if out.get("chu_tren_hinh") else [])
    if text:
        parts.append(f"Chữ trên hình: {'; '.join(text[:3])}.")
    return " ".join(p for p in parts if p)


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
                 structure_of=None, profile_of=None, signals_of=None):
        self._assets, self._index, self._adapters, self._media = assets, index, adapters, Path(media_dir)
        self._signals_of = signals_of or (lambda asset_id: None)
        self.store = None                                       # the canonical model, once the domain has handed it over
        self._profile_of = profile_of or (lambda asset_id: {})          # the measured and recognised fields of each beat, by (start, end)
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
        # Frames are drawn into a folder of this attempt's own and the chosen ones are then moved into the footage's folder
        # under the name of their place in time. Two runs over the same footage (one started when its words became known,
        # while another was still describing) therefore never take a frame from under each other: a frame, once kept, stays.
        kept = self._media / original.checksum[:2] / f"{original.checksum}_beats{BEAT_WIDTH}"
        kept.mkdir(parents=True, exist_ok=True)
        drawn = kept.with_name(f"{kept.name}.{ctx.claim.attempt_id or 'draw'}")
        try:
            whole = self._assets.path_of(original)
            on_original = whole.is_file()
            frames = self._adapters.submit("ffmpeg", Request("frames", inputs={"path": str(whole if on_original else source)}, params={
                "out_dir": str(drawn), "fps": BEAT_FRAME_FPS, "width": BEAT_WIDTH, "quality": 2,
                "color_transfer": original.metadata.get("probe", {}).get("color_transfer") if on_original else None}, attempt_id=ctx.claim.attempt_id)).outputs["frames"]
            segments = []
            fields = self._profile_of(ctx.subject_ref) or {}
            for beat in structure["beats"]:
                picks = []
                for t in beat["frames"] if frames else []:
                    made = Path(frames[min(len(frames) - 1, max(0, round(t * BEAT_FRAME_FPS)))])
                    place = kept / made.name
                    if not place.is_file() and made.is_file():
                        os.replace(made, place)
                    if str(place) not in picks:
                        picks.append(str(place))
                start, end = to_seconds(beat["start"], 2), to_seconds(beat["end"], 2)
                segments.append({"t_start": start, "t_end": end, "frames": picks, "labels": beat["labels"], "shot": beat["shot"],
                                 "start_tick": beat["start"], "end_tick": beat["end"], "profile": fields.get((start, end), {})})
        finally:
            shutil.rmtree(drawn, ignore_errors=True)
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
        probe = self._assets.original(ctx.subject_ref).metadata.get("probe", {})
        spoken = [w for m in self._index.moments(ctx.subject_ref, level="speech") for w in m.data.get("words", [])]
        before: list[str] = []                        # the things named in the beat before this one, in the same shot
        last_shot = None
        for i, seg in enumerate(ctx.inputs["segments"]["segments"]):
            if ctx.should_stop():
                break
            measured = {k: seg[k] for k in ("labels", "shot", "start_tick", "end_tick", "profile") if k in seg}
            if seg.get("shot") != last_shot:
                before, last_shot = [], seg.get("shot")
            words = " ".join(w["text"] for w in spoken if w["end"] > seg["t_start"] and w["start"] < seg["t_end"])
            facts = facts_of(seg.get("profile") or {}, seg.get("labels") or {}, words) if measured else ""
            # A beat's description answers one question: these frames, with this note and these measurements. The rule that divided
            # the footage is not part of it, so a beat whose bounds, frames and measurements a new division leaves alone keeps
            # what was said about it.
            if measured:
                analyzer = ":".join([BEAT_PROMPT_VERSION, f"w{BEAT_WIDTH}", "beat", hashlib.sha1("|".join(Path(f).name for f in seg["frames"]).encode()).hexdigest()[:8],
                                     hashlib.sha1(facts.encode()).hexdigest()[:8], vocab.VERSION, *whole.split(":")[2:]])
            else:
                analyzer = whole
            existing = self._index.get(ctx.subject_ref, "segment", seg["t_start"], seg["t_end"])
            if existing and (existing.source == "human" or existing.analyzer == analyzer):
                if measured and any(existing.data.get(k) != v for k, v in measured.items()):
                    self._index.merge_data(existing.moment_id, **measured)   # what was measured may have changed; what was said has not
                before = vocab.canonical_list((existing.data.get("detail") or {}).get("chu_the") or [])
                continue                                                    # cached: no model call
            if not seg["frames"]:
                continue
            out, who, frames_shown = None, None, 0
            # A small model shown many frames at once sometimes answers with something that is not JSON. It is then shown fewer:
            # the first, the middle and the last say most of what the stretch holds; failing that, the middle one alone.
            middle = seg["frames"][len(seg["frames"]) // 2]
            for shown in (seg["frames"], [seg["frames"][0], middle, seg["frames"][-1]] if len(seg["frames"]) > 3 else None, [middle] if len(seg["frames"]) > 1 else None):
                if shown is None:
                    continue
                gap = (seg["t_end"] - seg["t_start"]) / max(len(shown) - 1, 1) if measured else 1 / FRAME_FPS
                if measured:
                    prompt = BEAT_PROMPT.format(n=len(shown), gap=round(gap, 1), facts=facts, names=", ".join(vocab.LOCAL_NAMES), places=", ".join(vocab.PLACES))
                else:
                    prompt = DESCRIBE_PROMPT.format(n=len(shown), gap=round(gap, 1))
                prompt += CONTEXT_NOTE.format(context=context)
                try:
                    answer = self._adapters.submit("model", Request("describe", inputs={"images": shown},
                                                                   params={"prompt": prompt, "index": i, "max_tokens": 900 if measured else 700},
                                                                   attempt_id=ctx.claim.attempt_id)).outputs
                    out, frames_shown = answer["json"], len(shown)
                    who = answer.get("model")
                    break
                except AdapterError as err:
                    if err.code is not ErrorCode.OUTPUT_INVALID:
                        raise
            if out is None:
                unreadable += 1                      # one bad answer must not cost the whole video; the segment stays undescribed
                continue
            if self._assets.asset(ctx.subject_ref) is None:
                break                                # the footage was deleted while it was being described: nothing more is written for it
            data = {"frame": seg["frames"][len(seg["frames"]) // 2], "frames": seg["frames"], **measured,
                    # Provenance (design 2026-10-14, group 16): which model said it, asked what, shown how many frames, when.
                    "provenance": {"model": who, "prompt": BEAT_PROMPT_VERSION if measured else PROMPT_VERSION, "vocabulary": vocab.VERSION,
                                   "frames_shown": frames_shown, "facts": facts or None, "at": round(__import__("time").time())}}
            if measured:
                foreign = vocab.foreign_words(" ".join(str(out.get(k) or "") for k in ("mo_ta", "khac_truoc", "boi_canh")))
                out = tidy(out)
                data["model_labels"] = model_labels(out, seg.get("profile") or {})
                data["flags"] = [{**f, "state": "open"} for f in cross_checks(seg.get("profile") or {}, out, seg.get("labels") or {}, has_audio=bool(probe.get("has_audio")))]
                if foreign and not any(f["rule"] == "ngôn ngữ" for f in data["flags"]):
                    data["flags"].append({"rule": "ngôn ngữ", "message": "câu trả lời có từ ngoài tiếng Việt: " + ", ".join(foreign[:5]), "state": "open"})
                named = vocab.canonical_list(out.get("chu_the") or [])
                tags = ((seg.get("profile") or {}).get("scene_tags") or {}).get("value") or []
                out["khac_truoc"] = ", ".join(t for t in named if t not in before) if before else ""
                data["new_things"] = [t for t in named if t not in before] if before else named
                data["continues"] = bool(before) and not data["new_things"]
                data["recognised_tags"] = tags
            data["detail"] = out
            self._index.upsert(ctx.subject_ref, "segment", seg["t_start"], seg["t_end"], text_of(out, seg.get("profile") or {}, seg.get("labels") or {}),
                               data=data, analyzer=analyzer)
            before = vocab.canonical_list(out.get("chu_the") or []) or before
            done += 1
            ctx.heartbeat()
        if self.store is not None and self._assets.asset(ctx.subject_ref) is not None:
            from nexora.modules.intelligence import publish
            from nexora.modules.intelligence.analyzers import BY_NAME
            publish.descriptions(self.store, ctx.subject_ref, self._index.moments(ctx.subject_ref, level="segment"), BY_NAME["describe"])
        return {"described": done, "unreadable": unreadable}

    def _events(self, asset_id: str, segments) -> int:
        """Join beats showing one action into events (design group 07) and make them findable."""
        from nexora.modules.intelligence.profile import events_of
        structure = self._structure_of(asset_id) or {}
        shots = [{"start": to_seconds(s["start"], 2), "end": to_seconds(s["end"], 2)} for s in structure.get("shots", [])]
        found = self._signals_of(asset_id)
        motion = None
        if found is not None and len(getattr(found, "subject", [])):
            fps = found.fps
            motion = lambda a, b: float(found.subject[int(a * fps):max(int(a * fps) + 1, int(b * fps))].mean())
        beats = [{"start": m.t_start, "end": m.t_end, "shot": m.data.get("shot"), "detail": m.data.get("detail") or {}} for m in segments]
        made = events_of(beats, shots, motion, (found.subject, found.fps) if motion else None)
        by_start = {m.t_start: m for m in segments}
        for e in made[:MAX_STATES]:
            first, last = by_start.get(e["phases"]["bắt đầu"][0]), by_start.get(e["phases"]["kết thúc"][0])
            frames = [f for f in ((first.data.get("frames") or [None])[0] if first else None, (last.data.get("frames") or [None])[-1] if last else None) if f]
            if len(frames) == 2 and frames[0] != frames[1]:
                try:
                    said = self._adapters.submit("model", Request("describe", inputs={"images": frames}, params={
                        "prompt": STATE_PROMPT.format(what=f"{e['who']} {', '.join(e['actions'])}".strip()), "task": "state", "max_tokens": 200})).outputs["json"]
                    e["before"], e["after"] = vocab.mend(str(said.get("truoc") or "")), vocab.mend(str(said.get("sau") or ""))
                except AdapterError:
                    pass                                   # an event without its states is still an event
        if self.store is not None and self._assets.asset(asset_id) is not None:
            from nexora.modules.intelligence import publish
            from nexora.modules.intelligence.analyzers import BY_NAME
            publish.events(self.store, asset_id, made, BY_NAME["events"])
        self._index.remove(asset_id, "event")
        for e in made:
            cut = ", bị cụt đầu" if e["cut_start"] else ""
            cut += ", bị cụt đuôi" if e["cut_end"] else ""
            states = f" Trước: {e['before']} Sau: {e['after']}" if e.get("before") and e.get("after") else ""
            self._index.upsert(asset_id, "event", e["start"], e["end"], f"Sự việc: {(e['who'] + ' ') if e['who'] else ''}{', '.join(e['actions'])}{cut}.{states}",
                               data={"event": e}, analyzer=self.analyzer)
        return len(made)

    def _summarise(self, ctx):
        segments = self._index.moments(ctx.subject_ref, level="segment")
        if not segments:
            return {"skipped": "nothing to summarise"}
        self._events(ctx.subject_ref, segments)
        speech = self._index.moments(ctx.subject_ref, level="speech")
        rows = sorted([(m.t_start, f"[{clock(m.t_start)}] {m.text}") for m in segments] + [(m.t_start, f"[{clock(m.t_start)}] (lời nói) {m.text}") for m in speech])
        lines = self.context(ctx.subject_ref) + "\n\n" + "\n".join(r for _, r in rows)[:12000]
        out = self._adapters.submit("model", Request("chat", params={"prompt": SUMMARY_PROMPT.format(lines=lines, genres=", ".join(vocab.GENRES), emotions=", ".join(vocab.EMOTIONS)),
                                                                    "json": True, "max_tokens": 900}, attempt_id=ctx.claim.attempt_id)).outputs["json"]
        out = grounded(out, [m.text for m in segments] + [m.text for m in speech], {clock(m.t_start) for m in segments} | {clock(m.t_start) for m in speech})
        if self.store is not None and self._assets.asset(ctx.subject_ref) is not None:
            from nexora.modules.intelligence import publish
            publish.summary(self.store, ctx.subject_ref, out)
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
