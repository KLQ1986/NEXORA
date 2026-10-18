"""Associative illustration (design 2026-10-18): narration says something and the picture evokes it. A line carries how it is
illustrated (direct, associative, contrast), what is to be seen and what it evokes; a line that evokes is searched by those,
never by its words, ranked by the footage's measured feel, and judged on what it evokes."""
from nexora.app import build, illustration_style
from nexora.core import illustration as ILL

from tests.fakes import FakeModel, FakeVoice
from tests.library.test_analysis import drain, film, taken_in

STILL = {"labels": {"camera": {"value": "static", "speed": 0.01}}, "profile": {"light": {"brightness": 0.7}, "colour": {"kelvin": 4300}, "shot_size": {"value": "toàn"}, "people": {"count": 0}}}
MOVING = {"labels": {"camera": {"value": "pan", "speed": 0.4}}, "profile": {"light": {"brightness": 0.3}, "colour": {"kelvin": 7600}, "shot_size": {"value": "cận"}, "people": {"count": 5}}}

DRAFT = {"cau": [
    {"cau": "Có những ngày mình chỉ cần chậm lại.", "kieu": "lien_tuong", "hinh": "sóng biển rút chậm trên cát vắng", "goi": "chậm lại",
     "cam_giac": {"chuyen_dong": "tĩnh", "khung": "rộng", "nguoi": "không người", "mau": "tím"}},
    {"cau": "Quán cà phê nhỏ ở cuối bãi.", "kieu": "truc_tiep", "hinh": "quán cà phê ven biển"},
]}


def test_the_measured_feel_and_the_query_of_each_way():
    assert ILL.measured(STILL) == {"chuyen_dong": "tĩnh", "anh_sang": "sáng", "mau": "ấm", "khung": "rộng", "nguoi": "không người"}
    assert ILL.measured(MOVING) == {"chuyen_dong": "nhanh", "anh_sang": "tối", "mau": "lạnh", "khung": "cận", "nguoi": "đông người"}
    assert ILL.measured({}) == {}                                                       # nothing measured, nothing guessed
    share, said = ILL.feel_match({"chuyen_dong": "tĩnh", "khung": "rộng", "anh_sang": "tối"}, STILL)
    assert round(share, 2) == 0.67 and said == "tĩnh, rộng: khớp 2/3"
    assert ILL.feel_match({"chuyen_dong": "tĩnh"}, {}) == (0.0, None)
    assert ILL.feel_match({"chuyen_dong": "nhanh"}, STILL) == (0.0, "không khớp (nhanh)")
    # A value outside the vocabulary is dropped; a direct line evokes nothing.
    assert ILL.normalise({"kieu": "lien_tuong", "goi": "chậm lại", "cam_giac": {"mau": "tím", "chuyen_dong": "chậm"}}) == {"mode": "associative", "evokes": "chậm lại", "feel": {"chuyen_dong": "chậm"}}
    assert ILL.normalise({"kieu": "truc_tiep", "goi": "x"}) == {"mode": "direct"} and ILL.normalise({"kieu": "khac"}) == {}
    line = "Có những ngày mình chỉ cần chậm lại."
    assert ILL.query(line, "sóng rút trên cát", {"mode": "associative", "evokes": "chậm lại"}) == "sóng rút trên cát chậm lại"   # never the words
    assert ILL.query(line, "sóng rút trên cát", {"mode": "direct"}) == f"{line} sóng rút trên cát"
    assert "chậm lại" in ILL.judged_line(line, "sóng", {"mode": "associative", "evokes": "chậm lại"}) and "không cần thấy đúng" in ILL.judged_line(line, "sóng", {"mode": "associative"})


def test_a_mixed_draft_keeps_how_each_line_is_illustrated_through_saving_critique_and_revision(tmp_path):
    model = FakeModel()
    asked = []
    model.answers["draft"] = lambda r: asked.append(r.params["prompt"]) or DRAFT
    system = build(tmp_path / "data", model=model, voice=FakeVoice())
    project = system.planning.create_project("Biển sáng")
    lines = system.planning.draft_script("buổi sáng ở biển", lines=2, project_id=project)
    assert lines == ["Có những ngày mình chỉ cần chậm lại.", "Quán cà phê nhỏ ở cuối bãi."]
    assert "KHÔNG tả lại" in asked[-1] and "lien_tuong" in asked[-1]                      # mixed: the narration tells, the writer picks the way
    system.planning.draft_script("x", lines=2, style="direct")
    assert "CÓ trong kho footage" in asked[-1] and "KHÔNG tả lại" not in asked[-1]

    # Saved word for word from the editor, the lines bring the writer's notes back.
    system.planning.save_script(project, lines)
    first, second = system.projects.current_script(project)["shots"]
    assert first.brief == "sóng biển rút chậm trên cát vắng" and first.illustration == {"mode": "associative", "evokes": "chậm lại", "feel": {"chuyen_dong": "tĩnh", "khung": "rộng", "nguoi": "không người"}}
    assert second.illustration == {"mode": "direct"}

    # A line meant to evoke that only describes its picture is a measured critique note.
    system.projects.annotate_shot(first.shot_id, brief="có những ngày chỉ cần chậm lại")
    model.answers["critique"] = {"nhan_xet": []}
    notes = system.planning.critique(project)
    assert notes and notes[0]["line"] == 1 and notes[0]["measured"] and "tả lại hình" in notes[0]["issue"]
    # A rewrite of the same shape keeps each line's notes under its new words.
    model.answers["revise"] = {"cau": ["Đôi khi chỉ cần chậm lại một chút.", "Quán cà phê nhỏ ở cuối bãi."]}
    system.planning.revise(project)
    revised = system.projects.current_script(project)["shots"]
    assert revised[0].text == "Đôi khi chỉ cần chậm lại một chút." and revised[0].illustration["mode"] == "associative" and revised[0].brief == "có những ngày chỉ cần chậm lại"


