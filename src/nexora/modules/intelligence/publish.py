"""What each analyzer learnt, put into the canonical model (design 2026-10-15, section 3.2).

Every analyzer keeps its own working files beside the footage (measures, frames looked at, sound listened to). These
functions turn what it found into segments and observations, with one name per field whatever the source: a model's "co_canh"
and the measured shot size are both `shot_size`, from two sources, fused when read. They are called at the end of each stage,
and over the files already kept when a library is moved to the canonical model, so nothing is analysed again for it.
"""
from dataclasses import replace

from nexora.core.intelligence import Analyzer
from nexora.core.intelligence_store import IntelligenceStore
from nexora.core.timebase import to_seconds

# A model's label names, to the canonical field names.
MODEL_FIELDS = {"co_canh": "shot_size", "so_nguoi": "people", "noi_chon": "place", "goc_may": "angle", "goc_nhin": "viewpoint", "thoi_diem": "time_of_day",
                "loai_noi_dung": "content_kind", "huong_sang": "light_direction", "cam_xuc": "emotion"}


def _label_rows(start: float, end: float, labels: dict, default_source: str) -> list[tuple]:
    rows = []
    for field, label in (labels or {}).items():
        if not isinstance(label, dict) or "value" not in label:
            continue
        evidence = {k: v for k, v in label.items() if k not in ("value", "source", "confidence")}
        rows.append((start, end, field, label["value"], label.get("source", default_source), label.get("confidence", "medium"), evidence))
    return rows


def structure(store: IntelligenceStore, asset_id: str, made: dict, analyzer: Analyzer) -> None:
    """Shots and beats, and what was measured on every beat."""
    shots = [(to_seconds(s["start"], 3), to_seconds(s["end"], 3), {"transition_in": s.get("transition_in"), "pinned": s.get("pinned", False)}) for s in made.get("shots", [])]
    beats = [(to_seconds(b["start"], 3), to_seconds(b["end"], 3), {"shot": b.get("shot"), "pinned": b.get("pinned", False), "frames": b.get("frames", [])})
             for b in made.get("beats", [])]
    store.replace_segments(asset_id, "shot", shots, analyzer=f"{analyzer.name}@{analyzer.version}")
    store.replace_segments(asset_id, "beat", beats, analyzer=f"{analyzer.name}@{analyzer.version}")
    rows = [r for b in made.get("beats", []) for r in _label_rows(to_seconds(b["start"], 3), to_seconds(b["end"], 3), b.get("labels", {}), "measured")]
    store.observe_many(asset_id, rows, analyzer=f"{analyzer.name}@{analyzer.version}", replace=tuple({r[2] for r in rows}))
    store.ran(asset_id, analyzer)


def profile(store: IntelligenceStore, asset_id: str, made: dict, *, probe: dict, artifacts: dict, analyzers: list[Analyzer]) -> None:
    """The profile of a recording: fields beat by beat, text on screen, kinds of sound, people and things followed, the whole file."""
    tag = "+".join(f"{a.name}@{a.version}" for a in analyzers)
    rows = [r for b in made.get("beats", []) for r in _label_rows(b["start"], b["end"], b.get("profile", {}), "measured")]
    store.observe_many(asset_id, rows, analyzer=tag, replace=tuple({r[2] for r in rows}))
    spans = [(s["start"], s["end"], {**s, "type": "text"}) for s in made.get("text_spans", [])] + \
            [(e["start"], e["end"], {**e, "type": "sound"}) for e in made.get("sound_events", [])] + \
            [(t["start"], t["end"], {**t, "type": "track"}) for t in made.get("tracks", [])]
    store.replace_segments(asset_id, "span", spans, analyzer=tag)
    store.recording(asset_id, technical={k: v for k, v in probe.items() if k not in ("still",)}, summary={"profile": made.get("asset", {})})
    for kind, path in artifacts.items():
        store.artifact(asset_id, kind, path, analyzer=tag)
    for a in analyzers:
        store.ran(asset_id, a)


