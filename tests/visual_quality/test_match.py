"""Matching a subject's colour to a reference's."""
import subprocess
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from nexora.api.app import create_app
from nexora.core.adapter import Request
from nexora.core.visual_quality import filters_of, step_filters
from nexora.modules.visual_quality import match as CM
from nexora.modules.visual_quality import plan as P

from tests.visual_quality.test_vq import drain, fake_dlogm, texture, vq_system


def _pixels(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), np.float64).reshape(-1, 3) / 255.0


def _street(seed: int = 0) -> np.ndarray:
    """A scene with grey in it (road, wall, cloud) beside coloured things, as display RGB."""
    rng = np.random.default_rng(seed)
    grey = rng.uniform(0.3, 0.8, (6000, 1)) * np.ones((1, 3)) + rng.normal(0, 0.01, (6000, 3))
    things = rng.uniform(0.05, 0.95, (14000, 3))
    return np.clip(np.vstack([grey, things]), 0, 1)


def test_a_known_grade_is_found_again_and_a_picture_matched_to_itself_is_left_alone(tmp_path):
    src = _pixels(texture(tmp_path / "t.png", size=(320, 180)))
    truth = {"exposure": 0.35, "temperature": 0.1, "saturation": -0.2}
    made = CM.fit(src, CM.grade(src, truth), mode="scene")
    assert made["after"] < made["before"] * 0.1 and not made["doubtful"]
    assert abs(made["controls"]["temperature"] - 0.1) < 0.03 and abs(made["controls"]["saturation"] + 0.2) < 0.05
    assert made["controls"]["exposure"] > 0.2
    same = CM.fit(src, src)
    assert same["before"] == 0 and all(abs(v) < 1e-3 for v in same["controls"].values())


def test_the_look_of_a_camera_is_matched_on_the_grey_in_the_picture_whatever_else_it_shows():
    src = _street(1)
    made = CM.fit(src, CM.grade(src, {"exposure": -0.3, "temperature": 0.12}))
    assert made["balanced"] and not made["doubtful"] and made["after"] < 0.2 * made["before"]
    assert 0.07 < made["controls"]["temperature"] < 0.16 and made["controls"]["exposure"] < -0.15
    # Without anything grey (a frame of saturated colour) the white balance is not guessed at.
    colourful = np.random.default_rng(2).uniform(0, 1, (20000, 3)) * np.array([0.2, 1.0, 0.3])
    assert CM.fit(colourful, _street(3))["balanced"] is False


def test_a_reference_of_other_content_matched_as_a_scene_is_called_doubtful():
    blue = np.clip(np.random.default_rng(4).normal([0.45, 0.6, 0.9], 0.08, (20000, 3)), 0, 1)       # mostly sky
    green = np.clip(np.random.default_rng(5).normal([0.5, 0.75, 0.2], 0.08, (20000, 3)), 0, 1)      # mostly leaves
    made = CM.fit(blue, green, mode="scene")
    assert made["doubtful"] and made["pinned"]


def test_the_grade_is_baked_into_the_same_lut_for_the_same_numbers_and_zero_is_the_identity(tmp_path):
    a = CM.bake({"exposure": 0.2, "tint": 0.05}, tmp_path, amount=0.5)
    assert a == CM.bake({"exposure": 0.2, "tint": 0.05}, tmp_path, amount=0.5) and a != CM.bake({"exposure": 0.2, "tint": 0.05}, tmp_path)
    rows = np.loadtxt(CM.bake({}, tmp_path, size=5), skiprows=4)
    g = np.linspace(0, 1, 5)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")
    assert np.allclose(rows, np.stack([r, gg, b], -1).reshape(-1, 3), atol=1e-5)
    assert step_filters({"op": "match", "params": {"lut": a}})[0].startswith("lut3d=")


def test_a_still_matched_to_a_warmer_brighter_one_comes_out_closer_to_it(tmp_path):
    system = vq_system(tmp_path)
    client = TestClient(create_app(system))
    (tmp_path / "in").mkdir()
    plain = texture(tmp_path / "in" / "plain.png", size=(480, 270), seed=3)
    warm = tmp_path / "in" / "warm.png"
    px = _pixels(plain)
    Image.fromarray((CM.grade(px, {"exposure": 0.4, "temperature": 0.15, "saturation": 0.2}).reshape(270, 480, 3) * 255).round().astype(np.uint8)).save(warm)
    subject, reference = system.vq.subject_for_file(plain), system.vq.subject_for_file(warm)
    for s in (subject, reference):
        system.vq.analyse(s, denoise=False, sharpen=False)
    drain(system)
    recipe = system.vq_reader.recipe(subject)
    asked = client.post(f"/api/v1/vq/recipes/{recipe.recipe_id}/match", json={"reference": reference, "t": 0, "mode": "scene"})
    assert asked.status_code == 200, asked.text
    matched = system.vq_reader.by_id(asked.json()["recipe_id"])
    assert matched.status == "proposed" and matched.version == recipe.version + 1
    steps = matched.shots[0]["steps"]
    step = next(s for s in steps if s["op"] == "match")
    ops = [s["op"] for s in steps]
    assert ops == sorted(ops, key=P.ORDER.index)                              # after the shot's own colour
    assert step["params"]["after"] < step["params"]["before"] and step["params"]["reference"]["subject"] == reference
    # The picture as its recipe makes it is nearer the reference as the reference's own recipe makes it (its white balance
    # and levels too: in a cut the two are seen that way) than without the match.
    def look(path, steps, name):
        out = tmp_path / name
        system.adapters.submit("ffmpeg", Request("vq_render", inputs={"path": str(path)}, params={
            "kind": "still", "out": str(out), "t_in": 0.0, "filters": filters_of([s for s in steps if s["op"] in ("levels", "match")]), "width": 480}))
        return _pixels(out)
    wanted = look(warm, system.vq_reader.recipe(reference).shots[0]["steps"], "ref.png")
    without = look(plain, [s for s in steps if s["op"] != "match"], "without.png")
    assert CM.distance(look(plain, steps, "with.png"), wanted) < 0.3 * CM.distance(without, wanted)
    # The amount is a knob: half of it is a new version with its own LUT.
    halved = system.vq.edit_step(matched.recipe_id, 0, ops.index("match"), params={"amount": 0.5})
    lut = next(s for s in system.vq_reader.by_id(halved).shots[0]["steps"] if s["op"] == "match")["params"]["lut"]
    assert lut != step["params"]["lut"] and Path(lut).is_file()
    assert client.post(f"/api/v1/vq/recipes/{recipe.recipe_id}/match", json={"reference": subject}).status_code == 422
    assert client.post(f"/api/v1/vq/recipes/{recipe.recipe_id}/match", json={}).status_code == 422
    assert client.post(f"/api/v1/vq/recipes/{recipe.recipe_id}/match", json={"reference": reference, "mode": "hue"}).status_code == 422


