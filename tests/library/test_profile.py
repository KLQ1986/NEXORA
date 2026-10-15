"""The footage profile (design 2026-10-14): fields measured and recognised beat by beat, text on screen, kinds of sound and the
profile of a whole file, with what a model says checked against them."""
import math

import numpy as np
import pytest

from nexora.app import build
from nexora.modules.intelligence import profile as P
from nexora.modules.intelligence import vocab
from nexora.modules.intelligence.understand import facts_of, model_labels, tidy, text_of

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
    # The sounds heard are found as moments of their own; in a beat's text, a sound wrongly named would mislead a search for the picture.
    assert text == "Một người ăn phở. Thấy: bát phở. Hành động: người ăn phở. Hình: cảnh cận; máy lia ngang. Chữ trên hình: Phở Thìn."


def test_a_description_keeps_what_is_seen_and_says_where_it_is_and_drops_formulas_and_what_is_not_there():
    out = tidy({"mo_ta": "Hình ảnh cho thấy một bãi biển với thuyền thúng màu xanh trên cát. Không có người nào xuất hiện trong hình.",
                "chu_the_chinh": "thuyền thúng xanh, giữa khung", "tien_canh": "lá rau muống biển, tạo nên không gian yên bình", "trung_canh": "bãi cát",
                "hau_canh": "biển và nhiều thuyền nhỏ ngoài khơi", "chu_the": ["thuyền thúng", "biển", "không có người"]})
    assert out["mo_ta"] == "Một bãi biển với thuyền thúng màu xanh trên cát."
    assert out["tien_canh"] == "lá rau muống biển" and out["chu_the"] == ["thuyền thúng", "biển"]
    assert text_of(out, {}, {}) == ("Một bãi biển với thuyền thúng màu xanh trên cát. Chủ thể: thuyền thúng xanh, giữa khung. Gần máy: lá rau muống biển. "
                                    "Giữa: bãi cát. Xa: biển và nhiều thuyền nhỏ ngoài khơi. Thấy: thuyền thúng, biển.")
    assert tidy({"mo_ta": "Các khung hình liên tiếp cho thấy hai người đi trên lối đi."})["mo_ta"] == "Hai người đi trên lối đi."
    assert tidy({"mo_ta": "Đoạn video ghi lại một gian bếp. Trong hình không có chữ."})["mo_ta"] == "Một gian bếp."
    assert "Điểm mới" not in text_of({"mo_ta": "Bãi cát.", "chu_the": ["cát", "thuyền thúng"], "khac_truoc": "cát, thuyền thúng"}, {}, {})
    assert "Điểm mới" not in text_of({"mo_ta": "Bãi cát.", "chu_the": ["cát", "một chiếc thuyền ở xa"], "khac_truoc": "cát, chiếc thuyền ở xa"}, {}, {})
    assert "Điểm mới: thuyền thúng." in text_of({"mo_ta": "Bãi cát.", "chu_the": ["cát", "thuyền thúng"], "khac_truoc": "thuyền thúng"}, {}, {})
    moved = tidy({"mo_ta": "Bãi cát trắng. Máy quay di chuyển từ phải sang trái.", "chu_the_chinh": "máy quay di chuyển từ phải sang trái"})
    assert moved["mo_ta"] == "Bãi cát trắng." and moved["chu_the_chinh"] == ""        # the camera's movement is measured, not told


