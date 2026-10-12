"""Watching a finished cut the way a viewer would: does each picture show what is being said, does the opening earn the
next second, does it end (design v4.0, section 20.2).

One frame is taken from the middle of every shot of the rendered file itself, so what is judged is what will be seen:
crop, captions and all. A model that cannot answer for a shot leaves that shot unjudged; it never passes it.
"""
import time
from pathlib import Path

from nexora.core.adapter import AdapterError, AdapterRegistry, Request
from nexora.core.projects import ProjectStore

WATCH_PROMPT = (
    "Đây là một khung hình trong video, lúc lời dẫn nói: \"{line}\".\n"
    "Bỏ qua dòng phụ đề vẽ trên hình. Hình có cho thấy điều lời dẫn đang nói không? "
    "Chỉ trả về JSON với các khoá: khop (số nguyên 0 đến 10), thay (một câu ngắn tả cái thực sự thấy trong hình)."
)
MATCH_PASS = 5
LONG_OPENING_WORDS, LONG_OPENING_SECONDS = 18, 7.0


class Viewer:
    def __init__(self, projects: ProjectStore, adapters: AdapterRegistry, media_dir: str | Path):
        self._projects, self._adapters = projects, adapters
        self._frames = Path(media_dir) / "watch"
        self._frames.mkdir(parents=True, exist_ok=True)

    def watch(self, render_id: str) -> dict:
        render = self._projects.render(render_id)
        shots = render["qc"].get("shots") or []
        findings, judged, at = [], 0, 0.0
        add = lambda check, n, severity, text, fix: findings.append({"check": check, "shot": n, "severity": severity, "text": text, "fix": fix})
        for n, shot in enumerate(shots, 1):
            middle, at = at + shot["duration"] / 2, at + shot["duration"]
            if shot.get("gap"):
                continue
            frame = self._frames / f"{render_id}_{n}.jpg"
            try:
                self._adapters.submit("ffmpeg", Request("thumbnail", inputs={"path": render["path"]}, params={"out": str(frame), "at": round(middle, 2)}))
                out = self._adapters.submit("model", Request("describe", inputs={"images": [str(frame)]},
                                                            params={"prompt": WATCH_PROMPT.format(line=shot["text"]), "task": "watch", "line": shot["text"], "max_tokens": 160})).outputs["json"]
                score = max(0, min(10, int(float(out["khop"]))))
            except (AdapterError, KeyError, TypeError, ValueError):
                continue
            judged += 1
            if score < MATCH_PASS:
                add("Hình và lời", n, "cao" if score <= 2 else "vừa", f"Hình không khớp lời ({score}/10). Trong hình: {str(out.get('thay') or 'không rõ').strip()}", "Đổi sang clip khác cho câu này, hoặc sửa câu.")
        if shots:
            first, last = shots[0], shots[-1]
            if len(first["text"].split()) > LONG_OPENING_WORDS or first["duration"] > LONG_OPENING_SECONDS:
                add("Mở đầu", 1, "vừa", f"Câu mở đầu dài {len(first['text'].split())} từ và giữ {first['duration']:.1f} giây trước khi sang cảnh mới.", "Mở bằng một câu ngắn với hình mạnh nhất; đưa phần giải thích ra sau.")
            if last["text"].rstrip().endswith(("…", "...", ",")):
                add("Kết", len(shots), "thấp", "Câu cuối bỏ lửng.", "Kết bằng một câu trọn ý.")
            words = [w for s in shots for w in s["text"].lower().split() if len(w) > 3]
            common = max(set(words), key=words.count) if words else None
            if common and words.count(common) >= max(4, len(shots)):
                add("Lặp từ", 1, "thấp", f"Từ “{common}” xuất hiện {words.count(common)} lần trong {len(shots)} câu.", "Thay bằng từ khác ở vài chỗ.")
        result = {"at": time.time(), "judged": judged, "of": sum(1 for s in shots if not s.get("gap")), "findings": findings}
        self._projects.update_render_qc(render_id, viewer=result)
        return result
