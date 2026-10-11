"""Planning: projects and scripts (design v4.0, section 16)."""
import json
import time

from nexora.core.adapter import AdapterRegistry, PrivacyClass, Request
from nexora.core.assets import AssetStore
from nexora.core.index import MomentIndex
from nexora.core.projects import ProjectStore

DRAFT_PROMPT = (
    "Bạn là người viết lời dẫn cho video ngắn. Chủ đề: {topic}.\n"
    "Dưới đây là những gì có trong kho footage của người làm video:\n{inventory}\n\n"
    "Hãy viết lời dẫn tiếng Việt gồm {n} câu ngắn, mỗi câu nói về một hình ảnh CÓ trong kho footage ở trên để có hình minh hoạ. "
    "Chỉ trả về JSON với khoá cau (danh sách các câu)."
)


IDEAS_PROMPT = (
    "Bạn là biên tập viên của một kênh video ngắn. Dưới đây là những gì có trong kho footage của người làm video:\n{inventory}\n\n"
    "Hãy đề xuất {n} ý tưởng video khác nhau làm được từ kho này. Với mỗi ý tưởng, chấm từng tiêu chí từ 1 đến 5: "
    "hop_khan_gia (người xem có quan tâm không), co_hinh (kho có đủ hình không), moi_la (có khác những video quen thuộc không), de_lam (ít công không). "
    "Ghi rui_ro: một câu nói điều có thể làm hỏng video, hoặc chuỗi rỗng. "
    "Chỉ trả về JSON với khoá y_tuong: danh sách các mục có tieu_de, mo_ta (một câu), hop_khan_gia, co_hinh, moi_la, de_lam, rui_ro."
)
CRITERIA = ("hop_khan_gia", "co_hinh", "moi_la", "de_lam")
FIND_FACTS_PROMPT = (
    "Dưới đây là lời dẫn của một video, mỗi câu có số thứ tự:\n{lines}\n\n"
    "Câu nào nêu một dữ kiện kiểm chứng được (con số, ngày tháng, tên riêng gắn với một sự việc, điều được nói là đã xảy ra)? "
    "Câu chỉ tả cảnh hoặc nêu cảm nghĩ thì không tính. Chỉ trả về JSON với khoá du_kien: danh sách số thứ tự các câu."
)
CHECK_FACT_PROMPT = (
    "Câu cần kiểm chứng: \"{line}\"\n\nCác nguồn đã có:\n{sources}\n\n"
    "Chỉ dựa vào các nguồn trên, không dùng hiểu biết riêng. Trả về JSON với các khoá: "
    "ket_luan (dung nếu một nguồn nói đúng như câu, sai nếu một nguồn nói khác đi, khong_thay nếu không nguồn nào nhắc tới), "
    "nguon (số thứ tự của nguồn đã dùng, hoặc 0), trich (đoạn chép nguyên văn từ nguồn làm căn cứ, hoặc chuỗi rỗng), giai_thich (một câu)."
)
CRITIQUE_PROMPT = (
    "Bạn là người phản biện kịch bản video ngắn, khó tính và cụ thể. Chủ đề: {topic}.\nLời dẫn, mỗi câu có số thứ tự:\n{lines}\n\n"
    "Tìm những chỗ làm video kém đi: mở đầu yếu, câu dài hoặc khó đọc thành tiếng, ý lặp, ý mơ hồ, câu khó có hình minh hoạ, kết không rõ. "
    "Tối đa {n} nhận xét, chỉ nêu điều đáng sửa; nếu kịch bản đã ổn thì trả về danh sách rỗng. "
    "Chỉ trả về JSON với khoá nhan_xet: danh sách các mục có cau (số thứ tự câu, 0 nếu nói về cả bài), van_de (một câu), de_xuat (cách sửa, một câu)."
)
REVISE_PROMPT = (
    "Đây là lời dẫn của một video về {topic}:\n{lines}\n\nNgười phản biện nêu các điểm sau:\n{notes}\n\n"
    "Viết lại lời dẫn để xử lý các điểm đó. Giữ số câu gần như cũ, giữ nguyên những câu không bị nhận xét, không thêm dữ kiện mới. "
    "Chỉ trả về JSON với khoá cau (danh sách các câu)."
)
VERDICTS = {"dung": "supported", "sai": "contradicted", "khong_thay": "not_found"}
PASSAGE_CHARS = 1500


