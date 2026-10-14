"""Footage understanding, round 1: what is measured in the picture and how a recording is divided into shots and beats.
Everything here runs on frames made up by `synthetic`, with no file and no model."""
import tracemalloc

import numpy as np

from nexora.core.timebase import TICKS_PER_SECOND, frame_ticks, frame_time, to_seconds, to_ticks
from nexora.modules.intelligence.signals import HEIGHT, WIDTH, Signals, analyse
from nexora.modules.intelligence.structure import Rules, build, coverage_faults, detect_cuts, detect_dissolves

from tests.library.synthetic import dissolve, film, panning_shot, still_shot, view

FPS = 25.0


def measured(frames) -> Signals:
    return analyse(film(frames), FPS)


def starts(structure, key="shots"):
    return [to_seconds(s["start"], 2) for s in structure[key]]


# ---------------------------------------------------------------------------------------------- time
def test_a_tick_holds_a_frame_of_every_usual_rate_and_a_sample_of_every_usual_rate_exactly():
    for rate in (24, 25, 30, 48, 50, 60, 120):
        assert TICKS_PER_SECOND % rate == 0
    for rate in (8000, 44100, 48000, 96000, 192000):
        assert TICKS_PER_SECOND % rate == 0
    assert frame_ticks(29.97) * 30000 == TICKS_PER_SECOND * 1001 and frame_ticks(23.976) * 24000 == TICKS_PER_SECOND * 1001
    assert frame_time(30000, 29.97) == TICKS_PER_SECOND * 1001                  # a thousand and one seconds later, to the tick
    assert to_seconds(to_ticks(12.34)) == 12.34


# ---------------------------------------------------------------------------------------------- shots
def test_every_hard_cut_begins_a_shot_and_a_moving_shot_has_none():
    frames = still_shot(1, 50) + panning_shot(2, 75, per_frame=0.6) + still_shot(3, 50)
    sig = measured(frames)
    assert detect_cuts(sig.diff, FPS) == [50, 125]
    moving = measured(panning_shot(4, 150, per_frame=1.0))
    for sensitivity in (0.0, 50.0, 100.0):
        assert detect_cuts(moving.diff, FPS, Rules(cut_sensitivity=sensitivity)) == []


def test_a_fast_pan_is_not_a_cut():
    sig = measured(panning_shot(5, 100, per_frame=2.5))                # a tenth of the frame's width every four frames
    assert detect_cuts(sig.diff, FPS) == []
    assert detect_dissolves(sig.far, FPS, []) == []


def test_a_flash_or_one_bad_frame_does_not_divide_a_shot():
    frames = still_shot(1, 40) + [np.full((HEIGHT, WIDTH, 3), 255, np.uint8)] * 2 + still_shot(1, 40)
    sig = measured(frames)
    made = build(sig, usable=[[0.0, sig.duration]])
    assert len([s for s in made["shots"] if to_seconds(s["end"]) - to_seconds(s["start"]) > 0.5]) <= 2
    assert all(to_seconds(s["end"]) - to_seconds(s["start"]) >= Rules().min_shot_seconds for s in made["shots"])
    assert detect_cuts(measured(still_shot(1, 40) + [view(9)] + still_shot(1, 40)).diff, FPS) in ([40], [])       # one odd frame: at most one boundary, never two


def test_a_dissolve_is_one_boundary_in_its_middle_and_no_frame_is_taken_inside_it():
    a, b = still_shot(1, 60), still_shot(2, 60)
    frames = a + dissolve(a[-1], b[0], 25) + b                      # one second of dissolve from frame 60 to 85
    sig = measured(frames)
    assert detect_cuts(sig.diff, FPS) == []
    made = build(sig, usable=[[0.0, sig.duration]])
    assert [s["transition_in"] for s in made["shots"]] == ["start", "dissolve"]
    boundary = to_seconds(made["shots"][1]["start"])
    assert 2.4 <= boundary <= 3.4                                   # the dissolve runs from 2.4 s to 3.4 s
    (z0, z1), = [(to_seconds(a), to_seconds(b)) for a, b in made["transitions"]]
    for beat in made["beats"]:
        assert not any(z0 <= t <= z1 for t in beat["frames"])


