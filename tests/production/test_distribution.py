"""Distribution: the publishing ledger, figures at set marks, forecasts, experiments, titles and poster thumbnails."""
import json
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from nexora.adapters.outbox import MARKER, FolderPublisher, slug
from nexora.api.app import create_app
from nexora.app import build
from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result

from tests.conftest import make_video
from tests.fakes import FakeModel, FakeVoice

HOUR = 3600


def drain(system):
    while system.worker.run_once():
        pass


def packaged(tmp_path, *, publishers, titles=("Chợ sáng",)):
    model = FakeModel()
    system = build(tmp_path / "data", model=model, voice=FakeVoice(), segment_seconds=2.0, judge=False, publishers=publishers)
    client = TestClient(create_app(system))
    system.library.ingest(make_video(tmp_path / "a.mp4", picture=20)); drain(system)
    renders = []
    for title in titles:
        pid = client.post("/api/v1/projects", json={"title": title, "lines": ["chợ rau củ", "cá tươi trên sạp"]}).json()["project_id"]
        client.post(f"/api/v1/projects/{pid}/match"); drain(system)
        client.post(f"/api/v1/projects/{pid}/match/approve")
        client.post(f"/api/v1/projects/{pid}/render"); drain(system)
        client.post(f"/api/v1/projects/{pid}/render/decision", json={"approve": True})
        render = client.get(f"/api/v1/projects/{pid}").json()["renders"][0]["render_id"]
        client.post(f"/api/v1/renders/{render}/package", json={})
        renders.append(render)
    return system, model, client, renders


def test_a_cut_is_published_to_a_folder_once_however_often_it_is_asked(tmp_path):
    outbox = tmp_path / "Đã đăng"
    system, _, client, (render,) = packaged(tmp_path, publishers=[FolderPublisher(outbox)])
    assert [t["target"] for t in client.get("/api/v1/publishing").json()["targets"]][:2] == ["publish.folder", "youtube"]
    first = client.post(f"/api/v1/renders/{render}/publish", json={"target": "publish.folder"}).json()
    again = client.post(f"/api/v1/renders/{render}/publish", json={"target": "publish.folder"}).json()
    assert first["status"] == "published" and again["publication_id"] == first["publication_id"] and again["attempts"] == 1
    folders = [d for d in outbox.iterdir() if d.is_dir()]
    assert len(folders) == 1 and folders[0].name.endswith("-cho-sang") and {"video.mp4", "captions.srt", "README.txt", MARKER} <= {f.name for f in folders[0].iterdir()}
    assert json.loads((folders[0] / MARKER).read_text())["key"] == first["idempotency_key"] and not list(outbox.glob("*.partial"))
    assert client.post(f"/api/v1/renders/{render}/publish", json={"target": "publish.nowhere"}).status_code == 422
    assert client.post("/api/v1/renders/rnd_none/publish", json={"target": "publish.folder"}).status_code == 409
    assert slug("Một ngày ở Đà Nẵng!") == "mot-ngay-o-da-nang"


def test_a_send_with_no_clear_answer_is_settled_with_the_destination_before_anything_is_sent_again(tmp_path):
    class Flaky(Adapter):
        """Delivers, then loses the answer. The next question is whether it arrived."""
        def __init__(self): self.sent, self.delivered = 0, {}
        def describe(self): return Capability(name="publish.flaky", operations=("publish",), runs="cloud", supports_reconcile=True)
        def submit(self, request):
            self.sent += 1
            if self.sent == 1:
                self.delivered[request.idempotency_key] = "https://example.test/v/1"
                raise AdapterError(ErrorCode.TIMEOUT, "no answer")
            if self.sent == 2:
                raise AdapterError(ErrorCode.TIMEOUT, "no answer")           # this one never arrived
            return Result(outputs={"url": "https://example.test/v/2"}, external_ref="2")
        def reconcile(self, request):
            url = self.delivered.get(request.idempotency_key)
            return Result(outputs={"url": url}, external_ref="1") if url else None
    flaky = Flaky()
    system, _, client, (one, two) = packaged(tmp_path, publishers=[flaky], titles=("Một", "Hai"))
    row = client.post(f"/api/v1/renders/{one}/publish", json={"target": "publish.flaky"}).json()
    assert row["status"] == "unknown"
    settled = client.post(f"/api/v1/renders/{one}/publish", json={"target": "publish.flaky"}).json()
    assert settled["status"] == "published" and settled["url"] == "https://example.test/v/1" and flaky.sent == 1        # it had arrived: nothing was sent a second time

    lost = client.post(f"/api/v1/renders/{two}/publish", json={"target": "publish.flaky"}).json()
    assert lost["status"] == "unknown" and client.post(f"/api/v1/publications/{lost['publication_id']}/reconcile").json()["status"] == "failed"
    retried = client.post(f"/api/v1/renders/{two}/publish", json={"target": "publish.flaky"}).json()
    assert retried["status"] == "published" and retried["attempts"] == 2 and flaky.sent == 3                            # it had not: it is sent again


