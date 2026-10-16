"""Visual Quality: a source is profiled, assessed and given a recipe; the recipe is previewed, approved and applied, for
any file and for an asset of the library, and a cut or an extract uses only an approved recipe."""
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from nexora.api.app import create_app
from nexora.app import build
from nexora.core.visual_quality import filters_of, step_filters
from nexora.modules.visual_quality import measure as M
from nexora.modules.visual_quality import plan as P
from nexora.modules.visual_quality.registry import identify
from nexora.third_party.basicsr import degradations as D

from tests.conftest import make_video

IDENTITY = "LUT_3D_SIZE 2\n" + "".join(f"{r} {g} {b}\n" for b in (0, 1) for g in (0, 1) for r in (0, 1))


def drain(system):
    while system.worker.run_once():
        pass


def texture(path: Path, size=(960, 540), seed: int = 0) -> Path:
    """A natural-looking picture (1/f noise, as foliage and stone have), in colour."""
    rng = np.random.default_rng(seed)
    h, w = size[1], size[0]
    fy, fx = np.fft.fftfreq(h)[:, None], np.fft.fftfreq(w)[None, :]
    amp = 1.0 / np.maximum(np.hypot(fy, fx), 1.0 / max(h, w))
    chans = []
    for c in range(3):
        f = amp * np.exp(2j * np.pi * rng.random((h, w)))
        x = np.real(np.fft.ifft2(f))
        chans.append((x - x.min()) / (x.max() - x.min()))
    img = np.stack(chans, -1) * np.array([0.7, 0.85, 0.6]) + np.array([0.1, 0.05, 0.12])
    Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).save(path)
    return path


