"""Quality: measured checks on the file, captions and package; the rights gate; the viewer's review; the benchmark."""
import pytest
from fastapi.testclient import TestClient

from nexora.api.app import create_app
from nexora.app import build
from nexora.core.adapter import Result
from nexora.modules.quality.evaluation import overlaps
from nexora.modules.quality.qc import caption_findings, picture_and_sound
from nexora.modules.quality.rights import rights_report

from tests.conftest import make_video
from tests.fakes import FakeModel, FakeStock, FakeVoice
from tests.library.test_sync import room_sound


def drain(system):
    while system.worker.run_once():
        pass


def test_captions_that_cannot_be_read_and_black_or_silence_that_is_not_meant_are_found():
    found = caption_findings([{"text": "ngắn gọn", "duration": 2.0}, {"text": "a" * 60, "duration": 2.0}, {"text": "b" * 90, "duration": 20.0}, {"text": "", "duration": 1.0}])
    assert [(f["shot"], "đọc không kịp" in f["text"], "quá hai dòng" in f["text"]) for f in found] == [(2, True, False), (3, False, True)]
    measured = picture_and_sound([[0.0, 0.2], [4.0, 6.0], [9.0, 10.0]], [[1.0, 2.0], [3.0, 7.5]], 12.0, gap_ranges=[[4.0, 6.0]])
    assert measured["black"] == [[9.0, 10.0]] and measured["silence"] == [[3.0, 7.5]]            # a flash and a known gap are not faults; a second of black is
    assert measured["checks"] == {"Không có khung đen ngoài ý muốn": False, "Không có khoảng im lặng dài": False, "Mở đầu có hình": True, "Có tiếng trong 3 giây đầu": True}
    assert all(picture_and_sound([], [[0.0, 12.0]], 12.0)["checks"].values())                    # a cut with no sound at all is caught by "Có âm thanh", not here


def test_the_rights_report_names_what_blocks_publishing_and_what_must_be_disclosed():
    assets = {"a": {"origin": "self_shot", "name": "a.mp4", "rights": None},
              "s": {"origin": "licensed", "name": "s.mp4", "rights": {"license": "CC BY 4.0", "source_url": "https://example.org/s", "creator": "Lan"}},
              "x": {"origin": "licensed", "name": "x.mp4", "rights": {"license": "", "source_url": ""}},
              "g": {"origin": "generated", "name": "g.mp4", "rights": None}}
    shots = [{"asset_id": "a", "text": "một"}, {"asset_id": "s", "text": "hai"}, {"asset_id": "x", "text": "ba"}, {"asset_id": "g", "text": "bốn"}, {"asset_id": "a", "text": "năm", "is_fact": True},
             {"asset_id": None, "text": "sáu", "is_fact": True, "source": "N", "fact_check": {"verdict": "contradicted", "source": "N"}}]
    report = rights_report(shots, assets, music="/nhac/bai.mp3")
    assert [i["name"] for i in report["items"]] == ["a.mp4", "s.mp4", "x.mp4", "g.mp4", "bai.mp3"] and not report["clear"]
    assert len(report["blockers"]) == 4 and "x.mp4" in report["blockers"][0] and "Câu 5" in report["blockers"][1] and "trái với nguồn" in report["blockers"][2] and "bai.mp3" in report["blockers"][3]
    assert "sinh bằng AI" in report["disclosures"][0] and "Lan, CC BY 4.0, https://example.org/s" in report["disclosures"][1]
    assert rights_report(shots[:2], assets, music="/nhac/bai.mp3", music_cleared=True)["clear"]


def cut(tmp_path, lines=("chợ rau củ", "cá tươi trên sạp"), model=None, **more):
    model = model or FakeModel()
    system = build(tmp_path / "data", model=model, voice=FakeVoice(), segment_seconds=2.0, judge=False, **more)
    client = TestClient(create_app(system))
    system.library.ingest(make_video(tmp_path / "a.mp4", picture=20))
    drain(system)
    pid = client.post("/api/v1/projects", json={"title": "Chợ sáng", "lines": list(lines)}).json()["project_id"]
    client.post(f"/api/v1/projects/{pid}/match"); drain(system)
    client.post(f"/api/v1/projects/{pid}/match/approve")
    return system, client, pid


