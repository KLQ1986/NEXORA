"""Things, subjects and sounds followed across a recording and the library (design 2026-10-15, section 9 E).

A beat says what it shows; these join what the beats say into entities that last: a thing named in beat after beat is one
appearance, even across a cut; a person or an animal tracked in one shot is the same one in the next when their pictures are
alike; a sound heard is tied to what in the picture could make it, or said to come from out of frame.

Pure functions over what was kept; the profiler gathers their inputs and the domain publishes what they make.
"""
import re

import numpy as np

from nexora.modules.intelligence import vocab

# Words that say how a thing looks, not what it is: "thuyền thúng màu xanh lá" and "thuyền thúng xanh" are one thing.
_LOOKS = re.compile(r"\s+(màu\s+\S+(\s+(lá cây|lá|dương|nhạt|đậm|trắng))?|(xanh|đỏ|vàng|trắng|đen|nâu|tím|cam|hồng|xám)(\s+(lá cây|lá|dương|nhạt|đậm))?"
                    r"|lớn|nhỏ|to|cao|thấp|dài|ngắn|cũ|mới|đơn độc|xanh mướt|ở xa|ở gần|phía xa|phía trước|khác)\b.*$")
_COUNT = re.compile(r"^(một vài|một|vài|nhiều|hai|ba|bốn|năm|các|những|mấy)\s+(chiếc|cái|con|cây|bông|bụi|ngôi|toà|tòa)?\s*")


# What older descriptions listed among the things seen and is not one: what is not there, and how a place feels.
NOT_A_THING = re.compile(r"^không\b|không gian|bầu không khí|cảm giác")


def thing_name(said: str) -> str:
    """The name a thing is followed by: its canonical name without how many there are or how they look."""
    name = vocab.canonical(_COUNT.sub("", vocab.norm(said)))
    base = _LOOKS.sub("", name).strip(" ,.")
    return base or name


def things_of(beats: list[dict]) -> list[dict]:
    """Things named in the beats of the library, each with where it appears. `beats`: {asset_id, start, end, shot, things} in
    order within each recording. A thing named in beats in a row of one recording is one appearance, and `across_cut` says
    when that appearance runs over a cut. Returns {name, said (the ways it was named), appearances, assets}."""
    found: dict[str, dict] = {}
    by_asset: dict[str, list[dict]] = {}
    for b in beats:
        by_asset.setdefault(b["asset_id"], []).append(b)
    for asset_id, rows in by_asset.items():
        open_: dict[str, dict] = {}
        for k, b in enumerate(sorted(rows, key=lambda r: r["start"])):
            here = {}
            for said in b.get("things") or []:
                name = thing_name(str(said))
                if len(name) >= 2 and not NOT_A_THING.search(name):
                    here.setdefault(name, str(said))
            for name in list(open_):
                if name not in here:
                    found.setdefault(name, {"name": name, "said": set(), "appearances": []})["appearances"].append(open_.pop(name))
            for name, said in here.items():
                if name in open_:
                    a = open_[name]
                    a["end"] = b["end"]; a["beats"] += 1
                    a["across_cut"] = a["across_cut"] or b.get("shot") != a["shot"]
                    a["shot"] = b.get("shot")
                else:
                    open_[name] = {"asset_id": asset_id, "start": b["start"], "end": b["end"], "beats": 1, "shot": b.get("shot"), "across_cut": False}
                found.setdefault(name, {"name": name, "said": set(), "appearances": []})["said"].add(said)
        for name, a in open_.items():
            found[name]["appearances"].append(a)
    out = []
    for f in found.values():
        apps = [{k: v for k, v in a.items() if k != "shot"} for a in f["appearances"]]
        out.append({"name": f["name"], "said": sorted(f["said"]), "appearances": apps, "assets": sorted({a["asset_id"] for a in apps}),
                    "beats": sum(a["beats"] for a in apps), "across_cut": any(a["across_cut"] for a in apps)})
    return sorted(out, key=lambda x: (-len(x["assets"]), -x["beats"], x["name"]))


def seen_in_pictures(text_vector: np.ndarray, frames: np.ndarray, step: float, spans: list[tuple[float, float]]) -> list[float]:
    """For each span where a thing is said to be, how far its frames answer the thing's name better than the recording's other
    frames: the share of the frames outside the span that score below the span's median. 0.5: no better than the rest; a span
    covering the whole recording has nothing to be held against and gets 0.5 too. Only ranks are used: SigLIP's own
    probabilities for Vietnamese are not to be trusted (design 2026-10-15, section 7)."""
    if not len(frames):
        return [0.5 for _ in spans]
    scores = frames.astype(np.float32) @ text_vector.astype(np.float32)
    out = []
    for a, b in spans:
        i, j = int(a / step), max(int(a / step) + 1, int(b / step))
        part, rest = scores[i:j], np.concatenate([scores[:i], scores[j:]])
        out.append(round(float((rest < float(np.median(part))).mean()), 3) if len(part) and len(rest) else 0.5)
    return out


