"""Notes pinned to a moment of a recording or a cut."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexora.api.notes import add_notes


def client(tmp_path) -> TestClient:
    app = FastAPI()
    add_notes(app, tmp_path)
    return TestClient(app)


def test_a_note_is_kept_in_time_order_and_can_be_put_right_and_dropped(tmp_path):
    c = client(tmp_path)
    fault = c.post("/api/v1/notes", json={"subject": "a1", "t": 3.456, "text": "màu lệch", "kind": "issue"}).json()
    c.post("/api/v1/notes", json={"subject": "a1", "t": 1, "text": "đoạn này đẹp"})
    c.post("/api/v1/notes", json={"subject": "other", "text": "không phải của a1"})
    assert [n["t"] for n in c.get("/api/v1/notes", params={"subject": "a1"}).json()["notes"]] == [1.0, 3.46]
    assert c.patch(f"/api/v1/notes/{fault['note_id']}", json={"resolved": True}).json()["resolved"] is True
    assert c.delete(f"/api/v1/notes/{fault['note_id']}").status_code == 200
    assert c.delete(f"/api/v1/notes/{fault['note_id']}").status_code == 404
    assert len(client(tmp_path).get("/api/v1/notes").json()["notes"]) == 2       # kept on disk


def test_a_note_needs_a_subject_words_and_a_number_for_its_second(tmp_path):
    c = client(tmp_path)
    assert c.post("/api/v1/notes", json={"subject": "a1", "text": "  "}).status_code == 422
    assert c.post("/api/v1/notes", json={"subject": "a1", "text": "x", "t": "abc"}).status_code == 422


def test_a_note_may_cover_a_stretch(tmp_path):
    c = client(tmp_path)
    assert c.post("/api/v1/notes", json={"subject": "a1", "t": 4, "t_end": 5.5, "text": "tông màu lạnh hơn"}).json()["t_end"] == 5.5
    assert c.post("/api/v1/notes", json={"subject": "a1", "t": 4, "t_end": 2, "text": "ngược"}).json()["t_end"] is None
