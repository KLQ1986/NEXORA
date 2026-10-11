"""Planning: projects and scripts (design v4.0, section 16)."""
from nexora.core.adapter import AdapterRegistry, Request
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