# What can make a sound, by the words a beat names things with. Speech, laughter and singing come from people.
SOURCES = {
    "sóng biển": ("biển", "sóng", "bờ biển", "bãi biển", "mặt biển"), "nước": ("nước", "suối", "thác", "sông", "biển", "vòi"),
    "suối chảy": ("suối",), "thác nước": ("thác",), "mưa": ("mưa",), "vòi nước": ("vòi nước", "vòi", "bồn rửa"),
    "chim hót": ("chim",), "gà gáy": ("gà",), "gà": ("gà",), "chó sủa": ("chó",), "chó": ("chó",), "mèo kêu": ("mèo",), "mèo": ("mèo",),
    "vịt kêu": ("vịt",), "bò": ("bò",), "dế kêu": ("cỏ", "bụi cây"), "ếch kêu": ("ao", "hồ", "ruộng"),
    "xe cộ": ("xe", "ô tô", "xe máy", "đường"), "xe chạy qua": ("xe", "ô tô", "xe máy"), "còi xe": ("xe", "ô tô", "xe máy"),
    "xe máy": ("xe máy",), "xe tải": ("xe tải",), "xe buýt": ("xe buýt",), "động cơ": ("xe", "thuyền", "máy", "ô tô"),
    "thuyền": ("thuyền", "ghe", "tàu"), "thuyền máy": ("thuyền", "ghe", "ca nô"), "tàu hoả": ("tàu hoả", "đường ray"),
    "máy bay": ("máy bay",), "trực thăng": ("trực thăng",), "tiếng chuông": ("chuông", "chùa", "nhà thờ"), "chuông gió": ("chuông gió",),
    "lá xào xạc": ("cây", "lá", "tán lá"), "gió": ("cây", "lá", "cờ"), "lửa tí tách": ("lửa", "bếp"), "lửa": ("lửa",),
    "tiếng chiên xào": ("chảo", "bếp"), "tiếng sôi": ("nồi", "ấm", "bếp"), "bát đĩa va chạm": ("bát", "đĩa"), "thái đồ ăn": ("dao", "thớt"),
    "máy xay": ("máy xay",), "rót nước": ("cốc", "ly", "chai", "ấm"), "gõ phím": ("bàn phím", "máy tính"), "quạt": ("quạt",),
    "nhạc": ("đàn", "loa", "ca sĩ", "nhạc công", "trống"), "trống": ("trống",), "pháo hoa": ("pháo hoa",), "tiếng cửa": ("cửa",),
}
FROM_PEOPLE = ("lời nói", "tiếng trò chuyện", "tiếng cười", "tiếng hát", "la hét", "thì thầm", "tiếng khóc", "vỗ tay", "reo hò", "đám đông",
               "tiếng bước chân", "tiếng ho", "tiếng huýt sáo", "tiếng ngân nga", "trẻ em la")


def sound_sources(sounds: list[dict], beats: list[dict]) -> list[dict]:
    """Every sound heard, with what in the picture could make it. `sounds`: {kind, start, end}. `beats`: {start, end, things,
    people (a count or "không"), speaker ("trong khung" or "ngoài khung")}. A sound whose maker is not in the picture is said to
    come from out of frame; one the vocabulary cannot place is left unplaced, not guessed."""
    out = []
    for s in sounds:
        kind = s["kind"]
        over = [b for b in beats if b["end"] > s["start"] and b["start"] < s["end"]]
        if not over:
            continue
        if kind in FROM_PEOPLE:
            in_frame = any(b.get("speaker") == "trong khung" for b in over) if kind == "lời nói" else \
                any(b.get("people") not in (None, "không", 0) for b in over)
            out.append({**s, "source": "người", "seen": in_frame, "where": "trong khung" if in_frame else "ngoài khung"})
            continue
        makers = SOURCES.get(kind)
        if not makers:
            out.append({**s, "source": None, "seen": None, "where": "chưa rõ"})
            continue
        named = [str(t) for b in over for t in b.get("things") or []]
        hit = next((t for t in named if any(re.search(rf"\b{re.escape(m)}\b", vocab.norm(t)) for m in makers)), None)
        out.append({**s, "source": hit or makers[0], "seen": hit is not None, "where": "trong khung" if hit else "ngoài khung"})
    return out


def subjects_of(tracks: list[dict], vectors: list[np.ndarray | None], *, same: float = 0.88) -> list[int | None]:
    """Which tracks are one subject: people and animals followed inside a shot are joined across cuts, and across
    recordings, when the pictures of them are alike (SigLIP 2 vectors of their crops, the mean over each track). Two tracks
    seen at the same time in one recording are never one subject; nor are a person and an animal. Returns a subject number a
    track, None for a track without pictures."""
    n = len(tracks)
    unit = [None if v is None else v / max(float(np.linalg.norm(v)), 1e-9) for v in vectors]
    parent = list(range(n))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def together(i: int, j: int) -> bool:
        a, b = tracks[i], tracks[j]
        return a.get("asset_id") == b.get("asset_id") and a["start"] < b["end"] and b["start"] < a["end"]

    pairs = sorted(((float(unit[i] @ unit[j]), i, j) for i in range(n) for j in range(i + 1, n)
                    if unit[i] is not None and unit[j] is not None and tracks[i]["kind"] == tracks[j]["kind"]), reverse=True)
    members = {i: [i] for i in range(n)}
    for score, i, j in pairs:
        if score < same:
            break
        ri, rj = root(i), root(j)
        if ri == rj or any(together(x, y) for x in members[ri] for y in members[rj]):
            continue
        parent[rj] = ri
        members[ri] += members.pop(rj)
    roots = {}
    return [None if unit[i] is None else roots.setdefault(root(i), len(roots)) for i in range(n)]
