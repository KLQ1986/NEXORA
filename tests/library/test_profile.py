"""The footage profile (design 2026-10-14): fields measured and recognised beat by beat, text on screen, kinds of sound and the
profile of a whole file, with what a model says checked against them."""
import numpy as np
import pytest

from nexora.app import build
from nexora.modules.library import profile as P
from nexora.modules.library import vocab
from nexora.modules.library.understand import facts_of, model_labels, tidy, text_of

from tests.conftest import make_video
from tests.fakes import FakeModel, FakeSound, FakeVision


def drain(system):
    while system.worker.run_once():
        pass


# ------------------------------------------------------------------------------------------------------------ vocabulary
def test_one_name_for_one_thing_and_english_is_turned_vietnamese():
    assert vocab.canonical("Cây cối") == vocab.canonical("cây xanh") == vocab.canonical("những cây cỏ") == "cây"
    assert vocab.canonical("countryside") == "nông thôn"
    assert vocab.mend("Một con đường ở countryside") == "Một con đường ở nông thôn"
    assert vocab.foreign_words("Con đường ở countryside, có pathway") == ["countryside", "pathway"]
    assert vocab.foreign_words("Một quán cà phê có wifi và sofa, quay bằng camera DJI") == []


def test_picture_labels_have_vietnamese_names_and_the_rest_stay_english():
    vi, en = vocab.vision_tags([["outdoor", 0.9], ["blue_sky", 0.8], ["gazebo", 0.5], ["zucchini", 0.4], ["plant", 0.1]])
    assert vi == ["ngoài trời", "trời xanh", "chòi nghỉ"] and en == ["zucchini"]


# ------------------------------------------------------------------------------------------------------- people and size
@pytest.mark.parametrize("face, body, size", [(0.6, 0.0, "đặc tả"), (0.3, 0.9, "cận"), (0.12, 0.9, "trung"), (0.0, 0.5, "toàn"), (0.0, 0.1, "cực toàn")])
def test_how_tight_the_frame_is_comes_from_how_much_of_it_a_person_fills(face, body, size):
    assert P.size_from_people(face, body)[0] == size


def test_without_people_open_sky_is_wide_and_never_better_than_medium():
    assert P.size_from_scene([["outdoor", 0.9], ["sky", 0.9]], [[0.0, 0.2, 0.9, 0.6]]) == ("toàn", "medium")
    assert P.size_from_scene([["cup", 0.8], ["coffee", 0.7]], [[0.3, 0.3, 0.4, 0.4]]) == ("cận", "low")
    assert P.size_from_scene([["structure", 0.3]], []) is None


def test_a_posture_is_read_from_the_joints():
    standing = {"neck": [0.5, 0.2, 1], "root": [0.5, 0.5, 1], "left_knee": [0.5, 0.7, 1], "left_ankle": [0.5, 0.9, 1]}
    sitting = {"neck": [0.5, 0.2, 1], "root": [0.5, 0.5, 1], "left_knee": [0.65, 0.52, 1]}
    lying = {"neck": [0.2, 0.6, 1], "root": [0.6, 0.62, 1]}
    assert (P.posture(standing), P.posture(sitting), P.posture(lying)) == ("đứng", "ngồi", "nằm")


# ---------------------------------------------------------------------------------------------------------------- sound
def test_a_kind_of_sound_heard_in_one_window_alone_makes_no_event():
    windows = [{"t": 0.0, "d": 1.0, "top": [["smoke_detector", 0.9], ["beep", 0.8]]}, {"t": 0.5, "d": 1.0, "top": [["bird", 0.9]]},
               {"t": 1.0, "d": 1.0, "top": [["bird", 0.85]]}, {"t": 1.5, "d": 1.0, "top": [["bird", 0.8]]}]
    events = P.sound_events(windows, hop=0.5)
    assert [(e["kind"], e["start"], e["end"]) for e in events] == [("chim hót", 0.5, 2.5)]