def fake_dlogm(path: Path, seconds: int = 3) -> Path:
    """A flat 10-bit clip of a textured scene with a slow pan and sensor noise, tagged as an Osmo Action 6, as D-Log M comes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tex = texture(path.with_suffix(".png"))
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-framerate", "25", "-t", str(seconds), "-i", str(tex),
                    "-vf", "crop=640:360:'40+t*20':60,format=yuv420p10le,noise=alls=6:allf=t,eq=contrast=0.45:saturation=0.4:brightness=0.06",
                    "-c:v", "libx265", "-crf", "12", "-x265-params", "log-level=error", "-pix_fmt", "yuv420p10le", "-tag:v", "hvc1",
                    "-movflags", "use_metadata_tags", "-metadata", "make=DJI", "-metadata", "model=OsmoAction6", str(path)], check=True)
    return path


def vq_system(tmp_path):
    system = build(tmp_path / "data")
    (system.data_dir / "luts").mkdir(parents=True, exist_ok=True)
    (system.data_dir / "luts" / "dji_osmo_action6_dlogm_to_rec709.cube").write_text(IDENTITY)
    return system


# ------------------------------------------------------------------------------------------------------- pure parts
def test_an_encoding_is_taken_from_the_camera_and_the_look_together_and_never_guessed():
    dji = {"device": "DJI OsmoAction6", "bit_depth": 10, "color_transfer": "bt709"}
    m = identify(dji, contrast=0.3, saturation=0.08)
    assert m.encoding.key == "dji_osmo_action6_dlogm" and m.confidence == "high" and any("bt709" in w for w in m.warnings)
    assert identify(dji, contrast=0.6, saturation=0.3).encoding.key == "rec709"            # the same camera, shot in its normal colour
    unknown = identify({"device": "Acme Cam", "bit_depth": 10}, contrast=0.3, saturation=0.08)
    assert unknown.encoding is None and "không nhận ra" in unknown.warnings[0]
    assert identify({"color_transfer": "arib-std-b67", "dolby_vision": True}, contrast=0.5, saturation=0.2).encoding.key == "hdr_hlg"
    assert identify({"device": "Apple iPhone 15 Pro", "bit_depth": 10}, contrast=0.3, saturation=0.08).encoding.key == "apple_log"


def test_steps_become_filters_and_a_step_of_another_tool_asks_for_a_prepared_file():
    assert step_filters({"op": "color_transform", "params": {"lut": "/a b/x.cube"}}) == ["lut3d=file='/a b/x.cube':interp=tetrahedral"]
    lv = step_filters({"op": "levels", "params": {"black": [0.05] * 3, "white": [0.9, 0.95, 1.0], "gamma": 1.2, "saturation": 1.1}})
    assert lv[0] == "format=gbrp16le" and lv[1].startswith("colorlevels=rimin=0.0500:rimax=0.9000") and lv[2] == "eq=gamma=1.200:saturation=1.100"
    assert filters_of([{"op": "denoise", "tier": "apple_vt", "params": {}}]) is None
    assert filters_of([{"op": "sharpen", "params": {"strength": 0.3}, "off": True}]) == []


def test_exposure_and_white_balance_follow_the_picture_and_leave_a_low_key_scene_dark():
    dark = {"luma_p01": 0.02, "luma_p50": 0.18, "luma_p99": 0.7, "clipped_high": 0.0, "saturation": 0.2, "cast_r": 1.0, "cast_b": 1.0}
    lifted = P.exposure_balance(dark, content="camera")
    assert lifted["params"]["gamma"] > 1.2 and lifted["params"]["white"][0] < 1.0
    night = dict(dark, luma_p99=0.97, luma_p50=0.12)
    assert P.exposure_balance(night, content="camera")["params"]["gamma"] <= 1.15
    warm = dict(dark, luma_p50=0.45, luma_p99=0.95, cast_r=1.12, cast_b=0.86)
    w = P.exposure_balance(warm, content="camera")["params"]["white"]
    assert w[0] > 1.0 > w[2]                                                 # less red gain, more blue gain
    assert P.exposure_balance(dict(warm, cast_r=1.0, cast_b=1.0, luma_p01=0.0), content="camera") is None
    white_card = {"luma_p01": 0.44, "luma_p50": 0.9, "luma_p99": 0.98, "clipped_high": 0.0, "saturation": 0.2, "cast_r": 1.0, "cast_b": 1.0}
    card = P.exposure_balance(white_card, content="graphics")
    assert card is None or card["params"]["black"] == [0.0, 0.0, 0.0]          # a white card is not lifted blacks


def test_levels_are_baked_into_a_lut_that_does_exactly_what_they_say(tmp_path):
    lut = Path(P.levels_lut({"black": [0.1] * 3, "white": [0.9] * 3, "gamma": 1.0, "saturation": 1.0}, tmp_path, size=5))
    rows = [list(map(float, line.split())) for line in lut.read_text().splitlines() if line[:1].isdigit()]
    assert len(rows) == 125 and rows[0] == [0.0, 0.0, 0.0] and rows[-1] == [1.0, 1.0, 1.0]
    assert abs(rows[2][0] - (0.5 - 0.1) / 0.8) < 1e-6 and rows[2][1] == 0.0          # red 0.5 → 0.5 of the new range; red changes fastest
    assert P.levels_lut({"black": [0.1] * 3, "white": [0.9] * 3}, tmp_path, size=5) == str(lut)      # same numbers, same file


def test_temporal_qa_lets_a_grade_through_and_stops_a_frame_turned_black():
    from nexora.modules.visual_quality import qa as Q
    rng = np.random.default_rng(2)
    base = [np.clip(D.blur(rng.random((180, 320, 3)).astype(np.float32), 2) + 0.01 * k, 0, 1) for k in range(8)]
    graded = [np.power(f, 0.7) for f in base]
    assert Q.compare(base, graded, colour_changed=True)["verdict"] in ("pass", "warn")
    panning = [np.roll(f, 6 * k, axis=1) for k, f in enumerate(base)]               # a pan, graded with more contrast: not the grade's fault
    contrasty = [np.clip((f - 0.5) * 1.8 + 0.5, 0, 1) for f in panning]
    assert Q.compare(panning, contrasty, colour_changed=True, ops=["color_transform", "levels"])["verdict"] in ("pass", "warn")
    shimmer = [np.clip(f + 0.08 * (k % 2), 0, 1) for k, f in enumerate(panning)]    # a step that pumps brightness frame to frame
    assert Q.compare(panning, shimmer, colour_changed=False, ops=["denoise"])["verdict"] == "fail"
    black = [np.zeros_like(f) for f in base]
    bad = Q.compare(base, black, colour_changed=True)
    assert bad["verdict"] == "fail" and any("cấu trúc" in r for r in bad["reasons"])


def test_measures_see_the_defects_made_on_purpose():
    rng = np.random.default_rng(0)
    img = np.clip(np.stack([np.linspace(0.2, 0.8, 640)[None, :].repeat(360, 0)] * 3, -1) + rng.normal(0, 0.03, (360, 640, 3)), 0, 1).astype(np.float32)
    img = D.blur(img, 1.0)
    clean = M.look(img)
    assert M.look(D.add_gaussian_noise(img, 15)).noise > clean.noise * 3
    assert M.look(D.jpeg(img, 8)).blockiness > clean.blockiness + 0.3
    assert M.look(D.blur(img, 3)).sharpness < clean.sharpness / 3
    assert M.look(D.flatten_log(img)).contrast < clean.contrast * 0.6


# -------------------------------------------------------------------------------------------------------- end to end
def test_any_file_is_profiled_given_a_recipe_previewed_approved_and_written_with_rec709_tags(tmp_path):
    system = vq_system(tmp_path)
    src = fake_dlogm(tmp_path / "in" / "dlogm.mov")
    subject = system.vq.subject_for_file(src)
    system.vq.analyse(subject)
    drain(system)
    profile = system.vq_reader.profile(subject)
    assert profile["encoding"] == "dji_osmo_action6_dlogm" and profile["content"] == "camera"
    assert any("phẳng như log" in w for w in profile["warnings"])
    recipe = system.vq_reader.recipe(subject)
    ops = [s["op"] for s in recipe.shots[0]["steps"]]
    assert recipe.status == "proposed" and "color_transform" in ops
    assert system.vq_reader.filters_for(subject, 0, 1) == []                # not approved: nothing is applied
    system.vq.preview(subject, t=1.5, seconds=1.0)
    drain(system)
    shown = system.vq_reader.previews(recipe.recipe_id)[0]
    assert Path(shown["files"]["before_still"]).is_file() and Path(shown["files"]["after_video"]).is_file()
    assert shown["qa"]["verdict"] in ("pass", "warn", "fail") and "flicker" in shown["qa"]["metrics"]
    system.vq.approve(recipe.recipe_id)
    assert any("lut3d" in f for f in system.vq_reader.filters_for(subject, 0, 1))
    out = tmp_path / "out" / "graded.mp4"
    system.vq.apply(subject, out=out)
    drain(system)
    assert out.is_file()
    tags = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=color_primaries,color_transfer,pix_fmt",
                           "-of", "json", str(out)], capture_output=True, text=True).stdout
    stream = json.loads(tags)["streams"][0]
    assert stream["color_transfer"] == "bt709" and stream["color_primaries"] == "bt709" and stream["pix_fmt"] == "yuv420p10le"


def test_a_screen_recording_is_not_denoised_or_sharpened(tmp_path):
    system = vq_system(tmp_path)
    src = make_video(tmp_path / "in" / "screen.mp4", picture=2, size="640x360")
    subject = system.vq.subject_for_file(src)
    system.vq.analyse(subject, denoise=True, sharpen=True)
    drain(system)
    assert system.vq_reader.profile(subject)["content"] in ("screen", "graphics")
    ops = {s["op"] for shot in system.vq_reader.recipe(subject).shots for s in shot["steps"]}
    assert not ops & {"denoise", "sharpen", "stabilise"}


def test_a_still_is_profiled_and_written(tmp_path):
    system = vq_system(tmp_path)
    rng = np.random.default_rng(1)
    pic = (np.clip(rng.normal(0.25, 0.05, (400, 600, 3)), 0, 1) * 255).astype(np.uint8)          # dark and noisy
    src = tmp_path / "in" / "dark.jpg"
    src.parent.mkdir(parents=True)
    Image.fromarray(pic).save(src, quality=92)
    subject = system.vq.subject_for_file(src)
    system.vq.analyse(subject, approve=True)
    drain(system)
    recipe = system.vq_reader.recipe(subject, status="approved")
    assert system.vq_reader.profile(subject)["content"] == "still" and recipe is not None
    assert "levels" in {s["op"] for s in recipe.shots[0]["steps"]}
    out = tmp_path / "out" / "fixed.png"
    system.vq.apply(subject, out=out)
    drain(system)
    after = np.asarray(Image.open(out).convert("RGB"), np.float32) / 255
    assert float(M.luma(after).mean()) > float(M.luma(pic / 255.0).mean()) + 0.05


def test_an_asset_of_the_library_uses_video_intelligence_shots_and_the_api_shows_it(tmp_path):
    system = vq_system(tmp_path)
    asset, _ = system.library.ingest(fake_dlogm(tmp_path / "in" / "lib.mov"))
    drain(system)
    client = TestClient(create_app(system))
    run = client.post(f"/api/v1/assets/{asset}/vq/plan", json={}).json()
    assert run["run_id"]
    drain(system)
    shown = client.get(f"/api/v1/assets/{asset}/vq").json()
    assert shown["profile"]["encoding"] == "dji_osmo_action6_dlogm" and shown["recipe"]["status"] == "proposed"
    rid = shown["recipe"]["recipe_id"]
    assert client.post(f"/api/v1/vq/recipes/{rid}/approve").status_code == 200
    assert client.get(f"/api/v1/assets/{asset}/vq").json()["approved"] == rid
    job = client.post("/api/v1/vq/jobs", json={"path": str(fake_dlogm(tmp_path / "in" / "other.mov", 2))}).json()
    drain(system)
    assert client.get(f"/api/v1/vq/jobs/{job['subject']}").json()["profile"]["encoding"] == "dji_osmo_action6_dlogm"
    assert client.post("/api/v1/vq/jobs", json={"path": "/no/such/file.mov"}).status_code == 404


def test_an_extract_and_a_cut_take_the_approved_recipe_and_only_that(tmp_path):
    system = vq_system(tmp_path)
    asset, _ = system.library.ingest(fake_dlogm(tmp_path / "in" / "lib.mov"))
    drain(system)
    plain = system.extractor.extract(asset, 0.5, 1.5, kinds=("still",))
    assert "visual_quality" not in plain["card"]                          # no recipe yet: as it was
    system.vq.analyse(system.vq.subject_for_asset(asset))
    drain(system)
    recipe = system.vq_reader.recipe(asset)
    assert "visual_quality" not in system.extractor.extract(asset, 0.5, 1.5, kinds=("still",))["card"]   # proposed is not approved
    system.vq.approve(recipe.recipe_id)
    graded = system.extractor.extract(asset, 0.5, 1.5, kinds=("clip",), name="graded")
    assert graded["card"]["visual_quality"]["recipe_id"] == recipe.recipe_id
    tags = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=color_transfer", "-of", "json",
                                      graded["files"]["clip"]], capture_output=True, text=True).stdout)["streams"][0]
    assert tags["color_transfer"] == "bt709"
    treat: dict = {"color_transfer": "arib-std-b67"}
    path = str(system.assets.path_of(system.assets.original(asset)))
    _, _, key = system.edit._apply_vq(asset, path, 0.5, 1.0, "sum", treat)
    assert any(f.startswith("lut3d") for f in treat["vq_filters"]) and treat["color_transfer"] is None and key == "sum"


def test_an_enhanced_copy_carries_the_approved_recipe_with_the_same_steps(tmp_path):
    system = vq_system(tmp_path)
    asset, _ = system.library.ingest(fake_dlogm(tmp_path / "in" / "lib.mov", 2))
    drain(system)
    system.vq.analyse(system.vq.subject_for_asset(asset), approve=True)
    drain(system)
    recipe, whole = system.vq_reader.whole_filters(asset)
    assert recipe is not None and any(f.startswith("lut3d") for f in whole)
    system.library.enhance(asset, upscale=2)
    drain(system)
    enhanced = next(v for v in system.assets.versions(asset) if v.role == "enhanced")
    assert enhanced.metadata["visual_quality"] == recipe.recipe_id and f"_v{recipe.version}" in enhanced.relative_path
    size = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                           str(system.assets.path_of(enhanced))], capture_output=True, text=True).stdout.strip()
    assert size == "1280,720"


def test_the_benchmark_finds_each_damage_and_its_step_undoes_it(tmp_path):
    from nexora.modules.visual_quality import benchmark as B
    system = vq_system(tmp_path)
    clean = np.asarray(Image.open(texture(tmp_path / "clean.png", size=(640, 400), seed=5)).convert("RGB"), np.float32) / 255
    clean = D.blur(clean, 0.8)
    made = B.run(system.adapters, clean, cases=["noise", "jpeg", "dark", "cast"], lut_dir=tmp_path / "luts")
    by = {r["case"]: r for r in made["rows"]}
    assert by["noise"]["found"] and by["noise"]["psnr_fixed"] > by["noise"]["psnr_bad"] + 3
    assert by["jpeg"]["found"] and by["jpeg"]["helps"]
    assert by["dark"]["helps"] and by["cast"]["helps"]
    assert "Phát hiện đúng" in B.table(made)


APPLE = Path("data/tools/apple_frames/apple_frames").resolve()
FULL = Path("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg")


def shaky(path: Path, *, audio: bool = True, seconds: int = 3) -> Path:
    """A textured clip whose frame jumps a few pixels at random each frame, with sensor noise and a tone: handheld footage."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tex = texture(path.with_suffix(".png"), size=(800, 480), seed=7)
    # Things with edges and corners, as a real scene has, for a tracker to hold on to.
    from PIL import ImageDraw
    rng = np.random.default_rng(11)
    with Image.open(tex) as im:
        im = im.convert("RGB")
        draw = ImageDraw.Draw(im)
        for _ in range(140):
            x, y = int(rng.integers(0, 780)), int(rng.integers(0, 460))
            draw.rectangle([x, y, x + int(rng.integers(6, 40)), y + int(rng.integers(6, 40))], fill=tuple(int(v) for v in rng.integers(0, 255, 3)))
        im.save(tex)
    jitter = "crop=640:360:'80+12*sin(n*1.7)+9*sin(n*3.1)':'60+10*cos(n*2.3)+7*sin(n*4.7)'"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-framerate", "25", "-t", str(seconds), "-i", str(tex)]
    if audio:
        cmd += ["-f", "lavfi", "-t", str(seconds), "-i", "sine=frequency=440:sample_rate=48000"]
    cmd += ["-vf", f"{jitter},noise=alls=14:allf=t", "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p"] + (["-c:a", "aac", "-shortest"] if audio else []) + [str(path)]
    subprocess.run(cmd, check=True)
    return path