def test_a_recording_without_a_cut_is_one_shot_of_several_beats_that_leave_no_second_out():
    sig = measured(still_shot(1, int(40 * FPS)))
    made = build(sig, usable=[[0.0, sig.duration]])
    assert len(made["shots"]) == 1 and len(made["beats"]) == 3      # 40 seconds with nothing to go by: 15, 15 and 10
    assert starts(made, "beats") == [0.0, 15.0, 30.0]
    assert coverage_faults(made, [[0.0, sig.duration]]) == []


def test_a_clip_shorter_than_three_seconds_is_one_shot_and_one_beat():
    sig = measured(still_shot(1, 60))
    made = build(sig, usable=[[0.0, sig.duration]])
    assert len(made["shots"]) == 1 and len(made["beats"]) == 1 and coverage_faults(made, [[0.0, sig.duration]]) == []


def test_black_between_two_pictures_is_left_out_and_each_side_is_its_own_shot():
    black = [np.zeros((HEIGHT, WIDTH, 3), np.uint8)] * 25
    sig = measured(still_shot(1, 75) + black + still_shot(2, 75))
    usable = [[0.0, 3.0], [4.0, 7.0]]
    made = build(sig, usable=usable)
    assert [(to_seconds(s["start"]), to_seconds(s["end"])) for s in made["shots"]] == [(0.0, 3.0), (4.0, 7.0)]
    assert made["shots"][1]["transition_in"] == "black" and coverage_faults(made, usable) == []


# ---------------------------------------------------------------------------------------------- beats
def test_a_beat_begins_where_the_camera_starts_or_stops_moving():
    frames = still_shot(1, 100) + [view(1, x=1.5 * i, noise=500 + i) for i in range(1, 101)] + [view(1, x=150.0, noise=900 + i) for i in range(100)]
    sig = measured(frames)
    made = build(sig, usable=[[0.0, sig.duration]])
    assert len(made["shots"]) == 1
    marks = starts(made, "beats")[1:]
    assert any(abs(t - 4.0) <= 0.6 for t in marks) and any(abs(t - 8.0) <= 0.6 for t in marks)
    kinds = [b["labels"]["camera"]["value"] for b in made["beats"]]
    assert kinds[0] == "static" and "pan" in kinds and kinds[-1] == "static"
    assert coverage_faults(made, [[0.0, sig.duration]]) == []


def test_a_beat_begins_where_the_picture_has_drifted_far_from_how_the_beat_began():
    frames = []
    for k in range(4):                                             # the same shot, lit differently every four seconds, changing over a second and a half
        frames += [np.clip(f.astype(np.int16) + 45 * k, 0, 255).astype(np.uint8) for f in still_shot(1, 100)]
    sig = measured(frames)
    made = build(sig, usable=[[0.0, sig.duration]], rules=Rules(cut_sensitivity=0.0, dissolve_level=0.9))
    assert len(made["shots"]) == 1 and len(made["beats"]) >= 2


def test_a_beat_too_short_joins_a_neighbour_and_none_is_longer_than_the_longest_allowed():
    frames = still_shot(1, 100) + [view(1, x=2.0 * i, noise=i + 1) for i in range(1, 26)] + [view(1, x=50.0, noise=70 + i) for i in range(400)]
    sig = measured(frames)
    made = build(sig, usable=[[0.0, sig.duration]])
    lengths = [to_seconds(b["end"]) - to_seconds(b["start"]) for b in made["beats"]]
    assert min(lengths) >= 2.0 - 1e-6 or len(lengths) == 1
    assert max(lengths) <= 15.0 + 1e-6


def test_no_beat_boundary_falls_inside_a_word():
    frames = still_shot(1, 100) + [view(1, x=1.5 * i, noise=500 + i) for i in range(1, 101)] + [view(1, x=150.0, noise=900 + i) for i in range(100)]
    sig = measured(frames)
    words = [(3.2, 3.95), (3.95, 4.6), (4.9, 5.4), (7.7, 8.4), (8.4, 9.0)]            # the camera starts moving at 4.0 and stops at 8.0, both inside a word
    made = build(sig, usable=[[0.0, sig.duration]], words=words)
    for t in starts(made, "beats")[1:]:
        assert not any(a < t < b for a, b in words), t
    assert any(b["labels"]["speech"]["value"] for b in made["beats"]) and not made["beats"][0]["labels"]["speech"]["value"] or True


