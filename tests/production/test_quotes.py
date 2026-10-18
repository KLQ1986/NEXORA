"""Quotes in a script: a "> " line is someone in the footage saying it, played with their own sound. One picked from what the
footage says keeps its stretch of the recording; one typed is looked for in the speech heard. Nothing rewrites someone's own
words. And every line is written in the house voice: natural, flowing, in the words of the South."""
from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import build

from tests.fakes import FakeModel, FakeVoice
from tests.library.test_analysis import drain, film, taken_in


def _setup(tmp_path, **kw):
    model = FakeModel()
    system = build(tmp_path / "data", model=model, voice=FakeVoice(), segment_seconds=15.0, judge=False, **kw)
    client = TestClient(create_app(system))
    clip = taken_in(system, film(tmp_path / "talk.mp4", [("testsrc2", 12)]))
    said = system.index.upsert(clip, "speech", 2.0, 6.5, "em đi đâu anh đi theo đó")
    project = system.planning.create_project("Đi chơi")
    return system, model, client, clip, said, project


def test_a_picked_quote_keeps_its_stretch_and_plays_its_own_sound(tmp_path):
    system, model, client, clip, said, project = _setup(tmp_path)
    hits = client.get("/api/v1/speech", params={"q": "đi theo"}).json()["hits"]
    assert hits[0]["moment_id"] == said and hits[0]["asset"]["name"] == "talk.mp4" and (hits[0]["t_start"], hits[0]["t_end"]) == (2.0, 6.5)
    assert client.get("/api/v1/speech").json()["hits"]                                         # with no words: everything heard
    ref = {"asset_id": clip, "moment_id": said, "t_in": 2.0, "t_out": 6.5}
    client.put(f"/api/v1/projects/{project}/script", json={"lines": ["Mình đi dạo một vòng nha.", {"text": "> em đi đâu anh đi theo đó", "quote": ref}]})
    narration, quote = system.projects.current_script(project)["shots"]
    assert narration.quote is None and quote.quote == ref and quote.text == "em đi đâu anh đi theo đó"
    sel = system.projects.selection(quote.shot_id)
    assert (sel.status, sel.asset_id, sel.t_in, sel.t_out, sel.extras.get("live_sound")) == ("accepted", clip, 2.0, 6.5, True)
    view = client.get(f"/api/v1/projects/{project}").json()
    assert view["shots"][1]["quote"] == ref

    # Saved again from the editor as plain text, the quote keeps its stretch; without its "> " it is narration again.
    client.put(f"/api/v1/projects/{project}/script", json={"lines": ["Mình đi dạo một vòng nha.", "> em đi đâu anh đi theo đó"]})
    again = system.projects.current_script(project)["shots"][1]
    assert again.quote == ref and system.projects.selection(again.shot_id).extras.get("live_sound")
    system.projects.save_script(project, ["Mình đi dạo một vòng nha.", "em đi đâu anh đi theo đó"])
    assert system.projects.current_script(project)["shots"][1].quote is None

    # The clip match never gives a picked quote another picture.
    client.put(f"/api/v1/projects/{project}/script", json={"lines": [{"text": "> em đi đâu anh đi theo đó", "quote": ref}]})
    script = system.projects.current_script(project)
    system.sourcing.start_match(script["script_id"])
    drain(system)
    sel = system.projects.selection(script["shots"][0].shot_id)
    assert (sel.status, sel.asset_id, sel.t_in) == ("accepted", clip, 2.0)


def test_a_typed_quote_is_looked_for_in_what_the_footage_says(tmp_path):
    system, model, client, clip, said, project = _setup(tmp_path)
    system.projects.save_script(project, ["> em đi đâu anh đi theo đó", "> câu này không ai nói cả bao giờ"])
    script = system.projects.current_script(project)
    assert [s.quote for s in script["shots"]] == [{}, {}]                                      # quotes not yet found
    system.sourcing.start_match(script["script_id"])
    drain(system)
    found, missing = (system.projects.selection(s.shot_id) for s in script["shots"])
    assert (found.status, found.asset_id, found.t_in, found.t_out, found.extras.get("live_sound")) == ("proposed", clip, 2.0, 6.5, True)
    assert system.projects.shot(script["shots"][0].shot_id).quote["moment_id"] == said
    assert missing.status == "gap" and "Trích lời" in missing.reason