@pytest.mark.skipif(not APPLE.is_file(), reason="Apple's frame processors are not built on this machine")
def test_a_temporal_denoise_by_apple_is_prepared_with_its_sound_and_taken_by_a_cut(tmp_path):
    from nexora.adapters.apple_frames import AppleFrames
    system = vq_system(tmp_path)
    system.adapters.register(AppleFrames(APPLE))
    asset, _ = system.library.ingest(shaky(tmp_path / "in" / "noisy.mp4"))
    drain(system)
    subject = system.vq.subject_for_asset(asset)
    system.vq.analyse(subject, stabilise=False)
    drain(system)
    recipe = system.vq_reader.recipe(subject)
    tiers = {s["op"]: s.get("tier") for shot in recipe.shots for s in shot["steps"]}
    assert tiers.get("denoise") == "apple_vt"                              # the measured noise calls for it, and Apple's filter is here
    system.vq.approve(recipe.recipe_id)
    system.vq.apply(subject)
    drain(system)
    shot = recipe.shots[0]
    prepared = system.vq_reader.prepared_for(subject, shot["t_start"], shot["t_end"])
    assert prepared is not None and Path(prepared[0]).is_file()
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", prepared[0]], capture_output=True, text=True).stdout.split()
    assert "video" in streams and "audio" in streams
    path, t_in, key = system.edit._apply_vq(asset, str(system.assets.path_of(system.assets.original(asset))), shot["t_start"], 1.0, "sum", {})
    assert path == prepared[0] and key.startswith("sum:vq:")


