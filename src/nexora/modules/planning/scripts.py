"""Planning: projects and scripts (design v4.0, section 16)."""
import json
import re
import time
import unicodedata

from nexora.core.adapter import AdapterRegistry, PrivacyClass, Request

TEXT_ONLY = PrivacyClass.CLOUD_ALLOWED       # a prompt of words alone: it may be served by a cloud model if the operator routes it there
from nexora.core.assets import AssetStore
from nexora.core.index import MomentIndex
from nexora.core import illustration as ILL
from nexora.core.ideas import IdeaStore
from nexora.core.projects import ProjectStore
from nexora.modules.planning.ideas import OVERLAP, IdeaFinder, channel_text

DRAFT_PROMPT = (
    "Bạn là người viết lời dẫn cho video ngắn. {channel}Chủ đề: {topic}.\n"
    "Dưới đây là những gì có trong kho footage của người làm video:\n{inventory}\n\n"
    "Hãy viết lời dẫn tiếng Việt gồm {n} câu ngắn. {style}\n"
    "{shape}"
)


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
    "Bạn là người phản biện kịch bản video ngắn, khó tính và cụ thể. {channel}Chủ đề: {topic}.\nLời dẫn, mỗi câu có số thứ tự:\n{lines}\n\n"
    "Tìm những chỗ làm video kém đi: mở đầu yếu, câu dài hoặc khó đọc thành tiếng, ý lặp, ý mơ hồ, câu khó có hình minh hoạ, kết không rõ. "
    "Tối đa {n} nhận xét, chỉ nêu điều đáng sửa; nếu kịch bản đã ổn thì trả về danh sách rỗng. "
    "Chỉ trả về JSON với khoá nhan_xet: danh sách các mục có cau (số thứ tự câu, 0 nếu nói về cả bài), van_de (một câu), de_xuat (cách sửa, một câu)."
)
REVISE_PROMPT = (
    "{channel}Đây là lời dẫn của một video về {topic}:\n{lines}\n\nNgười phản biện nêu các điểm sau:\n{notes}\n\n"
    "Viết lại lời dẫn để xử lý các điểm đó. Giữ số câu gần như cũ, giữ nguyên những câu không bị nhận xét, không thêm dữ kiện mới. "
    "Chỉ trả về JSON với khoá cau (danh sách các câu)."
)
FLAT_SHAPE = "Chỉ trả về JSON với khoá cau: danh sách các mục như trên, theo thứ tự."
PARTS_SHAPE = ("Chia lời dẫn thành các phần theo đúng thứ tự sau: {parts}. "
               "Chỉ trả về JSON với khoá phan: danh sách các mục có ten (tên phần như trên) và cau (danh sách các mục như trên của phần đó).")
VARIANT_PROMPT = (
    "{channel}Đây là lời dẫn của một video về {topic}, mỗi câu có số thứ tự:\n{lines}\n\n"
    "Viết lại riêng {part} (câu {first} đến câu {last}) theo {n} cách khác nhau rõ rệt; phần còn lại giữ nguyên, không thêm dữ kiện mới. "
    "Chỉ trả về JSON với khoá phuong_an: danh sách các mục có ten (vài chữ nói cách này khác gì) và cau (các câu thay cho phần đó)."
)
PARTS = {"opening": ("phần mở bài", "Mở bài"), "ending": ("phần kết", "Kết")}
# Writing with the model on a stretch of the script: what each request asks, and how many lines each answer should have.
REWRITE_PROMPT = (
    "{channel}Đây là lời dẫn của một video về {topic}, mỗi câu có số thứ tự:\n{lines}\n\n"
    "Chỉ làm việc với {which}: {ask}\n"
    "Phần còn lại giữ nguyên, không thêm dữ kiện mới, giữ giọng của cả bài. Viết {n} phương án khác nhau rõ rệt. "
    "Chỉ trả về JSON với khoá phuong_an: danh sách các mục có ten (vài chữ nói phương án này khác gì) và cau (danh sách {shape})."
)
REWRITES = {
    "shorten": ("rút gọn, giữ ý chính, ngắn hơn rõ rệt, dễ đọc thành tiếng", "các câu thay cho đoạn đã chọn"),
    "tone": ("viết lại theo giọng: {instruction}", "các câu thay cho đoạn đã chọn"),
    "bridge": ("viết MỘT câu nối đặt ngay sau đoạn này, để chuyển mượt sang câu tiếp theo", "đúng một câu nối"),
    "split": ("tách thành các câu ngắn hơn, mỗi câu một ý, giữ nguyên nội dung", "các câu thay cho đoạn đã chọn"),
    "again": ("viết lại theo một cách khác, giữ ý", "các câu thay cho đoạn đã chọn"),
    "ask": ("{instruction}", "các câu thay cho đoạn đã chọn"),
}
WORDS_PER_SECOND = 2.6
MIN_LINE = 3.0
VERDICTS = {"dung": "supported", "sai": "contradicted", "khong_thay": "not_found"}
PASSAGE_CHARS = 1500