def _phone(path: Path, seconds: int = 2) -> Path:
    """A plain Rec.709 clip of the textured scene, warmer and brighter, tagged as a phone's."""
    tex = texture(path.with_suffix(".png"), seed=9)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-framerate", "25", "-t", str(seconds), "-i", str(tex),
                    "-vf", "crop=640:360:40:60,colorbalance=rs=0.15:bs=-0.15:rm=0.1:bm=-0.1,eq=brightness=0.06", "-pix_fmt", "yuv420p",
                    "-movflags", "use_metadata_tags", "-metadata", "make=Apple", "-metadata", "model=iPhone 15", str(path)], check=True)
    return path


def test_a_cut_proposes_matching_only_where_neighbouring_shots_come_from_different_sources(tmp_path):
    system = vq_system(tmp_path)
    client = TestClient(create_app(system))
    dji_a, _ = system.library.ingest(fake_dlogm(tmp_path / "in" / "a.mov", 2))
    dji_b, _ = system.library.ingest(fake_dlogm(tmp_path / "in" / "b.mov", 2))
    phone, _ = system.library.ingest(_phone(tmp_path / "in" / "p.mov"))
    drain(system)
    for asset in (dji_a, dji_b, phone):
        client.post(f"/api/v1/assets/{asset}/vq/plan", json={"denoise": False, "sharpen": False})
    drain(system)
    project = system.projects.create_project("Hai máy")
    script = system.projects.save_script(project, ["Câu một.", "Câu hai.", "Câu ba."])
    for shot, asset in zip(system.projects.script(script)["shots"], (dji_a, dji_b, phone)):
        system.projects.set_selection(shot.shot_id, status="accepted", asset_id=asset, t_in=0.2, t_out=1.6, decided_by="operator")
    pairs = client.get(f"/api/v1/projects/{project}/colour").json()["pairs"]
    assert len(pairs) == 1                                           # two DJI shots side by side are one camera: nothing to match
    pair = pairs[0]
    assert pair["change"]["asset_id"] == phone and pair["reference"]["asset_id"] == dji_b       # the cut leans on the DJI
    assert pair["mode"] == "look" and pair["state"] == "none" and pair["ready"] and pair["gap"] > 0
    made = client.post(f"/api/v1/projects/{project}/colour/match", json={"after": pair["after"]})
    assert made.status_code == 200, made.text
    step = next(s for shot in system.vq_reader.by_id(made.json()["recipe_id"]).shots for s in shot["steps"] if s["op"] == "match")
    assert step["params"]["reference"]["subject"] == dji_b and step["params"]["mode"] == "look"
    assert client.get(f"/api/v1/projects/{project}/colour").json()["pairs"][0]["state"] == "proposed"
    assert client.post(f"/api/v1/projects/{project}/colour/match", json={"after": 99}).status_code == 404


def test_two_sources_seen_in_one_place_match_their_whole_colour_and_screens_are_left_out():
    from types import SimpleNamespace as NS
    from nexora.modules.edit.colour import colour_pairs
    shots = [NS(shot_id=f"s{k}", position=k) for k in range(4)]
    picks = {"s0": "dji", "s1": "phone", "s2": "screen", "s3": "phone"}
    projects = NS(current_script=lambda _p: {"shots": shots},
                  selection=lambda sid: NS(status="accepted", asset_id=picks[sid], t_in=1.0, t_out=3.0))
    devices = {"dji": ("DJI OsmoAction6", "camera"), "phone": ("Apple iPhone 15", "camera"), "screen": (None, "screen")}
    vq = NS(profile=lambda a: {"technical": {"device": devices[a][0]}, "encoding": "rec709", "content": devices[a][1]},
            recipe=lambda a, status=None: None)
    vi = NS(entities=lambda kind: [{"key": "vườn", "name": "vườn dừa", "data": {}, "appearances": [
        {"asset_id": "dji", "t_start": 0.0, "t_end": 5.0}, {"asset_id": "phone", "t_start": 1.5, "t_end": 2.5}]}])
    pairs = colour_pairs(projects, vq, vi, "p")
    assert [p["after"] for p in pairs] == [0]                       # beside the screen recording nothing is proposed
    assert pairs[0]["mode"] == "scene" and pairs[0]["place"] == "vườn dừa"
    assert pairs[0]["reference"]["asset_id"] == "phone"             # the phone is used twice: it is the cut's main source
