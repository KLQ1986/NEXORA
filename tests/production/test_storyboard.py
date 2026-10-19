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
    assert system.storyboard_planner.resolve(project, "S2").shot_id == system.storyboard_planner.resolve(project, "sc2").shot_id   # the first codes still name their shot
    assert [s["code"] for s in view["shots"]] == ["SC1", "SC2", "SC3"] and view["shots"][1]["spec"]["line"] == "Chú Tư đi một vòng quanh vườn."
    assert len(view["scenes"]) == 1 and view["scenes"][0]["script"].startswith("Mỗi sáng")
    ops = [{"op": "retime", "shot": "SC2", "seconds": 4}, {"op": "set", "shot": "SC1", "field": "framing.lens", "value": "85mm"},
           {"op": "insert", "after": "SC2", "spec": {"intent": "Cận tay bổ dừa", "duration": 3, "source": "footage"}},
           {"op": "set", "shot": "SC1", "field": "nope", "value": 1}, {"op": "delete", "shot": "SC9"}]
    preview = client.post(f"/api/v1/projects/{project}/storyboard/ops", json={"ops": ops, "preview": True}).json()
    assert [d["title"] for d in preview["diff"]] == ["SC2 · thời lượng", "SC1 · ống kính", "chèn sau SC2"] and len(preview["problems"]) == 2
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
    after = client.post(f"/api/v1/projects/{project}/storyboard/ops", json={"ops": [{"op": "split", "shot": "SC4"}, {"op": "move", "shot": "SC3", "after": "SC1"}]}).json()["storyboard"]["shots"]
    assert [s["spec"]["intent"] for s in after][1] == "Cận tay bổ dừa" and len(after) == 5
    merged = client.post(f"/api/v1/projects/{project}/storyboard/ops", json={"ops": [{"op": "merge", "shot": "SC4", "with": "SC5"}]}).json()["storyboard"]["shots"]
    assert len(merged) == 4


def test_continuity_is_read_at_every_cut_and_a_camera_across_the_axis_is_shown_and_flipped(tmp_path):
    system, _, client = _system(tmp_path)
    project = _project(system, ["Một.", "Hai.", "Ba."])
    client.post(f"/api/v1/projects/{project}/storyboard/from-script")
    ops = [{"op": "set", "shot": "SC1", "field": "direction", "value": "phải"}, {"op": "set", "shot": "SC2", "field": "direction", "value": "trái"},
           {"op": "set", "shot": "SC1", "field": "continuity.entities", "value": ["Chú Tư", "Áo bà ba"]},
           {"op": "set", "shot": "SC2", "field": "continuity.entities", "value": ["Chú Tư"]},
           {"op": "set", "shot": "SC2", "field": "framing.size", "value": "cận"}, {"op": "set", "shot": "SC3", "field": "framing.size", "value": "cận"},
           {"op": "set", "shot": "SC2", "field": "continuity.time_of_day", "value": "sáng"}, {"op": "set", "shot": "SC3", "field": "continuity.time_of_day", "value": "hoàng hôn"},
           {"op": "flip_camera", "shot": "SC3"}]
    view = client.post(f"/api/v1/projects/{project}/storyboard/ops", json={"ops": ops}).json()["storyboard"]
    s12, s23 = view["seams"]
    by = lambda seam: {c["key"]: c["st"] for c in seam["checks"]}
    assert by(s12)["direction"] == "fail" and by(s12)["look"] == "warn" and s12["worst"] == "fail"
    assert by(s23)["jump"] == "warn" and by(s23)["colour"] == "warn"
    assert any(f["ops"][0]["op"] == "flip_camera" for f in s12["fixes"])
    plan = view["plans"][0]
    assert plan["crossed"] == [view["shots"][2]["shot_id"]]                      # SC3's camera flipped to the far side
    fixed = client.post(f"/api/v1/projects/{project}/storyboard/ops", json={"ops": next(f for f in s12["fixes"] if f["ops"][0]["op"] == "flip_camera")["ops"]}).json()["storyboard"]
    assert {c["key"]: c["st"] for c in fixed["seams"][0]["checks"]}["direction"] == "pass"