def test_a_cut_with_unvouched_music_is_not_packaged_until_the_music_is_cleared_or_a_reason_is_given(tmp_path):
    system, client, pid = cut(tmp_path)
    client.patch(f"/api/v1/projects/{pid}", json={"music_path": str(room_sound(tmp_path / "nhac.wav", 9, seconds=6))})
    client.post(f"/api/v1/projects/{pid}/render"); drain(system)
    client.post(f"/api/v1/projects/{pid}/render/decision", json={"approve": True})
    render = client.get(f"/api/v1/projects/{pid}").json()["renders"][0]
    assert render["qc"]["passed"] and render["qc"]["checks"]["Không có khung đen ngoài ý muốn"] and render["qc"]["checks"]["Không có khoảng im lặng dài"]
    report = client.get(f"/api/v1/renders/{render['render_id']}/rights").json()
    assert not report["clear"] and "nhac.wav" in report["blockers"][0]
    refused = client.post(f"/api/v1/renders/{render['render_id']}/package", json={})
    assert refused.status_code == 409 and "nhac.wav" in refused.json()["detail"]

    forced = client.post(f"/api/v1/renders/{render['render_id']}/package", json={"override_reason": "Nhạc tôi tự sáng tác."}).json()
    assert forced["rights"]["override_reason"] == "Nhạc tôi tự sáng tác." and all(forced["checks"].values())
    client.patch(f"/api/v1/projects/{pid}", json={"options": {"music_cleared": True}})
    cleared = client.post(f"/api/v1/renders/{render['render_id']}/package", json={}).json()
    assert cleared["rights"]["clear"] and cleared["rights"]["override_reason"] is None and cleared["checks"]["Có phụ đề rời"]


def test_the_viewer_judges_frames_of_the_finished_cut_and_an_unanswered_shot_is_not_passed(tmp_path):
    class Eyes(FakeModel):
        def submit(self, request):
            if request.operation == "describe" and request.params.get("task") == "watch":
                if "cá tươi" in request.params["line"]:
                    return Result(outputs={"json": {"khop": 1, "thay": "một bãi biển vắng"}})
                if "pha cà phê" in request.params["line"]:
                    return Result(outputs={"json": {"khop": "không biết"}})
                return Result(outputs={"json": {"khop": 9, "thay": "sạp rau"}})
            return super().submit(request)
    system, client, pid = cut(tmp_path, lines=("chợ rau củ", "cá tươi trên sạp", "pha cà phê", "tên lửa phóng lên quỹ đạo…"), model=Eyes())
    client.post(f"/api/v1/projects/{pid}/render"); drain(system)
    render = client.get(f"/api/v1/projects/{pid}").json()["renders"][0]
    seen = client.post(f"/api/v1/renders/{render['render_id']}/watch").json()
    assert (seen["judged"], seen["of"]) == (2, 3)                                # the rocket line is a gap; the coffee line got no usable answer
    assert [(f["check"], f["shot"]) for f in seen["findings"]] == [("Hình và lời", 2), ("Kết", 4)] and "bãi biển vắng" in seen["findings"][0]["text"]
    assert client.get(f"/api/v1/projects/{pid}").json()["renders"][0]["qc"]["viewer"]["judged"] == 2

    blind = build(tmp_path / "blind", voice=FakeVoice())
    assert TestClient(create_app(blind)).post(f"/api/v1/renders/{render['render_id']}/watch").status_code in (404, 409)


def test_accepted_clips_become_a_benchmark_and_a_change_that_loses_them_is_flagged(tmp_path):
    system, client, pid = cut(tmp_path)
    shots = client.get(f"/api/v1/projects/{pid}").json()["shots"]
    assert client.post("/api/v1/evaluation/run").status_code == 409
    for shot in shots:
        assert client.post("/api/v1/evaluation/cases", json={"shot_id": shot["shot_id"]}).status_code == 201
    assert client.post("/api/v1/evaluation/cases", json={"shot_id": shots[0]["shot_id"]}).json()["cases"] == 2          # the same answer twice is one case
    assert client.post("/api/v1/evaluation/cases", json={"shot_id": "sht_none"}).status_code == 409
    moment = system.index.moments(shots[0]["selection"]["asset"]["asset_id"], level="segment")[-1]
    by_hand = client.post("/api/v1/evaluation/cases", json={"line": "khung cảnh cuối video", "moment_id": moment.moment_id}).json()        # the operator's own choice, not the system's
    assert by_hand["by_hand"] and by_hand["cases"] == 3 and client.post("/api/v1/evaluation/cases", json={"line": " ", "moment_id": moment.moment_id}).status_code == 422
    client.delete(f"/api/v1/evaluation/cases/{by_hand['case_id']}")
    first = client.post("/api/v1/evaluation/run").json()["runs"][0]
    assert (first["cases"], first["first"], first["top3"]) == (2, 1.0, 1.0) and "change" not in first and first["config"]["segment_seconds"] == 2.0

    # The descriptions change under the benchmark, as they would after a prompt or a model was changed for the worse.
    for moment in system.index.moments(shots[1]["selection"]["asset"]["asset_id"], level="segment"):
        system.index.correct(moment.moment_id, "một khung cảnh không liên quan")
    system.evaluation._threshold = 0.9
    runs = client.post("/api/v1/evaluation/run").json()["runs"]
    assert runs[0]["first"] < 1.0 and runs[0]["change"]["regression"] and runs[0]["change"]["lost"] and runs[0]["change"]["config"] == {}
    assert client.delete(f"/api/v1/evaluation/cases/{client.get('/api/v1/evaluation').json()['cases'][0]['case_id']}").json()["cases"].__len__() == 1
    assert overlaps(0, 4, 3, 6) and not overlaps(0, 2, 2.2, 4) and overlaps(1, 2, 0, 10)
