"""Which neighbouring shots of a cut should have their colour matched, and how.

Footage from different sources cut together (a DJI shot beside a phone's, stock, an AI clip) does not look like one film even
when each is right on its own. Measured on the library (2026-10-17), the colour gap cannot tell this case: two moments of one
clip sat as far apart (up to 7.4) as two different clips (median 7.0), since a camera that turns sees other things. So a pair is
proposed by what it is made from: two different sources side by side, the camera (or what made the picture) not being the
same. Screens and graphics are never proposed: their colours are the content. The way to match follows what Video
Intelligence knows: two shots of one place match their whole spread of colours (`scene`), others only the camera's look
(`look`). The source the cut uses most is the reference and stays as it is; the other side is brought to it. The match itself
is a step of Visual Quality's recipe for that source, proposed there and approved like any step.
"""
from __future__ import annotations

from collections import Counter

from nexora.core.intelligence import VideoIntelligence
from nexora.core.projects import ProjectStore
from nexora.core.visual_quality import VisualQuality

NEVER = ("screen", "graphics")


def source_of(vq: VisualQuality, asset_id: str) -> dict:
    """What made a picture, as Visual Quality profiled it: the device, the encoding and the kind of content."""
    profile = vq.profile(asset_id) or {}
    technical = profile.get("technical") or {}
    device = technical.get("device") or " ".join(str(v) for v in (technical.get("make"), technical.get("model")) if v) or None
    encoding, content = profile.get("encoding"), profile.get("content")
    return {"device": device, "encoding": encoding, "content": content, "profiled": bool(profile),
            "key": (device or "?", encoding or "?", content or "?"), "name": device or profile.get("encoding_name") or "không rõ máy"}


def _same_source(a: dict, b: dict) -> bool:
    if a["device"] and b["device"]:
        return a["device"] == b["device"] and a["encoding"] == b["encoding"]
    return False                                     # a side whose maker is not known (stock, the web) is another source


def _place(vi: VideoIntelligence, a: str, ta: float, b: str, tb: float) -> str | None:
    """A place Video Intelligence saw in both shots at the times used (in both sources, when the times are not covered)."""
    places = vi.entities("place")

    def at(e, asset, t, exact):
        return any(x["asset_id"] == asset and (not exact or x["t_start"] - 0.5 <= t <= x["t_end"] + 0.5) for x in e["appearances"])
    for exact in (True, False):
        for e in places:
            if at(e, a, ta, exact) and at(e, b, tb, exact):
                return e["name"] or (e.get("data") or {}).get("name") or e["key"]
    return None


def _state(vq: VisualQuality, asset_id: str, reference: str) -> str:
    """Whether the source already has a match to the reference: in its approved recipe, in a newer proposed one, or not."""
    def has(recipe):
        return recipe is not None and any(s["op"] == "match" and not s.get("off") and (s.get("params") or {}).get("reference", {}).get("subject") == reference
                                          for shot in recipe.shots for s in shot.get("steps", []))
    if has(vq.recipe(asset_id, status="approved")):
        return "approved"
    if has(vq.recipe(asset_id)):
        return "proposed"
    return "none"


def colour_pairs(projects: ProjectStore, vq: VisualQuality, vi: VideoIntelligence, project_id: str) -> list[dict]:
    """The neighbouring shots of a project's cut that come from different sources, each with the side to change, the reference
    and the time in it, the way to match, and whether it has been done."""
    script = projects.current_script(project_id)
    if script is None:
        return []
    used = []
    for shot in script["shots"]:
        sel = projects.selection(shot.shot_id)
        if sel is None or sel.status == "gap" or not sel.asset_id:
            used.append(None)
            continue
        t_in = float(sel.t_in or 0.0)
        t_out = float(sel.t_out) if sel.t_out is not None else t_in + 2.0
        used.append({"position": shot.position, "shot_id": shot.shot_id, "asset_id": sel.asset_id, "t": round((t_in + t_out) / 2, 2),
                     "source": source_of(vq, sel.asset_id)})
    weight = Counter(u["source"]["key"] for u in used if u)
    pairs = []
    for a, b in zip(used, used[1:]):
        if not a or not b or a["asset_id"] == b["asset_id"]:
            continue
        sa, sb = a["source"], b["source"]
        if sa["content"] in NEVER or sb["content"] in NEVER or _same_source(sa, sb):
            continue
        # The source the cut leans on is the reference; on a tie, the earlier shot.
        ref, change = (b, a) if weight[sb["key"]] > weight[sa["key"]] else (a, b)
        place = _place(vi, a["asset_id"], a["t"], b["asset_id"], b["t"])
        pairs.append({
            "after": a["position"], "shots": [a["shot_id"], b["shot_id"]],
            "reference": {"asset_id": ref["asset_id"], "t": ref["t"], "source": ref["source"]["name"]},
            "change": {"asset_id": change["asset_id"], "t": change["t"], "source": change["source"]["name"]},
            "mode": "scene" if place else "look", "place": place,
            "ready": sa["profiled"] and sb["profiled"],                 # both analysed by Visual Quality, or there is nothing to match with
            "state": _state(vq, change["asset_id"], ref["asset_id"]),
        })
    return pairs