def test_a_room_is_named_in_vietnamese_without_the_cameras_movement_or_a_subject_that_is_only_a_place_in_the_frame():
    # What qwen3-vl answered for 0059, a bathroom: English for the towels, the push-in among the things, a subject that is a side.
    out = tidy({"mo_ta": "Một phòng tắm với bồn cầu trắng. Máy đẩy vào phía gương.", "chu_the_chinh": "phía trái",
                "trung_canh": "ở giữa khung hình", "hau_canh": "cửa sổ gỗ, phía sau",
                "chu_the": ["gương", "towel rack", "towel", "bình xà phòng", "máy đẩy vào", "máy quay", "shampoo dispenser"]})
    assert out["mo_ta"] == "Một phòng tắm với bồn cầu trắng."
    assert out["chu_the"] == ["gương", "giá treo khăn", "khăn tắm", "bình xà phòng", "máy quay"]     # a camera in the picture is a thing
    assert out["chu_the_chinh"] == "" and out["trung_canh"] == "" and out["hau_canh"] == "cửa sổ gỗ, phía sau"
    assert tidy({"chu_the_chinh": "người đàn ông, ở giữa"})["chu_the_chinh"] == "người đàn ông, ở giữa"
    assert tidy({"mo_ta": "Máy quay lia ngang qua công viên giải trí có vòng quay."})["mo_ta"] == "Máy quay lia ngang qua công viên giải trí có vòng quay."
    assert tidy({"trung_canh": "cây dừa, mái ngói đỏ", "hau_canh": "Cây dừa, mái ngói đỏ"})["hau_canh"] == ""
    assert vocab.mend("towel rack bên bình xà phòng") == "giá treo khăn bên bình xà phòng"      # a phrase is one thing; "bình" is not "bin"


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
    made = system.intelligence.profiler.profile(asset)
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
    assert system.intelligence.profiler.prints(asset) is not None


def test_the_beats_are_put_into_words_again_from_what_was_said_without_asking_the_model_again(tmp_path):
    model = FakeModel()
    system = build(tmp_path / "data", model=model, segment_seconds=2.0, recognisers=[FakeVision(), FakeSound()])
    asset, _ = system.library.ingest(make_video(tmp_path / "f.mp4", picture=4))
    drain(system)
    beat = system.index.moments(asset, level="segment")[0]
    said = {**beat.data["detail"], "chu_the": ["gương", "towel", "máy đẩy vào"], "chu_the_chinh": "phía trái"}      # cleaned the old way
    system.index.upsert(asset, "segment", beat.t_start, beat.t_end, "Thấy: gương, towel, máy đẩy vào.", data={**beat.data, "detail": said},
                        analyzer=beat.analyzer)
    described = model.calls["describe"]
    assert system.intelligence.retell(asset) >= 1
    again = system.index.get(asset, "segment", beat.t_start, beat.t_end)
    assert "Thấy: gương, khăn tắm." in again.text and "máy đẩy vào" not in again.text and "Chủ thể" not in again.text
    assert again.analyzer == beat.analyzer and not system.index.without_vectors(asset)       # still current, and found by meaning
    assert model.calls["describe"] == described                                               # nothing was looked at again


def test_without_recognisers_the_measured_fields_are_still_there(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=2.0)
    asset, _ = system.library.ingest(make_video(tmp_path / "f.mp4", picture=4))
    drain(system)
    made = system.intelligence.profiler.profile(asset)
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



def test_a_room_seen_from_inside_is_a_medium_shot_and_never_more_than_low_confidence():
    classes = [["structure", 0.62], ["wood_processed", 0.6], ["interior_room", 0.27], ["bathroom", 0.27]]    # 0059, the first second
    assert P.size_from_scene(classes, [[0.26, 0.04, 0.57, 0.72]]) == ("trung", "low")
    assert P.size_from_scene([["structure", 0.8], ["window", 0.8]], [[0.1, 0.2, 0.6, 0.8]]) is None        # a window alone says nothing


def test_a_sentence_is_the_persons_whose_face_alone_is_seen_while_their_mouth_moves_and_their_voice_carries_it_out_of_frame():
    said = lambda t0, t1, voice, text, a="v": {"asset_id": a, "t_start": t0, "t_end": t1, "voice": voice, "text": text}
    sentences = [said(1.0, 3.0, 1, "xin chào"), said(5.0, 7.0, 2, "chào bạn"), said(9.0, 10.0, 1, "đi thôi"), said(12.0, 13.0, 3, "ai đó")]
    faces = [{"asset_id": "v", "t": t, "group": 0} for t in (1.0, 1.5, 2.0, 2.5)] + \
            [{"asset_id": "v", "t": t, "group": g} for t in (5.0, 5.5, 6.0) for g in (0, 1)] + [{"asset_id": "v", "t": 12.0, "group": 1}]
    talking = {"v": [(0.0, 7.0)]}                                     # after 7 s the speaker is out of frame
    who = P.voices_of(sentences, faces, talking)
    assert [(x["text"], x["by"]) for x in who[0]] == [("xin chào", "mặt"), ("đi thôi", "giọng")]
    assert 1 not in who                    # two faces while "chào bạn" was said; "ai đó" was said out of frame by a voice never seen


