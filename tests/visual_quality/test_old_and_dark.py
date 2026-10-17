"""Old footage (tape) and dark footage: what the recipe finds and proposes for them."""
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from nexora.modules.visual_quality import measure as M
from nexora.modules.visual_quality import plan as P

from tests.visual_quality.test_vq import drain, texture, vq_system


def _tape(path: Path, *, seconds: int = 2) -> Path:
    """An SD capture from tape: interlaced (top field first, marked progressive), colour carried 6 px to the right, the last
    8 rows torn sideways, a little soft and noisy."""
    work = path.parent / "tape_frames"
    work.mkdir(parents=True, exist_ok=True)
    with Image.open(texture(path.with_suffix(".png"), size=(1000, 600), seed=5)) as im:
        scene = np.asarray(im.convert("RGB"), np.float64)
    rng = np.random.default_rng(3)
    for k in range(seconds * 60):                                  # 59.94 progressive frames, interlaced into 29.97 below
        f = scene[40:520, 20 + k * 2:740 + k * 2].copy()
        y = f @ np.array([0.2126, 0.7152, 0.0722])
        f = y[..., None] + np.roll(f - y[..., None], 6, axis=1)
        for r in range(472, 480):
            f[r] = np.roll(f[r], int(rng.integers(10, 40)), axis=0) + rng.normal(0, 20, f[r].shape)
        Image.fromarray(np.clip(f + rng.normal(0, 3, f.shape), 0, 255).astype(np.uint8)).save(work / f"{k:04d}.png")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", "60000/1001", "-i", str(work / "%04d.png"),
                    "-vf", "interlace=scan=tff,setfield=prog", "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def _night(path: Path) -> Path:
    """A clip dark all over (no bright part), with faint noise that only shows once it is lifted."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(texture(path.with_suffix(".png"), size=(960, 540), seed=8)) as im:
        dark = (np.asarray(im.convert("RGB"), np.float64) * 0.22).astype(np.uint8)
    Image.fromarray(dark).save(path.with_suffix(".dark.png"))
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-framerate", "25", "-t", "2", "-i", str(path.with_suffix(".dark.png")),
                    "-vf", "crop=800:450:'20+t*20':40,noise=alls=5:allf=t", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def test_the_scan_of_a_video_is_read_from_its_picture_and_a_split_reading_is_not_taken_for_interlace():
    assert P.scan_of({"tff": 120, "bff": 0, "progressive": 0, "undetermined": 0, "repeated": 0, "frames": 120}) == "interlaced"
    assert P.scan_of({"tff": 120, "bff": 0, "progressive": 0, "undetermined": 0, "repeated": 48, "frames": 120}) == "telecine"
    assert P.scan_of({"tff": 53, "bff": 48, "progressive": 19, "undetermined": 0, "repeated": 0, "frames": 120}) == "progressive"
    assert P.scan_of({"tff": 0, "bff": 0, "progressive": 0, "undetermined": 201, "repeated": 0, "frames": 201}) == "progressive"
    assert P.scan_of(None) is None


def test_a_tape_capture_is_deinterlaced_its_colour_put_back_and_its_torn_rows_covered(tmp_path):
    system = vq_system(tmp_path)
    clip = _tape(tmp_path / "in" / "tape.mp4")
    subject = system.vq.subject_for_file(clip)
    system.vq.analyse(subject, stabilise=False)
    drain(system)
    tech = system.vq_reader.profile(subject)["technical"]
    assert P.scan_of(tech["idet"]) == "interlaced" and tech["field_order"] == "progressive"
    assert 4.5 <= tech["chroma_offset"][0] <= 7.5 and tech["bottom_band"] >= 6
    steps = {s["op"]: s for s in system.vq_reader.recipe(subject).shots[0]["steps"]}
    assert "deinterlace" in steps and "thấy trên hình" in steps["deinterlace"]["why"]
    assert steps["chroma_align"]["params"]["cb"] == -3                # 6 px is 3 chroma samples in 4:2:0
    assert steps["trim_band"]["params"]["rows"] >= 6
    assert "upscale" not in steps                                      # no model here to make 1080p: a resample is left to the cut


def test_a_dark_shot_is_lifted_further_and_its_faint_noise_denoised_for_the_lift(tmp_path):
    system = vq_system(tmp_path)
    subject = system.vq.subject_for_file(_night(tmp_path / "in" / "night.mp4"))
    system.vq.analyse(subject, stabilise=False, sharpen=False)
    drain(system)
    shot = system.vq_reader.recipe(subject).shots[0]
    steps = {s["op"]: s for s in shot["steps"]}
    assert steps["levels"]["params"]["gamma"] > 1.4 and "thiếu sáng" in steps["levels"]["why"]
    assert steps["denoise"]["params"]["lift"] > 1.2 and "sau khi nâng sáng" in steps["denoise"]["why"]


def test_lift_is_the_slope_of_the_levels_at_the_middle():
    assert P.lift(None, 0.4) == 1.0
    assert P.lift({"black": [0, 0, 0], "white": [0.6] * 3, "gamma": 1.7}, 0.15) == 1.735
    assert P.lift({"black": [0, 0, 0], "white": [1.0] * 3, "gamma": 0.8}, 0.3) == 1.0    # where a curve flattens it is never under 1


def test_measures_of_tape_damage_find_what_was_done_and_nothing_on_a_clean_frame(tmp_path):
    img = np.asarray(Image.open(texture(tmp_path / "c.png", size=(720, 480), seed=2)).convert("RGB"), np.float64)
    assert max(abs(v) for v in M.chroma_offset(img)) < 1.0 and M.bottom_band([img] * 4) == 0
    y = img @ np.array([0.2126, 0.7152, 0.0722])
    moved = y[..., None] + np.roll(img - y[..., None], 4, axis=1)
    assert abs(M.chroma_offset(moved)[1] - 4) < 0.6