def test_uploads_made_by_hand_are_recorded_measured_at_marks_forecast_and_compared(tmp_path):
    system, _, client, renders = packaged(tmp_path, publishers=[], titles=("A", "B", "C", "D", "E"))
    assert client.post(f"/api/v1/renders/{renders[0]}/publish", json={"target": "youtube", "url": "javascript:alert(1)"}).status_code == 422
    pubs = [client.post(f"/api/v1/renders/{r}/publish", json={"target": "youtube", "url": f"https://youtu.be/{i}"}).json() for i, r in enumerate(renders)]
    assert client.post(f"/api/v1/renders/{renders[0]}/publish", json={"target": "youtube", "url": "https://youtu.be/other"}).json()["url"] == "https://youtu.be/0"     # one upload, one row
    assert client.post(f"/api/v1/publications/{pubs[0]['publication_id']}/metrics", json={"likes": "nhiều"}).status_code == 422
    assert client.post(f"/api/v1/publications/{pubs[0]['publication_id']}/metrics", json={}).status_code == 422

    now = time.time()
    for pub, (day, week) in zip(pubs[:4], [(100, 300), (200, 400), (50, 200), (400, 800)]):          # four earlier videos, a week old
        system.publishing._set(pub["publication_id"], published_at=now - 200 * HOUR)
        system.publishing.add_snapshot(pub["publication_id"], {"views": day}, at=now - 176 * HOUR)
        system.publishing.add_snapshot(pub["publication_id"], {"views": week, "likes": week // 10}, at=now - 32 * HOUR)
    newest = pubs[4]["publication_id"]
    system.publishing._set(newest, published_at=now - 26 * HOUR)
    due = client.get("/api/v1/publishing").json()["due"]
    assert [(d["publication_id"], d["mark"]) for d in due] == [(newest, 24)]
    assert [n["kind"] for n in system.orch.notifications()].count("metrics_due") == 1 and client.get("/api/v1/publishing").json()["due"] and \
        [n["kind"] for n in system.orch.notifications()].count("metrics_due") == 1                                          # announced once
    assert client.get(f"/api/v1/publications/{newest}/forecast").json()["ready"] is False
    client.post(f"/api/v1/publications/{newest}/metrics", json={"views": 150, "likes": 12})
    assert client.get("/api/v1/publishing").json()["due"] == []
    forecast = client.get(f"/api/v1/publications/{newest}/forecast").json()
    assert forecast["ready"] and forecast["based_on"] == 4 and forecast["week"] == 375 and (forecast["low"], forecast["high"]) == (300, 600)      # median growth 2.5 times

    experiment = client.post("/api/v1/experiments", json={"question": "Tiêu đề có số có hơn không?", "publications": [pubs[0]["publication_id"], pubs[1]["publication_id"]], "labels": ["Có số", "Không số"]}).json()
    assert experiment["verdict"]["decided"] and experiment["verdict"]["leader"] == "Không số" and experiment["compared_at_hours"] == pytest.approx(168, abs=1)
    close = client.post("/api/v1/experiments", json={"question": "Mới so với cũ", "publications": [pubs[0]["publication_id"], newest]}).json()
    assert close["compared_at_hours"] < 26.5 and [v["value"] for v in close["variants"]] == [100, 150] and close["verdict"]["decided"]       # compared at the same age, not at today's totals
    near = client.post("/api/v1/experiments", json={"question": "Gần nhau", "publications": [pubs[1]["publication_id"], pubs[3]["publication_id"]], "metric": "likes"}).json()
    assert near["verdict"]["decided"]
    assert client.post("/api/v1/experiments", json={"question": "Một mình", "publications": [newest]}).status_code == 422
    closed = client.post(f"/api/v1/experiments/{experiment['experiment_id']}/close", json={"conclusion": "Thử lại với 5 video nữa."}).json()
    assert closed["conclusion"] == "Thử lại với 5 video nữa." and closed["closed_at"]
    groups = {(g["kind"], g["name"]): g for g in client.get("/api/v1/publishing").json()["breakdown"]}
    assert groups[("Khung hình", "Ngang")]["videos"] == 4 and groups[("Nơi đăng", "youtube")]["median"] == 150


def test_titles_are_suggested_with_what_can_be_measured_and_a_frame_becomes_a_poster(tmp_path):
    system, model, client, (render,) = packaged(tmp_path, publishers=[])
    model.answers["titles"] = {"tieu_de": [{"ten": "Bí mật triệu đô của giới siêu giàu Dubai khiến bạn sốc nặng luôn nhé", "ly_do": "gây tò mò"}, {"ten": "Chợ rau củ và sạp cá tươi buổi sớm", "ly_do": "đúng nội dung"},
                                           {"ten": "Chợ", "ly_do": ""}, {"ten": "Chợ rau củ và sạp cá tươi buổi sớm"}, "Cá tươi trên sạp ở chợ rau củ"]}
    titles = client.post(f"/api/v1/renders/{render}/titles").json()["titles"]
    assert [t["title"] for t in titles][:2] == ["Chợ rau củ và sạp cá tươi buổi sớm", "Cá tươi trên sạp ở chợ rau củ"] and titles[0]["notes"] == [] and len(titles) == 4
    assert {"quá dài, sẽ bị cắt", "phần lớn từ không có trong lời dẫn"} <= set(titles[-1]["notes"]) or "quá ngắn" in titles[-1]["notes"]
    package = client.patch(f"/api/v1/renders/{render}/package", json={"title": titles[0]["title"]}).json()
    assert package["title"] == "Chợ rau củ và sạp cá tươi buổi sớm"
    poster = client.patch(f"/api/v1/renders/{render}/package", json={"poster_text": "Chợ sớm Hội An", "base": package["thumbnails"][1]}).json()
    assert poster["thumbnail"] == "poster_1.jpg" and poster["thumbnails"][-1] == "poster_1.jpg"
    from pathlib import Path
    base, made = Image.open(Path(poster["folder"]) / package["thumbnails"][1]), Image.open(Path(poster["folder"]) / "poster_1.jpg")
    assert made.size == base.size and made.convert("L").getextrema()[1] > 240                     # white letters are on it
    assert client.patch(f"/api/v1/renders/{render}/package", json={"poster_text": "x", "base": "khong-co.jpg"}).status_code == 422
    assert client.get(f"/api/v1/renders/{render}/package/poster_1.jpg").status_code == 200
