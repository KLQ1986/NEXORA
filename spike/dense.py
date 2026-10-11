"""Spike step 2: dense re-sampling of candidate ranges, to locate exact in and out points.

Usage: uv run --with pillow python dense.py <ranges.json> <out_dir>
ranges.json: [{"name": "L3_a", "video": "footage/x.webm", "start": 56, "end": 62}, ...]
"""
import json, subprocess, sys, tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

FPS, COLS, THUMB_W = 2, 8, 256
ranges, out = json.load(open(sys.argv[1])), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
font = ImageFont.load_default(size=13)
for r in ranges:
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(r["start"]), "-t", str(r["end"] - r["start"]),
                        "-i", r["video"], "-vf", f"fps={FPS},scale={THUMB_W}:-2", "-q:v", "4", f"{tmp}/f_%04d.jpg"], check=True)
        frames = sorted(Path(tmp).glob("f_*.jpg"))
        w, h = Image.open(frames[0]).size
        rows = (len(frames) + COLS - 1) // COLS
        sheet = Image.new("RGB", (COLS * w, rows * h), "black")
        for i, f in enumerate(frames):
            img = Image.open(f); t = r["start"] + i / FPS
            d = ImageDraw.Draw(img); label = f"{int(t // 60):02d}:{t % 60:04.1f}"
            box = d.textbbox((4, 3), label, font=font)
            d.rectangle((box[0] - 3, box[1] - 2, box[2] + 3, box[3] + 2), fill="black"); d.text((4, 3), label, fill="yellow", font=font)
            sheet.paste(img, ((i % COLS) * w, (i // COLS) * h))
        sheet.save(out / f"{r['name']}.jpg", quality=82)
        print(r["name"], len(frames), "frames")
