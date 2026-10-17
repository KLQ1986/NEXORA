"""The project's storyboard: shot specs as contracts, typed operations and their versions, continuity at the cuts and on the
camera plan, the Director's pass over the library, the conversation, and the writing into the project's script."""
from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import build
from nexora.modules.planning import storyboard as SB

from tests.fakes import FakeModel
from tests.library.test_analysis import film, taken_in


def _system(tmp_path):
    model = FakeModel()
    system = build(tmp_path / "data", model=model, segment_seconds=15.0)
    return system, model, TestClient(create_app(system))


def _project(system, lines):
    project = system.projects.create_project("Vườn dừa")
    system.projects.save_script(project, lines)
    return project


def test_a_spec_is_whole_and_bounded_whatever_it_was_given():
    s = SB.normalise({"intent": "Chú Tư đi trong vườn", "duration": 900, "framing": {"size": "CẬN", "lens": "999mm"}, "source": "ai", "direction": "lên"})
    assert s["duration"]["target"] == 120 and s["framing"]["size"] == "cận" and s["framing"]["lens"] == "35mm"
    assert s["source"]["policy"] == "generate" and s["direction"] == "" and s["source"]["query"] == "Chú Tư đi trong vườn"
    assert [c["check"] for c in s["criteria"]] == ["match", "duration"]                      # footage only is held to steadiness
    assert SB.normalise({"intent": "x", "source": "footage"})["criteria"][-1]["check"] == "no_shake"
    assert SB.criterion({"check": "made_up"}) is None and SB.criterion({"check": "human", "text": "cảm giác bình yên"})["by"] == "human"
    # A model writes the vocabulary's words inside its own ("góc thấp"): the word is found, the rest is not guessed.
    assert SB.normalise({"framing": {"angle": "góc thấp", "size": "cận cảnh", "move": "lắc lư"}})["framing"] == {"size": "cận", "angle": "thấp", "move": "đứng yên", "lens": "35mm"}


def test_a_storyboard_from_the_script_and_operations_that_make_versions_and_can_be_undone(tmp_path):
    system, _, client = _system(tmp_path)
    project = _project(system, ["Mỗi sáng bắt đầu từ hàng dừa.", "Chú Tư đi một vòng quanh vườn.", "Chiều xuống, ghe về."])
    view = client.post(f"/api/v1/projects/{project}/storyboard/from-script").json()
    assert [s["code"] for s in view["shots"]] == ["S1", "S2", "S3"] and view["shots"][1]["spec"]["line"] == "Chú Tư đi một vòng quanh vườn."
    assert len(view["scenes"]) == 1 and view["scenes"][0]["script"].startswith("Mỗi sáng")
    ops = [{"op": "retime", "shot": "S2", "seconds": 4}, {"op": "set", "shot": "S1", "field": "framing.lens", "value": "85mm"},
           {"op": "insert", "after": "S2", "spec": {"intent": "Cận tay bổ dừa", "duration": 3, "source": "footage"}},
           {"op": "set", "shot": "S1", "field": "nope", "value": 1}, {"op": "delete", "shot": "S9"}]
    preview = client.post(f"/api/v1/projects/{project}/storyboard/ops", json={"ops": ops, "preview": True}).json()
    assert [d["title"] for d in preview["diff"]] == ["S2 · thời lượng", "S1 · ống kính", "chèn sau S2"] and len(preview["problems"]) == 2
    done = client.post(f"/api/v1/projects/{project}/storyboard/ops", json={"ops": ops}).json()
    shots = done["storyboard"]["shots"]
    assert len(done["done"]) == 3 and [s["spec"]["intent"] for s in shots][2] == "Cận tay bổ dừa"
    s1 = shots[0]
    assert s1["version"] == 2 and s1["spec"]["framing"]["lens"] == "85mm"
    back = client.post(f"/api/v1/projects/{project}/storyboard/shots/{s1['shot_id']}/revert", json={"version": 1}).json()
    assert back["shots"][0]["version"] == 3 and back["shots"][0]["spec"]["framing"]["lens"] == "35mm"
    versions = client.get(f"/api/v1/projects/{project}/storyboard/shots/{s1['shot_id']}/versions").json()["versions"]
    assert [v["version"] for v in versions] == [3, 2, 1] and versions[0]["note"] == "quay lại v1"
    # split and merge keep the time; move puts a shot elsewhere
    after = client.post(f"/api/v1/projects/{project}/storyboard/ops", json={"ops": [{"op": "split", "shot": "S4"}, {"op": "move", "shot": "S3", "after": "S1"}]}).json()["storyboard"]["shots"]
    assert [s["spec"]["intent"] for s in after][1] == "Cận tay bổ dừa" and len(after) == 5
    merged = client.post(f"/api/v1/projects/{project}/storyboard/ops", json={"ops": [{"op": "merge", "shot": "S4", "with": "S5"}]}).json()["storyboard"]["shots"]
    assert len(merged) == 4