def test_the_director_finds_footage_measures_it_and_brings_what_it_cannot_accept_to_you(tmp_path):
    system, _, client = _system(tmp_path)
    taken_in(system, film(tmp_path / "market.mp4", [("testsrc2", 4), ("smptebars", 4)]))
    project = _project(system, ["Chợ rau củ buổi sáng.", "Một con tàu vũ trụ rời bệ phóng.", "Người ta pha cà phê."])
    client.post(f"/api/v1/projects/{project}/storyboard/from-script")
    client.post(f"/api/v1/projects/{project}/storyboard/ops", json={"ops": [{"op": "set", "shot": "SC2", "field": "source.policy", "value": "generate"},
                                                                           {"op": "add_criterion", "shot": "SC1", "criterion": {"check": "shot_size", "value": "trung"}}]})
    client.patch(f"/api/v1/projects/{project}/storyboard/shared", json={"autonomy": 2})
    run = client.post(f"/api/v1/projects/{project}/storyboard/run", json={}).json()
    shots = {s["code"]: s for s in run["storyboard"]["shots"]}
    s1 = shots["SC1"]
    assert s1["assignment"]["kind"] == "footage" and s1["frame_url"].startswith("/api/v1/vq/subjects/")
    checks = {c["check"]: c for c in s1["checks"]}
    assert checks["duration"]["st"] == "pass" and checks["shot_size"]["st"] == "unmeasured"   # a field not released is never passed
    assert s1["state"] == "needs"                                                             # so it waits for you, even at level 2
    assert shots["SC2"]["state"] == "needs" and shots["SC2"]["checks"][0]["check"] == "keyframe"
    accepted = client.post(f"/api/v1/projects/{project}/storyboard/shots/{s1['shot_id']}/decide", json={"accept": True}).json()
    assert next(s for s in accepted["shots"] if s["code"] == "SC1")["state"] == "accepted"
    client.post(f"/api/v1/projects/{project}/storyboard/ops", json={"ops": [{"op": "set", "shot": "SC2", "field": "generation.provider", "value": "image_gen.pollinations"}]})
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
    model.answers["storyboard_ops"] = {"tra_loi": "Rút SC2 và đổi góc SC3.", "ops": [{"op": "retime", "shot": "SC2", "seconds": 2},
                                                                                   {"op": "set", "shot": "SC3", "field": "framing.angle", "value": "thấp"},
                                                                                   {"op": "explode", "shot": "SC2"},
                                                                                   {"op": "set", "shot": "SC2", "field": "framing.angle", "value": "góc ngang mắt"}]}
    m = client.post(f"/api/v1/projects/{project}/storyboard/say", json={"text": "SC2 ngắn lại", "scope": "shot", "shot": s2}).json()["message"]
    assert [d["title"] for d in m["proposal"]["diff"]] == ["SC2 · thời lượng"]                 # SC3 is out of the shot's scope; "explode" is no op
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


def test_a_character_is_checked_against_the_bible_s_reference_and_without_a_face_it_is_not_passed(tmp_path):
    import json
    system, _, client = _system(tmp_path)
    market = taken_in(system, film(tmp_path / "market.mp4", [("testsrc2", 4)]))
    project = _project(system, ["Chợ rau củ buổi sáng."])
    system.projects.update_project(project, bible=json.dumps([{"name": "Chú Tư", "kind": "character", "asset_id": market}, {"name": "Vườn", "kind": "place"}]))
    client.post(f"/api/v1/projects/{project}/storyboard/from-script")
    client.post(f"/api/v1/projects/{project}/storyboard/ops", json={"ops": [{"op": "set", "shot": "SC1", "field": "continuity.entities", "value": ["Chú Tư", "Vườn"]},
                                                                           {"op": "add_criterion", "shot": "SC1", "criterion": {"check": "character"}}]})
    character = lambda: next(c for c in client.get(f"/api/v1/projects/{project}/storyboard").json()["shots"][0]["checks"] if c["check"] == "character")
    asked = []
    system.director._likeness = lambda a, ref: asked.append(ref) or 0.94
    client.post(f"/api/v1/projects/{project}/storyboard/run", json={})
    assert character()["st"] == "pass" and character()["value"] == "0.94" and asked == [market]       # the place has no likeness to take
    system.director._likeness = lambda a, ref: 0.86
    client.post(f"/api/v1/projects/{project}/storyboard/run", json={})
    assert character()["st"] == "fail"
    system.director._likeness = lambda a, ref: None                                                  # no face in the picture
    client.post(f"/api/v1/projects/{project}/storyboard/run", json={})
    assert character()["st"] == "unmeasured" and character()["value"] == "không thấy khuôn mặt"


