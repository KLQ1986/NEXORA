"""The Semantic Editing Copilot as a mode of the storyboard: decisions per sentence with reasons, evidence and confidence; fillers
and retakes measured, repetition measured by meaning, numbers and calls to action never cut without review; a length that
cannot hold every key point said instead of a point dropped; applied, the kept sentences become shots with their own sound."""
from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import build

from tests.fakes import FakeModel
from tests.library.test_analysis import film, taken_in

SAID = [
    ("Ờ.", 0.0, 0.6),
    ("Vườn dừa này là niềm tự hào của cả làng.", 0.8, 3.6),
    ("Mỗi cây cho chừng 120 trái một năm.", 3.8, 6.4),
    ("Mỗi cây cho chừng một trăm hai mươi trái một năm.", 6.6, 9.6),
    ("Người ta còn làm kẹo từ nước dừa.", 9.8, 12.2),
    ("Chiều về ghe chở dừa ra chợ nổi.", 12.4, 15.0),
    ("Hãy đăng ký kênh để xem tiếp nhé.", 15.2, 17.4),
]


def _words(text, a, b):
    ws = text.split()
    step = (b - a) / len(ws)
    return [{"text": w, "start": round(a + k * step, 2), "end": round(a + (k + 1) * step, 2), "p": 0.9} for k, w in enumerate(ws)]


def _setup(tmp_path):
    model = FakeModel()
    system = build(tmp_path / "data", model=model, segment_seconds=15.0)
    client = TestClient(create_app(system))
    asset_id = taken_in(system, film(tmp_path / "talk.mp4", [("testsrc2", 18)]))
    for text, a, b in SAID:
        system.index.upsert(asset_id, "speech", a, b, text, data={"words": _words(text, a, b)})
    project = system.projects.create_project("Vườn dừa")
    return system, model, client, asset_id, project


def test_the_copilot_proposes_a_cut_that_keeps_the_points_and_says_why(tmp_path):
    system, model, client, asset_id, project = _setup(tmp_path)
    url = f"/api/v1/projects/{project}/storyboard/copilot"
    assert client.get(f"{url}/sources").json()["sources"][0]["asset_id"] == asset_id
    model.answers["copilot_read"] = {"cau": [{"so": 2, "vai": "hook", "quan_trong": 0.9, "ly_do": "nêu chủ đề"},
                                             {"so": 3, "vai": "point", "quan_trong": 0.8, "ly_do": "số liệu sản lượng"},
                                             {"so": 4, "vai": "point", "quan_trong": 0.6, "ly_do": "nhắc lại sản lượng"},
                                             {"so": 5, "vai": "example", "quan_trong": 0.3, "ly_do": "ví dụ phụ"},
                                             {"so": 6, "vai": "point", "quan_trong": 0.7, "ly_do": "chợ nổi"},
                                             {"so": 7, "vai": "cta", "quan_trong": 0.5, "ly_do": "kêu gọi"}],
                                     "luan_diem": [{"ten": "Sản lượng", "cau": [3, 4]}, {"ten": "Chợ nổi", "cau": [6]}]}
    m = client.post(url, json={"assets": [asset_id], "presets": ["shorten", "repetition"], "target_seconds": 12}).json()["message"]
    p = m["proposal"]
    by = {d["sentence"]: d for d in p["decisions"]}
    assert by[0]["action"] == "REMOVE" and "tiếng đệm" in by[0]["reasons"][0]            # measured, not inferred
    assert by[1]["required"] and by[1]["reasons"][0] == "mở đầu"
    # Said twice: the rough cut keeps the later take; the earlier one holds a number, so its removal waits for the operator.
    assert by[2]["action"] == "REMOVE" and "nói lại" in by[2]["reasons"][0] and "có số liệu" in by[2]["protect"] and by[2]["review"] == "needs_review"
    assert by[3]["action"] == "KEEP" and by[3]["required"]                            # the point "Sản lượng" is still told
    assert by[4]["action"] == "REMOVE" and by[4]["reasons"][-1] == "không cần cho độ dài này"
    assert by[6]["required"] and by[6]["evidence"]["inferred"]["role"] == "kêu gọi hành động"
    assert {c["point"]: c["kept"] for c in p["coverage"]} == {"Sản lượng": True, "Chợ nổi": True}
    assert p["summary"]["kept_seconds"] <= 14 and all(d["evidence"]["range"] for d in p["decisions"])
    # Too short to hold every point: said, nothing required is dropped.
    tight = client.post(url, json={"assets": [asset_id], "presets": ["shorten"], "target_seconds": 5}).json()["message"]["proposal"]
    assert tight["notes"] and "không tự bỏ ý" in tight["notes"][0]
    assert all(d["action"] != "REMOVE" for d in tight["decisions"] if d.get("required"))
    # A stronger opening: the hook moved to the front. Applied with one decision turned off by the operator.
    opening = client.post(url, json={"assets": [asset_id], "presets": ["opening"], "goal": "mở đầu mạnh hơn"}).json()["message"]
    keep = [d["decision_id"] for d in opening["proposal"]["decisions"] if d["action"] != "REMOVE" and d["sentence"] != 5]
    view = client.post(f"{url}/{opening['message_id']}/apply", json={"keep": keep}).json()
    shots = view["shots"]
    assert len(shots) == len(keep) and all(s["assignment"]["treat"]["live_sound"] for s in shots)
    assert shots[0]["assignment"]["t_in"] < 1.5 and shots[0]["spec"]["line"].startswith("Vườn dừa")
    assert not any(s["spec"]["line"].startswith("Chiều về") for s in shots)
    assert client.post(f"{url}/{opening['message_id']}/apply", json={}).status_code == 404     # applied once


def test_without_the_models_reading_only_what_is_measured_is_cut(tmp_path):
    system, model, client, asset_id, project = _setup(tmp_path)
    model.answers["copilot_read"] = {}
    p = client.post(f"/api/v1/projects/{project}/storyboard/copilot", json={"assets": [asset_id], "presets": ["repetition"]}).json()["message"]["proposal"]
    removed = [d for d in p["decisions"] if d["action"] == "REMOVE"]
    assert removed and all(any("tiếng đệm" in r or "nói lại" in r or "lặp ý" in r for r in d["reasons"]) for d in removed)
    assert all(d["review"] == "needs_review" for d in p["decisions"] if d["action"] != "REMOVE") and p["notes"]