def test_continuity_is_read_at_every_cut_and_a_camera_across_the_axis_is_shown_and_flipped(tmp_path):
    system, _, client = _system(tmp_path)
    project = _project(system, ["Một.", "Hai.", "Ba."])
    client.post(f"/api/v1/projects/{project}/storyboard/from-script")
    ops = [{"op": "set", "shot": "S1", "field": "direction", "value": "phải"}, {"op": "set", "shot": "S2", "field": "direction", "value": "trái"},
           {"op": "set", "shot": "S1", "field": "continuity.entities", "value": ["Chú Tư", "Áo bà ba"]},
           {"op": "set", "shot": "S2", "field": "continuity.entities", "value": ["Chú Tư"]},
           {"op": "set", "shot": "S2", "field": "framing.size", "value": "cận"}, {"op": "set", "shot": "S3", "field": "framing.size", "value": "cận"},
           {"op": "set", "shot": "S2", "field": "continuity.time_of_day", "value": "sáng"}, {"op": "set", "shot": "S3", "field": "continuity.time_of_day", "value": "hoàng hôn"},
           {"op": "flip_camera", "shot": "S3"}]
    view = client.post(f"/api/v1/projects/{project}/storyboard/ops", json={"ops": ops}).json()["storyboard"]
    s12, s23 = view["seams"]
    by = lambda seam: {c["key"]: c["st"] for c in seam["checks"]}
    assert by(s12)["direction"] == "fail" and by(s12)["look"] == "warn" and s12["worst"] == "fail"
    assert by(s23)["jump"] == "warn" and by(s23)["colour"] == "warn"
    assert any(f["ops"][0]["op"] == "flip_camera" for f in s12["fixes"])
    plan = view["plans"][0]
    assert plan["crossed"] == [view["shots"][2]["shot_id"]]                      # S3's camera flipped to the far side
    fixed = client.post(f"/api/v1/projects/{project}/storyboard/ops", json={"ops": next(f for f in s12["fixes"] if f["ops"][0]["op"] == "flip_camera")["ops"]}).json()["storyboard"]
    assert {c["key"]: c["st"] for c in fixed["seams"][0]["checks"]}["direction"] == "pass"


def test_the_director_finds_footage_measures_it_and_brings_what_it_cannot_accept_to_you(tmp_path):
    system, _, client = _system(tmp_path)
    taken_in(system, film(tmp_path / "market.mp4", [("testsrc2", 4), ("smptebars", 4)]))
    project = _project(system, ["Chợ rau củ buổi sáng.", "Một con tàu vũ trụ rời bệ phóng.", "Người ta pha cà phê."])
    client.post(f"/api/v1/projects/{project}/storyboard/from-script")
    client.post(f"/api/v1/projects/{project}/storyboard/ops", json={"ops": [{"op": "set", "shot": "S2", "field": "source.policy", "value": "generate"},
                                                                           {"op": "add_criterion", "shot": "S1", "criterion": {"check": "shot_size", "value": "trung"}}]})
    client.patch(f"/api/v1/projects/{project}/storyboard/shared", json={"autonomy": 2})
    run = client.post(f"/api/v1/projects/{project}/storyboard/run", json={}).json()
    shots = {s["code"]: s for s in run["storyboard"]["shots"]}
    s1 = shots["S1"]
    assert s1["assignment"]["kind"] == "footage" and s1["frame_url"].startswith("/api/v1/vq/subjects/")
    checks = {c["check"]: c for c in s1["checks"]}
    assert checks["duration"]["st"] == "pass" and checks["shot_size"]["st"] == "unmeasured"   # a field not released is never passed
    assert s1["state"] == "needs"                                                             # so it waits for you, even at level 2
    assert shots["S2"]["state"] == "needs" and shots["S2"]["checks"][0]["check"] == "keyframe"
    accepted = client.post(f"/api/v1/projects/{project}/storyboard/shots/{s1['shot_id']}/decide", json={"accept": True}).json()
    assert next(s for s in accepted["shots"] if s["code"] == "S1")["state"] == "accepted"
    client.post(f"/api/v1/projects/{project}/storyboard/ops", json={"ops": [{"op": "set", "shot": "S2", "field": "generation.provider", "value": "image_gen.pollinations"}]})
    # Written to the script: a line per shot, the accepted picture as its selection, the generated one as a gap to make.
    synced = client.post(f"/api/v1/projects/{project}/storyboard/sync").json()
    lines = system.projects.script(synced["script_id"])["shots"]
    assert [l.text for l in lines] == ["Chợ rau củ buổi sáng.", "Một con tàu vũ trụ rời bệ phóng.", "Người ta pha cà phê."]
    assert system.projects.selection(lines[0].shot_id).status == "accepted" and system.projects.selection(lines[1].shot_id).status == "gap"
    assert lines[0].target_seconds == s1["spec"]["duration"]["target"] and lines[1].gen.get("subject")
    assert lines[1].gen.get("provider_image") == "image_gen.pollinations" and "provider_video" not in lines[1].gen     # empty choices are not written