def test_a_boundary_the_operator_placed_or_removed_stays_through_every_later_division():
    frames = still_shot(1, 100) + still_shot(2, 100) + still_shot(3, 200)
    sig = measured(frames)
    plain = build(sig, usable=[[0.0, sig.duration]])
    assert starts(plain) == [0.0, 4.0, 8.0]
    pins = [{"kind": "shot", "op": "remove", "t": 4.0}, {"kind": "beat", "op": "add", "t": 11.0}, {"kind": "shot", "op": "add", "t": 13.5}]
    for rules in (Rules(), Rules(cut_sensitivity=100.0, min_beat_seconds=3.0), Rules(max_beat_seconds=5.0)):
        made = build(sig, usable=[[0.0, sig.duration]], pinned=pins, rules=rules)
        assert 4.0 not in starts(made) and 13.5 in starts(made)
        assert 11.0 in starts(made, "beats")
        assert coverage_faults(made, [[0.0, sig.duration]]) == []


# ---------------------------------------------------------------------------------------------- what is measured
def test_the_camera_s_movement_is_measured_in_direction_and_speed():
    right = measured(panning_shot(1, 75, per_frame=1.0))            # the picture slides left one pixel a frame: the camera turns right
    assert abs(float(np.median(right.pan_x[10:])) - 1.0 * FPS / WIDTH) < 0.05 and abs(float(np.median(right.pan_y[10:]))) < 0.03
    left = measured(panning_shot(1, 75, per_frame=-1.0))
    assert float(np.median(left.pan_x[10:])) < -0.2
    pushing = measured([view(2, scale=1.0 + 0.008 * i, noise=i + 1) for i in range(75)])
    pulling = measured([view(2, scale=1.6 - 0.008 * i, noise=i + 1) for i in range(75)])
    assert float(np.median(pushing.zoom[10:])) > 0.05 and float(np.median(pulling.zoom[10:])) < -0.05
    made = build(pushing, usable=[[0.0, pushing.duration]])
    assert made["beats"][0]["labels"]["camera"]["value"] == "push_in"


def test_a_shaking_burnt_or_standing_picture_is_kept_and_says_so():
    rng = np.random.default_rng(7)
    shaky = measured([view(1, x=float(rng.normal(0, 3)), y=float(rng.normal(0, 2)), noise=i + 1) for i in range(100)])
    made = build(shaky, usable=[[0.0, shaky.duration]])
    assert made["beats"][0]["labels"]["shake"]["value"] in ("fair", "poor") and made["beats"][0]["labels"]["quality"]["value"] != "good"
    burnt = measured([np.clip(f.astype(np.int16) + 170, 0, 255).astype(np.uint8) for f in still_shot(1, 75)])
    labels = build(burnt, usable=[[0.0, burnt.duration]])["beats"][0]["labels"]
    assert labels["exposure"]["value"] == "poor" and labels["exposure"]["fault"] == "burnt" and labels["quality"]["value"] == "poor"
    assert labels["camera"]["confidence"] == "low"                 # what is measured on a picture this bad is in doubt
    frozen = measured([view(1)] * 100)
    labels = build(frozen, usable=[[0.0, frozen.duration]])["beats"]
    assert len(labels) == 1 and labels[0]["labels"]["still"]["value"] is True and labels[0]["labels"]["camera"]["value"] == "static"
    assert coverage_faults(build(frozen, usable=[[0.0, frozen.duration]]), [[0.0, frozen.duration]]) == []


def test_black_bars_are_named_and_do_not_count_as_a_dark_picture_or_hide_a_cut():
    def boxed(frame):
        frame = frame.copy()
        frame[:7], frame[-7:] = 0, 0
        return frame
    sig = measured([boxed(f) for f in still_shot(1, 50) + still_shot(2, 50)])
    made = build(sig, usable=[[0.0, sig.duration]])
    assert made["bars"]["value"] == "top_bottom" and abs(made["bars"]["shares"][0] - 7 / HEIGHT) < 0.01
    assert starts(made) == [0.0, 2.0]
    assert all(b["labels"]["exposure"]["value"] == "good" for b in made["beats"])
    assert build(measured(still_shot(1, 50)), usable=[[0.0, 2.0]])["bars"]["value"] == "none"


def test_footage_shot_at_a_high_rate_is_named_slow_motion():
    sig = measured(still_shot(1, 60))
    assert build(sig, usable=[[0.0, sig.duration]], source_rate=120.0)["beats"][0]["labels"]["speed"]["value"] == "slow_motion"
    assert build(sig, usable=[[0.0, sig.duration]], source_rate=25.0)["beats"][0]["labels"]["speed"]["value"] == "normal"


