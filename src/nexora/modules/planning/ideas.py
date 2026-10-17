"""Ideas from the library (design v4.0, 16.6; design 2026-10-18): the footage is grouped first, by subject and by shooting
session, and measured; a model is asked only for the angle of each group and the shots it would need; every needed shot is
then looked for in the index, so what a score says about footage is measured, not taken from the model's opinion."""
from __future__ import annotations

import math
import re
import unicodedata

from nexora.core.adapter import AdapterRegistry, PrivacyClass, Request
from nexora.core.assets import AssetStore
from nexora.core.index import MomentIndex
from nexora.core.projects import ProjectStore

TEXT_ONLY = PrivacyClass.CLOUD_ALLOWED
COVERED = 0.5                  # a needed shot is covered when its best moment scores this much (the radar's threshold)
GAP_SECONDS = 4.0
HOLD = (2.0, 6.0)              # a covered shot holds its moment's length within this range
MIN_SECONDS = 10.0             # a cluster shorter than this cannot carry a video

ANGLE_PROMPT = (
    "Bạn là biên tập viên của một kênh video. {channel}"
    "Đây là một nhóm footage trong kho ({why}):\n{material}\n\n"
    "Đề xuất MỘT ý tưởng video làm được chủ yếu từ nhóm footage này. Các mẫu video có thể dùng: {templates}.\n"
    "Những video đã làm (đừng lặp lại): {past}.\n"
    "Trả về JSON với các khoá: tieu_de (ngắn, dưới 10 chữ, viết như câu thường), goc_ke (một câu: video kể điều gì, theo cách nào), mau (tên một mẫu ở trên), "
    "canh (danh sách 5 đến 8 cảnh cần có, mỗi cảnh một cụm từ ngắn tả HÌNH nhìn thấy được; không ghi âm thanh, lời dẫn hay chữ trên hình), hop_khan_gia (1-5), {fit}"
    "rui_ro (một câu nói điều có thể làm hỏng video, hoặc chuỗi rỗng), "
    "muc_rui_ro (\"chan\" chỉ khi không thể làm video nếu chưa xử lý: người trong hình chưa đồng ý, nội dung riêng tư, thông tin sai hoặc vi phạm pháp luật; "
    "\"luu_y\" cho mọi điều khác; chuỗi rỗng nếu không có rủi ro)."
)


def _fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(ch) != "Mn").replace("đ", "d")


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", _fold(text)) if len(w) > 1}


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


SAME, UNRELATED = 0.85, 0.35    # the embedding's similarity of the same idea said twice, and of two unrelated ones (bge-m3, measured 2026-10-18)
OVERLAP = 0.6                    # a group sharing this much of its footage with one already proposed for is passed over


def _score(x: float) -> int:
    """A share from 0 to 1 as a score from 1 to 5."""
    return max(1, min(5, round(1 + 4 * max(0.0, min(1.0, x)))))


def channel_text(channel: dict | None) -> str:
    """The channel's profile in words, for a prompt: who it is for and how it speaks."""
    if not channel:
        return ""
    parts = [f"Kênh \"{channel['name']}\""]
    for key, label in (("platform", "đăng trên"), ("audience", "người xem"), ("tone", "giọng văn"), ("pacing", "nhịp"), ("notes", "ghi chú")):
        if channel.get(key):
            parts.append(f"{label}: {channel[key]}")
    if channel.get("banned"):
        parts.append("không bao giờ nói: " + ", ".join(f"\"{b}\"" for b in channel["banned"]))
    return "; ".join(parts) + ". "