def _overlap(a: str, b: str) -> float:
    """The share of the shorter text's words that the other has too: how much a line repeats what is to be seen."""
    wa, wb = {w for w in re.findall(r"\w+", _fold(a)) if len(w) > 1}, {w for w in re.findall(r"\w+", _fold(b)) if len(w) > 1}
    return len(wa & wb) / min(len(wa), len(wb)) if wa and wb else 0.0


def _fold(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).lower().split())


class Planning:
    def __init__(self, projects: ProjectStore, assets: AssetStore, index: MomentIndex, adapters: AdapterRegistry, ideas: IdeaStore | None = None):
        self._projects, self._assets, self._index, self._adapters = projects, assets, index, adapters
        self.ideas = ideas
        self._finder = IdeaFinder(projects, assets, index, adapters)

    def create_project(self, title: str, *, format: str = "landscape") -> str:
        return self._projects.create_project(title, format=format)

    def save_script(self, project_id: str, lines: list) -> str:
        """The next version of a project's script. A line saved word for word as the writer drafted it brings the writer's
        notes on it (what to see, how to illustrate)."""
        drafted = self._projects.drafted(project_id)
        return self._projects.save_script(project_id, [l if isinstance(l, dict) or str(l).strip() not in drafted else {"text": str(l).strip(), **drafted[str(l).strip()]} for l in lines])

    def inventory(self) -> list[str]:
        """What the library holds, one line per understood video: the basis for footage-aware scripting."""
        out = []
        for asset in self._assets.assets():
            for moment in self._index.moments(asset["asset_id"], level="video"):
                title = moment.data.get("detail", {}).get("tieu_de") or ""
                out.append(f"- {title}: {moment.text}".strip())
        return out

    # ------------------------------------------------------------------ ideas from the library
    def clusters(self) -> list[dict]:
        return self._finder.clusters()

    def find_ideas(self, *, count: int = 4, channel: dict | None = None, templates: list[str] | None = None) -> list[dict]:
        """An idea for each of the `count` largest groups of unused footage, kept in the idea store in place of every idea
        not decided on yet. Returns the store's open ideas."""
        past = self._finder._past()
        made, used = 0, []
        self.ideas.clear_open()
        for cluster in self._finder.clusters():
            if made >= count:
                break
            mine = set(cluster["assets"])
            if any(len(mine & u) >= OVERLAP * len(mine) for u in used):          # mostly the same footage as a group already proposed for
                continue
            idea = self._finder.propose(cluster, channel=channel, templates=templates or [], past=past)
            if idea is None:
                continue
            self.ideas.propose(cluster["key"], [idea])
            used.append(mine)
            past.append(f"{idea['title']}. {idea['angle']}")                    # the next idea is told this one exists
            made += 1
        return self.ideas.ideas(status=("new", "blocked"))

    # ------------------------------------------------------------------ writing
    def draft(self, topic: str, *, lines: int = 6, channel: dict | None = None, structure: list[dict] | None = None, style: str = "mixed") -> list:
        """Ask the model for a script that only calls for footage that exists, each line with what is to be seen and how the
        picture illustrates it (`style`: direct, associative or mixed). With a template's structure, one scene per segment
        (`# <label>`), in the segments' order. Lines come as {text, brief, illustration}; scene headings as strings."""
        inventory = "\n".join(self.inventory()) or "(kho đang trống)"
        parts = "; ".join(f"{seg['label']} ({seg['min']:g}–{seg['max']:g} giây{': ' + seg['goal'] if seg.get('goal') else ''})" for seg in structure or [])
        shape = PARTS_SHAPE.format(parts=parts) if structure else FLAT_SHAPE
        style = style if style in ILL.STYLES else "mixed"
        out = self._adapters.submit("model", Request("chat", privacy_class=TEXT_ONLY, params={
            "prompt": DRAFT_PROMPT.format(topic=topic, inventory=inventory, n=lines, channel=channel_text(channel), shape=shape, style=ILL.style_prompt(style)),
            "json": True, "max_tokens": 1400, "task": "draft"})).outputs["json"]

        def line(item) -> dict | None:
            if isinstance(item, str):
                return {"text": item.strip()} if item.strip() else None
            if not isinstance(item, dict) or not str(item.get("cau") or "").strip():
                return None
            feel = item.get("cam_giac") if isinstance(item.get("cam_giac"), dict) else {}
            feel = dict(list(feel.items())[:3])                 # the few qualities that matter for the line: a small model fills every key
            ill = ILL.normalise({"kieu": "truc_tiep" if style == "direct" else item.get("kieu"), "goi": item.get("goi"), "cam_giac": feel})
            return {"text": str(item["cau"]).strip(), "brief": str(item.get("hinh") or "").strip() or None, "illustration": ill or None}
        if structure and out.get("phan"):
            written = []
            for seg, part in zip(structure, out.get("phan") or []):
                said = [l for l in (line(c) for c in (part.get("cau") if isinstance(part, dict) else []) or []) if l]
                if said:
                    written += [f"# {seg['label']}", *said]
            if written:
                return written
        return [l for l in (line(c) for c in out.get("cau", [])) if l]

    def draft_script(self, topic: str, *, lines: int = 6, channel: dict | None = None, structure: list[dict] | None = None, style: str = "mixed",
                     project_id: str | None = None) -> list[str]:
        """The draft's words alone, as the script editor shows them; with `project_id` the notes of each line are kept, so saving
        the draft with a line unchanged brings them back."""
        written = self.draft(topic, lines=lines, channel=channel, structure=structure, style=style)
        if project_id:
            self._projects.keep_draft(project_id, written)
        return [l if isinstance(l, str) else l["text"] for l in written]

    def structure(self, project_id: str, structure: list[dict]) -> dict:
        """The script measured against its template's structure: each scene's estimated length (a line's own hold time,
        else its words read at 2.6 a second, at least 3 s) against its segment's range, and segments the script does not have."""
        script = self._projects.current_script(project_id)
        scenes: dict[str, float] = {}
        for shot in (script or {}).get("shots", []):
            seconds = shot.target_seconds or max(MIN_LINE, len(shot.text.split()) / WORDS_PER_SECOND)      # as the storyboard times a line
            scenes[_fold(shot.scene or "")] = scenes.get(_fold(shot.scene or ""), 0.0) + seconds
        rows, findings = [], []
        for seg in structure:
            seconds = scenes.get(_fold(seg["label"]))
            state = "missing" if seconds is None else "short" if seconds < seg["min"] else "long" if seconds > seg["max"] else "ok"
            rows.append({**seg, "seconds": round(seconds, 1) if seconds is not None else None, "state": state})
            if state == "missing":
                findings.append(f"Chưa có phần “{seg['label']}”.")
            elif state != "ok":
                findings.append(f"Phần “{seg['label']}” khoảng {seconds:.0f} giây, {'ngắn hơn' if state == 'short' else 'dài hơn'} {seg['min']:g}–{seg['max']:g} giây.")
        return {"segments": rows, "findings": findings, "unplaced": round(sum(v for k, v in scenes.items() if k not in {_fold(s["label"]) for s in structure}), 1)}

    def variants(self, project_id: str, part: str, *, n: int = 2, channel: dict | None = None) -> list[dict]:
        """Alternatives for the opening or the ending: the first (last) scene, or the first (last) line when the script has
        no scenes, written again `n` ways; the rest is not touched. "A" is the script as it is."""
        script, project = self._projects.current_script(project_id), self._projects.project(project_id)
        shots = (script or {}).get("shots", [])
        if part not in PARTS or not shots:
            raise ValueError("an opening or an ending of a script that has lines")
        edge = shots[0] if part == "opening" else shots[-1]
        span = [k for k, s in enumerate(shots) if edge.scene and s.scene == edge.scene] or [0 if part == "opening" else len(shots) - 1]
        lines = "\n".join(f"{i}. {s.text}" for i, s in enumerate(shots, 1))
        out = self._adapters.submit("model", Request("chat", privacy_class=TEXT_ONLY, params={"task": "variant", "json": True, "max_tokens": 700,
                                    "prompt": VARIANT_PROMPT.format(channel=channel_text(channel), topic=project["title"], lines=lines, part=PARTS[part][0],
                                                                    first=span[0] + 1, last=span[-1] + 1, n=n)})).outputs["json"]

        def whole(replacement: list[str]) -> list[str]:
            texts = [s.text for s in shots]
            texts[span[0]:span[-1] + 1] = replacement
            scenes = [s.scene for s in shots]
            scenes[span[0]:span[-1] + 1] = [edge.scene] * len(replacement)
            written, scene = [], None
            for text, sc in zip(texts, scenes):
                if sc != scene:
                    scene = sc
                    if sc:
                        written.append(f"# {sc}")
                written.append(text)
            return written
        items = [{"label": f"{PARTS[part][1]} A", "note": "như kịch bản hiện tại", "lines": whole([shots[k].text for k in span])}]
        for raw in (out.get("phuong_an") or [])[:n]:
            said = [str(c).strip() for c in (raw.get("cau") if isinstance(raw, dict) else []) or [] if str(c).strip()]
            if said and said != [shots[k].text for k in span]:
                items.append({"label": f"{PARTS[part][1]} {chr(ord('A') + len(items))}", "note": str(raw.get("ten") or "").strip(), "lines": whole(said)})
        if len(items) == 1:
            return []
        self._projects.add_variants(project_id, script["script_id"], part, items)
        return [v for v in self._projects.variants(project_id) if v["script_id"] == script["script_id"] and v["part"] == part and v["chosen"] is None]

    def rewrite(self, lines: list[str], first: int, last: int, action: str, *, topic: str, instruction: str = "", n: int = 3,
                channel: dict | None = None) -> list[dict]:
        """Write a stretch of a script with the model: the lines `first`..`last` (indices into `lines`, the editor's lines as
        they stand, scene headings included) shortened, in another voice, split, written another way, as the operator asks,
        or followed by a bridging line. The whole script is the context. Returns `n` proposals, each the lines that take the
        stretch's place and anything it found against the channel; nothing is saved."""
        if action not in REWRITES:
            raise ValueError("unknown request")
        if action in ("tone", "ask") and not instruction.strip():
            raise ValueError("this request needs words from the operator")
        if not (0 <= first <= last < len(lines)) or any(str(lines[k]).strip().startswith("#") for k in range(first, last + 1)):
            raise ValueError("choose lines of one scene, without its heading")
        spoken = [k for k, l in enumerate(lines) if str(l).strip() and not str(l).strip().startswith("#")]
        if not all(k in spoken for k in range(first, last + 1)):
            raise ValueError("choose lines of the script")
        numbered = "\n".join(f"{i}. {str(lines[k]).strip()}" for i, k in enumerate(spoken, 1))
        a, b = spoken.index(first) + 1, spoken.index(last) + 1
        which = f"câu {a}" if a == b else f"câu {a} đến câu {b}"
        ask, shape = REWRITES[action]
        out = self._adapters.submit("model", Request("chat", privacy_class=TEXT_ONLY, params={"task": "rewrite", "json": True, "max_tokens": 900,
                                    "prompt": REWRITE_PROMPT.format(channel=channel_text(channel), topic=topic, lines=numbered, which=which,
                                                                    ask=ask.format(instruction=instruction.strip()), n=n, shape=shape)})).outputs["json"]
        chosen = [str(lines[k]).strip() for k in range(first, last + 1)]
        proposals, seen = [], set()
        for raw in (out.get("phuong_an") or [])[:n]:
            said = [str(c).strip() for c in (raw.get("cau") if isinstance(raw, dict) else []) or [] if str(c).strip()]
            if action == "bridge":
                said = chosen + said[:1] if said else []          # the stretch stays; one line follows it
            if not said or said == chosen or tuple(said) in seen:
                continue
            seen.add(tuple(said))
            flags = [f"Có cụm từ kênh không dùng: “{w}”." for w in (channel or {}).get("banned") or [] if w and any(_fold(w) in _fold(x) for x in said)]
            proposals.append({"label": str(raw.get("ten") or "").strip() or f"Phương án {len(proposals) + 1}", "lines": said, "flags": flags})
        return proposals

    # ------------------------------------------------------------------ research and fact checking
    def research(self, project_id: str) -> list[dict]:
        return json.loads(self._projects.project(project_id).get("research") or "[]")

    def read_source(self, project_id: str, url: str) -> dict:
        """Read a page the operator names and keep it as a source of the project: who published it, when, and its opening passage.
        Only the address leaves this machine."""
        page = self._adapters.submit("web", Request("read", inputs={"url": url}, privacy_class=PrivacyClass.CLOUD_ALLOWED)).outputs
        # The passage is the article's running prose: whole sentences, not the coordinates, menus and notes a page opens with.
        prose = "\n".join(line for line in page["text"].splitlines() if len(line) >= 80 and line.rstrip()[-1:] in ".!?”\"" and "°" not in line[:40]) or page["text"]
        source = {"title": page["title"] or page["url"], "publisher": page["publisher"], "date": page["date"], "url": page["url"],
                  "passage": prose[:PASSAGE_CHARS], "retrieved_at": time.time()}
        kept = [s for s in self.research(project_id) if s.get("url") != source["url"]]
        self._projects.update_project(project_id, research=json.dumps(kept + [source], ensure_ascii=False))
        return source

    def find_sources(self, project_id: str, query: str, *, limit: int = 3) -> list[dict]:
        """Look the subject up and read what is found into the project's sources. Only the search words and the addresses found
        leave this machine. A page that cannot be read is passed over; finding nothing is an answer, not a failure."""
        from nexora.core.adapter import AdapterError
        results = self._adapters.submit("web", Request("search", inputs={"query": query}, params={"limit": limit}, privacy_class=PrivacyClass.CLOUD_ALLOWED)).outputs["results"]
        read = []
        for result in results:
            try:
                read.append(self.read_source(project_id, result["url"]))
            except AdapterError:
                continue
        return read

    def find_facts(self, project_id: str) -> list[str]:
        """Mark the lines that state something checkable. A line the operator already marked stays marked."""
        script = self._projects.current_script(project_id)
        if not script or not script["shots"]:
            return []
        lines = "\n".join(f"{i}. {s.text}" for i, s in enumerate(script["shots"], 1))
        out = self._adapters.submit("model", Request("chat", privacy_class=TEXT_ONLY, params={"prompt": FIND_FACTS_PROMPT.format(lines=lines), "json": True, "max_tokens": 120, "task": "facts"})).outputs["json"]
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
                out = self._adapters.submit("model", Request("chat", privacy_class=TEXT_ONLY, params={"prompt": CHECK_FACT_PROMPT.format(line=shot.text, sources=listing), "json": True, "max_tokens": 300, "task": "check"})).outputs["json"]
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
    def critique(self, project_id: str, *, limit: int = 5, channel: dict | None = None) -> list[dict]:
        """A second opinion on the script, kept with the version it was given on."""
        script, project = self._projects.current_script(project_id), self._projects.project(project_id)
        if not script or not script["shots"]:
            return []
        lines = "\n".join(f"{i}. {s.text}" for i, s in enumerate(script["shots"], 1))
        out = self._adapters.submit("model", Request("chat", privacy_class=TEXT_ONLY, params={"prompt": CRITIQUE_PROMPT.format(topic=project["title"], lines=lines, n=limit, channel=channel_text(channel)), "json": True, "max_tokens": 600, "task": "critique"})).outputs["json"]
        notes, said = [], {shot.text.strip().rstrip(".") for shot in script["shots"]}
        for raw in (out.get("nhan_xet") or [])[:limit]:
            # A note that only repeats a line of the script says nothing about it; small models do this when they have no remark to make.
            if isinstance(raw, dict) and str(raw.get("van_de", "")).strip() and str(raw["van_de"]).strip().rstrip(".") not in said:
                try:
                    line = int(raw.get("cau") or 0)
                except (TypeError, ValueError):
                    line = 0
                notes.append({"line": line if 0 <= line <= len(script["shots"]) else 0, "issue": str(raw["van_de"]).strip(), "fix": str(raw.get("de_xuat") or "").strip()})
        for k, shot in enumerate(script["shots"], 1):              # a line meant to evoke that only describes what is seen
            ill = shot.illustration or {}
            if ill.get("mode") in ("associative", "contrast") and shot.brief and _overlap(shot.text, shot.brief) >= 0.6:
                notes.insert(0, {"line": k, "issue": "Câu này chỉ tả lại hình, trong khi hình được chọn để gợi ý của câu.",
                                 "fix": "Nói ý hay cảm nghĩ mà hình gợi ra, đừng tả điều đang thấy.", "measured": True})
        for k, shot in enumerate(script["shots"], 1):              # what the channel never says is measured, not judged
            for phrase in (channel or {}).get("banned") or []:
                if phrase and _fold(phrase) in _fold(shot.text):
                    notes.insert(0, {"line": k, "issue": f"Có cụm từ kênh không dùng: “{phrase}”.", "fix": "Bỏ hoặc nói cách khác.", "measured": True})
        self._projects.set_critique(script["script_id"], notes)
        return notes

    def revise(self, project_id: str, *, channel: dict | None = None) -> str | None:
        """Rewrite the script to answer its critique, as the next version. Scene headings stay where they were."""
        script, project = self._projects.current_script(project_id), self._projects.project(project_id)
        notes = (script or {}).get("critique") or []
        if not notes:
            return None
        lines = "\n".join(f"{i}. {s.text}" for i, s in enumerate(script["shots"], 1))
        listed = "\n".join(f"- {'Câu ' + str(n['line']) if n['line'] else 'Cả bài'}: {n['issue']} Đề xuất: {n['fix']}" for n in notes)
        out = self._adapters.submit("model", Request("chat", privacy_class=TEXT_ONLY, params={"prompt": REVISE_PROMPT.format(topic=project["title"], lines=lines, notes=listed, channel=channel_text(channel)), "json": True, "max_tokens": 700, "task": "revise"})).outputs["json"]
        new = [str(c).strip() for c in out.get("cau") or [] if str(c).strip()]
        if not new or new == [s.text for s in script["shots"]]:
            return None
        if len(new) == len(script["shots"]):                     # same shape: keep each line under its scene, with its notes
            with_scenes, scene = [], None
            for shot, text in zip(script["shots"], new):
                if shot.scene != scene:
                    scene = shot.scene
                    if scene:
                        with_scenes.append(f"# {scene}")
                with_scenes.append({"text": text, "brief": shot.brief, "illustration": shot.illustration or None})
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
