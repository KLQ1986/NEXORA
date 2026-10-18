"""A script from a topic (design 2026-10-18, Claude Code as NEXORA's writer): a writer that can read the web looks the
subject up and returns a package of its sources and the lines it wrote on them. Nothing in the package is taken on trust:
a source needs a web address and a passage to rest on, a line stating a fact keeps only a source the package has, and a
package with no line is refused before anything is written."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable

from nexora.core import db
from nexora.core.adapter import AdapterError, ErrorCode, PrivacyClass, Request
from nexora.core.pipeline import PipelineDefinition, StageDef

UNSOURCED_NOTE = "Người viết không dẫn nguồn cho câu này."
MODES = ("direct", "associative", "contrast")
PASSAGE = 600

PACKAGE_SCHEMA = {
    "type": "object", "required": ["title", "angle", "sources", "lines", "unverified"], "additionalProperties": False,
    "properties": {
        "title": {"type": "string"}, "angle": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "object", "required": ["id", "url", "title", "publisher", "date", "passage"], "additionalProperties": False,
                    "properties": {k: {"type": "string"} for k in ("id", "url", "title", "publisher", "date", "passage")}}},
        "lines": {"type": "array", "items": {"type": "object", "required": ["part", "text", "fact", "sources", "brief", "illustration"], "additionalProperties": False,
                  "properties": {"part": {"type": "string"}, "text": {"type": "string"}, "fact": {"type": "boolean"},
                                 "sources": {"type": "array", "items": {"type": "string"}}, "brief": {"type": "string"}, "screen_text": {"type": "string"},
                                 "illustration": {"type": "object", "required": ["mode"], "additionalProperties": False,
                                                  "properties": {"mode": {"type": "string", "enum": list(MODES)}, "evokes": {"type": "string"}}}}}},
        "unverified": {"type": "array", "items": {"type": "string"}},
    },
}

# What kind of video it is: each kind is told the way it tells its story.
FORMS = {
    "reportage": ("Phóng sự", "Kể như một phóng sự: mở bằng một cảnh, một con người hay một nơi chốn cụ thể, đi vào sự việc, nêu các bên liên quan "
                              "và hệ quả, kết bằng điều còn bỏ ngỏ hoặc hướng đi sắp tới."),
    "science": ("Diễn giải khoa học", "Giải thích một hiện tượng: mở bằng một câu hỏi gợi tò mò, đi từ điều người xem đã biết tới cơ chế, mỗi bước một ý, "
                                      "dùng so sánh đời thường cho khái niệm khó, thuật ngữ nào cũng giải nghĩa ngay."),
    "history": ("Tài liệu lịch sử", "Kể theo dòng thời gian: bối cảnh, các mốc chính có năm tháng, nhân vật và quyết định của họ, rồi ý nghĩa của câu chuyện tới hôm nay."),
    "story": ("Chân dung / kể chuyện", "Kể một câu chuyện xoay quanh một người, một nơi hay một vật: có nhân vật, có biến cố, có chuyển biến; chi tiết cụ thể, giàu hình ảnh."),
    "analysis": ("Phân tích / bình luận", "Đặt một câu hỏi rõ ràng, trình bày lập luận và bằng chứng của từng phía, cân nhắc chúng, rồi đưa ra một nhận định có cơ sở; "
                                          "tách rõ đâu là dữ kiện, đâu là nhận định."),
    "news": ("Điểm tin", "Nói điều quan trọng nhất trước: chuyện gì, ở đâu, khi nào, vì sao quan trọng; sau đó bối cảnh và diễn biến tiếp theo; câu ngắn, rõ, không bình luận."),
    "howto": ("Hướng dẫn", "Chỉ người xem làm một việc: nói trước sẽ đạt được gì và cần chuẩn bị gì, rồi từng bước theo thứ tự, mỗi câu một thao tác, "
                           "kèm lưu ý hay lỗi thường gặp."),
}
DEFAULT_FORM = "reportage"
WORDS_PER_SECOND = 2.6          # as the editor and the storyboard time narration
MIN_LINE = 3.0
MIN_SECONDS, MAX_SECONDS, DEFAULT_SECONDS = 60, 900, 180
OFF_BY = 0.3                    # a draft this much shorter or longer than asked is said to be


def spoken_seconds(texts: list[str]) -> int:
    """How long lines take to read aloud, as the editor times them."""
    return round(sum(max(MIN_LINE, len(t.split()) / WORDS_PER_SECOND) for t in texts))


def clamp_seconds(value, default: int = DEFAULT_SECONDS) -> int:
    try:
        return max(MIN_SECONDS, min(MAX_SECONDS, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


SYSTEM = (
    "Bạn là biên kịch video của NEXORA, viết lời dẫn tiếng Việt để đọc thành tiếng trên hình. Thể loại: {form}. {how}\n{voice}\n"
    "Bạn tìm hiểu chủ đề bằng WebSearch và WebFetch: đọc nguồn đáng tin (báo lớn, cơ quan nhà nước, tạp chí khoa học, tổ chức chuyên môn), "
    "ưu tiên nguồn gốc hơn bài đăng lại, và ghi lại mỗi nguồn đã dùng với một đoạn trích nguyên văn (không quá {passage} ký tự) làm chỗ dựa.\n"
    "Quy tắc dữ kiện: câu nào nêu con số, ngày tháng, tên người, tên nơi chốn hay sự kiện thì đặt fact = true và dẫn id của nguồn đã đọc có nói điều đó. "
    "Không bịa. Điều gì muốn nói mà không tìm được nguồn thì không đưa vào lời dẫn, ghi vào unverified.\n"
    "Mỗi câu kèm brief (hình cần thấy, cụ thể, quay được hoặc tìm được trong kho stock) và illustration: mode direct khi hình cho thấy đúng điều câu nói, "
    "associative khi hình gợi cảm xúc hay ý của câu (kèm evokes: điều hình gợi ra, 2 đến 5 chữ), contrast khi hình đối lập để tạo ý. {style}\n"
    "Mỗi câu một ý, nên dưới 30 chữ, để người nghe theo kịp và hình đổi theo câu. Không viết câu trích lời, không dùng dấu > ở đầu câu. "
    "Trả lời bằng đúng cấu trúc JSON được yêu cầu."
)
STYLES = {"direct": "Phần lớn các câu minh hoạ trực tiếp.", "associative": "Phần lớn các câu minh hoạ liên tưởng.",
          "mixed": "Pha trộn: câu nêu dữ kiện minh hoạ trực tiếp, câu cảm xúc hay chuyển ý minh hoạ liên tưởng."}


def topic_prompt(topic: str, *, goal: str = "", seconds: int = DEFAULT_SECONDS, form: str = DEFAULT_FORM, structure: list[dict] | None = None,
                 voice: str = "", style: str = "mixed", siblings: list[str] | None = None) -> tuple[str, str]:
    name, how = FORMS.get(form, FORMS[DEFAULT_FORM])
    system = SYSTEM.format(form=name, how=how, voice=voice.strip(), passage=PASSAGE, style=STYLES.get(style, STYLES["mixed"]))
    parts = [f"Chủ đề: {topic.strip()}."]
    if goal.strip():
        parts.append(f"Mục tiêu của video: {goal.strip()}.")
    minutes = f"{seconds / 60:g}".replace(".", ",")
    parts.append(f"Độ dài: lời dẫn đọc hết khoảng {minutes} phút ({seconds} giây), tức khoảng {round(seconds * WORDS_PER_SECOND)} chữ khi đọc 2,6 chữ mỗi giây. "
                 "Đừng ngắn hơn hay dài hơn nhiều: chủ đề cần bao nhiêu ý thì tìm đủ nguồn cho bấy nhiêu ý.")
    if structure:
        # A template's timings are for its own short videos: its parts keep their weight, and share out the length asked.
        weights = [max(0.0, (float(p.get("min") or 0) + float(p.get("max") or 0)) / 2) or 1.0 for p in structure]
        named = [f"{p.get('label') or p.get('name') or p.get('role') or f'Phần {i}'} (khoảng {round(seconds * w / sum(weights))} giây)"
                 + (f": {p['goal']}" if p.get("goal") else "") for i, (p, w) in enumerate(zip(structure, weights), 1)]
        parts.append("Chia lời dẫn theo đúng các phần sau, theo thứ tự, ghi tên phần vào part: " + "; ".join(named) + ".")
    else:
        parts.append("Ghi part là Mở đầu, Thân bài hoặc Kết.")
    if siblings:
        parts.append("Dự án này đã có các video: " + "; ".join(siblings) + ". Chọn một góc khác các video đó.")
    return system, "\n".join(parts)


def _date(value) -> str | None:
    """A date as the writer gave it, when it is one: "không rõ" and the like are no date."""
    text = str(value or "").strip()
    return text if re.match(r"^\d{4}(-\d{2}){0,2}$", text) else None


def check_package(raw: dict, *, seconds: int | None = None) -> dict:
    sources, seen_ids, seen_urls = [], set(), set()
    for s in raw.get("sources") or []:
        if not isinstance(s, dict):
            continue
        sid, url, passage = str(s.get("id") or "").strip(), str(s.get("url") or "").strip(), " ".join(str(s.get("passage") or "").split())
        if not sid or sid in seen_ids or not url.startswith(("http://", "https://")) or url in seen_urls or not passage:
            continue
        seen_ids.add(sid)
        seen_urls.add(url)
        sources.append({"id": sid, "url": url, "title": str(s.get("title") or url).strip(), "publisher": str(s.get("publisher") or "").strip() or None,
                        "date": _date(s.get("date")), "passage": passage[:PASSAGE]})
    by_id = {s["id"]: s for s in sources}
    lines = []
    for l in raw.get("lines") or []:
        if not isinstance(l, dict):
            continue
        text = str(l.get("text") or "").strip().lstrip(">").strip()
        if not text:
            continue
        cited = [by_id[c] for c in (l.get("sources") or []) if c in by_id]
        art = l.get("illustration") if isinstance(l.get("illustration"), dict) else {}
        mode = art.get("mode") if art.get("mode") in MODES else "direct"
        lines.append({"part": str(l.get("part") or "").strip(), "text": text, "fact": bool(l.get("fact")), "brief": str(l.get("brief") or "").strip(),
                      "screen_text": str(l.get("screen_text") or "").strip(), "illustration": {"mode": mode, **({"evokes": str(art["evokes"]).strip()} if art.get("evokes") else {})},
                      "source": cited[0]["title"] if cited else None, "unsourced": bool(l.get("fact")) and not cited})
    if not lines:
        raise ValueError("no lines")
    warnings = [f"{sum(l['unsourced'] for l in lines)} câu nêu dữ kiện chưa có nguồn"] if any(l["unsourced"] for l in lines) else []
    spoken = spoken_seconds([l["text"] for l in lines])
    if seconds and abs(spoken - seconds) > OFF_BY * seconds:
        warnings.append(f"Bản nháp đọc hết khoảng {spoken // 60} phút {spoken % 60:02d} giây, {'ngắn' if spoken < seconds else 'dài'} hơn nhiều so với {seconds // 60} phút {seconds % 60:02d} giây đã yêu cầu")
    return {"title": str(raw.get("title") or "").strip(), "angle": str(raw.get("angle") or "").strip(), "sources": sources, "lines": lines, "seconds": spoken,
            "unverified": [str(u).strip() for u in raw.get("unverified") or [] if str(u).strip()], "warnings": warnings}


def script_lines(package: dict) -> list:
    out, part = [], None
    for l in package["lines"]:
        if l["part"] and l["part"] != part:
            part = l["part"]
            out.append(f"# {part}")
        line = {"text": l["text"], "illustration": l["illustration"], "is_fact": l["fact"]}
        for key in ("brief", "screen_text", "source"):
            if l.get(key):
                line[key] = l[key]
        if l["unsourced"]:
            line["fact_check"] = {"verdict": "not_found", "source": None, "quote": "", "note": UNSOURCED_NOTE, "checked_at": time.time()}
        out.append(line)
    return out


# ---------------------------------------------------------------------------------------------------------- the pipeline
# One stage, on a lane of its own with one worker: a writer that reads the web takes minutes, and never holds up a match or a
# render the operator is waiting for, nor runs twice at once on the operator's plan.
TOPIC = PipelineDefinition("planning.topic_script", "1", [StageDef("write", requires=("model.claude_code",), lane="claude_code", timeout_seconds=2700, max_attempts=2)])
STATES = ("asked", "written", "offered", "applied")
TABLE = """CREATE TABLE IF NOT EXISTS topic_scripts (run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, topic TEXT NOT NULL, goal TEXT,
    lines INTEGER, package TEXT, state TEXT NOT NULL, created_at REAL NOT NULL, seconds INTEGER, form TEXT)"""


class TopicWriter:
    """Asks for a script from a topic and keeps what came back: asked, written (checked, not yet given to anyone), offered (to the
    operator in the editor) and applied (saved into the video). `context(project_id)` gives the house voice, the template's
    structure, the way of illustrating and the titles of the production's other videos."""

    def __init__(self, db_path: str | Path, adapters, *, context: Callable[[str], dict], submit: Callable[..., str]):
        self._db = db.LocalConnections(db_path)
        self._adapters, self._context, self._submit = adapters, context, submit
        with db.write(self._db.get()) as c:
            c.execute(TABLE)
            have = {r[1] for r in c.execute("PRAGMA table_info(topic_scripts)")}
            for column, ddl in (("seconds", "INTEGER"), ("form", "TEXT")):
                if column not in have:
                    c.execute(f"ALTER TABLE topic_scripts ADD COLUMN {column} {ddl}")

    @property
    def _conn(self):
        return self._db.get()

    def register(self, registry) -> None:
        registry.register(TOPIC, {"write": self._write})

    def start(self, project_id: str, topic: str, *, goal: str = "", seconds: int = DEFAULT_SECONDS, form: str = DEFAULT_FORM) -> str:
        """A script on `topic`, read aloud in about `seconds`, told as `form` tells it."""
        run_id = self._submit(TOPIC, subject_ref=project_id)
        with db.write(self._conn) as c:
            c.execute("INSERT INTO topic_scripts (run_id, project_id, topic, goal, seconds, form, package, state, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                      (run_id, project_id, topic.strip(), goal.strip(), clamp_seconds(seconds), form if form in FORMS else DEFAULT_FORM, None, "asked", time.time()))
        return run_id

    def _row(self, r) -> dict | None:
        return {**dict(r), "package": json.loads(r["package"]) if r["package"] else None} if r else None

    def get(self, run_id: str) -> dict | None:
        return self._row(self._conn.execute("SELECT * FROM topic_scripts WHERE run_id = ?", (run_id,)).fetchone())

    def latest(self, project_id: str) -> dict | None:
        return self._row(self._conn.execute("SELECT * FROM topic_scripts WHERE project_id = ? ORDER BY created_at DESC LIMIT 1", (project_id,)).fetchone())

    def mark(self, run_id: str, state: str) -> None:
        assert state in STATES
        with db.write(self._conn) as c:
            c.execute("UPDATE topic_scripts SET state = ? WHERE run_id = ?", (state, run_id))

    def _write(self, ctx) -> dict:
        asked = self.get(ctx.claim.run_id)
        if asked is None:
            raise AdapterError(ErrorCode.MISSING_INPUT, "no topic was asked for this run", retryable=False)
        context = self._context(asked["project_id"])
        seconds = asked["seconds"] or DEFAULT_SECONDS
        system, prompt = topic_prompt(asked["topic"], goal=asked["goal"] or "", seconds=seconds, form=asked["form"] or DEFAULT_FORM, structure=context.get("structure"),
                                      voice=context.get("voice", ""), style=context.get("style", "mixed"), siblings=context.get("siblings"))
        # A longer script means more to look up: ten minutes, and two more for each minute asked, within the stage's time.
        result = self._adapters.submit("model.claude_code", Request("research", params={"prompt": prompt, "system": system, "schema": PACKAGE_SCHEMA},
                                                                    privacy_class=PrivacyClass.CLOUD_ALLOWED, attempt_id=ctx.claim.attempt_id,
                                                                    deadline_seconds=min(2600, 600 + 2 * seconds)))
        try:
            package = check_package(result.outputs["json"], seconds=seconds)
        except (ValueError, KeyError, TypeError, AttributeError) as err:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"the writer's package is not usable: {err}", retryable=False) from None
        package["api_equivalent"] = result.outputs.get("api_equivalent", 0.0)
        with db.write(self._conn) as c:
            c.execute("UPDATE topic_scripts SET package = ?, state = 'written' WHERE run_id = ?", (json.dumps(package, ensure_ascii=False), ctx.claim.run_id))
        return {"lines": len(package["lines"]), "sources": len(package["sources"]), "api_equivalent": package["api_equivalent"]}