def test_loudness_clipping_and_wind_are_measured_from_the_samples():
    rate = 16000
    t = np.arange(rate) / rate
    quiet = 0.01 * np.sin(2 * np.pi * 1000 * t)
    clipped = np.clip(2.0 * np.sin(2 * np.pi * 1000 * t), -1, 1)
    wind = 0.3 * np.sin(2 * np.pi * 60 * t)
    got = P.levels(np.concatenate([quiet, clipped, wind]).astype(np.float32), rate)
    assert len(got["rms_db"]) == 30
    assert max(got["rms_db"][:10]) < -35 and min(got["clipped"][10:20]) > 0.1 and max(got["clipped"][:10]) == 0
    assert min(got["low_share"][20:]) > 0.9 and max(got["low_share"][:10]) < 0.1


def test_loudness_of_a_stretch_is_averaged_as_energy():
    momentary = [-20.0] * 10 + [-30.0] * 10 + [None] * 10
    assert P.r128_between(momentary, 0.0, 1.0) == -20.0
    assert P.r128_between(momentary, 0.0, 2.0) == pytest.approx(-22.6, abs=0.1)
    assert P.r128_between(momentary, 2.0, 3.0) is None


# ----------------------------------------------------------------------------------------------------------------- text
def _text(t, box, conf=0.95):
    return {"text": t, "box": box, "confidence": conf}


def test_text_read_in_frame_after_frame_is_one_stretch_and_its_kind_comes_from_where_and_how_it_shows():
    sub = [0.3, 0.85, 0.4, 0.06]
    pictures = [{"text": [_text("Chào mừng tới Hội An", sub), _text("DJI", [0.85, 0.05, 0.05, 0.03])]} for _ in range(4)] + \
               [{"text": [_text("DJI", [0.85, 0.05, 0.05, 0.03])]} for _ in range(6)]
    spans = P.text_spans(pictures, step=0.5, duration=5.0)
    assert [(s["text"], s["kind"]) for s in spans] == [("DJI", "watermark"), ("Chào mừng tới Hội An", "phụ đề")]
    sub_span = spans[1]
    assert (sub_span["start"], sub_span["end"]) == (0.0, 1.75)


def test_text_that_moves_with_the_picture_is_part_of_the_scene():
    pictures = [{"text": [_text("Phở Thìn", [0.2 + 0.05 * k, 0.4, 0.2, 0.05])]} for k in range(4)]
    assert P.text_spans(pictures, step=0.5, duration=2.0, camera_moving=lambda t: True)[0]["kind"] == "chữ trong cảnh"


def test_a_fixed_mark_in_a_corner_is_found_without_letters():
    rng = np.random.default_rng(0)
    stack = rng.random((12, 90, 160)).astype(np.float32)
    stack[:, 5:15, 140:155] = np.tile(np.linspace(0, 1, 15), (10, 1))          # a logo: the same pixels in every frame
    marks = P.static_marks(stack)
    assert marks and marks[0][0] > 0.8 and marks[0][1] < 0.2


# ------------------------------------------------------------------------------------------------------- light and colour
def test_warm_light_cold_light_and_colourless_footage_are_told_apart():
    warm = np.zeros((90, 160, 3), np.uint8); warm[...] = (210, 160, 110)
    cold = np.zeros((90, 160, 3), np.uint8); cold[...] = (120, 150, 210)
    grey = np.zeros((90, 160, 3), np.uint8); grey[...] = (128, 128, 128)
    assert P.measure_frame(warm).warmth > 1.12 and P.measure_frame(cold).warmth < 0.9
    m = P.measure_frame(grey)
    assert m.saturation < 0.02 and m.palette[0][2] == "xám"
    assert P.colour_name((200, 30, 30)) == "đỏ" and P.colour_name((40, 160, 60)) == "xanh lá" and P.colour_name((20, 20, 20)) == "đen"


def test_footage_shot_flat_for_grading_is_named_log():
    flat = [P.FrameMeasure(0.45, 0.3, 0.1, 1.0, 6500, 1.0, 0.2, 0.2, 0.2, 0.2, None, None, None, []) for _ in range(5)]
    punchy = [P.FrameMeasure(0.45, 0.8, 0.4, 1.0, 6500, 1.0, 0.2, 0.2, 0.2, 0.2, None, None, None, []) for _ in range(5)]
    assert P.detect_log({"bit_depth": 10}, flat) is True and P.detect_log({"bit_depth": 10}, punchy) is False