def test_the_storyboard_is_where_pictures_are_chosen_ordered_treated_and_approved_for_the_cut(tmp_path):
    """The clip step folded into the storyboard: cards moved by hand, another option used or made a shot of its own, "no clip
    fits" remembered, a clip trimmed and treated, and the approval that writes all of it to the cut."""
    system, _, client = _system(tmp_path)
    for name, src in (("market.mp4", "testsrc2"), ("bars.mp4", "smptebars"), ("rgb.mp4", "rgbtestsrc")):
        taken_in(system, film(tmp_path / name, [(src, 4)]))
    project = _project(system, ["Chợ rau củ buổi sáng.", "Người ta pha cà phê.", "Chiều xuống."])
    url = f"/api/v1/projects/{project}/storyboard"
    client.post(f"{url}/from-script")
    # Moved by hand: SC3 dropped on SC1 goes before it; SC1 sent to the end of the scene.
    view = client.get(url).json()
    s1, s2, s3 = (s["shot_id"] for s in view["shots"])
    scene = view["scenes"][0]["scene_id"]
    order = lambda v: [s["shot_id"] for s in v["shots"]]
    v = client.post(f"{url}/ops", json={"ops": [{"op": "move", "shot": s3, "before": s1}]}).json()["storyboard"]
    assert order(v) == [s3, s1, s2]
    v = client.post(f"{url}/ops", json={"ops": [{"op": "move", "shot": s3, "scene": scene}]}).json()["storyboard"]
    assert order(v) == [s1, s2, s3]
    # The Director picks with the clip step's search; the shot's other options are counted apart from its picture.
    v = client.post(f"{url}/run", json={}).json()["storyboard"]
    first = v["shots"][0]
    others = first["assignment"]["others"]
    assert first["assignment"]["asset_id"] and others and all((o["asset_id"], o["t_in"]) != (first["assignment"]["asset_id"], first["assignment"]["t_in"]) for o in others)
    was, chosen = first["assignment"], others[0]
    v = client.post(f"{url}/shots/{s1}/use", json={"candidate": 0}).json()
    now = v["shots"][0]["assignment"]
    assert (now["asset_id"], now["t_in"]) == (chosen["asset_id"], chosen["t_in"]) and any((o["asset_id"], o["t_in"]) == (was["asset_id"], was["t_in"]) for o in now["others"])
    told = system.projects.feedback("Chợ rau củ buổi sáng.")
    assert told.get(chosen["moment_id"]) == "accepted" and told.get(was["moment_id"]) == "rejected"   # the clip step will know it too
    # Another option made a shot of its own, right after, with that clip and its length.
    extra = now["others"][0]
    v = client.post(f"{url}/shots/{s1}/add-clip", json={"candidate": 0}).json()
    new = v["shots"][1]
    assert len(v["shots"]) == 4 and new["assignment"]["asset_id"] == extra["asset_id"] and new["spec"]["source"]["policy"] == "footage"
    assert abs(new["spec"]["duration"]["target"] - (extra["t_out"] - extra["t_in"])) < 0.05
    # Trimmed and treated; a wrong answer is refused.
    v = client.post(f"{url}/shots/{s1}/trim", json={"t_in": 0.5, "t_out": 2.5}).json()
    assert (v["shots"][0]["assignment"]["t_in"], v["shots"][0]["assignment"]["t_out"]) == (0.5, 2.5)
    v = client.patch(f"{url}/shots/{s1}/treatment", json={"speed": 0.6, "stabilise": True}).json()
    assert v["shots"][0]["assignment"]["treat"] == {"speed": 0.5, "stabilise": True}
    assert client.post(f"{url}/shots/{s1}/use", json={"candidate": 99}).status_code == 409
    # "No clip fits": the shot waits without a picture.
    v = client.post(f"{url}/shots/{s3}/none-fits").json()
    gone = next(s for s in v["shots"] if s["shot_id"] == s3)
    assert gone["assignment"] is None and gone["state"] == "needs"
    # Approved: the script carries every picture, accepted, its options and treatment; the clips count as approved.
    done = client.post(f"{url}/approve").json()
    assert done["pictured"] == 2 and done["missing"] == 2                 # nothing in the footage shows coffee; SC3 was turned down
    script = system.projects.script(done["script_id"])
    assert script["match_approved"]
    sel = system.projects.selection(script["shots"][0].shot_id)
    assert sel.status == "accepted" and (sel.t_in, sel.t_out) == (0.5, 2.5) and sel.alternates and sel.extras["speed"] == 0.5 and sel.extras["stabilise"]