@pytest.mark.skipif(not FULL.is_file(), reason="an FFmpeg with vidstab is not installed")
def test_a_shaky_clip_is_steadied_and_measures_steadier(tmp_path):
    system = build(tmp_path / "data", ffmpeg_binary=str(FULL))
    src = shaky(tmp_path / "in" / "shaky.mp4", audio=False)
    subject = system.vq.subject_for_file(src)
    system.vq.analyse(subject, denoise=False)
    drain(system)
    recipe = system.vq_reader.recipe(subject)
    steps = [s for shot in recipe.shots for s in shot["steps"]]
    stab = [s for s in steps if s["op"] == "stabilise"]
    assert stab and stab[0]["tier"] == "vidstab"
    out = system.vq._render(src, stab, out=tmp_path / "out" / "steady.mov", kind="video", t_in=0.0, seconds=3.0, master=True)
    before = system.vq.profiler.sample(src, duration=3, subject=subject, width=480, fps=12, tag="b")
    after = system.vq.profiler.sample(out, duration=3, subject=subject, width=480, fps=12, tag="a")
    assert M.shake(after) < M.shake(before) * 0.6


GYROFLOW = Path("/Applications/Gyroflow.app/Contents/MacOS/gyroflow")


class _Recorder:
    """A stand-in for a frame tool: copies the span it is given to ProRes, and records what it was given."""
    def __init__(self, name, ops, calls, gyro=False):
        self.name, self.ops, self.calls, self.gyro = name, ops, calls, gyro

    def describe(self):
        from nexora.core.adapter import Capability
        return Capability(name=self.name, operations=self.ops, runs="local")

    def available(self):
        return True

    def environment(self):
        return {"available": True, "denoise": True}

    def submit(self, request):
        from nexora.core.adapter import Result
        if request.operation == "probe":
            return Result(outputs={"gyro": self.gyro})
        p = request.params
        self.calls.append((self.name, request.inputs["path"], float(p.get("t_in", 0.0))))
        Path(p["out"]).parent.mkdir(parents=True, exist_ok=True)
        span = (["-ss", f"{p['t_in']}"] if p.get("t_in") else []) + (["-t", f"{p['seconds']}"] if p.get("seconds") else [])
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *span, "-i", request.inputs["path"], "-an", "-c:v", "prores_ks", p["out"]], check=True)
        return Result(outputs={}, files=(p["out"],))


