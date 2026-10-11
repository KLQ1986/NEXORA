"""Spike step 3: cut the selected ranges and build an HTML report the operator can grade."""
import html, json, subprocess
from pathlib import Path
from PIL import Image

root = Path("/Users/kevin/NEXORA/spike")
sel = json.load(open(root / "selections.json"))
lines = {l["id"]: l["text"] for l in json.load(open(root / "script_lines.json"))["lines"]}
videos = {Path(v["path"]).name: v for v in json.load(open(root / "out/videos.json"))}
rep = root / "report"; (rep / "clips").mkdir(parents=True, exist_ok=True)

def mmss(t): return f"{int(t // 60)}:{t % 60:04.1f}"

def cut(video, t_in, t_out, name):
    dst = rep / "clips" / f"{name}.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(t_in), "-t", str(t_out - t_in), "-i", str(root / "footage" / video),
                    "-vf", "scale=-2:540", "-an", "-c:v", "h264_videotoolbox", "-b:v", "2500k", str(dst)], check=True)
    strip = rep / "clips" / f"{name}.jpg"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(t_in), "-t", str(t_out - t_in), "-i", str(root / "footage" / video),
                    "-vf", f"fps={5 / max(t_out - t_in, 0.1)},scale=256:-2,tile=5x1", "-frames:v", "1", "-q:v", "4", str(strip)], check=True)
    return dst.name, strip.name

rows = []
for s in sel["selections"]:
    text = html.escape(lines[s["line"]])
    if s.get("gap"):
        rows.append(f'<section class="gap"><h2>Câu {s["line"]}: {text}</h2><p class="tag gapt">Khoảng trống: không có footage phù hợp</p><p>{html.escape(s["reason"])}</p></section>')
        continue
    clip, strip = cut(s["video"], s["t_in"], s["t_out"], f'L{s["line"]:02d}')
    alts = []
    for i, (a, b) in enumerate(s.get("alternates", []), 1):
        c, st = cut(s["video"], a, b, f'L{s["line"]:02d}_alt{i}')
        alts.append(f'<div class="alt"><p>Dự phòng {i}: {mmss(a)} → {mmss(b)}</p><video controls muted preload="metadata" src="clips/{c}"></video></div>')
    conf = s["confidence"]
    rows.append(f'''<section><h2>Câu {s["line"]}: {text}</h2>
<p><span class="tag c-{ {"cao": "hi", "trung bình": "mid", "thấp": "lo"}[conf] }">Độ tin cậy: {conf}</span> <code>{html.escape(s["video"])}</code> · {mmss(s["t_in"])} → {mmss(s["t_out"])} ({s["t_out"] - s["t_in"]:.1f} giây)</p>
<div class="main"><video controls muted preload="metadata" src="clips/{clip}"></video><img src="clips/{strip}" alt="khung hình của đoạn được chọn"></div>
<p>{html.escape(s["reason"])}</p>
<div class="alts">{"".join(alts)}</div>
<p class="grade">Chấm: ☐ đúng &nbsp; ☐ dùng phương án dự phòng &nbsp; ☐ sai</p></section>''')

total = sum(v["duration"] for v in videos.values())
vt = "".join(f'<tr><td>{html.escape(n)}</td><td>{mmss(v["duration"])}</td><td>{v["width"]}×{v["height"]}</td><td>{v["frames"]}</td><td>{v["prepare_seconds"]} s</td></tr>' for n, v in videos.items())
doc = f'''<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>NEXORA — Kết quả thử nghiệm khớp kịch bản</title><style>
:root{{--fg:#1d2733;--bg:#fff;--mut:#5f6b78;--line:#d8dee5;--hi:#1e7b46;--mid:#9a6a00;--lo:#b3342d;--card:#f6f8fa}}
@media (prefers-color-scheme:dark){{:root{{--fg:#e6e9ec;--bg:#15181c;--mut:#9aa3ad;--line:#353b43;--hi:#5fc98c;--mid:#e0b04a;--lo:#f0827a;--card:#1d2127}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,"Segoe UI",Helvetica,Arial,sans-serif}}
main{{max-width:960px;margin:0 auto;padding:24px 16px 64px}}h1{{font-size:1.5rem}}h2{{font-size:1.05rem;margin:0 0 6px}}
section{{border:1px solid var(--line);border-radius:8px;padding:14px;margin:14px 0;background:var(--card)}}
video{{width:100%;max-width:460px;border-radius:6px;background:#000}}img{{max-width:100%;border-radius:6px}}
.main{{display:flex;flex-direction:column;gap:8px}}.alts{{display:flex;flex-wrap:wrap;gap:12px}}.alt{{flex:1 1 240px;max-width:300px}}.alt p{{margin:6px 0 4px;color:var(--mut);font-size:.9rem}}
.tag{{font-weight:600}}.c-hi{{color:var(--hi)}}.c-mid{{color:var(--mid)}}.c-lo,.gapt{{color:var(--lo)}}.grade{{color:var(--mut)}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid var(--line);padding:5px 8px;text-align:left}}.tw{{overflow-x:auto}}code{{font-size:.9em}}
</style></head><body><main>
<h1>Kết quả thử nghiệm khớp kịch bản với footage</h1>
<p>{html.escape(sel["method"])}</p>
<p>Footage thử: {len(videos)} video, tổng {mmss(total)}, tải từ Wikimedia Commons (giấy phép trong <code>footage/SOURCES.json</code>). 12 câu kịch bản được viết từ tên video, trước khi xem bất kỳ khung hình nào; câu 11 và 12 cố ý không có footage.</p>
<div class="tw"><table><tr><th>Video</th><th>Độ dài</th><th>Khung hình</th><th>Số khung đã trích</th><th>Thời gian trích</th></tr>{vt}</table></div>
{"".join(rows)}
<section><h2>Những điều rút ra</h2><ul>{"".join(f"<li>{html.escape(f)}</li>" for f in sel["findings"])}</ul></section>
</main></body></html>'''
(rep / "index.html").write_text(doc, encoding="utf-8")
print("report:", rep / "index.html")