def test_nothing_rewrites_someones_own_words(tmp_path):
    system, model, client, clip, said, project = _setup(tmp_path)
    ref = {"asset_id": clip, "moment_id": said, "t_in": 2.0, "t_out": 6.5}
    system.projects.save_script(project, ["Bữa nay trời đẹp.", {"text": "> em đi đâu anh đi theo đó", "quote": ref}])
    asked = []
    model.answers["critique"] = lambda r: asked.append(r.params["prompt"]) or {"nhan_xet": [{"cau": 2, "van_de": "câu cụt", "de_xuat": "viết lại"}]}
    system.planning.critique(project)
    assert "2. em đi đâu anh đi theo đó (trích lời)" in asked[-1]
    # Even when the model rewrites a quote, it comes back word for word with its stretch.
    model.answers["revise"] = {"cau": ["Bữa nay trời đẹp ghê.", "em đi đâu thì anh theo đó"]}
    system.planning.revise(project)
    first, second = system.projects.current_script(project)["shots"]
    assert first.text == "Bữa nay trời đẹp ghê." and second.text == "em đi đâu anh đi theo đó" and second.quote == ref
    # Writing with the model refuses a quote before asking it.
    out = client.post(f"/api/v1/projects/{project}/script/rewrite", json={"lines": ["Bữa nay trời đẹp ghê.", "> em đi đâu anh đi theo đó"], "first": 1, "last": 1, "action": "shorten"})
    assert out.status_code == 422 and "trích lời" in out.json()["detail"]


def test_a_quote_on_the_storyboard_is_accepted_with_its_own_sound_and_never_searched_again(tmp_path):
    system, model, client, clip, said, project = _setup(tmp_path)
    ref = {"asset_id": clip, "moment_id": said, "t_in": 2.0, "t_out": 6.5}
    system.projects.save_script(project, ["Mình đi dạo một vòng nha.", {"text": "> em đi đâu anh đi theo đó", "quote": ref}])
    system.storyboard_planner.from_script(project)
    shot = system.storyboard.shots(project)[1]
    assert shot.spec["quote"] and shot.state == "accepted" and shot.assignment["asset_id"] == clip and shot.assignment["treat"] == {"live_sound": True}
    system.director.run(project, only=shot.shot_id)                                             # asked to search it again: it keeps its words
    assert system.storyboard.shots(project)[1].assignment["t_in"] == 2.0
    client.post(f"/api/v1/projects/{project}/storyboard/approve")
    back = system.projects.current_script(project)["shots"][1]
    sel = system.projects.selection(back.shot_id)
    assert back.quote == ref and (sel.asset_id, sel.t_in, sel.extras.get("live_sound")) == (clip, 2.0, True)


def test_every_line_is_written_in_the_house_voice_unless_the_operator_sets_another(tmp_path):
    system, model, client, clip, said, project = _setup(tmp_path)
    asked = []
    model.answers["draft"] = lambda r: asked.append(r.params["prompt"]) or {"cau": [{"cau": "Bữa nay mình ghé biển nha.", "kieu": "truc_tiep"}]}
    system.planning.draft_script("biển", lines=1)
    assert "miền Nam" in asked[-1] and "liền mạch" in asked[-1] and "ly chứ không cốc" in asked[-1]
    system.orch.set_setting("writing_voice", "Giọng trang trọng, chuẩn mực. ")
    system.planning.draft_script("biển", lines=1)
    assert "Giọng trang trọng, chuẩn mực." in asked[-1] and "miền Nam" not in asked[-1]