def test_gyro_stabilising_is_chosen_only_with_gyro_data_and_runs_first_on_the_original(tmp_path):
    system = vq_system(tmp_path)
    calls: list = []
    system.adapters.register(_Recorder("gyroflow", ("probe", "stabilise"), calls, gyro=True))
    src = shaky(tmp_path / "in" / "gyro.mp4")
    subject = system.vq.subject_for_file(src)
    system.vq.analyse(subject, denoise=False)
    drain(system)
    assert system.vq_reader.profile(subject)["technical"]["gyro"] is True
    stab = [s for shot in system.vq_reader.recipe(subject).shots for s in shot["steps"] if s["op"] == "stabilise"]
    assert stab and stab[0]["tier"] == "gyroflow"                              # the gyro beats guessing motion from the picture
    # Placed after a denoise by the order of steps, it is still run first, on the original and at the shot's own time.
    system.adapters.register(_Recorder("apple_frames", ("denoise",), calls))
    steps = [{"op": "denoise", "tier": "apple_vt", "params": {"strength": 0.5}}, stab[0], {"op": "sharpen", "tier": "ffmpeg", "params": {"strength": 0.2}}]
    out, rest = system.vq._prepare(src, steps, t_in=1.0, seconds=1.0, work=tmp_path / "work")
    assert [c[0] for c in calls] == ["gyroflow", "apple_frames"]
    assert calls[0][1] == str(src) and calls[0][2] == 1.0 and calls[1][1] != str(src)
    assert [s["op"] for s in rest] == ["sharpen"] and out.is_file()