def descriptions(store: IntelligenceStore, asset_id: str, beats: list, analyzer: Analyzer) -> None:
    """What a model saw in each beat: its description, its labels under their canonical names, and where it disagreed with a measure."""
    rows = []
    for m in beats:
        detail = m.data.get("detail") or {}
        evidence = {"frames": m.data.get("frames"), **(m.data.get("provenance") or {})}
        if m.text:
            rows.append((m.t_start, m.t_end, "description", m.text, "human" if m.source == "human" else "model", "medium", evidence))
        for key, label in (m.data.get("model_labels") or {}).items():
            field = MODEL_FIELDS.get(key)
            if field and isinstance(label, dict):
                rows.append((m.t_start, m.t_end, field, label["value"], "model", label.get("confidence", "medium"), evidence))
        for key in ("chu_the", "hanh_dong", "quan_he"):
            if detail.get(key):
                rows.append((m.t_start, m.t_end, {"chu_the": "things", "hanh_dong": "actions", "quan_he": "relations"}[key], detail[key], "model", "medium", evidence))
        if m.data.get("flags"):
            rows.append((m.t_start, m.t_end, "flags", m.data["flags"], "measured", "high", {}))
    fields = tuple({r[2] for r in rows if r[4] == "model"} | {"flags"})
    store.observe_many(asset_id, rows, analyzer=f"{analyzer.name}@{analyzer.version}", replace=fields)
    # A recording counts as described at the oldest prompt any of its beats was described with, so that one described before
    # the prompt changed is seen to be out of date, even when its texts were put into words again since.
    asked = sorted({(m.data.get("provenance") or {}).get("prompt") or "" for m in beats if m.data.get("detail")})
    store.ran(asset_id, analyzer if not asked or asked[0] == analyzer.version else replace(analyzer, version=asked[0] or "?"))


def pictures(store: IntelligenceStore, asset_id: str, path: str, analyzer: Analyzer) -> None:
    """The frames of a recording as vectors of the picture-and-words model, for search by what is in the picture."""
    store.artifact(asset_id, "pictures", path, analyzer=f"{analyzer.name}@{analyzer.version}")
    store.ran(asset_id, analyzer)


def summary(store: IntelligenceStore, asset_id: str, detail: dict) -> None:
    store.recording(asset_id, summary={"description": detail})


def events(store: IntelligenceStore, asset_id: str, found: list[dict], analyzer: Analyzer) -> None:
    store.replace_segments(asset_id, "event", [(e["start"], e["end"], e) for e in found], analyzer=f"{analyzer.name}@{analyzer.version}")
    store.ran(asset_id, analyzer)


def speech(store: IntelligenceStore, asset_id: str, sentences: list, analyzer: Analyzer) -> None:
    """What was said, sentence by sentence, with its words, and who said it."""
    store.replace_segments(asset_id, "sentence", [(m.t_start, m.t_end, {"text": m.text, "words": m.data.get("words", []), "speaker": m.data.get("speaker")})
                                                  for m in sentences], analyzer=f"{analyzer.name}@{analyzer.version}")
    rows = [(m.t_start, m.t_end, "speaker_id", m.data["speaker"]["value"], "measured", m.data["speaker"].get("confidence", "medium"), {})
            for m in sentences if (m.data.get("speaker") or {}).get("value") is not None]
    store.observe_many(asset_id, rows, analyzer=f"{analyzer.name}@{analyzer.version}", replace=("speaker_id",))
    store.ran(asset_id, analyzer)


def scenes(store: IntelligenceStore, made: list[dict], asset_ids: list[str], analyzer: Analyzer) -> None:
    """The scenes of a shoot, in each recording they pass through."""
    for asset_id in asset_ids:
        mine = [(b["start"], b["end"], {"scene": s["number"], "name": s["name"], "why": s["why"], "assets": s["assets"]})
                for s in made for b in s["beats"] if b["asset_id"] == asset_id]
        joined: list[tuple] = []
        for a, b, data in mine:
            if joined and joined[-1][2]["scene"] == data["scene"]:
                joined[-1] = (joined[-1][0], b, data)
            else:
                joined.append((a, b, data))
        store.replace_segments(asset_id, "scene", joined, analyzer=f"{analyzer.name}@{analyzer.version}")
        store.ran(asset_id, analyzer)


def entities(store: IntelligenceStore, kind: str, groups: list[dict]) -> None:
    """People (faces grouped) or places (pictures grouped), with every appearance, keeping the names the operator gave."""
    keep = set()
    for g in groups:
        key = g.get("key") or f"{kind}:" + ",".join(sorted({f"{a['asset_id']}@{a.get('start', a.get('t'))}" for a in g["appearances"][:3]}))
        keep.add(key)
        seen = [(a["asset_id"], float(a.get("start", a.get("t", 0.0))), float(a.get("end", a.get("t", 0.0) + 0.5)), {k: v for k, v in a.items() if k not in ("asset_id",)})
                for a in g["appearances"]]
        store.entity(kind, key, name=g.get("name") if kind == "person" else None, data={k: v for k, v in g.items() if k not in ("appearances", "key")}, appearances=seen)
    store.drop_entities(kind, keep)
