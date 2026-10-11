"""Cropping around the subject, and cutting to a second picture inside one shot."""
import subprocess

from PIL import Image

from nexora.adapters.media import FFmpegAdapter
from nexora.core.adapter import Request


def colour_at(video, t, tmp_path):
    out = tmp_path / f"f{t}.png"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(t), "-i", str(video), "-frames:v", "1", str(out)], check=True)
    r, g, b = Image.open(out).convert("RGB").resize((1, 1)).getpixel((0, 0))
    return "red" if r > 150 and b < 100 else "blue" if b > 150 and r < 100 else f"other({r},{g},{b})"


def two_halves(path):
    """A wide clip: red on the left, blue on the right."""
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x180:r=25:d=3", "-f", "lavfi", "-i",
                    "color=c=blue:s=320x180:r=25:d=3", "-filter_complex", "hstack", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def test_a_narrow_frame_is_cropped_around_the_subject_not_the_middle(tmp_path):
    src = two_halves(tmp_path / "wide.mp4")
    for focus, seen in ((0.1, "red"), (0.9, "blue")):
        out = tmp_path / f"{seen}.mp4"
        FFmpegAdapter().submit(Request("segment", inputs={"path": str(src)}, params={"out": str(out), "duration": 2, "width": 180, "height": 320, "fill": "cover", "focus_x": focus}))
        assert colour_at(out, 1, tmp_path) == seen


def test_an_insert_takes_over_the_picture_from_its_moment_to_the_end_of_the_shot(tmp_path):
    main, red = tmp_path / "main.mp4", tmp_path / "red.jpg"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=25:d=4", "-pix_fmt", "yuv420p", str(main)], check=True)
    Image.new("RGB", (640, 360), (230, 20, 20)).save(red)
    out = tmp_path / "cut.mp4"
    FFmpegAdapter().submit(Request("segment", inputs={"path": str(main)}, params={"out": str(out), "duration": 3, "width": 320, "height": 180,
                                                                                    "inserts": [{"path": str(red), "at": 1.5}]}))
    assert colour_at(out, 0.7, tmp_path) == "blue" and colour_at(out, 2.3, tmp_path) == "red"