def test_a_cards_words_edited_in_place_change_its_line_and_the_intent_that_repeated_it(tmp_path):
    # The card's own editor sends the line and, when the intent only repeated it (a shot made from a script line without a
    # brief), the intent too, in one operation: one new version, both changed, nothing else touched.
    system, _, client = _system(tmp_path)
    project = _project(system, ["Mỗi sáng bắt đầu từ hàng dừa."])
    client.post(f"/api/v1/projects/{project}/storyboard/from-script")
    before = system.storyboard.shots(project)[0]
    assert before.spec["line"] == before.spec["intent"] == "Mỗi sáng bắt đầu từ hàng dừa."
    said = "Mỗi sáng của tôi bắt đầu từ hàng dừa sau nhà."
    view = client.post(f"/api/v1/projects/{project}/storyboard/ops", json={"ops": [{"op": "set", "shot": "SC1", "field": "line", "value": said},
                                                                                {"op": "set", "shot": "SC1", "field": "intent", "value": said}], "note": "sửa lời thoại"}).json()
    after = system.storyboard.shots(project)[0]
    assert after.spec["line"] == after.spec["intent"] == said and after.version == before.version + 1
    assert after.spec["framing"] == before.spec["framing"] and after.spec["duration"] == before.spec["duration"]
    assert view["storyboard"]["shots"][0]["spec"]["line"] == said


def test_a_picture_that_does_not_show_the_line_is_taken_off_and_another_found_in_the_library_put_in_its_place(tmp_path):
    system, _, client = _system(tmp_path)
    for name, src in (("market.mp4", "testsrc2"), ("bars.mp4", "smptebars")):
        taken_in(system, film(tmp_path / name, [(src, 4)]))
    project = _project(system, ["Chợ rau củ buổi sáng.", "Chiều xuống."])
    url = f"/api/v1/projects/{project}/storyboard"
    client.post(f"{url}/from-script")
    v = client.post(f"{url}/run", json={}).json()["storyboard"]
    s1 = v["shots"][0]["shot_id"]
    was, others = v["shots"][0]["assignment"], v["shots"][0]["assignment"]["others"]
    # Taken off: no picture, turned down for these words, its other options kept to choose from.
    v = client.post(f"{url}/shots/{s1}/remove").json()
    gone = v["shots"][0]
    assert gone["state"] == "needs" and not gone["assignment"].get("asset_id")
    assert [(o["asset_id"], o["t_in"]) for o in gone["assignment"]["others"]] == [(o["asset_id"], o["t_in"]) for o in others]
    assert system.projects.feedback("Chợ rau củ buổi sáng.").get(was["moment_id"]) == "rejected"
    assert client.post(f"{url}/shots/{s1}/remove").status_code == 409          # nothing left to take off
    # Any stretch found in the Library put in its place, as long as the shot, and remembered as chosen.
    hit = next(h for h in client.get("/api/v1/library/search", params={"q": "chợ"}).json()["hits"] if h["level"] != "video")
    v = client.post(f"{url}/shots/{s1}/use-moment", json={"moment_id": hit["moment_id"]}).json()
    now = v["shots"][0]["assignment"]
    assert (now["asset_id"], now["moment_id"], now["t_in"]) == (hit["asset_id"], hit["moment_id"], round(hit["t_start"], 2))
    assert now["t_out"] - now["t_in"] <= v["shots"][0]["spec"]["duration"]["target"] + 0.01
    assert system.projects.feedback("Chợ rau củ buổi sáng.").get(hit["moment_id"]) == "accepted"
    assert client.post(f"{url}/shots/{s1}/use-moment", json={"moment_id": "nope"}).status_code == 409