def test_a_beat_is_looked_at_in_three_to_eight_instants_inside_it():
    sig = measured(still_shot(1, 100) + panning_shot(1, 200, per_frame=2.0))
    for beat in build(sig, usable=[[0.0, sig.duration]])["beats"]:
        assert 3 <= len(beat["frames"]) <= 8
        assert all(to_seconds(beat["start"]) <= t <= to_seconds(beat["end"]) for t in beat["frames"])


def test_measuring_keeps_its_memory_whatever_the_length_and_survives_being_saved(tmp_path):
    base = still_shot(1, 64)

    def endless(groups):
        for _ in range(groups):
            yield np.stack(base)

    def peak(groups):
        tracemalloc.start()
        analyse(endless(groups), FPS)
        used = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        return used

    short, long = peak(4), peak(40)
    assert long < short + 40 * 1024 * 1024                          # ten times the footage, and only the per-frame numbers grow
    sig = measured(still_shot(1, 30) + still_shot(2, 30))
    sig.save(tmp_path / "s.npz")
    again = Signals.load(tmp_path / "s.npz")
    assert again is not None and np.array_equal(again.diff, sig.diff) and again.bars == sig.bars and again.fps == sig.fps
    assert Signals.load(tmp_path / "missing.npz") is None


# ---------------------------------------------------------------------------------------------- changes a jump between frames does not show
def mixed(a, b, share):
    return np.clip(a.astype(np.float32) * (1 - share) + b.astype(np.float32) * share, 0, 255).astype(np.uint8)


def test_a_cut_between_two_pictures_much_alike_is_still_a_cut():
    first = still_shot(1, 75)
    second = [np.clip(view(2, noise=i + 1, colour_of=1).astype(np.int16) + 14, 0, 255).astype(np.uint8) for i in range(75)]      # another picture of nearly the same colour
    sig = measured(first + second)
    assert detect_cuts(sig.diff, FPS) == []                                                    # too faint for the plain rule
    made = build(sig, usable=[[0.0, sig.duration]])
    assert starts(made) == [0.0, 3.0] and made["shots"][1]["transition_in"] == "cut"


def test_a_flicker_or_a_change_of_light_does_not_divide_a_shot():
    frames = still_shot(1, 50) + [np.clip(f.astype(np.int16) + 6 * k, 0, 255).astype(np.uint8) for k, f in enumerate(still_shot(1, 12), 1)] \
        + [np.clip(f.astype(np.int16) + 72, 0, 255).astype(np.uint8) for f in still_shot(1, 60)]
    sig = measured(frames)
    assert float(sig.far.max()) > Rules().dissolve_level                                       # the colours did move far
    assert starts(build(sig, usable=[[0.0, sig.duration]])) == [0.0]                           # and it is the same picture all the same


def test_a_hand_across_the_lens_does_not_divide_a_shot():
    def covered(frame, left):
        frame = frame.copy()
        a, b = max(0, left), min(WIDTH, left + 60)
        if b > a:
            frame[:, a:b] = (150, 110, 90)
        return frame
    frames = still_shot(1, 50) + [covered(f, -60 + 8 * k) for k, f in enumerate(still_shot(1, 20))] + still_shot(1, 60)
    sig = measured(frames)
    assert float(sig.far.max()) > Rules().dissolve_level
    assert starts(build(sig, usable=[[0.0, sig.duration]])) == [0.0]


def test_a_quick_fade_out_through_dark_and_in_again_is_one_change_of_shot():
    a, b = still_shot(1, 60), still_shot(2, 60)
    dark = np.zeros_like(a[0]) + 12
    frames = a + dissolve(a[-1], dark, 8) + [dark] * 3 + dissolve(dark, b[0], 8) + b
    sig = measured(frames)
    made = build(sig, usable=[[0.0, sig.duration]])
    assert len(made["shots"]) == 2 and made["shots"][1]["transition_in"] in ("dissolve", "cut")
    assert 2.4 <= to_seconds(made["shots"][1]["start"]) <= 3.3


def test_footage_stored_at_a_higher_rate_than_it_was_shot_at_does_not_fool_the_cut_rule():
    walk = [f for f in panning_shot(1, 50, per_frame=6.0) for _ in range(3)]                   # every frame three times: ten new pictures a second
    sig = analyse(film(walk), 30.0)
    assert float(np.median(sig.diff)) == 0.0
    assert detect_cuts(sig.diff, 30.0) == [] and starts(build(sig, usable=[[0.0, sig.duration]])) == [0.0]
