"""A script from a topic (design 2026-10-18, Claude Code as NEXORA's writer): a writer that can read the web looks the
subject up and returns a package of its sources and the lines it wrote on them. Nothing in the package is taken on trust:
a source needs a web address and a passage to rest on, a line stating a fact keeps only a source the package has, and a
package with no line is refused before anything is written."""
from __future__ import annotations

import time

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
                        "date": str(s.get("date") or "").strip() or None, "passage": passage[:PASSAGE]})
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