def test_one_beat_of_action_still_has_a_start_a_peak_and_an_end_from_how_the_subject_moves():
    beats = [{"start": 0.0, "end": 5.0, "shot": 0, "detail": {"hanh_dong": [{"ai": "người", "lam_gi": "quay video", "voi": ""}]}}]
    fps = 10.0
    motion = np.zeros(60, np.float32); motion[5:45] = 0.3; motion[30] = 1.0          # moves from 0.5 s to 4.5 s, most at 3.0 s
    made = P.events_of(beats, [{"start": 0.0, "end": 6.0}], motion=lambda a, b: 0.5, series=(motion, fps))
    assert made[0]["moving_from"] == 0.5 and made[0]["moving_to"] == 4.5
    assert made[0]["phases"] == {"bắt đầu": [0.5, 2.5], "cao trào": [2.5, 3.5], "kết thúc": [3.5, 4.5], "peak_at": 3.0}


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
    from nexora.modules.intelligence.understand import grounded
    out = grounded({"chu_de": ["bãi biển", "tàu vũ trụ"], "the_loai": "vlog du lịch", "cau_truc": [{"phan": "mở đầu", "tu": "0:00"}, {"phan": "cao trào", "tu": "9:99"}],
                    "cam_xuc": [{"tu": "0:05", "cam_xuc": "vui"}, {"tu": "0:05", "cam_xuc": "phấn khích"}], "khan_gia": "người thích du lịch"},
                   ["Bãi biển vắng, thuyền thúng trên cát."], {"0:00", "0:05"})
    assert out["chu_de"] == ["bãi biển"] and out["the_loai"] == "vlog du lịch"
    assert out["cau_truc"] == [{"phan": "mở đầu", "tu": "0:00"}] and out["cam_xuc"] == [{"tu": "0:05", "cam_xuc": "vui"}]
    assert "khan_gia" in out["inferred"]


def test_a_person_is_followed_through_a_shot_and_never_across_a_cut():
    person = lambda x: {"humans": [{"box": [x, 0.2, 0.2, 0.6], "confidence": 0.9}]}
    pictures = [person(0.1), person(0.15), person(0.2), person(0.3), person(0.35)]
    made = P.tracks_of(pictures, step=0.5, shots=[{"start": 0.0, "end": 1.5}, {"start": 1.5, "end": 3.0}])
    assert [(t["start"], t["end"], t["frames"]) for t in made] == [(0.0, 1.5, 3), (1.5, 2.5, 2)]
    assert made[0]["moves"] == "tại chỗ" and P.tracks_of([person(0.1), person(0.18), person(0.26), person(0.34)], step=0.5, shots=[{"start": 0, "end": 9}])[0]["moves"] == "trái sang phải"


def test_an_action_is_timed_to_a_tenth_of_a_second_from_how_the_subject_moves():
    motion = np.zeros(300, np.float32); motion[62:181] = 0.8
    assert P.refine_bounds(0.0, 10.0, motion, 30.0) == (2.1, 6.0)
    assert P.refine_bounds(0.0, 10.0, np.zeros(300, np.float32), 30.0) == (0.0, 10.0)


def test_content_credentials_are_noticed(tmp_path):
    marked, plain = tmp_path / "a.mp4", tmp_path / "b.mp4"
    marked.write_bytes(b"\\0" * 100 + b"jumbc2pa" + b"\\0" * 100); plain.write_bytes(b"\\0" * 300)
    assert P.has_content_credentials(marked) and not P.has_content_credentials(plain)


def test_what_the_channel_says_needs_five_videos_and_compares_with_and_without():
    few = P.what_works([{"retention": 0.5, "traits": {"x": True}}] * 4)
    assert few["enough"] is False and few["findings"] == []
    videos = [{"retention": r, "traits": {"có mặt người": f}} for r, f in ((0.7, True), (0.6, True), (0.65, True), (0.3, False), (0.35, False))]
    found = P.what_works(videos)["findings"]
    assert abs(found[0]["difference"]) == pytest.approx(0.325, abs=1e-3) and next(f for f in found if f["value"] == "True")["difference"] > 0 and {f["value"] for f in found} == {"True", "False"}


