"""Spike step 1: turn videos into time-stamped contact sheets that a vision model can read.

Throwaway code for the validation spike (design v4.0, section 11.5). Not part of NEXORA.

Usage:  uv run --with pillow python prepare.py <video-or-folder> [--fps 1] [--out out]
"""
import argparse, json, subprocess, sys, time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".webm", ".ogv"}
COLS, ROWS, THUMB_W = 4, 4, 384


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True).stdout
    info = json.loads(out)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
    num, den = (video.get("avg_frame_rate") or "0/1").split("/")
    return {
        "duration": float(info["format"].get("duration") or video.get("duration") or 0),
        "width": video["width"], "height": video["height"],
        "fps": round(float(num) / float(den or 1), 3) if float(den or 1) else 0,
        "codec": video["codec_name"],
        "color_transfer": video.get("color_transfer"),
        "has_audio": bool(audio),
        "created": info["format"].get("tags", {}).get("creation_time"),
    }


def scene_changes(path, threshold=0.3):
    """Timestamps where the picture changes sharply (FFmpeg scene score)."""
    err = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-vf", f"select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    return [round(float(line.split("pts_time:")[1].split()[0]), 2) for line in err.splitlines() if "pts_time:" in line]


def extract_frames(path, fps, frames_dir):
    frames_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
         "-vf", f"fps={fps},scale={THUMB_W}:-2", "-q:v", "4", str(frames_dir / "f_%05d.jpg")],
        check=True)
    return sorted(frames_dir.glob("f_*.jpg"))


def stamp(seconds):
    return f"{int(seconds // 60):02d}:{seconds % 60:04.1f}"


def contact_sheets(frames, fps, sheets_dir):
    sheets_dir.mkdir(parents=True, exist_ok=True)
    font = ImageFont.load_default(size=max(11, THUMB_W // 20))
    per_sheet, sheets = COLS * ROWS, []
    for start in range(0, len(frames), per_sheet):
        batch = frames[start:start + per_sheet]
        first = Image.open(batch[0])
        w, h = first.size
        sheet = Image.new("RGB", (COLS * w, ROWS * h), "black")
        times = []
        for i, frame in enumerate(batch):
            t = (start + i) / fps
            img = Image.open(frame)
            draw = ImageDraw.Draw(img)
            label = stamp(t)
            box = draw.textbbox((6, 4), label, font=font)
            draw.rectangle((box[0] - 4, box[1] - 2, box[2] + 4, box[3] + 2), fill="black")
            draw.text((6, 4), label, fill="yellow", font=font)
            sheet.paste(img, ((i % COLS) * w, (i // COLS) * h))
            times.append(round(t, 2))
        name = sheets_dir / f"sheet_{start // per_sheet:03d}.jpg"
        sheet.save(name, quality=80)
        sheets.append({"file": name.name, "t_start": times[0], "t_end": round(times[-1] + 1 / fps, 2)})
    return sheets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--out", default="out")
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--rows", type=int, default=4)
    ap.add_argument("--thumb", type=int, default=384)
    args = ap.parse_args()
    global COLS, ROWS, THUMB_W
    COLS, ROWS, THUMB_W = args.cols, args.rows, args.thumb
    src = Path(args.source).expanduser()
    videos = sorted(p for p in (src.rglob("*") if src.is_dir() else [src]) if p.suffix.lower() in VIDEO_EXT)
    if not videos:
        sys.exit(f"no video files found under {src}")
    out = Path(args.out)
    report = []
    for n, video in enumerate(videos, 1):
        vid = f"v{n:02d}"
        t0 = time.time()
        meta = probe(video)
        frames = extract_frames(video, args.fps, out / vid / "frames")
        sheets = contact_sheets(frames, args.fps, out / vid / "sheets")
        cuts = scene_changes(video)
        entry = {"id": vid, "path": str(video), **meta, "frames": len(frames), "sheets": sheets,
                 "scene_changes": cuts, "prepare_seconds": round(time.time() - t0, 1)}
        (out / vid / "index.json").write_text(json.dumps(entry, indent=2, ensure_ascii=False))
        report.append(entry)
        print(f"{vid}  {video.name}  {meta['duration']:.0f}s  {meta['width']}x{meta['height']}  audio={meta['has_audio']}  "
              f"transfer={meta['color_transfer']}  frames={len(frames)}  sheets={len(sheets)}  cuts={len(cuts)}  prep={entry['prepare_seconds']}s")
    (out / "videos.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