def test_the_conversation_proposes_operations_within_its_scope_and_an_idea_becomes_a_storyboard(tmp_path):
    system, model, client = _system(tmp_path)
    project = _project(system, ["Một.", "Hai.", "Ba."])
    view = client.post(f"/api/v1/projects/{project}/storyboard/from-script").json()
    s2 = view["shots"][1]["shot_id"]
    model.answers["storyboard_ops"] = {"tra_loi": "Rút S2 và đổi góc S3.", "ops": [{"op": "retime", "shot": "S2", "seconds": 2},
                                                                                   {"op": "set", "shot": "S3", "field": "framing.angle", "value": "thấp"},
                                                                                   {"op": "explode", "shot": "S2"},
                                                                                   {"op": "set", "shot": "S2", "field": "framing.angle", "value": "góc ngang mắt"}]}
    m = client.post(f"/api/v1/projects/{project}/storyboard/say", json={"text": "S2 ngắn lại", "scope": "shot", "shot": s2}).json()["message"]
    assert [d["title"] for d in m["proposal"]["diff"]] == ["S2 · thời lượng"]                 # S3 is out of the shot's scope; "explode" is no op
    done = client.post(f"/api/v1/projects/{project}/storyboard/messages/{m['message_id']}/apply").json()
    assert done["storyboard"]["shots"][1]["spec"]["duration"]["target"] == 2
    assert client.post(f"/api/v1/projects/{project}/storyboard/messages/{m['message_id']}/apply").status_code == 404     # settled once
    model.answers["storyboard_idea"] = {"chung": {"bang_mau": [{"ten": "Xanh lá dừa", "hex": "#3f6b4f"}, {"ten": "sai", "hex": "green"}], "van_tay": "vườn dừa nhiều tầng tán",
                                                  "giong_dieu": ["Bình yên"], "phong_cach": ["Máy chậm"]},
                                        "canh": [{"tieu_de": "Mở", "muc_dich": "Đặt nơi chốn", "shot": [{"muc_tieu": "Vườn dừa lúc bình minh", "loi": "Mỗi sáng…", "giay": 5, "nguon": "ai", "co_canh": "toàn cảnh"},
                                                                                              {"muc_tieu": "", "giay": 3}]},
                                                 {"tieu_de": "Kết", "shot": [{"muc_tieu": "Ghe về lúc hoàng hôn", "giay": 6, "nguon": "stock", "huong": "phải"}]}]}
    m2 = client.post(f"/api/v1/projects/{project}/storyboard/idea", json={"idea": "Một ngày ở vườn dừa", "seconds": 30}).json()["message"]
    assert m2["proposal"]["summary"] == "2 cảnh, 2 shot, 11s"
    board = client.post(f"/api/v1/projects/{project}/storyboard/messages/{m2['message_id']}/apply").json()["storyboard"]
    assert [s["title"] for s in board["scenes"]] == ["Mở", "Kết"] and board["shots"][0]["spec"]["source"]["policy"] == "generate"
    assert board["shared"]["palette"] == [{"name": "Xanh lá dừa", "hex": "#3f6b4f"}] and board["shared"]["fingerprint"] == "vườn dừa nhiều tầng tán"
    assert [m["role"] for m in board["messages"]][-1] == "director"