# --------------------------------------------------------------------------------------------------------- one beat
def test_a_beat_with_a_person_speaking_to_camera():
    pictures = [{"faces": [{"box": [0.4, 0.2, 0.15, 0.3], "confidence": 0.9, "mouth": m}], "humans": [{"box": [0.3, 0.1, 0.4, 0.9], "confidence": 0.9}],
                 "classes": [["interior_room", 0.8]], "salient": [[0.35, 0.15, 0.3, 0.6]]} for m in (0.02, 0.2, 0.05)]
    words = [{"text": "xin", "start": 0.2, "end": 0.5}, {"text": "chào", "start": 0.6, "end": 0.9}]
    fields = P.profile_beat(0.0, 1.5, pictures, [], words=words, events=[], momentary=[], audio={}, camera="static", spans=[], log_profile=False)
    assert fields["people"]["value"] == "một" and fields["shot_size"]["value"] == "cận" and fields["shot_size"]["by"] == "người"
    assert fields["speaker"]["value"] == "trong khung" and fields["place"]["value"] == "trong nhà"


def test_speech_with_no_face_in_frame_is_said_to_come_from_outside_it():
    pictures = [{"faces": [], "humans": [], "classes": [["outdoor", 0.9]]}] * 3
    fields = P.profile_beat(0.0, 1.5, pictures, [], words=[{"text": "đẹp", "start": 0.1, "end": 0.4}], events=[], momentary=[], audio={},
                            camera=None, spans=[], log_profile=False)
    assert fields["speaker"]["value"] == "ngoài khung" and fields["people"]["value"] == "không"


# ------------------------------------------------------------------------------------------------- the model checked
def test_what_a_model_says_against_what_was_measured_raises_flags():
    fields = {"shot_size": {"value": "toàn", "confidence": "medium"}, "people": {"value": "không", "count": 0, "confidence": "high"},
              "place": {"value": "ngoài trời", "confidence": "high"}, "music": {"value": False}}
    detail = {"mo_ta": "Một người đàn ông trong countryside, nhạc vang lên", "co_canh": "cận", "so_nguoi": "một", "noi_chon": "trong nhà",
              "chu_tren_hinh": "SALE"}
    rules = {f["rule"] for f in P.cross_checks(fields, detail, {"camera": {"value": "pan"}}, has_audio=True)}
    assert rules == {"cỡ cảnh", "số người", "nơi chốn", "chữ trên hình", "âm thanh", "ngôn ngữ"}
    labels = model_labels(tidy(detail), fields)
    assert labels["co_canh"] == {"value": "cận", "source": "model", "confidence": "low"}
    assert labels["noi_chon"]["confidence"] == "low"


def test_the_model_is_told_only_what_is_sure_and_the_text_found_by_says_what_was_measured():
    fields = {"people": {"value": "một", "count": 1, "confidence": "high"}, "shot_size": {"value": "cận", "by": "người"},
              "sound": {"value": ["chim hót"]}, "text": {"value": ["Phở Thìn"]}}
    told = facts_of(fields, {"camera": {"value": "pan"}}, "ngon quá")
    assert "có 1 người trong hình" in told and "cỡ cảnh: cận" in told and "máy lia ngang" in told and "Phở Thìn" in told
    assert "ngon quá" not in told                      # spoken words are not told: a small model copied them into the text on screen
    assert "không có người nào trong hình" in facts_of({"people": {"count": 0, "confidence": "high"}}, {})
    text = text_of(tidy({"mo_ta": "Một người ăn phở.", "khac_truoc": "tiếp diễn", "chu_the": ["bát phở"], "hanh_dong": [{"ai": "người", "lam_gi": "ăn", "voi": "phở"}]}),
                   fields, {"camera": {"value": "pan"}})
    assert text == "Một người ăn phở. Thấy: bát phở. Hành động: người ăn phở. Hình: cảnh cận; máy lia ngang; tiếng chim hót. Chữ trên hình: Phở Thìn."