class Planning:
    def __init__(self, projects: ProjectStore, assets: AssetStore, index: MomentIndex, adapters: AdapterRegistry):
        self._projects, self._assets, self._index, self._adapters = projects, assets, index, adapters

    def create_project(self, title: str, *, format: str = "landscape") -> str:
        return self._projects.create_project(title, format=format)

    def save_script(self, project_id: str, lines: list[str]) -> str:
        return self._projects.save_script(project_id, lines)

    def inventory(self) -> list[str]:
        """What the library holds, one line per understood video: the basis for footage-aware scripting."""
        out = []
        for asset in self._assets.assets():
            for moment in self._index.moments(asset["asset_id"], level="video"):
                title = moment.data.get("detail", {}).get("tieu_de") or ""
                out.append(f"- {title}: {moment.text}".strip())
        return out

    def ideas(self, *, count: int = 4) -> list[dict]:
        """Video ideas the library can actually support, each with a visible scorecard. How much footage really covers an idea is
        measured from the index, not taken from the model's own opinion; a stated risk is shown, never averaged away."""
        inventory = "\n".join(self.inventory())
        if not inventory:
            return []
        out = self._adapters.submit("model", Request("chat", params={"prompt": IDEAS_PROMPT.format(inventory=inventory, n=count), "json": True, "max_tokens": 900})).outputs["json"]
        ideas = []
        for raw in out.get("y_tuong", [])[:count]:
            if not isinstance(raw, dict) or not str(raw.get("tieu_de", "")).strip():
                continue
            scores = {}
            for key in CRITERIA:
                try:
                    scores[key] = max(1, min(5, int(float(raw.get(key, 3)))))
                except (TypeError, ValueError):
                    scores[key] = 3
            text = f"{raw['tieu_de']} {raw.get('mo_ta', '')}"
            hits = self._index.search(text, limit=5)
            top = sorted((h.score for h in hits), reverse=True)[:3]
            scores["co_hinh"] = max(1, min(5, round(1 + 4 * (sum(top) / 3))))       # measured coverage replaces the model's guess
            ideas.append({"title": str(raw["tieu_de"]).strip(), "summary": str(raw.get("mo_ta", "")).strip(), "scores": scores,
                          "total": sum(scores.values()), "risk": str(raw.get("rui_ro", "")).strip()})
        return sorted(ideas, key=lambda i: (bool(i["risk"]), -i["total"]))

    def draft_script(self, topic: str, *, lines: int = 6) -> list[str]:
        """Ask the model for a script that only calls for footage that exists."""
        inventory = "\n".join(self.inventory()) or "(kho đang trống)"
        out = self._adapters.submit("model", Request("chat", params={"prompt": DRAFT_PROMPT.format(topic=topic, inventory=inventory, n=lines),
                                                                    "json": True, "max_tokens": 600})).outputs["json"]
        return [str(c).strip() for c in out.get("cau", []) if str(c).strip()]

    # ------------------------------------------------------------------ research and fact checking
    def research(self, project_id: str) -> list[dict]:
        return json.loads(self._projects.project(project_id).get("research") or "[]")

    def read_source(self, project_id: str, url: str) -> dict:
        """Read a page the operator names and keep it as a source of the project: who published it, when, and its opening passage.
        Only the address leaves this machine."""
        page = self._adapters.submit("web", Request("read", inputs={"url": url}, privacy_class=PrivacyClass.CLOUD_ALLOWED)).outputs
        source = {"title": page["title"] or page["url"], "publisher": page["publisher"], "date": page["date"], "url": page["url"],
                  "passage": page["text"][:PASSAGE_CHARS], "retrieved_at": time.time()}
        kept = [s for s in self.research(project_id) if s.get("url") != source["url"]]
        self._projects.update_project(project_id, research=json.dumps(kept + [source], ensure_ascii=False))
        return source

    def find_facts(self, project_id: str) -> list[str]:
        """Mark the lines that state something checkable. A line the operator already marked stays marked."""
        script = self._projects.current_script(project_id)
        if not script or not script["shots"]:
            return []
        lines = "\n".join(f"{i}. {s.text}" for i, s in enumerate(script["shots"], 1))
        out = self._adapters.submit("model", Request("chat", params={"prompt": FIND_FACTS_PROMPT.format(lines=lines), "json": True, "max_tokens": 120, "task": "facts"})).outputs["json"]
        found = []
        for n in out.get("du_kien") or []:
            if isinstance(n, (int, float)) and 1 <= int(n) <= len(script["shots"]):
                shot = script["shots"][int(n) - 1]
                self._projects.annotate_shot(shot.shot_id, is_fact=True)
                found.append(shot.shot_id)
        return found

    def check_facts(self, project_id: str) -> list[dict]:
        """Hold every factual line against the project's sources. The verdict comes with the passage it rests on, so the operator
        can read it rather than trust it; a line no source mentions is reported, never passed."""
        script, sources = self._projects.current_script(project_id), self.research(project_id)
        results = []
        listing = "\n\n".join(f"[{i}] {s['title']} ({s.get('publisher') or 'không rõ nơi xuất bản'}, {s.get('date') or 'không rõ ngày'}):\n{s.get('passage', '')}" for i, s in enumerate(sources, 1))
        for shot in (script["shots"] if script else []):
            if not shot.is_fact:
                continue
            result = {"verdict": "not_found", "source": None, "quote": "", "note": "Dự án chưa có nguồn tham khảo nào.", "checked_at": time.time()}
            if sources:
                out = self._adapters.submit("model", Request("chat", params={"prompt": CHECK_FACT_PROMPT.format(line=shot.text, sources=listing), "json": True, "max_tokens": 300, "task": "check"})).outputs["json"]
                verdict = VERDICTS.get(str(out.get("ket_luan", "")).strip().lower(), "not_found")
                try:
                    source = sources[int(out.get("nguon") or 0) - 1] if int(out.get("nguon") or 0) >= 1 else None
                except (ValueError, IndexError, TypeError):
                    source = None
                quote = str(out.get("trich") or "").strip()
                if verdict != "not_found" and (source is None or not quote or " ".join(quote.split()).lower() not in " ".join(source.get("passage", "").split()).lower()):
                    verdict, quote = "not_found", ""        # a verdict whose quote is not in the source is the model's own opinion, not a check
                result = {"verdict": verdict, "source": source["title"] if source and verdict != "not_found" else None, "quote": quote,
                          "note": str(out.get("giai_thich") or "").strip(), "checked_at": time.time()}
                if verdict == "supported" and not shot.source:
                    self._projects.annotate_shot(shot.shot_id, source=source["title"])
            self._projects.set_fact_check(shot.shot_id, result)
            results.append({"shot_id": shot.shot_id, "text": shot.text, **result})
        return results

    # ------------------------------------------------------------------ critique and revision
    def critique(self, project_id: str, *, limit: int = 5) -> list[dict]:
        """A second opinion on the script, kept with the version it was given on."""
        script, project = self._projects.current_script(project_id), self._projects.project(project_id)
        if not script or not script["shots"]:
            return []
        lines = "\n".join(f"{i}. {s.text}" for i, s in enumerate(script["shots"], 1))
        out = self._adapters.submit("model", Request("chat", params={"prompt": CRITIQUE_PROMPT.format(topic=project["title"], lines=lines, n=limit), "json": True, "max_tokens": 600, "task": "critique"})).outputs["json"]
        notes = []
        for raw in (out.get("nhan_xet") or [])[:limit]:
            if isinstance(raw, dict) and str(raw.get("van_de", "")).strip():
                try:
                    line = int(raw.get("cau") or 0)
                except (TypeError, ValueError):
                    line = 0
                notes.append({"line": line if 0 <= line <= len(script["shots"]) else 0, "issue": str(raw["van_de"]).strip(), "fix": str(raw.get("de_xuat") or "").strip()})
        self._projects.set_critique(script["script_id"], notes)
        return notes

    def revise(self, project_id: str) -> str | None:
        """Rewrite the script to answer its critique, as the next version. Scene headings stay where they were."""
        script, project = self._projects.current_script(project_id), self._projects.project(project_id)
        notes = (script or {}).get("critique") or []
        if not notes:
            return None
        lines = "\n".join(f"{i}. {s.text}" for i, s in enumerate(script["shots"], 1))
        listed = "\n".join(f"- {'Câu ' + str(n['line']) if n['line'] else 'Cả bài'}: {n['issue']} Đề xuất: {n['fix']}" for n in notes)
        out = self._adapters.submit("model", Request("chat", params={"prompt": REVISE_PROMPT.format(topic=project["title"], lines=lines, notes=listed), "json": True, "max_tokens": 700, "task": "revise"})).outputs["json"]
        new = [str(c).strip() for c in out.get("cau") or [] if str(c).strip()]
        if not new or new == [s.text for s in script["shots"]]:
            return None
        if len(new) == len(script["shots"]):                     # same shape: keep each line under its scene
            with_scenes, scene = [], None
            for shot, text in zip(script["shots"], new):
                if shot.scene != scene:
                    scene = shot.scene
                    if scene:
                        with_scenes.append(f"# {scene}")
                with_scenes.append(text)
            new = with_scenes
        return self._projects.save_script(project_id, new)

    # ------------------------------------------------------------------ opportunity radar
    def radar(self, topics: list[str] | None = None) -> dict:
        """What the library could carry next. Two measurements, both taken from the index rather than asked of a model:
        footage that no project has used yet, grouped by subject; and, for each topic the operator is watching, how much
        of the library answers it."""
        used = self._projects.used_assets()
        subjects: dict[str, dict] = {}
        for asset in self._assets.assets():
            for moment in self._index.moments(asset["asset_id"], level="video"):
                detail = moment.data.get("detail", {})
                for subject in [str(t).strip().lower() for t in detail.get("chu_de") or [] if str(t).strip()] or ["chưa rõ chủ đề"]:
                    row = subjects.setdefault(subject, {"subject": subject, "videos": 0, "seconds": 0.0, "unused_videos": 0, "unused_seconds": 0.0, "examples": []})
                    row["videos"] += 1
                    row["seconds"] += moment.t_end
                    if asset["asset_id"] not in used:
                        row["unused_videos"] += 1
                        row["unused_seconds"] += moment.t_end
                        if len(row["examples"]) < 3:
                            row["examples"].append({"asset_id": asset["asset_id"], "title": detail.get("tieu_de") or "", "summary": moment.text})
        watched = []
        for topic in topics or []:
            hits = self._index.search(topic, limit=8)
            strong = [h for h in hits if h.score >= 0.5]
            watched.append({"topic": topic, "moments": len(strong), "best": round(max((h.score for h in hits), default=0.0), 2),
                            "assets": len({h.moment.asset_id for h in strong}),
                            "verdict": "đủ hình để làm" if len(strong) >= 4 else "có ít hình" if strong else "chưa có hình"})
        return {"unused": sorted((s for s in subjects.values() if s["unused_videos"]), key=lambda s: -s["unused_seconds"]),
                "subjects": sorted(subjects.values(), key=lambda s: -s["seconds"]), "watched": watched}