@pytest.mark.skipif(not GYROFLOW.is_file(), reason="Gyroflow is not installed")
def test_gyroflow_says_a_file_without_gyro_has_none_and_renders_the_span_asked(tmp_path):
    from nexora.adapters.gyroflow import Gyroflow
    from nexora.core.adapter import Request
    src = shaky(tmp_path / "in" / "plain.mp4", audio=False)
    tool = Gyroflow(GYROFLOW)
    assert tool.submit(Request("probe", inputs={"path": str(src)})).outputs["gyro"] is False
    out = tmp_path / "out" / "span.mov"
    tool.submit(Request("stabilise", inputs={"path": str(src)}, params={"out": str(out), "t_in": 1.0, "seconds": 1.0, "smoothness": 0.6}))
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=codec_name,nb_read_frames",
                                       "-of", "json", str(out)], capture_output=True, text=True).stdout)["streams"][0]
    assert probe["codec_name"] == "prores" and int(probe["nb_read_frames"]) == 25        # the span asked, to the frame


def test_a_step_across_frames_is_applied_shot_by_shot_so_it_never_blends_across_a_cut(tmp_path):
    system = vq_system(tmp_path)
    a, b = texture(tmp_path / "a.png", seed=1), texture(tmp_path / "b.png", seed=2)
    src = tmp_path / "in" / "cut.mp4"
    src.parent.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-framerate", "25", "-t", "2", "-i", str(a),
                    "-loop", "1", "-framerate", "25", "-t", "2", "-i", str(b), "-filter_complex",
                    "[0]crop=640:360:'40+n*2':60[x];[1]hflip,hue=h=180,eq=brightness=0.25,crop=640:360:'40+n*2':60[y];[x][y]concat=n=2:v=1",
                    "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(src)], check=True)
    subject = system.vq.subject_for_file(src)
    system.vq.analyse(subject, target_fps=50, denoise=False, sharpen=False, stabilise=False, exposure=False)
    drain(system)
    recipe = system.vq_reader.recipe(subject)
    assert len(recipe.shots) == 2 and all(any(s["op"] == "interpolate" for s in shot["steps"]) for shot in recipe.shots)
    system.vq.approve(recipe.recipe_id)
    out = tmp_path / "out" / "smooth.mp4"
    system.vq.apply(subject, out=str(out))
    drain(system)
    parts = sorted((system.data_dir / "vq" / subject / "apply" / recipe.recipe_id).glob("part_*"))
    assert len(parts) == 2                                                     # one render per shot, joined after
    frames = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames",
                             "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
    assert 196 <= int(frames) <= 204