# ------------------------------------------------------------------------------------------------------- the whole file
def test_a_vertical_clip_suits_short_platforms_and_text_low_in_the_frame_is_named():
    beats = [{"start": 0.0, "end": 20.0, "labels": {}, "profile": {"people": {"count": 1}}}]
    spans = [{"text": "Mua ngay", "start": 1.0, "end": 3.0, "box": [0.3, 0.88, 0.4, 0.06], "kind": "chữ chèn", "size": 0.06}]
    made = P.asset_profile(probe={"duration": 20.0, "orientation": "dọc"}, shots=[{"start": 0.0, "end": 20.0}], beats=beats,
                           words=[{"text": "xin", "start": 0.4, "end": 0.6}], spans=spans, events=[], integrated=None, signals_diff=None, fps=None, language="vi")
    assert made["platforms"]["YouTube"]["fits"] != "tốt"
    assert any("vùng giao diện" in r for r in made["platforms"]["TikTok"]["reasons"])
    assert made["hook"]["face_in_first_3s"] and made["hook"]["text_in_first_3s"] and made["calls_to_action"] == ["mua ngay"]


# -------------------------------------------------------------------------------------------------------- end to end
def test_footage_is_profiled_after_ingest_and_the_profile_reaches_the_beats_and_the_search(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=2.0, recognisers=[FakeVision(), FakeSound()])
    asset, _ = system.library.ingest(make_video(tmp_path / "f.mp4", picture=4))
    drain(system)
    made = system.library.profiler.profile(asset)
    assert made and made["recognised"] and made["beats"]
    beat = made["beats"][0]["profile"]
    assert beat["people"]["value"] == "một" and beat["shot_size"]["value"] == "cận" and beat["place"]["value"] == "ngoài trời"
    assert beat["light"]["value"] and beat["colour"]["palette"] and beat["noise"]["value"]
    segments = system.index.moments(asset, level="segment")
    assert segments and all(m.data.get("profile") for m in segments)
    assert any("cảnh cận" in m.text for m in segments)
    found = system.index.search("Chợ Hội An buổi sáng", level=("text",))
    assert found and found[0].moment.asset_id == asset and found[0].moment.data["span"]["kind"] == "phụ đề"
    assert system.assets.original(asset).metadata["profile"]["platforms"]["YouTube"]["fits"]
    assert system.library.profiler.prints(asset) is not None


def test_without_recognisers_the_measured_fields_are_still_there(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=2.0)
    asset, _ = system.library.ingest(make_video(tmp_path / "f.mp4", picture=4))
    drain(system)
    made = system.library.profiler.profile(asset)
    assert made and not made["recognised"]
    beat = made["beats"][0]["profile"]
    assert "people" not in beat and beat["light"]["value"] and beat["colour"]["value"]


def test_beats_doing_the_same_thing_are_one_event_with_phases_and_an_event_at_the_end_of_its_shot_is_cut_off():
    act = lambda verb: {"hanh_dong": [{"ai": "người bán", "lam_gi": verb, "voi": "bột"}]}
    beats = [{"start": 0.0, "end": 3.0, "shot": 0, "detail": {}}, {"start": 3.0, "end": 6.0, "shot": 0, "detail": act("nhào")},
             {"start": 6.0, "end": 9.0, "shot": 0, "detail": act("nhào")}, {"start": 9.0, "end": 12.0, "shot": 0, "detail": act("nhào")},
             {"start": 12.0, "end": 15.0, "shot": 1, "detail": act("cắt")}]
    shots = [{"start": 0.0, "end": 12.0}, {"start": 12.0, "end": 15.0}]
    made = P.events_of(beats, shots, motion=lambda a, b: {3.0: 0.1, 6.0: 0.6, 9.0: 0.2}.get(a, 0.0))
    assert [(e["start"], e["end"], e["actions"]) for e in made] == [(3.0, 12.0, ["nhào"]), (12.0, 15.0, ["cắt"])]
    assert made[0]["phases"]["cao trào"] == [6.0, 9.0] and made[0]["beats"] == 3 and made[0]["who"] == "người bán"
    assert made[0]["cut_end"] is True and made[0]["cut_start"] is False
    assert made[1]["cut_start"] is True and made[1]["cut_end"] is True