def test_a_template_takes_the_shape_captions_and_pace_of_a_reference_video():
    whole = {"orientation": "dọc", "style": {"captions": {"position_y": 0.8, "height": 0.07}, "music_share": 0.7, "cuts_per_minute": 24,
                                             "shot_sizes": {"cận": 0.6, "toàn": 0.4}, "look": {"rực rỡ": 1.0}, "loudness_lufs": -14}}
    made = P.template_from_style(whole, "Như kênh X")
    assert (made["format"], made["caption_position"], made["caption_scale"], made["music_gain"]) == ("portrait", "bottom", 1.4, 0.5)
    assert made["style"] == {"cuts_per_minute": 24, "shot_size": "cận", "look": "rực rỡ", "loudness_lufs": -14}


def test_a_phone_held_up_by_the_operator_is_sized_by_the_phone_not_by_the_operator():
    pov = lambda hand: {"faces": [], "humans": [{"box": [0.0, 0.0, 0.9, 0.95], "confidence": 0.9}], "hands": [{"box": [0.5, 0.3, 0.3, hand], "confidence": 0.9}],
                        "classes": [], "salient": [[0.3, 0.2, 0.4, 0.5]]}
    beat = lambda pictures: P.profile_beat(0.0, 1.5, pictures, [], words=[], events=[], momentary=[], audio={}, camera=None, spans=[], log_profile=False)
    assert beat([pov(0.6)] * 3)["shot_size"]["value"] == "cận" and beat([pov(0.6)] * 3)["shot_size"]["by"] == "tay cầm vật"
    assert "shot_size" not in beat([pov(0.3)] * 3)                  # small hands: close or very close cannot be told, so nothing is said


def test_the_cameras_own_record_gives_its_angle_tilt_and_turning():
    import struct
    from nexora.modules.intelligence import telemetry
    def varint(n):
        out = b""
        while True:
            b = n & 0x7F; n >>= 7
            out += bytes([b | (0x80 if n else 0)])
            if not n: return out
    def msg(f, body): return varint((f << 3) | 2) + varint(len(body)) + body
    def flt(f, v): return varint((f << 3) | 5) + struct.pack("<f", v)
    def packet(gy, gz, gw, q):
        frame = msg(9, b"".join(flt(k, v) for k, v in zip((1, 2, 3, 4), q))) + msg(10, flt(2, gy) + flt(3, gz) + flt(4, gw)) + msg(3, flt(1, 400.0))
        return msg(3, msg(2, frame))
    down = [packet(-0.87, 0.0, -0.49, [1.0, 0.0, 0.0, 0.0])] * 30
    turning = [packet(0.0, 0.0, -1.0, [math.cos(math.radians(i) / 2), 0.0, 0.0, math.sin(math.radians(i) / 2)]) for i in range(0, 60, 2)]
    records = telemetry.frames(down + turning)
    assert len(records) == 60 and records[0]["pitch"] == pytest.approx(-60.5, abs=0.5) and records[0]["iso"] == 400.0
    first = telemetry.beat_fields(records, 30.0, 0.0, 1.0)
    second = telemetry.beat_fields(records, 30.0, 1.0, 2.0)
    assert first["angle"]["value"] == "từ trên xuống" and second["angle"]["value"] == "ngang tầm"
    assert second["turning"]["value"] == pytest.approx(60.0, abs=3) and first["turning"]["value"] == 0.0


def test_a_hand_over_the_main_thing_is_holding_it():
    pictures = [{"faces": [], "humans": [], "hands": [{"box": [0.4, 0.4, 0.2, 0.2], "confidence": 0.9}], "classes": [["phone", 0.8]], "salient": [[0.3, 0.3, 0.4, 0.4]]}] * 3
    fields = P.profile_beat(0.0, 1.5, pictures, [], words=[], events=[], momentary=[], audio={}, camera=None, spans=[], log_profile=False)
    assert fields["holding"]["value"] == ["người", "cầm", "điện thoại"]