def test_a_line_that_evokes_is_found_by_what_is_seen_and_ranked_by_feel(tmp_path):
    model = FakeModel()
    system = build(tmp_path / "data", model=model, voice=FakeVoice(), segment_seconds=15.0, judge=False)
    still, moving, literal = (taken_in(system, film(tmp_path / f"{n}.mp4", [("testsrc2", 12)])) for n in ("still", "moving", "literal"))
    system.index.upsert(still, "segment", 0.0, 8.0, "sóng biển rút trên cát vắng", data=STILL)
    system.index.upsert(moving, "segment", 0.0, 8.0, "sóng biển rút trên cát vắng", data=MOVING)
    system.index.upsert(literal, "segment", 0.0, 8.0, "có những ngày mình chỉ cần chậm lại", data=MOVING)
    feel = {"chuyen_dong": "tĩnh", "khung": "rộng", "nguoi": "không người"}

    # The storyboard's search: the same meaning on two stretches, the measured feel puts the still, wide, empty one first.
    found = system.sourcing.find("sóng biển rút trên cát vắng chậm lại", 4.0, illustration={"mode": "associative", "evokes": "chậm lại", "feel": feel})
    assert found[0]["asset_id"] == still and "Cảm giác tĩnh, rộng, không người: khớp 3/3" in found[0]["reason"]
    assert system.sourcing.find("sóng biển rút trên cát vắng", 4.0)[0]["asset_id"] in (still, moving)       # a direct search is unchanged by feel
    # The feel only chooses among stretches that mean the right thing: a garden in the wrong light beats a bucket of soil in the
    # right one (the first real run put a man stirring soil on "a quiet garden" when feel was added to meaning, not multiplied).
    garden, bucket = (taken_in(system, film(tmp_path / f"{n}.mp4", [("smptebars", 12)])) for n in ("garden", "bucket"))
    system.index.upsert(garden, "segment", 0.0, 8.0, "khu vườn yên bình với hoa vàng cam", data=MOVING)
    system.index.upsert(bucket, "segment", 0.0, 8.0, "người đàn ông khuấy đất trong thùng nhựa", data=STILL)
    picked = system.sourcing.find("khu vườn yên bình với hoa vàng cam chữa lành", 4.0, illustration={"mode": "associative", "evokes": "chữa lành", "feel": feel})
    assert picked[0]["asset_id"] == garden

    # The clip match of a script: an associative line is searched by its brief, so the stretch that says its words is not taken.
    project = system.planning.create_project("Biển")
    system.projects.save_script(project, [{"text": "Có những ngày mình chỉ cần chậm lại.", "brief": "sóng biển rút trên cát vắng",
                                           "illustration": {"mode": "associative", "evokes": "chậm lại", "feel": feel}}])
    script = system.projects.current_script(project)
    system.sourcing.start_match(script["script_id"])
    drain(system)
    sel = system.projects.selection(script["shots"][0].shot_id)
    assert sel.asset_id == still and sel.asset_id != literal

    # Laid out on a storyboard, the line keeps how it is illustrated and is searched the same way.
    system.storyboard_planner.from_script(project)
    shot = system.storyboard.shots(project)[0]
    assert shot.spec["illustration"]["mode"] == "associative" and shot.spec["source"]["query"] == "sóng biển rút trên cát vắng chậm lại"


def test_the_judge_is_asked_what_an_evoking_line_should_call_up(tmp_path):
    model = FakeModel()
    seen = []
    plain = model.submit
    model.submit = lambda r: (seen.append(r.params.get("prompt", "")) if r.params.get("task") == "judge" else None) or plain(r)
    system = build(tmp_path / "data", model=model, voice=FakeVoice(), segment_seconds=15.0)
    clip = taken_in(system, film(tmp_path / "a.mp4", [("testsrc2", 12)]))
    system.index.upsert(clip, "segment", 0.0, 8.0, "sóng biển rút trên cát vắng", data={**STILL, "frames": [str(tmp_path / "a.mp4")]})
    project = system.planning.create_project("Biển")
    system.projects.save_script(project, [{"text": "Có những ngày mình chỉ cần chậm lại.", "brief": "sóng biển rút trên cát", "illustration": {"mode": "associative", "evokes": "chậm lại"}}])
    system.sourcing.start_match(system.projects.current_script(project)["script_id"])
    drain(system)
    assert seen and all("gợi ý \"chậm lại\"" in p and "không cần thấy đúng điều câu nói" in p for p in seen)


def test_how_a_project_illustrates_comes_from_its_channel_then_its_template(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), voice=FakeVoice())
    import json
    assert illustration_style(system, {}) == "mixed"
    system.orch.set_setting("templates", json.dumps([{"name": "Tài liệu", "format": "landscape", "voice": "", "music_gain": 0.3, "auto_accept": False, "illustration": "direct"}]))
    system.orch.set_setting("channels", json.dumps([{"name": "Thơ", "illustration": "associative"}, {"name": "Tin", "illustration": None}]))
    assert illustration_style(system, {"template": "Tài liệu"}) == "direct"
    assert illustration_style(system, {"template": "Tài liệu", "channel": "Thơ"}) == "associative"
    assert illustration_style(system, {"template": "Tài liệu", "channel": "Tin"}) == "direct"