def test_a_shoot_is_grouped_into_scenes_across_files_by_time_place_and_picture():
    v = lambda *xs: np.array(xs, np.float32) / np.linalg.norm(xs)
    beach, beach2, room = v(1, 0.1, 0), v(1, 0.15, 0.05), v(0, 0.2, 1)
    beats = [{"asset_id": "a", "start": 0, "end": 5, "at": 0, "end_at": 5, "print": beach, "place": "ngoài trời", "tags": ["bãi biển", "thuyền"]},
             {"asset_id": "b", "start": 0, "end": 5, "at": 60, "end_at": 65, "print": beach2, "place": "ngoài trời", "tags": ["bãi biển", "cát"]},
             {"asset_id": "c", "start": 0, "end": 5, "at": 120, "end_at": 125, "print": room, "place": "trong nhà", "tags": ["phòng tắm", "gương"]},
             {"asset_id": "d", "start": 0, "end": 5, "at": 5000, "end_at": 5005, "print": room, "place": "trong nhà", "tags": ["phòng tắm"]}]
    scenes = P.scenes_of(beats)
    assert [s["assets"] for s in scenes] == [["a", "b"], ["c"], ["d"]]
    assert "đổi nơi chốn" in scenes[1]["why"] and scenes[2]["why"][0].startswith("cách nhau")
    assert scenes[0]["name"] == "ngoài trời: bãi biển, thuyền, cát"


def test_a_beat_print_is_the_unit_mean_of_its_frames():
    prints = np.array([[1, 0], [1, 0], [0, 1], [0, 1]], np.float16)
    assert np.allclose(P.beat_print(prints, 0.5, 0.0, 1.0), [1, 0]) and np.allclose(P.beat_print(prints, 0.5, 0.0, 2.0), [0.7071, 0.7071], atol=1e-3)


def test_text_being_typed_is_one_stretch_and_a_fragment_read_once_is_dropped():
    box = [0.3, 0.4, 0.3, 0.05]
    typed = ["Anh Cần", "Anh Cần cho em", "Anh Cần cho em hỏi", "Anh Cần cho em hỏi hồ sơ"]
    pictures = [{"text": [_text(t, box)]} for t in typed] + [{"text": [_text("Gang câu", [0.1, 0.1, 0.1, 0.04], 0.5)]}]
    spans = P.text_spans(pictures, step=0.5, duration=3.0)
    assert [s["text"] for s in spans] == ["Anh Cần cho em hỏi hồ sơ"]


def test_hands_seen_from_the_operators_eyes_are_one_person():
    hands = {"faces": [], "humans": [], "hands": [{"box": [0.4, 0.5, 0.2, 0.3], "confidence": 0.9}, {"box": [0.1, 0.5, 0.2, 0.3], "confidence": 0.8}]}
    assert P.people_in(hands)["count"] == 1 and P.people_in({"faces": [], "humans": [], "hands": []})["count"] == 0


def test_a_summary_keeps_only_what_the_footage_shows_for_it():
    from nexora.modules.library.understand import grounded
    out = grounded({"chu_de": ["bãi biển", "tàu vũ trụ"], "the_loai": "vlog du lịch", "cau_truc": [{"phan": "mở đầu", "tu": "0:00"}, {"phan": "cao trào", "tu": "9:99"}],
                    "cam_xuc": [{"tu": "0:05", "cam_xuc": "vui"}, {"tu": "0:05", "cam_xuc": "phấn khích"}], "khan_gia": "người thích du lịch"},
                   ["Bãi biển vắng, thuyền thúng trên cát."], {"0:00", "0:05"})
    assert out["chu_de"] == ["bãi biển"] and out["the_loai"] == "vlog du lịch"
    assert out["cau_truc"] == [{"phan": "mở đầu", "tu": "0:00"}] and out["cam_xuc"] == [{"tu": "0:05", "cam_xuc": "vui"}]
    assert "khan_gia" in out["inferred"]
