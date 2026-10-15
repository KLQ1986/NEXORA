"""Things, subjects and sounds followed across a recording and the library."""
import numpy as np

from nexora.modules.intelligence import entities as E


def test_a_thing_is_named_without_how_many_or_how_it_looks():
    assert E.thing_name("thuyền thúng màu xanh lá cây") == "thuyền thúng"
    assert E.thing_name("một vài chiếc thuyền nhỏ khác") == "thuyền"
    assert E.thing_name("Bồn cầu trắng") == "bồn cầu"
    assert E.thing_name("gương") == "gương"


def test_a_thing_named_in_beats_in_a_row_is_one_appearance_even_across_a_cut():
    beats = [{"asset_id": "a", "start": 0.0, "end": 3.0, "shot": 0, "things": ["gương", "bồn cầu"]},
             {"asset_id": "a", "start": 3.0, "end": 6.0, "shot": 1, "things": ["bồn cầu trắng", "cửa sổ"]},
             {"asset_id": "a", "start": 6.0, "end": 9.0, "shot": 1, "things": ["gương"]},
             {"asset_id": "b", "start": 0.0, "end": 4.0, "shot": 0, "things": ["bồn cầu", "không người", "không gian yên tĩnh"]}]
    made = {t["name"]: t for t in E.things_of(beats)}
    loo = made["bồn cầu"]
    assert loo["assets"] == ["a", "b"] and loo["said"] == ["bồn cầu", "bồn cầu trắng"] and loo["across_cut"]
    assert [(a["asset_id"], a["start"], a["end"], a["beats"]) for a in loo["appearances"]] == [("a", 0.0, 6.0, 2), ("b", 0.0, 4.0, 1)]
    assert [(a["start"], a["end"]) for a in made["gương"]["appearances"]] == [(0.0, 3.0), (6.0, 9.0)]     # gone, then back: two
    assert set(made) == {"gương", "bồn cầu", "cửa sổ"}                       # what is not there, and a feeling, are no things


def test_how_far_a_stretchs_pictures_answer_a_things_name():
    frames = np.array([[1, 0], [0.9, 0.1], [0, 1], [0.1, 0.9]], np.float32)
    assert E.seen_in_pictures(np.array([1.0, 0.0]), frames, 1.0, [(0.0, 2.0), (2.0, 4.0), (0.0, 4.0)]) == [1.0, 0.0, 0.5]


def test_a_sound_is_tied_to_what_in_the_picture_could_make_it_or_said_to_come_from_out_of_frame():
    beats = [{"start": 0.0, "end": 5.0, "things": ["bờ cát", "sóng biển"], "people": "không", "speaker": "ngoài khung"},
             {"start": 5.0, "end": 9.0, "things": ["bồn cầu"], "people": "không", "speaker": "ngoài khung"}]
    sounds = [{"kind": "sóng biển", "start": 0.0, "end": 4.0}, {"kind": "lời nói", "start": 6.0, "end": 7.0},
              {"kind": "chim hót", "start": 1.0, "end": 2.0}, {"kind": "tiếng bíp", "start": 7.0, "end": 8.0}]
    made = E.sound_sources(sounds, beats)
    assert [(m["kind"], m["source"], m["where"]) for m in made] == [
        ("sóng biển", "sóng biển", "trong khung"), ("lời nói", "người", "ngoài khung"), ("chim hót", "chim", "ngoài khung"), ("tiếng bíp", None, "chưa rõ")]


def test_people_tracked_in_two_shots_are_one_subject_when_they_look_alike_but_never_two_seen_at_once():
    t = lambda a, s, e, kind="humans": {"asset_id": a, "start": s, "end": e, "kind": kind}
    tracks = [t("a", 0, 3), t("a", 4, 7), t("a", 4, 7), t("b", 0, 2), t("a", 8, 9, "animals")]
    v = lambda *x: np.array(x, np.float32)
    vectors = [v(1, 0, 0), v(0.97, 0.05, 0), v(0.96, 0.08, 0), v(0.99, 0.02, 0), v(1, 0, 0)]
    made = E.subjects_of(tracks, vectors)
    assert made[0] == made[3] and len({made[0], made[1], made[2]}) == 3 - 1     # 1 and 2 are seen together: one of them is someone else
    assert made[4] != made[0]                                                    # an animal is not a person
    assert E.subjects_of([t("a", 0, 1)], [None]) == [None]
