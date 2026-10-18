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

SYSTEM = (
    "Bạn là biên kịch phim tài liệu ngắn của NEXORA, viết lời dẫn tiếng Việt để đọc thành tiếng trên hình. {voice}\n"
    "Bạn tìm hiểu chủ đề bằng WebSearch và WebFetch: đọc nguồn đáng tin (báo lớn, cơ quan nhà nước, tạp chí khoa học, tổ chức chuyên môn), "
    "ưu tiên nguồn gốc hơn bài đăng lại, và ghi lại mỗi nguồn đã dùng với một đoạn trích nguyên văn (không quá {passage} ký tự) làm chỗ dựa.\n"
    "Quy tắc dữ kiện: câu nào nêu con số, ngày tháng, tên người, tên nơi chốn hay sự kiện thì đặt fact = true và dẫn id của nguồn đã đọc có nói điều đó. "
    "Không bịa. Điều gì muốn nói mà không tìm được nguồn thì không đưa vào lời dẫn, ghi vào unverified.\n"
    "Mỗi câu kèm brief (hình cần thấy, cụ thể, quay được hoặc tìm được trong kho stock) và illustration: mode direct khi hình cho thấy đúng điều câu nói, "
    "associative khi hình gợi cảm xúc hay ý của câu (kèm evokes: điều hình gợi ra, 2 đến 5 chữ), contrast khi hình đối lập để tạo ý. {style}\n"
    "Không viết câu trích lời, không dùng dấu > ở đầu câu. Trả lời bằng đúng cấu trúc JSON được yêu cầu."
)
STYLES = {"direct": "Phần lớn các câu minh hoạ trực tiếp.", "associative": "Phần lớn các câu minh hoạ liên tưởng.",
          "mixed": "Pha trộn: câu nêu dữ kiện minh hoạ trực tiếp, câu cảm xúc hay chuyển ý minh hoạ liên tưởng."}


def topic_prompt(topic: str, *, goal: str = "", lines: int = 8, structure: list[dict] | None = None, voice: str = "", style: str = "mixed",
                 siblings: list[str] | None = None) -> tuple[str, str]:
    system = SYSTEM.format(voice=voice.strip(), passage=PASSAGE, style=STYLES.get(style, STYLES["mixed"]))
    parts = [f"Chủ đề: {topic.strip()}."]
    if goal.strip():
        parts.append(f"Mục tiêu của video: {goal.strip()}.")
    parts.append(f"Viết khoảng {lines} câu lời dẫn.")
    if structure:
        parts.append("Chia lời dẫn theo đúng các phần sau, theo thứ tự, ghi tên phần vào part: "
                     + "; ".join(f"{p['name']} ({p.get('min', 0)}–{p.get('max', 0)} giây)" for p in structure) + ". Đọc khoảng 2,6 chữ mỗi giây.")
    else:
        parts.append("Ghi part là Mở đầu, Thân bài hoặc Kết.")
    if siblings:
        parts.append("Dự án này đã có các video: " + "; ".join(siblings) + ". Chọn một góc khác các video đó.")
    return system, "\n".join(parts)


def _date(value) -> str | None:
    """A date as the writer gave it, when it is one: "không rõ" and the like are no date."""
    text = str(value or "").strip()
    return text if re.match(r"^\d{4}(-\d{2}){0,2}$", text) else None


def check_package(raw: dict) -> dict:
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
    return {"title": str(raw.get("title") or "").strip(), "angle": str(raw.get("angle") or "").strip(), "sources": sources, "lines": lines,
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
TOPIC = PipelineDefinition("planning.topic_script", "1", [StageDef("write", requires=("model.claude_code",), lane="claude_code", timeout_seconds=1200, max_attempts=2)])
STATES = ("asked", "written", "offered", "applied")
TABLE = """CREATE TABLE IF NOT EXISTS topic_scripts (run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, topic TEXT NOT NULL, goal TEXT,
    lines INTEGER, package TEXT, state TEXT NOT NULL, created_at REAL NOT NULL)"""


class TopicWriter:
    """Asks for a script from a topic and keeps what came back: asked, written (checked, not yet given to anyone), offered (to the
    operator in the editor) and applied (saved into the video). `context(project_id)` gives the house voice, the template's
    structure, the way of illustrating and the titles of the production's other videos."""

    def __init__(self, db_path: str | Path, adapters, *, context: Callable[[str], dict], submit: Callable[..., str]):
        self._db = db.LocalConnections(db_path)
        self._adapters, self._context, self._submit = adapters, context, submit
        with db.write(self._db.get()) as c:
            c.execute(TABLE)

    @property
    def _conn(self):
        return self._db.get()

    def register(self, registry) -> None:
        registry.register(TOPIC, {"write": self._write})

    def start(self, project_id: str, topic: str, *, goal: str = "", lines: int = 8) -> str:
        run_id = self._submit(TOPIC, subject_ref=project_id)
        with db.write(self._conn) as c:
            c.execute("INSERT INTO topic_scripts (run_id, project_id, topic, goal, lines, package, state, created_at) VALUES (?,?,?,?,?,?,?,?)",
                      (run_id, project_id, topic.strip(), goal.strip(), int(lines), None, "asked", time.time()))
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
        system, prompt = topic_prompt(asked["topic"], goal=asked["goal"] or "", lines=asked["lines"] or 8, structure=context.get("structure"),
                                      voice=context.get("voice", ""), style=context.get("style", "mixed"), siblings=context.get("siblings"))
        result = self._adapters.submit("model.claude_code", Request("research", params={"prompt": prompt, "system": system, "schema": PACKAGE_SCHEMA},
                                                                    privacy_class=PrivacyClass.CLOUD_ALLOWED, attempt_id=ctx.claim.attempt_id))
        try:
            package = check_package(result.outputs["json"])
        except (ValueError, KeyError, TypeError, AttributeError) as err:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, f"the writer's package is not usable: {err}", retryable=False) from None
        package["api_equivalent"] = result.outputs.get("api_equivalent", 0.0)
        with db.write(self._conn) as c:
            c.execute("UPDATE topic_scripts SET package = ?, state = 'written' WHERE run_id = ?", (json.dumps(package, ensure_ascii=False), ctx.claim.run_id))
        return {"lines": len(package["lines"]), "sources": len(package["sources"]), "api_equivalent": package["api_equivalent"]}