class IdeaFinder:
    def __init__(self, projects: ProjectStore, assets: AssetStore, index: MomentIndex, adapters: AdapterRegistry):
        self._projects, self._assets, self._index, self._adapters = projects, assets, index, adapters

    # ------------------------------------------------------------------------------------------------------ measured
    def _session(self, asset: dict) -> str:
        if asset.get("session"):
            return asset["session"]
        created = ((self._assets.original(asset["asset_id"]).metadata.get("probe") or {}).get("created") or "")[:10]
        return f"ngày {created}" if created else "không rõ ngày quay"

    def clusters(self) -> list[dict]:
        """The understood footage grouped by subject and by shooting session, each group measured: its seconds, the part no
        project uses, its sessions and the places it shows. Groups with the same footage are one; the most unused first."""
        used = self._projects.used_assets()
        groups: dict[str, dict] = {}
        for asset in self._assets.assets():
            if asset.get("rejected") or asset.get("reference_only"):
                continue
            whole = self._index.moments(asset["asset_id"], level="video")
            if not whole:
                continue
            detail = whole[0].data.get("detail", {})
            seconds = max((m.t_end for m in whole), default=0.0)
            segments = self._index.moments(asset["asset_id"], level="segment")
            session = self._session(asset)
            keys = [("chủ đề", str(t).strip().lower()) for t in dict.fromkeys(detail.get("chu_de") or []) if str(t).strip()] + [("buổi quay", session)]
            for kind, name in keys:
                g = groups.setdefault(f"{kind}:{name}", {"key": f"{kind}:{name}", "kind": kind, "name": name, "assets": [], "seconds": 0.0, "unused_seconds": 0.0,
                                                          "sessions": set(), "places": {}, "samples": []})
                g["assets"].append(asset["asset_id"])
                g["seconds"] += seconds
                g["unused_seconds"] += 0.0 if asset["asset_id"] in used else seconds
                g["sessions"].add(session)
                for s in segments:
                    place = str((s.data.get("detail") or {}).get("boi_canh") or "").strip()
                    if place:
                        g["places"][place] = g["places"].get(place, 0) + 1
                if detail.get("tieu_de") or whole[0].text:
                    g["samples"].append(f"{detail.get('tieu_de') or ''}: {whole[0].text}".strip(": "))
                g["samples"].extend(s.text for s in segments[:3] if s.text)
        seen, out = set(), []
        for g in sorted(groups.values(), key=lambda g: (-g["unused_seconds"], -g["seconds"], g["key"])):
            footprint = frozenset(g["assets"])
            if footprint in seen or g["seconds"] < MIN_SECONDS:
                continue
            seen.add(footprint)
            out.append({**g, "seconds": round(g["seconds"], 1), "unused_seconds": round(g["unused_seconds"], 1), "sessions": sorted(g["sessions"]),
                        "places": [p for p, _ in sorted(g["places"].items(), key=lambda kv: -kv[1])[:4]], "samples": list(dict.fromkeys(g["samples"]))[:8]})
        return out

    def _past(self) -> list[str]:
        """What has been made already: each project's title and the start of its script."""
        out = []
        for p in self._projects.projects():
            script = self._projects.current_script(p["project_id"])
            lines = " ".join(s.text for s in (script or {}).get("shots", [])[:3]) if script else ""
            out.append(f"{p['title']}. {lines}".strip())
        return out

    def _difference(self, text: str, past: list[str]) -> float:
        """How far an idea is from everything already made: 1 minus the closest meaning (the index's embedding), else words."""
        if not past:
            return 1.0
        if self._index.embed is not None:
            try:
                vectors = self._index.embed([text, *past])
                closest = max(_cosine(vectors[0], v) for v in vectors[1:])
                return max(0.0, min(1.0, (SAME - closest) / (SAME - UNRELATED)))
            except Exception:
                pass                                       # the embedding model is unavailable: words alone
        mine = _words(text)
        return 1.0 - max((len(mine & _words(p)) / len(mine | _words(p)) if mine | _words(p) else 0.0) for p in past)

    def _cover(self, needs: list[str]) -> tuple[list[dict], list[str], float]:
        """Each needed shot looked for in the index: the moment that would carry it, or a gap. And the length that makes."""
        shots, gaps, seconds, taken = [], [], 0.0, set()
        for need in needs:
            hits = [h for h in self._index.search(need, limit=5) if h.moment.moment_id not in taken]
            best = hits[0] if hits else None
            if best is not None and best.score >= COVERED:
                m = best.moment
                taken.add(m.moment_id)
                shots.append({"need": need, "covered": True, "moment_id": m.moment_id, "asset_id": m.asset_id, "t_in": m.t_start, "t_out": m.t_end,
                              "score": best.score, "text": m.text})
                seconds += max(HOLD[0], min(HOLD[1], m.t_end - m.t_start))
            else:
                shots.append({"need": need, "covered": False, "score": best.score if best else 0.0})
                gaps.append(need)
                seconds += GAP_SECONDS
        return shots, gaps, round(seconds, 1)

    # ------------------------------------------------------------------------------------------------------ asked
    def propose(self, cluster: dict, *, channel: dict | None, templates: list[str], past: list[str]) -> dict | None:
        """One idea for one group of footage: the model writes the angle and the shots, the rest is measured."""
        material = "\n".join(f"- {s}" for s in cluster["samples"]) + (f"\nNơi quay: {', '.join(cluster['places'])}." if cluster["places"] else "")
        why = f"cùng {cluster['kind']} \"{cluster['name']}\", {len(cluster['assets'])} video, {round(cluster['seconds'])} giây"
        prompt = ANGLE_PROMPT.format(channel=channel_text(channel), why=why, material=material, templates=", ".join(templates) or "(không có)",
                                     past="; ".join(p.split(".")[0] for p in past[:12]) or "(chưa có)", fit="hop_kenh (1-5, hợp với kênh không), " if channel else "")
        out = self._adapters.submit("model", Request("chat", privacy_class=TEXT_ONLY, params={"task": "idea_angle", "prompt": prompt, "json": True, "max_tokens": 700})).outputs["json"]
        title = str(out.get("tieu_de") or "").strip()
        needs = [str(c).strip() for c in out.get("canh") or [] if str(c).strip()][:8]
        if not title or not needs:
            return None
        shots, gaps, seconds = self._cover(needs)
        angle = str(out.get("goc_ke") or "").strip()

        def asked(key: str) -> int:
            try:
                return max(1, min(5, int(float(out.get(key, 3)))))
            except (TypeError, ValueError):
                return 3
        coverage = sum(s["covered"] for s in shots) / len(shots)
        scores = {"hop_khan_gia": asked("hop_khan_gia"), **({"hop_kenh": asked("hop_kenh")} if channel else {}), "co_hinh": _score(coverage),
                  "moi": _score(cluster["unused_seconds"] / cluster["seconds"] if cluster["seconds"] else 0.0),
                  "khac_biet": _score(self._difference(f"{title}. {angle}", past))}
        template = str(out.get("mau") or "").strip()
        return {"title": title, "angle": angle, "template": template if template in templates else (templates[0] if templates else None),
                "channel": channel["name"] if channel else None, "scores": scores, "total": sum(scores.values()), "coverage": round(coverage, 3),
                "shots": shots, "gaps": gaps, "seconds": seconds, "risk": str(out.get("rui_ro") or "").strip(),
                "blocking": bool(str(out.get("rui_ro") or "").strip()) and str(out.get("muc_rui_ro") or "").strip().lower() in ("chan", "chặn"),
                "material": {k: cluster[k] for k in ("kind", "name", "assets", "seconds", "unused_seconds", "sessions", "places")}}