DNG = Path("data/samples/raw/DJI_0254.DNG").resolve()                      # raw.pixls.us, CC0: a DJI Osmo Action RAW


@pytest.mark.skipif(not Path("/usr/bin/sips").is_file(), reason="HEIC is decoded by macOS")
def test_a_heic_is_decoded_keeping_its_camera_and_given_a_recipe(tmp_path):
    system = vq_system(tmp_path)
    jpg = tmp_path / "in" / "p.jpg"
    jpg.parent.mkdir(parents=True)
    Image.open(texture(tmp_path / "t.png", size=(800, 600))).save(jpg, exif=_exif("Apple", "iPhone 16 Pro"))
    heic = tmp_path / "in" / "p.heic"
    subprocess.run(["sips", "-s", "format", "heic", str(jpg), "--out", str(heic)], check=True, capture_output=True)
    subject = system.vq.subject_for_file(heic)
    system.vq.analyse(subject)
    drain(system)
    tech = system.vq_reader.profile(subject)["technical"]
    assert tech["kind"] == "still" and tech["container"] == "heic" and tech["decoded"] and tech["device"] == "Apple iPhone 16 Pro"
    out = tmp_path / "out" / "p.jpg"
    system.vq.approve(system.vq_reader.recipe(subject).recipe_id)
    system.vq.apply(subject, out=str(out))
    drain(system)
    with Image.open(out) as im:
        assert im.size == (800, 600)


