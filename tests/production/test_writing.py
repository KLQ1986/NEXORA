"""Writing a stretch of a script with the model, from the editor: the lines chosen shortened, in another voice, split, written
another way, as the operator asks, or followed by a bridging line. The whole script is the context; only proposals come back."""
from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import build

from tests.fakes import FakeModel

LINES = ["# Mở bài", "Sáng nay biển rất êm.", "# Thân", "Tôi đi chậm dọc bờ cát.", "Ly cà phê nóng trên bàn gỗ.", "# Kết", "Ngày mới bắt đầu."]


def _setup(tmp_path, answer):
    model = FakeModel()
    asked = []
    model.answers["rewrite"] = lambda r: asked.append(r.params["prompt"]) or (answer(r) if callable(answer) else answer)
    system = build(tmp_path / "data", model=model)
    client = TestClient(create_app(system))
    project = system.planning.create_project("Biển sáng")
    return system, client, project, asked


def test_a_stretch_is_written_again_with_the_whole_script_as_context(tmp_path):
    answer = {"phuong_an": [{"ten": "gọn", "cau": ["Tôi thong thả trên cát.", "Cà phê nóng chờ sẵn."]},
                            {"ten": "một câu", "cau": ["Tôi thong thả trên cát, cà phê nóng chờ sẵn."]},
                            {"ten": "y nguyên", "cau": ["Tôi đi chậm dọc bờ cát.", "Ly cà phê nóng trên bàn gỗ."]},       # the same as now: dropped
                            {"ten": "lặp", "cau": ["Tôi thong thả trên cát.", "Cà phê nóng chờ sẵn."]}]}                 # twice: dropped
    system, client, project, asked = _setup(tmp_path, answer)
    out = client.post(f"/api/v1/projects/{project}/script/rewrite", json={"lines": LINES, "first": 3, "last": 4, "action": "shorten"}).json()
    assert [p["lines"] for p in out["proposals"]] == [["Tôi thong thả trên cát.", "Cà phê nóng chờ sẵn."], ["Tôi thong thả trên cát, cà phê nóng chờ sẵn."]]
    assert (out["first"], out["last"]) == (3, 4)
    # The model sees every line, numbered without the headings, and is told which to work on.
    assert "1. Sáng nay biển rất êm." in asked[-1] and "4. Ngày mới bắt đầu." in asked[-1] and "câu 2 đến câu 3" in asked[-1] and "rút gọn" in asked[-1]
    assert system.projects.current_script(project) is None                                       # nothing is saved


def test_each_request_and_its_checks(tmp_path):
    system, client, project, asked = _setup(tmp_path, {"phuong_an": [{"ten": "nối", "cau": ["Rồi tôi dừng lại ở quán nhỏ."]}]})
    url = f"/api/v1/projects/{project}/script/rewrite"
    # A bridge keeps the stretch and adds one line after it.
    out = client.post(url, json={"lines": LINES, "first": 3, "last": 3, "action": "bridge"}).json()
    assert out["proposals"][0]["lines"] == ["Tôi đi chậm dọc bờ cát.", "Rồi tôi dừng lại ở quán nhỏ."]
    # A voice and a free request carry the operator's words; without them they are refused.
    client.post(url, json={"lines": LINES, "first": 1, "last": 1, "action": "tone", "instruction": "hài hước hơn"})
    assert "hài hước hơn" in asked[-1]
    assert client.post(url, json={"lines": LINES, "first": 1, "last": 1, "action": "ask"}).status_code == 422
    # A stretch across a scene heading, or a heading alone, is refused before the model is asked.
    n = len(asked)
    assert client.post(url, json={"lines": LINES, "first": 1, "last": 3, "action": "shorten"}).status_code == 422
    assert client.post(url, json={"lines": LINES, "first": 0, "last": 0, "action": "shorten"}).status_code == 422
    assert client.post(url, json={"lines": LINES, "first": 1, "last": 1, "action": "nope"}).status_code == 422 and len(asked) == n


def test_a_proposal_with_a_phrase_the_channel_never_says_is_flagged(tmp_path):
    system, client, project, asked = _setup(tmp_path, {"phuong_an": [{"ten": "kêu", "cau": ["Biển sáng nay siêu đỉnh."]}, {"ten": "mộc", "cau": ["Biển sáng nay lặng."]}]})
    client.post("/api/v1/channels", json={"channels": [{"name": "Quê", "tone": "mộc", "banned": ["siêu đỉnh"]}]})
    system.projects.update_project(project, channel="Quê")
    out = client.post(f"/api/v1/projects/{project}/script/rewrite", json={"lines": LINES, "first": 1, "last": 1, "action": "again"}).json()
    assert out["proposals"][0]["flags"] == ["Có cụm từ kênh không dùng: “siêu đỉnh”."] and out["proposals"][1]["flags"] == []
    assert "giọng văn: mộc" in asked[-1]                                                         # the channel speaks in the prompt
