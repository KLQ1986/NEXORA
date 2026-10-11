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

    def draft_script(self, topic: str, *, lines: int = 6) -> list[str]:
        """Ask the model for a script that only calls for footage that exists."""
        inventory = "\n".join(self.inventory()) or "(kho đang trống)"
        out = self._adapters.submit("model", Request("chat", params={"prompt": DRAFT_PROMPT.format(topic=topic, inventory=inventory, n=lines),
                                                                    "json": True, "max_tokens": 600})).outputs["json"]
        return [str(c).strip() for c in out.get("cau", []) if str(c).strip()]