@pytest.mark.skipif(not DNG.is_file(), reason="the RAW sample is not downloaded")
def test_a_raw_is_decoded_by_libraw_at_16_bits_and_named_by_its_camera(tmp_path):
    system = vq_system(tmp_path)
    subject = system.vq.subject_for_file(DNG)
    system.vq.analyse(subject)
    drain(system)
    tech = system.vq_reader.profile(subject)["technical"]
    assert tech["raw"] and tech["container"] == "dng" and tech["device"] == "DJI Osmo Action" and (tech["width"], tech["height"]) == (4000, 3000)
    bits = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=pix_fmt", "-of", "csv=p=0", str(system.vq.path_of(subject))], capture_output=True, text=True).stdout
    assert "48" in bits                                                        # the working copy keeps 16 bits a channel


def _exif(make: str, model: str):
    exif = Image.Exif()
    exif[271], exif[272] = make, model
    return exif


ESRGAN = Path("data/tools/realesrgan").resolve()


def test_ai_is_offered_for_a_small_still_only_beside_the_classic_step_it_must_beat():
    shot = {"t_start": 0.0, "t_end": 0.0, "scores": {"blockiness": 1.9, "noise": 1.0, "sharpness": 50, "flicker": 0, "shake": 0},
            "defects": [{"kind": "blocking", "severity": 0.9}], "display": {"flat_blocks": 0.0}}
    profile = {"content": "still", "technical": {"kind": "still", "width": 1200, "height": 675}}
    have = {"ffmpeg:deblock", "ffmpeg:lut3d", "realesrgan"}
    steps = P.plan_shot(shot, profile=profile, colour=[], have=have, options={"exposure": False, "target_height": 2700})
    by = {s["op"]: s for s in steps}
    assert by["restore"]["tier"] == "realesrgan" and by["restore"]["generative"] and by["restore"]["classic"]["op"] == "deblock"
    assert by["upscale"]["tier"] == "realesrgan" and by["upscale"]["classic"]["tier"] == "ffmpeg"
    without = P.plan_shot(shot, profile=profile, colour=[], have=have - {"realesrgan"}, options={"exposure": False})
    assert [s["op"] for s in without] == ["deblock"]
    big = P.plan_shot(shot, profile={**profile, "technical": {"kind": "still", "width": 4000, "height": 3000}}, colour=[], have=have, options={"exposure": False})
    assert [s["op"] for s in big] == ["deblock"]                              # too large for ×4: the classic step


@pytest.mark.skipif(not (ESRGAN / "realesrgan-ncnn-vulkan").is_file(), reason="Real-ESRGAN is not set up")
def test_a_crushed_jpeg_is_restored_by_ai_only_because_it_measures_more_natural_and_upscaled_to_the_height_asked(tmp_path):
    from nexora.adapters.restore_local import RestoreLocal
    system = vq_system(tmp_path)
    system.adapters.register(RestoreLocal(ESRGAN))
    bad = tmp_path / "in" / "bad.jpg"
    bad.parent.mkdir(parents=True)
    with Image.open(texture(tmp_path / "t.png", size=(640, 360), seed=5)) as im:
        im.save(bad, quality=8)
    subject = system.vq.subject_for_file(bad)
    system.vq.analyse(subject, exposure=False, target_height=1080)
    drain(system)
    shot = system.vq_reader.recipe(subject).shots[0]
    ops = {s["op"]: s for s in shot["steps"]}
    dropped = {d["op"] for d in shot["dropped"]}
    stands_for = {"restore": "deblock", "upscale": "upscale"}
    decided = 0
    for op, classic in stands_for.items():
        ai = ops.get(op) if ops.get(op, {}).get("tier") == "realesrgan" else None
        if ai:                                                                 # kept: with the measure that earned it
            assert ai["checked"]["niqe_ai"] < ai["checked"]["niqe_classic"] - 0.5 and "classic" not in ai
        else:                                                                  # refused: its classic step instead, and why
            assert op in dropped and ops[classic]["tier"] == "ffmpeg"
        decided += 1
    assert decided == 2
    if ops.get("restore"):
        assert not {"deblock", "deband", "denoise"} & set(ops)                 # the restore stands for them
    system.vq.approve(system.vq_reader.recipe(subject).recipe_id)
    out = tmp_path / "out" / "good.png"
    system.vq.apply(subject, out=str(out))
    drain(system)
    with Image.open(out) as im:
        assert im.size[1] == 1080 or im.size[1] == 360 * 4
