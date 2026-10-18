"""A script written from what people say in the footage: their sentences (fragments a short pause apart joined, too short ones
left out) numbered for the model, which picks quotes by number, so their words are never retyped or invented, and writes the
narration between them; saved as written, every quote keeps its stretch and its own sound."""
from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import build

from tests.fakes import FakeModel, FakeVoice
from tests.library.test_analysis import film, taken_in


def _setup(tmp_path, answer):
    model = FakeModel()
    asked = []
    model.answers["draft_speech"] = lambda r: asked.append(r.params["prompt"]) or (answer(r) if callable(answer) else answer)
    system = build(tmp_path / "data", model=model, voice=FakeVoice(), segment_seconds=15.0)
    client = TestClient(create_app(system))
    clip = taken_in(system, film(tmp_path / "trip.mp4", [("testsrc2", 20)]))
    system.index.upsert(clip, "speech", 1.0, 2.0, "em đi đâu")                          # joined with the next: 0.5 s apart
    system.index.upsert(clip, "speech", 2.5, 4.0, "anh đi theo đó")
    system.index.upsert(clip, "speech", 8.0, 8.4, "Hill")                                # too short to quote
    system.index.upsert(clip, "speech", 10.0, 13.0, "chỗ này đẹp quá trời luôn", data={"speaker": 1})     # speakers are numbered in real speech
    quiet = taken_in(system, film(tmp_path / "quiet.mp4", [("smptebars", 6)]))
    project = system.planning.create_project("Đi chơi")
    return system, client, clip, quiet, project, asked


def test_the_sentences_to_quote_and_the_recordings_that_have_them(tmp_path):
    system, client, clip, quiet, project, asked = _setup(tmp_path, {})
    said = system.planning.speech_sentences([clip])
    assert [s["text"] for s in said] == ["em đi đâu anh đi theo đó", "chỗ này đẹp quá trời luôn"]
    assert (said[0]["t_in"], said[0]["t_out"]) == (1.0, 4.0)
    rows = client.get("/api/v1/speech/recordings").json()["recordings"]
    assert [r["asset_id"] for r in rows] == [clip] and rows[0]["sentences"] == 2                 # a recording with nothing said is not offered


def test_a_script_from_speech_quotes_by_number_and_keeps_each_stretch(tmp_path):
    answer = {"cau": [{"loai": "dan", "cau": "Bữa nay hai vợ chồng đi chơi biển.", "kieu": "truc_tiep", "hinh": "hai người trên bãi biển"},
                      {"loai": "trich", "so": 1},
                      {"loai": "trich", "so": 1},                                              # quoted twice: once only
                      {"loai": "trich", "so": 9},                                              # no such sentence: dropped
                      {"loai": "trich", "so": 2, "cau": "chỗ này đẹp lắm"},                    # retyped words are ignored: the transcript's are used
                      {"loai": "dan", "cau": "Chỗ này đẹp quá trời luôn, ai cũng mê."},              # only says the quote again: dropped
                      {"loai": "dan", "cau": "Rồi mình về, lòng nhẹ tênh.", "kieu": "lien_tuong", "goi": "về nhà"}]}
    system, client, clip, quiet, project, asked = _setup(tmp_path, answer)
    out = client.post(f"/api/v1/projects/{project}/draft-from-speech", json={"asset_ids": [clip], "goal": "chuyến đi chơi", "lines": 6})
    lines = out.json()["lines"]
    assert lines == ["Bữa nay hai vợ chồng đi chơi biển.", "> em đi đâu anh đi theo đó", "> chỗ này đẹp quá trời luôn", "Rồi mình về, lòng nhẹ tênh."]
    prompt = asked[-1]
    assert "[1] (trip.mp4 0:01) em đi đâu anh đi theo đó" in prompt and "[2] (trip.mp4 0:10, người nói 1) chỗ này đẹp quá trời luôn" in prompt and "Hill" not in prompt
    assert "Mục tiêu: chuyến đi chơi." in prompt and "miền Nam" in prompt                       # the goal and the house voice
    assert system.projects.current_script(project) is None                                     # nothing saved yet

    # Saved from the editor as written, each quote has its stretch and its own sound; the narration keeps its notes.
    client.put(f"/api/v1/projects/{project}/script", json={"lines": lines})
    shots = system.projects.current_script(project)["shots"]
    assert [s.quote is not None for s in shots] == [False, True, True, False]
    sel = system.projects.selection(shots[1].shot_id)
    assert (sel.status, sel.asset_id, sel.t_in, sel.t_out, sel.extras.get("live_sound")) == ("accepted", clip, 1.0, 4.0, True)
    assert shots[0].brief == "hai người trên bãi biển" and shots[3].illustration == {"mode": "associative", "evokes": "về nhà"}


def test_refusals(tmp_path):
    system, client, clip, quiet, project, asked = _setup(tmp_path, {"cau": [{"loai": "dan", "cau": "Chỉ có lời dẫn."}]})
    url = f"/api/v1/projects/{project}/draft-from-speech"
    assert client.post(url, json={"asset_ids": []}).status_code == 422
    assert client.post(url, json={"asset_ids": [quiet]}).status_code == 422 and not asked             # nothing said: the model is not asked
    out = client.post(url, json={"asset_ids": [clip]})
    assert out.status_code == 422 and "không chọn được câu nói" in out.json()["detail"]             # a script with no quote is not one from speech
