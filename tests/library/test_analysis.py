"""Footage understanding, round 1, through the real pipeline: footage is measured and divided as it is taken in, with or
without a model, and what the operator has said or marked outlives every later division."""
import subprocess
from pathlib import Path

import pytest

from nexora.app import build
from nexora.core.states import RunStatus
from nexora.core.timebase import to_seconds
from nexora.modules.library.structure import Rules, beat_seconds

from tests.conftest import make_video
from tests.fakes import FakeModel, FakeSpeech


def drain(system):
    while system.worker.run_once():
        pass


def film(path, parts, *, size="320x180", rate=25, extra=(), filters="null"):
    """A test recording joined from `parts`: (lavfi source, seconds) one after another, cut hard between them."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    inputs = []
    for source, seconds in parts:
        inputs += ["-f", "lavfi", "-i", f"{source}=size={size}:rate={rate}:duration={seconds}"]
    graph = "".join(f"[{i}:v]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=1,{filters}[v]"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", graph, "-map", "[v]", "-pix_fmt", "yuv420p", *extra, str(path)], check=True)
    return path


TWO_SHOTS = [("testsrc2", 4), ("smptebars", 4)]


def taken_in(system, path):
    asset_id, _ = system.library.ingest(path)
    drain(system)
    return asset_id


def shot_starts(structure):
    return [to_seconds(s["start"], 2) for s in structure["shots"]]


def test_footage_is_divided_at_its_cut_as_it_is_taken_in_and_no_moment_runs_across_the_cut(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=15.0)
    asset = taken_in(system, film(tmp_path / "two.mp4", TWO_SHOTS))
    runs = [system.orch.run_info(r) for r in system.orch.runs_for_subject(asset)]
    assert all(system.orch.run_status(r["run_id"]) is RunStatus.SUCCEEDED for r in runs)
    made = system.library.analysis.structure(asset)
    assert shot_starts(made) == [0.0, 4.0] and [s["transition_in"] for s in made["shots"]] == ["start", "cut"]
    assert system.library.analysis.faults(asset) == []
    meta = system.assets.original(asset).metadata
    assert meta["scene_cuts"] == [4.0] and meta["structure"]["shots"] == 2
    segments = system.index.moments(asset, level="segment")
    assert [(m.t_start, m.t_end) for m in segments] == beat_seconds(made)
    assert all(m.t_end <= 4.0 or m.t_start >= 4.0 for m in segments)
    assert all(m.text and 3 <= len(m.data["frames"]) <= 8 and all(Path(f).is_file() for f in m.data["frames"]) for m in segments)
    assert all(m.data["labels"]["camera"]["source"] == "measured" and m.data["shot"] in (0, 1) for m in segments)
    assert segments[0].data["labels"]["speech"]["value"] is False          # nobody speaks in it, and it says so


def test_without_any_model_footage_still_has_its_shots_beats_and_measured_labels(tmp_path):
    system = build(tmp_path / "data")
    asset = taken_in(system, film(tmp_path / "two.mp4", TWO_SHOTS))
    made = system.library.analysis.structure(asset)
    assert shot_starts(made) == [0.0, 4.0] and len(made["beats"]) >= 2
    assert all({"camera", "shake", "exposure", "quality", "speech", "speed", "still", "direction", "position"} <= set(b["labels"]) for b in made["beats"])
    assert system.index.moments(asset, level="segment") == []              # nothing has been said about it; its structure is known all the same


def test_a_photograph_and_a_second_copy_of_a_file_are_not_measured(tmp_path):
    from PIL import Image
    system = build(tmp_path / "data", model=FakeModel())
    Image.new("RGB", (640, 360), (90, 140, 200)).save(tmp_path / "p.jpg")
    photo = taken_in(system, tmp_path / "p.jpg")
    assert system.library.analysis.structure(photo) is None
    assert len(system.index.moments(photo, level="segment")) == 1         # one moment, itself its only frame
    first = taken_in(system, film(tmp_path / "a.mp4", TWO_SHOTS))
    (tmp_path / "copy").mkdir()
    (tmp_path / "copy" / "b.mp4").write_bytes((tmp_path / "a.mp4").read_bytes())
    second = taken_in(system, tmp_path / "copy" / "b.mp4")
    assert system.library.analysis.structure(first) is not None
    assert "duplicate_of" in system.assets.original(second).metadata and "structure" not in system.assets.original(second).metadata


def test_footage_shot_at_a_high_rate_is_thinned_for_measuring_and_named_slow_motion(tmp_path):
    system = build(tmp_path / "data")
    asset = taken_in(system, film(tmp_path / "fast.mp4", [("testsrc2", 2)], rate=120))
    assert system.library.analysis.signals(asset).fps == 30.0
    assert system.library.analysis.structure(asset)["beats"][0]["labels"]["speed"]["value"] == "slow_motion"


def test_a_cut_in_footage_of_uneven_frame_timing_is_placed_at_its_real_time(tmp_path):
    system = build(tmp_path / "data")
    uneven = film(tmp_path / "vfr.mp4", TWO_SHOTS, filters="select='not(eq(mod(n\\,7)\\,3)+eq(mod(n\\,11)\\,5))'", extra=["-fps_mode", "vfr"])
    made = system.library.analysis.structure(taken_in(system, uneven))
    assert len(made["shots"]) == 2 and abs(shot_starts(made)[1] - 4.0) <= 0.1


def test_black_bars_in_real_footage_are_named_and_the_cut_is_still_found(tmp_path):
    system = build(tmp_path / "data")
    made = system.library.analysis.structure(taken_in(system, film(tmp_path / "wide.mp4", TWO_SHOTS, filters="pad=320:240:0:30:black", size="320x180")))
    assert made["bars"]["value"] == "top_bottom" and shot_starts(made) == [0.0, 4.0]
    assert system.assets.original(system.assets.assets()[0]["asset_id"]).metadata["structure"]["bars"] == "top_bottom"


def test_with_the_footage_away_the_proxy_is_measured_and_measuring_twice_reads_what_was_kept(tmp_path):
    system = build(tmp_path / "data")
    source = film(tmp_path / "gone.mp4", TWO_SHOTS)
    asset = taken_in(system, source)
    original = system.assets.original(asset)
    kept = tmp_path / "data" / "media" / original.checksum[:2] / f"{original.checksum}_signals.npz"
    assert kept.is_file()
    run = system.library.analyse(asset)
    drain(system)
    assert system.orch.stages(run)[0].outputs == {"cached": True}
    kept.unlink()
    source.unlink()                                                        # the drive that holds it has been taken away
    run = system.library.analyse(asset)
    drain(system)
    assert system.orch.run_status(run) is RunStatus.SUCCEEDED and kept.is_file()
    assert shot_starts(system.library.analysis.structure(asset)) == [0.0, 4.0]


def test_a_mark_of_the_operator_is_kept_through_later_divisions_and_only_changed_beats_are_described_again(tmp_path):
    model = FakeModel()
    system = build(tmp_path / "data", model=model, segment_seconds=15.0)
    asset = taken_in(system, film(tmp_path / "two.mp4", TWO_SHOTS))
    before = beat_seconds(system.library.analysis.structure(asset))
    assert before == [(0.0, 4.0), (4.0, 8.0)]
    calls = model.calls["describe"]
    first_frames = [f for m in system.index.moments(asset, level="segment") for f in m.data["frames"]]
    made = system.library.mark_boundary(asset, kind="beat", op="add", t=6.0)
    drain(system)
    assert beat_seconds(made) == [(0.0, 4.0), (4.0, 6.0), (6.0, 8.0)]
    assert model.calls["describe"] == calls + 2                            # the first shot was left alone and nobody looked at it again
    assert all(Path(f).is_file() for f in first_frames)                    # frames an earlier run chose are never taken away by a later one
    folder = Path(first_frames[0]).parent
    assert [p.name for p in folder.parent.iterdir() if p.name.startswith(folder.name + ".")] == []     # and no run leaves its own folder behind
    assert [(m.t_start, m.t_end) for m in system.index.moments(asset, level="segment")] == beat_seconds(made)

    system.library.analysis.rules = Rules(max_beat_seconds=15.0, cut_sensitivity=100.0, min_beat_seconds=1.0)      # a rule is changed
    calls = model.calls["describe"]
    again = system.library.redivide(asset)
    drain(system)
    assert 6.0 in [a for a, _ in beat_seconds(again)]                       # the mark is still there
    assert beat_seconds(again) == beat_seconds(made) and model.calls["describe"] == calls      # nothing moved, so nothing was asked

    system.library.mark_boundary(asset, kind="shot", op="remove", t=4.0)
    drain(system)
    made = system.library.analysis.structure(asset)
    assert shot_starts(made) == [0.0] and system.assets.original(asset).metadata["scene_cuts"] == []
    system.library.mark_boundary(asset, kind="shot", op="clear", t=4.0)    # the mark is let go: the rules decide again
    assert shot_starts(system.library.analysis.structure(asset)) == [0.0, 4.0]


def test_what_the_operator_wrote_about_a_stretch_outlives_the_division_it_was_written_on(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=15.0)
    asset = taken_in(system, film(tmp_path / "two.mp4", TWO_SHOTS))
    second = system.index.moments(asset, level="segment")[1]
    system.index.correct(second.moment_id, "Người đàn ông quăng lưới xuống sông.")
    system.library.mark_boundary(asset, kind="beat", op="add", t=6.0)       # the stretch it was written on is divided in two
    drain(system)
    assert [(m.t_start, m.t_end) for m in system.index.moments(asset, level="segment")] == [(0.0, 4.0), (4.0, 6.0), (6.0, 8.0)]
    kept = system.index.moments(asset, level="note")
    assert len(kept) == 1 and kept[0].text == "Người đàn ông quăng lưới xuống sông." and kept[0].source == "human" and (kept[0].t_start, kept[0].t_end) == (4.0, 8.0)
    assert system.index.search("quăng lưới", level=("segment", "note"))[0].moment.moment_id == second.moment_id
    system.library.annotate(asset, note="Quay ở bến Ninh Kiều")              # the operator's note on the whole file is another thing
    assert {m.text for m in system.index.moments(asset, level="note")} == {"Người đàn ông quăng lưới xuống sông.", "Quay ở bến Ninh Kiều"}


def test_once_the_words_are_known_no_beat_begins_inside_one(tmp_path):
    speech = FakeSpeech("một hai ba bốn năm sáu bảy tám chín mười mười_một mười_hai mười_ba mười_bốn")       # words from 0.5 s to 7.4 s, back to back
    system = build(tmp_path / "data", model=FakeModel(), speech=speech, segment_seconds=15.0)
    silent = film(tmp_path / "silent.mp4", [("testsrc2", 8)])
    source = tmp_path / "talk.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(silent), "-f", "lavfi", "-i", "sine=frequency=300:duration=8",
                    "-c:v", "copy", "-c:a", "aac", "-shortest", str(source)], check=True)
    asset = taken_in(system, source)
    words = [(w["start"], w["end"]) for m in system.index.moments(asset, level="speech") for w in m.data["words"]]
    assert len(words) == 14
    system.library.analysis.rules = Rules(max_beat_seconds=3.2, min_beat_seconds=3.2)      # even pieces of 3.2 s would begin inside the words at 3.0 and 6.0
    made = system.library.redivide(asset)
    drain(system)
    starts = [a for a, _ in beat_seconds(made)][1:]
    assert len(starts) == 2 and not any(a < t < b for t in starts for a, b in words), starts
    assert all(b["labels"]["speech"]["value"] for b in made["beats"])
    assert system.library.analysis.faults(asset) == []
    assert [(m.t_start, m.t_end) for m in system.index.moments(asset, level="segment")] == beat_seconds(made)


def test_a_clip_longer_than_its_moment_runs_on_inside_the_shot_and_never_past_the_footage_or_across_a_cut(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=15.0)
    asset = taken_in(system, film(tmp_path / "two.mp4", TWO_SHOTS))
    system.library.mark_boundary(asset, kind="beat", op="add", t=6.0)
    drain(system)
    assert system.sourcing._whole_shot(asset, 6.0, 9.5) == (4.5, 8.0)       # past the end: moved back, still inside the second shot
    assert system.sourcing._whole_shot(asset, 2.0, 5.0)[1] <= 4.0 - 0.1     # across the cut: moved to the side that has room
    assert system.sourcing._whole_shot(asset, 4.0, 7.0) == (4.0, 7.0)       # on into the next beat of the same shot: allowed


def test_a_verdict_on_a_clip_still_counts_after_the_footage_is_divided_anew(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=15.0)
    asset = taken_in(system, film(tmp_path / "two.mp4", TWO_SHOTS))
    old = system.index.moments(asset, level="segment")[1]
    system.projects.add_feedback("cá tươi trên sạp", old.moment_id, "rejected", asset_id=asset, span=(old.t_start, old.t_end))
    system.library.mark_boundary(asset, kind="beat", op="add", t=6.0)
    drain(system)
    new = system.index.moments(asset, level="segment")
    assert old.moment_id not in {m.moment_id for m in new}
    assert [system.sourcing._said("cá tươi trên sạp", m) for m in new] == [None, "rejected", "rejected"]


# ---------------------------------------------------------------------------------------------- over the API, and measured
def test_the_structure_of_an_asset_is_served_marked_and_measured_against_the_operators_own_marks(tmp_path):
    from fastapi.testclient import TestClient
    from nexora.api.app import create_app
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=15.0)
    client = TestClient(create_app(system))
    asset = taken_in(system, film(tmp_path / "three.mp4", [("testsrc2", 4), ("smptebars", 4), ("testsrc", 4)]))
    view = client.get(f"/api/v1/assets/{asset}/structure").json()
    assert view["measured"] and [s["t_start"] for s in view["shots"]] == [0.0, 4.0, 8.0] and view["faults"] == [] and view["reference"] is False
    assert view["boundaries"] == {"shot": [4.0, 8.0], "beat": [4.0, 8.0]}
    assert all(b["moment"]["text"] and b["labels"]["quality"]["value"] in ("good", "fair", "poor") for b in view["beats"])
    assert client.get("/api/v1/assets/nope/structure").status_code == 404
    assert client.post(f"/api/v1/assets/{asset}/structure/marks", json={"kind": "beat", "op": "add", "t": 99}).status_code == 422
    assert client.post(f"/api/v1/assets/{asset}/structure/marks", json={"kind": "frame", "op": "add", "t": 2}).status_code == 422

    # The operator says: the cut at 8 is not a cut, and there is a beat at 2 the rules did not see. Then keeps that as the answer.
    client.post(f"/api/v1/assets/{asset}/structure/marks", json={"kind": "shot", "op": "remove", "t": 8.0})
    view = client.post(f"/api/v1/assets/{asset}/structure/marks", json={"kind": "beat", "op": "add", "t": 2.0}).json()
    drain(system)
    assert view["boundaries"] == {"shot": [4.0], "beat": [2.0, 4.0]} and len(view["marks"]) == 2
    view = client.post(f"/api/v1/assets/{asset}/structure/marks", json={"kind": "beat", "op": "move", "t": 2.0, "to": 2.5}).json()
    drain(system)
    assert view["boundaries"]["beat"] == [2.5, 4.0]
    assert client.post(f"/api/v1/assets/{asset}/structure/reference", json={"on": True}).json()["reference"] is True

    run = client.post("/api/v1/evaluation/structure/run").json()["structure"]
    assert run["references"] == [{"asset_id": asset, "name": "three.mp4", "shots": 1, "beats": 2}]
    summary = run["runs"][0]["summary"]
    assert summary["assets"] == 1 and summary["faults"] == 0
    assert summary["shot"] == {"found": 2, "marked": 1, "matched": 1, "precision": 0.5, "recall": 1.0}        # the rules alone still see the cut at 8
    assert summary["beat"] == {"found": 2, "marked": 2, "matched": 1, "precision": 0.5, "recall": 0.5}
    detail = run["runs"][0]["details"][0]
    assert detail["shot"]["extra"] == [8.0] and detail["beat"]["missed"] == [2.5]

    system.library.analysis.rules = Rules(max_beat_seconds=15.0, cut_sensitivity=0.0)                          # a rule is changed, and measured again
    run = client.post("/api/v1/evaluation/structure/run").json()["structure"]["runs"]
    assert run[0]["change"]["config"]["cut_sensitivity"] == [50.0, 0.0] and "regression" in run[0]["change"]
    assert client.post(f"/api/v1/assets/{asset}/structure/reference", json={"on": False}).json()["reference"] is False
    assert client.get("/api/v1/evaluation").json()["structure"]["references"] == []


def test_boundaries_found_are_paired_with_boundaries_marked_one_to_one_and_nearest_first():
    from nexora.modules.quality.evaluation import score_boundaries
    scored = score_boundaries([1.0, 1.3, 5.0, 9.0], [1.2, 5.4, 12.0])
    assert scored["matched"] == 2 and scored["precision"] == 0.5 and scored["recall"] == round(2 / 3, 3)
    assert scored["missed"] == [12.0] and scored["extra"] == [1.0, 9.0]
    assert score_boundaries([], [])["precision"] is None and score_boundaries([], [3.0])["recall"] == 0.0


def test_a_beat_the_model_could_not_answer_for_is_shown_again_with_fewer_frames(tmp_path):
    from nexora.core.adapter import AdapterError, ErrorCode

    class Overwhelmed(FakeModel):
        """Answers only when shown few enough frames."""
        most = 3

        def __init__(self):
            super().__init__()
            self.shown = []

        def submit(self, request):
            if request.operation == "describe" and not request.params.get("task"):
                self.shown.append(len(request.inputs["images"]))
                if len(request.inputs["images"]) > self.most:
                    raise AdapterError(ErrorCode.OUTPUT_INVALID, "not JSON")
            return super().submit(request)

    model = Overwhelmed()
    system = build(tmp_path / "data", model=model, segment_seconds=15.0)
    asset = taken_in(system, film(tmp_path / "long.mp4", [("testsrc2", 10)]))
    segments = system.index.moments(asset, level="segment")
    assert segments and all(m.text for m in segments) and len(segments) == len(beat_seconds(system.library.analysis.structure(asset)))
    assert max(model.shown) > 3 and 3 in model.shown
    assert all(len(m.data["frames"]) > 3 for m in segments)                 # the beat keeps all its frames; only the question was made smaller

    class Hopeless(Overwhelmed):
        most = 1
    model = Hopeless()
    system = build(tmp_path / "data2", model=model, segment_seconds=15.0)
    asset = taken_in(system, film(tmp_path / "long2.mp4", [("smptebars", 10)]))
    assert all(m.text for m in system.index.moments(asset, level="segment")) and 1 in model.shown       # the middle frame alone, as the last resort

